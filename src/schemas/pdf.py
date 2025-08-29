from typing import List, Optional
from pydantic import BaseModel, Field
from enum import Enum


class TaskStatus(str, Enum):
    """Task status enumeration"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskCreateResponse(BaseModel):
    """Response for task creation"""
    task_id: str = Field(description="Unique task identifier")
    status: TaskStatus = Field(description="Current task status")
    message: str = Field(description="Task creation message")


class TaskProgressResponse(BaseModel):
    """Response for task progress"""
    task_id: str = Field(description="Task identifier")
    status: TaskStatus = Field(description="Current task status")
    progress: Optional[float] = Field(description="Progress percentage (0-100)", ge=0, le=100)
    message: str = Field(description="Current status message")
    
    # Results (only when completed)
    filename: Optional[str] = Field(default=None, description="Original PDF filename")
    total_rows: Optional[int] = Field(default=None, description="Total rows extracted")
    total_columns: Optional[int] = Field(default=None, description="Total columns found")
    columns: Optional[List[str]] = Field(default=None, description="Column names found")
    processing_time: Optional[float] = Field(default=None, description="Processing time in seconds")
    statement_file_id: Optional[str] = Field(default=None, description="File ID to download bank statement file")
    
    # Error details (only when failed)
    error: Optional[str] = Field(default=None, description="Error message if failed")