import asyncio
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional, List

import redis
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, BackgroundTasks, Request
from fastapi.responses import FileResponse

from src.middleware.auth import get_client_ip, get_current_user_optional
from src.models.user import User
from src.services.pdf_extraction_service import pdf_extraction_service
from src.services.task_manager import task_manager
from src.services.redis_credit_service import redis_credit_service
from src.services.file_cache_service import file_cache_service
from src.services.azure_storage_service import azure_storage_service
from src.database import get_db
from src.schemas.pdf import TaskCreateResponse, TaskProgressResponse, TaskStatus
from src.utils.logger import get_logger
from src.utils.pdf_utils import count_pdf_pages
from src.utils.rate_limiting import reserve_anonymous_pages, refund_anonymous_pages
from src.configuration.config import settings

logger = get_logger(__name__)

# Thread pool for running multiprocessing tasks without blocking FastAPI
thread_pool = ThreadPoolExecutor(max_workers=None)  # Unlimited workers

router = APIRouter(prefix="/pdf", tags=["pdf"])


@router.post("/tasks", response_model=TaskCreateResponse)
async def create_pdf_extraction_task(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(..., description="Bank statement PDF file to process"),
    columns: Optional[List[str]] = Form(
        None, 
        description="Optional list of column names to extract"
    ),
    current_user: Optional[User] = Depends(get_current_user_optional),
    db = Depends(get_db)
):
    """
    Create a Bank statement processing task.
    
    Returns a task ID that can be used to check progress.
    """
    client_ip = get_client_ip(request)
    user_info = f"user {current_user.email}" if current_user else f"anonymous user from {client_ip}"
    logger.info(f"Task creation request from {user_info} for file: {file.filename}")
    
    # Validate file
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported"
        )
    
    # Check file size (limit to 50MB)
    max_size = 50 * 1024 * 1024  # 50MB
    file_content = await file.read()
    if len(file_content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size too large. Maximum size is 50MB."
        )
    
    # Count pages for both anonymous and authenticated users
    page_count = count_pdf_pages(file_content)
    if page_count is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PDF file"
        )
    
    # Normalize columns - split comma-separated strings into individual column names
    normalized_columns = []
    if columns:
        for col in columns:
            if col and col.strip():  # Only process non-empty strings
                if ',' in col:
                    # Split comma-separated column names
                    normalized_columns.extend([c.strip() for c in col.split(',') if c.strip()])
                else:
                    normalized_columns.append(col.strip())
    
    # If no valid columns found, set to None for consistent "all columns" handling
    if not normalized_columns:
        normalized_columns = None
    
    # Check if file has been processed before with these exact columns (column-aware caching)
    logger.info(f"Checking cache for file {file.filename} with original columns: {columns}")
    logger.info(f"Checking cache for file {file.filename} with normalized columns: {normalized_columns}")
    file_hash, columns_hash, cache_key, cached_file = await file_cache_service.store_pdf_and_get_cache_info(
        file_content, file.filename, normalized_columns, current_user.id if current_user else None, db
    )
    logger.info(f"Cache check result - file_hash: {file_hash[:8]}..., columns_hash: {columns_hash}, cache_key: {cache_key[:16]}..., cached_file: {'Found' if cached_file else 'Not found'}")
    
    # If we found a cached successful result for this exact file+columns combination, return it immediately
    if cached_file:
        logger.info(f"Returning cached result for cache key {cache_key[:16]}... (user: {user_info})")
        task_id = task_manager.create_task(file.filename, current_user.id if current_user else None, page_count, get_client_ip(request) if not current_user else None)
        
        # Complete the task immediately with cached results
        task_manager.complete_task(task_id, {
            "total_rows": 0,  # We don't store this in cache
            "columns": [],    # We don't store this in cache  
            "processing_time": cached_file.processing_time_seconds or 0,
            "statement_file_id": cache_key
        })
        
        return TaskCreateResponse(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            message="File already processed with these columns. Returning cached results."
        )
    
    # Reserve pages for anonymous users immediately
    if not current_user:
        client_ip = get_client_ip(request)
        
        # Try to reserve pages immediately
        if not await reserve_anonymous_pages(client_ip, page_count):
            # Get current usage for error message
            today = datetime.now().strftime("%Y-%m-%d")
            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            pages_used_today = int(redis_client.get(f"anonymous_pages:{client_ip}:{today}") or "0")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Daily page limit exceeded. You've used {pages_used_today}/{settings.free_tier_max_pages} pages today. This PDF has {page_count} pages. Sign up for unlimited access."
            )
        
        logger.info(f"Anonymous user {client_ip}: Reserved {page_count} pages for processing")
    elif current_user:
        # Reserve credits for authenticated users immediately using Redis
        required_credits = page_count  # 1 credit per page
        
        # Initialize user credits in Redis if not exists
        await redis_credit_service.initialize_user_credits(current_user.id, current_user.credits_balance)
        
        # Reserve credits atomically
        if not await redis_credit_service.reserve_credits_atomic(current_user.id, required_credits):
            current_stats = await redis_credit_service.get_user_stats(current_user.id)
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Insufficient credits. You need {required_credits} credits but have {current_stats['available_credits']}. Upgrade your plan for more credits."
            )
        
        logger.info(f"User {current_user.email}: Reserved {required_credits} credits for {page_count} pages using Redis")
    
    # Create task
    user_id = current_user.id if current_user else None
    client_ip = get_client_ip(request) if not current_user else None
    task_id = task_manager.create_task(file.filename, user_id, page_count, client_ip)
    
    # Use columns directly from form data
    if normalized_columns:
        logger.info(f"Extracting specific columns: {normalized_columns}")
    else:
        logger.info("Extracting all columns")
    
    # Start background processing
    background_tasks.add_task(
        process_pdf_task,
        task_id,
        file_content,
        file.filename,
        normalized_columns,
        current_user.id if current_user else None,
        file_hash,
        columns_hash,
        cache_key
    )
    
    return TaskCreateResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task created successfully. Processing will begin shortly."
    )


