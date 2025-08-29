from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class ProcessedFile(BaseModel):
    """Track processed PDF files and their cached results in Azure Blob Storage"""
    
    __tablename__ = "processed_files"
    
    # User Reference (nullable for anonymous users)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    
    # File Identification
    file_hash = Column(String, nullable=False, index=True)  # SHA-256 hash of file content
    columns_hash = Column(String, nullable=False, index=True)  # Hash of requested columns
    cache_key = Column(String, unique=True, nullable=False, index=True)  # file_hash + columns_hash
    columns = Column(String, nullable=True)  # JSON string of requested columns (null = all columns)
    original_filename = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    
    # Azure Blob Storage URLs
    azure_pdf_url = Column(String, nullable=False)  # Private blob URL for original PDF
    azure_excel_url = Column(String, nullable=True)  # Private blob URL for generated Excel (null if failed)
    
    # Processing Status
    processing_status = Column(String, nullable=False)  # 'completed' or 'failed'
    processing_time_seconds = Column(Float, nullable=True)
    error_message = Column(String, nullable=True)  # Error details if processing failed
    
    # Relationships (lazy loaded to avoid circular imports)
    user = relationship("User", back_populates="processed_files", lazy="select")
    
    # Performance Indexes
    __table_args__ = (
        # Critical: Composite index for main cache lookup query (now using cache_key)
        Index('ix_processed_files_cache_status', 'cache_key', 'processing_status'),
        
        # Analytics: User activity queries
        Index('ix_processed_files_user_status', 'user_id', 'processing_status'),
        
        # Monitoring: Recent activity queries  
        Index('ix_processed_files_created_status', 'created_at', 'processing_status'),
        
        # File content tracking (for analytics)
        Index('ix_processed_files_file_hash', 'file_hash'),
    )
    
    def __repr__(self):
        return f"<ProcessedFile(id={self.id}, hash='{self.file_hash[:8]}...', status='{self.processing_status}')>"
