import hashlib
import json
from datetime import datetime
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.models.processed_file import ProcessedFile
from src.services.azure_storage_service import azure_storage_service
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FileCacheService:
    """Service for managing file caching and duplicate detection"""
    
    @staticmethod
    def calculate_file_hash(file_content: bytes) -> str:
        """Calculate SHA-256 hash of file content"""
        return hashlib.sha256(file_content).hexdigest()
    
    @staticmethod
    def calculate_columns_hash(columns: Optional[list]) -> str:
        """Calculate hash of requested columns for cache key"""
        if not columns:
            return "all_columns"
        
        # Sort columns to ensure consistent hash regardless of order
        sorted_columns = sorted(str(col).lower().strip() for col in columns)
        columns_str = "|".join(sorted_columns)
        columns_hash = hashlib.sha256(columns_str.encode('utf-8')).hexdigest()[:16]
        
        return columns_hash
    
    @staticmethod
    def generate_cache_key(file_hash: str, columns_hash: str) -> str:
        """Generate unique cache key from file hash and columns hash"""
        return f"{file_hash}_{columns_hash}"
    
    async def check_cached_file(self, cache_key: str, db: AsyncSession) -> Optional[ProcessedFile]:
        """
        Check if a file with this cache key has been successfully processed before
        Returns ProcessedFile if found and completed, None otherwise
        """
        try:
            # Only return files that were successfully processed
            result = await db.execute(
                select(ProcessedFile).where(
                    ProcessedFile.cache_key == cache_key,
                    ProcessedFile.processing_status == "completed"
                )
            )
            cached_file = result.scalar_one_or_none()
            
            if cached_file:
                logger.info(f"Found cached file for cache key {cache_key[:16]}... - returning existing result")
                return cached_file
            else:
                logger.info(f"No cached file found for cache key {cache_key[:16]}... - will process")
                return None
                
        except Exception as e:
            logger.error(f"Error checking cached file for cache key {cache_key[:16]}...: {e}")
            return None
    
    async def save_processed_file(
        self,
        db: AsyncSession,
        user_id: Optional[int],
        file_hash: str,
        columns_hash: str,
        cache_key: str,
        columns: Optional[List[str]],
        original_filename: str,
        file_size_bytes: int,
        azure_pdf_url: str,
        azure_excel_url: Optional[str],
        processing_status: str,
        processing_time_seconds: Optional[float],
        error_message: Optional[str] = None
    ) -> ProcessedFile:
        """
        Save processed file information to database
        """
        try:
            # Check if a record with this cache_key already exists
            existing_result = await db.execute(
                select(ProcessedFile).where(ProcessedFile.cache_key == cache_key)
            )
            existing_file = existing_result.scalar_one_or_none()
            
            if existing_file:
                # Update existing record
                existing_file.azure_excel_url = azure_excel_url
                existing_file.processing_status = processing_status
                existing_file.processing_time_seconds = processing_time_seconds
                existing_file.error_message = error_message
                existing_file.updated_at = datetime.utcnow()
                
                await db.commit()
                await db.refresh(existing_file)
                
                logger.info(f"Updated existing processed file: {cache_key[:16]}... status={processing_status}")
                return existing_file
            else:
                # Create new record
                # Convert columns list to JSON string for storage
                columns_json = json.dumps(columns) if columns else None
                
                processed_file = ProcessedFile(
                    user_id=user_id,
                    file_hash=file_hash,
                    columns_hash=columns_hash,
                    cache_key=cache_key,
                    columns=columns_json,
                    original_filename=original_filename,
                    file_size_bytes=file_size_bytes,
                    azure_pdf_url=azure_pdf_url,
                    azure_excel_url=azure_excel_url,
                    processing_status=processing_status,
                    processing_time_seconds=processing_time_seconds,
                    error_message=error_message
                )
                
                db.add(processed_file)
                await db.commit()
                await db.refresh(processed_file)
                
                logger.info(f"Saved new processed file: {cache_key[:16]}... status={processing_status}")
                return processed_file
            
        except Exception as e:
            logger.error(f"Error saving processed file {cache_key[:16]}...: {e}")
            await db.rollback()
            raise
    
    async def store_pdf_and_get_cache_info(
        self,
        file_content: bytes,
        filename: str,
        columns: Optional[list],
        user_id: Optional[int],
        db: AsyncSession
    ) -> tuple[str, str, str, Optional[ProcessedFile]]:
        """
        Calculate hashes, check cache, and store PDF if new
        Returns (file_hash, columns_hash, cache_key, cached_file_if_exists)
        """
        # Calculate file and columns hashes
        file_hash = self.calculate_file_hash(file_content)
        columns_hash = self.calculate_columns_hash(columns)
        cache_key = self.generate_cache_key(file_hash, columns_hash)
        
        # Check if we have a cached successful result for this exact combination
        cached_file = await self.check_cached_file(cache_key, db)
        
        if cached_file:
            # File with these exact columns already processed successfully
            return file_hash, columns_hash, cache_key, cached_file
        
        # New combination - store PDF in Azure (only once per unique file content)
        try:
            azure_pdf_url = await azure_storage_service.upload_pdf(file_content, file_hash)
            logger.info(f"Stored PDF in Azure for file hash {file_hash[:8]}... with columns {columns_hash}")
            return file_hash, columns_hash, cache_key, None
            
        except Exception as e:
            logger.error(f"Error storing PDF for cache key {cache_key[:16]}...: {e}")
            raise
    
    async def store_excel_result(
        self,
        cache_key: str,
        excel_content: bytes
    ) -> str:
        """
        Store Excel file in Azure Blob Storage
        Returns the Azure URL
        """
        try:
            # Use cache_key for unique Excel file naming
            azure_excel_url = await azure_storage_service.upload_excel(excel_content, cache_key.replace('_', '-'))
            logger.info(f"Stored Excel result in Azure for cache key {cache_key[:16]}...")
            return azure_excel_url
            
        except Exception as e:
            logger.error(f"Error storing Excel for cache key {cache_key[:16]}...: {e}")
            raise


# Global instance
file_cache_service = FileCacheService()