@router.get("/tasks/{task_id}", response_model=TaskProgressResponse)
async def get_task_progress(
    task_id: str
):
    """
    Get task progress and results.
    
    Returns current status, progress, and results when completed.
    No authentication required - task IDs are UUID-based for security.
    """
    task = task_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found"
        )
    
    return task


@router.get("/download/{file_id}")
async def download_statement_file(
    file_id: str,
    db = Depends(get_db)
):
    """Download the generated bank statement file. No authentication required - file IDs are UUID-based for security."""
    logger.info(f"Download request for file: {file_id}")
    
    # First try to get from Azure (new cache system) using file_id as cache_key
    try:
        # Use file_id directly as the cache_key
        cache_key = file_id
        
        # Try to find the file in our cache
        from sqlalchemy import select
        from src.models.processed_file import ProcessedFile
        
        result = await db.execute(
            select(ProcessedFile).where(
                ProcessedFile.cache_key == cache_key,
                ProcessedFile.processing_status == "completed"
            )
        )
        cached_file = result.scalar_one_or_none()
        
        if cached_file and cached_file.azure_excel_url:
            # Download from Azure and serve
            file_content, content_type = await azure_storage_service.download_file(cached_file.azure_excel_url)
            
            from fastapi.responses import Response
            import urllib.parse
            
            # Handle Unicode characters in filename properly
            safe_filename = cached_file.original_filename.replace('.pdf', '.xlsx')
            encoded_filename = urllib.parse.quote(safe_filename, safe='')
            
            return Response(
                content=file_content,
                media_type=content_type,
                headers={
                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"
                }
            )
    except Exception as e:
        logger.warning(f"Failed to download from Azure cache for {file_id}: {e}")
        # Continue to local fallback
    
    # Fallback to original local file system for backwards compatibility
    # Try both with and without .xlsx extension for old files
    temp_dir = tempfile.gettempdir()
    
    # First try the file_id as-is (for old UUID-based files that include .xlsx)
    file_path = os.path.join(temp_dir, file_id)
    if os.path.exists(file_path) and file_id.endswith('.xlsx'):
        return FileResponse(
            path=file_path,
            filename=file_id,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # Then try adding .xlsx to the file_id (for hash-based IDs)
    file_path_with_ext = os.path.join(temp_dir, f"{file_id}.xlsx")
    if os.path.exists(file_path_with_ext):
        return FileResponse(
            path=file_path_with_ext,
            filename=f"{file_id}.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    # File not found anywhere
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="File not found or has expired"
    )


async def process_pdf_task(task_id: str, file_bytes: bytes, filename: str, columns: Optional[list], user_id: Optional[int] = None, file_hash: Optional[str] = None, columns_hash: Optional[str] = None, cache_key: Optional[str] = None):
    """Background task to process PDF extraction without blocking FastAPI"""
    try:
        # Update status to processing
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Starting PDF extraction", 10.0)
        
        # Run the multiprocessing extraction in a separate thread to avoid blocking FastAPI
        loop = asyncio.get_event_loop()
        
        def run_extraction():
            """Run the extraction in a thread to avoid blocking the event loop"""
            return asyncio.run(pdf_extraction_service.extract_bank_statement(
                file_bytes=file_bytes,
                filename=filename,
                required_columns=columns,
                task_id=task_id
            ))
        
        # Update progress - start at 10% as per task manager's calculation
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Processing PDF pages...", 10.0)
        
        # Run extraction in thread pool to keep FastAPI responsive
        result = await loop.run_in_executor(thread_pool, run_extraction)
        
        # Update progress
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Finalizing results...", 90.0)
        
        if result["success"] and task_id in task_manager.tasks:
            page_count = task_manager.tasks[task_id].get('page_count', 0)
            
            # Store Excel file in Azure and save to cache
            if cache_key and result.get("excel_path"):
                try:
                    # Read the Excel file content
                    with open(result["excel_path"], "rb") as excel_file:
                        excel_content = excel_file.read()
                    
                    # Store Excel in Azure with cache_key for unique naming
                    azure_excel_url = await file_cache_service.store_excel_result(cache_key, excel_content)
                    
                    # Save processing result to cache
                    from src.database import get_db
                    async for db in get_db():
                        azure_pdf_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net/bank-statements/pdfs/{file_hash}.pdf"
                        await file_cache_service.save_processed_file(
                            db=db,
                            user_id=user_id,
                            file_hash=file_hash,
                            columns_hash=columns_hash,
                            cache_key=cache_key,
                            columns=columns,
                            original_filename=filename,
                            file_size_bytes=len(file_bytes),
                            azure_pdf_url=azure_pdf_url,
                            azure_excel_url=azure_excel_url,
                            processing_status="completed",
                            processing_time_seconds=result["processing_time"]
                        )
                        logger.info(f"Saved successful processing result to cache for key {cache_key[:16]}...")
                        break
                except Exception as e:
                    logger.error(f"Error saving to cache for task {task_id}: {e}")
            
            if user_id:
                # Confirm credit usage for authenticated users after successful processing
                try:
                    if page_count > 0:
                        required_credits = page_count  # 1 credit per page
                        await redis_credit_service.confirm_credit_usage_atomic(user_id, required_credits)
                        logger.info(f"Confirmed {required_credits} credits usage for user_id {user_id} for task {task_id}")
                        
                        # Sync database balance with Redis
                        from src.database import get_db
                        async for db in get_db():
                            await redis_credit_service.sync_database_balance(user_id, db)
                            break
                except Exception as e:
                    logger.error(f"Failed to confirm credit usage for task {task_id}: {e}")
            else:
                # Pages already reserved for anonymous users - no additional action needed on success
                logger.info(f"Anonymous user successfully processed {page_count} pages for task {task_id}")
            
            # Complete the task
            task_manager.complete_task(task_id, {
                "total_rows": result["total_rows"],
                "columns": result["columns"],
                "processing_time": result["processing_time"],
                "statement_file_id": cache_key if cache_key else os.path.basename(result["excel_path"])
            })
        else:
            # Fail the task - refund pages/credits for failed processing
            if task_id in task_manager.tasks:
                page_count = task_manager.tasks[task_id].get('page_count', 0)
                
                # Save failed processing result to cache
                if cache_key:
                    try:
                        from src.database import get_db
                        async for db in get_db():
                            azure_pdf_url = f"https://{settings.azure_storage_account_name}.blob.core.windows.net/bank-statements/pdfs/{file_hash}.pdf"
                            await file_cache_service.save_processed_file(
                                db=db,
                                user_id=user_id,
                                file_hash=file_hash,
                                columns_hash=columns_hash,
                                cache_key=cache_key,
                                columns=columns,
                                original_filename=filename,
                                file_size_bytes=len(file_bytes),
                                azure_pdf_url=azure_pdf_url,
                                azure_excel_url=None,
                                processing_status="failed",
                                processing_time_seconds=None,
                                error_message=result.get("error", "Unknown error")
                            )
                            logger.info(f"Saved failed processing result to cache for key {cache_key[:16]}...")
                            break
                    except Exception as e:
                        logger.error(f"Error saving failed result to cache for task {task_id}: {e}")
                
                if not user_id:
                    # Refund pages for anonymous users
                    try:
                        client_ip = task_manager.tasks[task_id].get('client_ip')
                        if client_ip and page_count > 0:
                            await refund_anonymous_pages(client_ip, page_count)
                            logger.info(f"Refunded {page_count} pages to anonymous user {client_ip} for failed task {task_id}")
                    except Exception as e:
                        logger.error(f"Failed to refund anonymous pages for task {task_id}: {e}")
                else:
                    # Refund credits for authenticated users
                    try:
                        if page_count > 0:
                            required_credits = page_count  # 1 credit per page
                            await redis_credit_service.refund_credits_atomic(user_id, required_credits)
                            logger.info(f"Refunded {required_credits} credits to user_id {user_id} for failed task {task_id}")
                    except Exception as e:
                        logger.error(f"Failed to refund credits for task {task_id}: {e}")
            
            task_manager.fail_task(task_id, result.get("error", "Unknown error"))
            
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}")
        task_manager.fail_task(task_id, str(e))