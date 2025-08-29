import hashlib
import io
from typing import Optional, Tuple
from azure.storage.blob import BlobServiceClient, BlobClient, StandardBlobTier
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

from src.configuration.config import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class AzureStorageService:
    """Service for managing file uploads and downloads to Azure Blob Storage"""
    
    def __init__(self):
        self.blob_service_client = BlobServiceClient(
            account_url=f"https://{settings.azure_storage_account_name}.blob.core.windows.net",
            credential=settings.azure_storage_account_key
        )
        self.container_name = "bank-statements"
        self._ensure_container_exists()
    
    def _ensure_container_exists(self):
        """Ensure the container exists, create if not"""
        try:
            container_client = self.blob_service_client.get_container_client(self.container_name)
            container_client.create_container()
            logger.info(f"Created Azure container: {self.container_name}")
        except ResourceExistsError:
            # Container already exists, which is fine
            pass
        except Exception as e:
            logger.error(f"Error ensuring container exists: {e}")
            raise
    
    def calculate_file_hash(self, file_content: bytes) -> str:
        """Calculate SHA-256 hash of file content"""
        return hashlib.sha256(file_content).hexdigest()
    
    async def upload_pdf(self, file_content: bytes, file_hash: str) -> str:
        """
        Upload PDF file to Azure Blob Storage
        Returns the blob URL
        """
        blob_name = f"pdfs/{file_hash}.pdf"
        
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # Upload with Cool tier for cost optimization
            blob_client.upload_blob(
                data=file_content,
                overwrite=True,
                blob_type="BlockBlob",
                standard_blob_tier=StandardBlobTier.Cool
            )
            
            blob_url = blob_client.url
            logger.info(f"Uploaded PDF to Azure: {blob_name}")
            return blob_url
            
        except Exception as e:
            logger.error(f"Error uploading PDF {blob_name}: {e}")
            raise
    
    async def upload_excel(self, file_content: bytes, file_hash: str) -> str:
        """
        Upload Excel file to Azure Blob Storage
        Returns the blob URL
        """
        blob_name = f"excel/{file_hash}.xlsx"
        
        try:
            blob_client = self.blob_service_client.get_blob_client(
                container=self.container_name,
                blob=blob_name
            )
            
            # Upload with Cool tier for cost optimization
            blob_client.upload_blob(
                data=file_content,
                overwrite=True,
                blob_type="BlockBlob",
                standard_blob_tier=StandardBlobTier.Cool
            )
            
            blob_url = blob_client.url
            logger.info(f"Uploaded Excel to Azure: {blob_name}")
            return blob_url
            
        except Exception as e:
            logger.error(f"Error uploading Excel {blob_name}: {e}")
            raise
    
    async def download_file(self, blob_url: str) -> Tuple[bytes, str]:
        """
        Download file from Azure Blob Storage
        Returns (file_content, content_type)
        """
        try:
            blob_client = BlobClient.from_blob_url(blob_url, credential=settings.azure_storage_account_key)
            
            # Download the blob
            download_stream = blob_client.download_blob()
            file_content = download_stream.readall()
            
            # Determine content type based on blob name
            blob_name = blob_client.blob_name
            if blob_name.endswith('.pdf'):
                content_type = "application/pdf"
            elif blob_name.endswith('.xlsx'):
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            else:
                content_type = "application/octet-stream"
            
            logger.info(f"Downloaded file from Azure: {blob_name}")
            return file_content, content_type
            
        except ResourceNotFoundError:
            logger.error(f"File not found in Azure: {blob_url}")
            raise FileNotFoundError(f"File not found: {blob_url}")
        except Exception as e:
            logger.error(f"Error downloading file from Azure {blob_url}: {e}")
            raise
    
    async def delete_file(self, blob_url: str) -> bool:
        """
        Delete file from Azure Blob Storage
        Returns True if successful, False if file didn't exist
        """
        try:
            blob_client = BlobClient.from_blob_url(blob_url, credential=settings.azure_storage_account_key)
            blob_client.delete_blob()
            logger.info(f"Deleted file from Azure: {blob_client.blob_name}")
            return True
            
        except ResourceNotFoundError:
            logger.warning(f"File not found for deletion: {blob_url}")
            return False
        except Exception as e:
            logger.error(f"Error deleting file from Azure {blob_url}: {e}")
            raise


# Global instance
azure_storage_service = AzureStorageService()
