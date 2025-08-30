import asyncio
import json
import os
from typing import Optional, List

from src.celery_app import celery_app
from src.services.pdf_extraction_service import pdf_extraction_service
from src.services.task_manager import task_manager
from src.services.redis_credit_service import redis_credit_service
from src.services.file_cache_service import file_cache_service
from src.utils.logger import get_logger
from src.utils.rate_limiting import refund_anonymous_pages
from src.schemas.pdf import TaskStatus
from src.configuration.config import settings
# Import all models to ensure SQLAlchemy can find all relationships
from src.models.user import User
from src.models.processed_file import ProcessedFile
from src.models.user_subscription import UserSubscription
from src.models.subscription_plan import SubscriptionPlan
from src.models.transaction import Transaction
from src.models.base import Base

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="src.services.celery_tasks.process_pdf_task",
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 2, "countdown": 60},
    soft_time_limit=1800,  # 30 minutes soft limit
    time_limit=2400,       # 40 minutes hard limit
)
def process_pdf_task(
    self,
    task_id: str,
    file_bytes: bytes,
    filename: str,
    columns: Optional[List[str]],
    user_id: Optional[int] = None,
    file_hash: Optional[str] = None,
    columns_hash: Optional[str] = None,
    cache_key: Optional[str] = None
):
    """Celery task to process PDF extraction with async support"""
    try:
        logger.info(f"Starting Celery task {self.request.id} for PDF task {task_id}")
        
        # Update status to processing
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Starting PDF extraction", 10.0)
        
        # Run the async extraction
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                _process_pdf_async(
                    task_id=task_id,
                    file_bytes=file_bytes,
                    filename=filename,
                    columns=columns,
                    user_id=user_id,
                    file_hash=file_hash,
                    columns_hash=columns_hash,
                    cache_key=cache_key,
                    celery_task=self
                )
            )
            return result
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Celery task {self.request.id} failed with exception: {e}")
        task_manager.fail_task(task_id, str(e))
        
        # Handle refunds on failure
        task_data = task_manager.get_task(task_id)
        if task_data:
            # Get task data from Redis
            task_key = f"task:{task_id}"
            task_json = task_manager.redis_client.get(task_key)
            if task_json:
                task_info = json.loads(task_json)
                page_count = task_info.get('page_count', 0)
                
                if not user_id:
                    # Refund pages for anonymous users
                    try:
                        client_ip = task_info.get('client_ip')
                        if client_ip and page_count > 0:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(refund_anonymous_pages(client_ip, page_count))
                                logger.info(f"Refunded {page_count} pages to anonymous user {client_ip}")
                            finally:
                                loop.close()
                    except Exception as refund_error:
                        logger.error(f"Failed to refund anonymous pages: {refund_error}")
            else:
                # Refund credits for authenticated users
                try:
                    if page_count > 0:
                        required_credits = page_count
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            loop.run_until_complete(
                                redis_credit_service.refund_credits_atomic(user_id, required_credits)
                            )
                            logger.info(f"Refunded {required_credits} credits to user_id {user_id}")
                        finally:
                            loop.close()
                except Exception as refund_error:
                    logger.error(f"Failed to refund credits: {refund_error}")
        
        raise


async def _process_pdf_async(
    task_id: str,
    file_bytes: bytes,
    filename: str,
    columns: Optional[List[str]],
    user_id: Optional[int] = None,
    file_hash: Optional[str] = None,
    columns_hash: Optional[str] = None,
    cache_key: Optional[str] = None,
    celery_task=None
):
    """Async PDF processing logic"""
    try:
        # Update progress
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Processing PDF pages...", 10.0)
        
        # Run extraction
        result = await pdf_extraction_service.extract_bank_statement(
            file_bytes=file_bytes,
            filename=filename,
            required_columns=columns,
            task_id=task_id
        )
        
        # Update progress
        task_manager.update_task_status(task_id, TaskStatus.PROCESSING, "Finalizing results...", 90.0)
        
        if result["success"]:
            # Get task data from Redis
            task_key = f"task:{task_id}"
            task_json = task_manager.redis_client.get(task_key)
            if task_json:
                task_info = json.loads(task_json)
                page_count = task_info.get('page_count', 0)
                
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
                
                return {"success": True, "task_id": task_id}
        else:
            # Handle failed processing
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
            
            error_msg = result.get("error", "Unknown error")
            task_manager.fail_task(task_id, error_msg)
            raise Exception(f"PDF processing failed: {error_msg}")
            
    except Exception as e:
        logger.error(f"Task {task_id} failed with exception: {e}")
        task_manager.fail_task(task_id, str(e))
        raise
