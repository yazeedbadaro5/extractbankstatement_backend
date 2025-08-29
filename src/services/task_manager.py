import uuid
import asyncio
from typing import Dict, Optional
from datetime import datetime
from src.schemas.pdf import TaskStatus, TaskProgressResponse
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TaskManager:
    """Simple in-memory task manager for PDF processing jobs"""
    
    def __init__(self):
        self.tasks: Dict[str, Dict] = {}
    
    def create_task(self, filename: str, user_id: Optional[str], page_count: Optional[int] = None, client_ip: Optional[str] = None) -> str:
        """Create a new task and return task ID"""
        task_id = str(uuid.uuid4())
        
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": TaskStatus.PENDING,
            "filename": filename,
            "user_id": user_id,
            "page_count": page_count,
            "client_ip": client_ip,
            "created_at": datetime.now(),
            "progress": 0.0,
            "message": "Task created, waiting to start processing"
        }
        
        logger.info(f"Created task {task_id} for user {user_id}, file: {filename}, pages: {page_count}")
        return task_id
    
    def update_task_status(self, task_id: str, status: TaskStatus, message: str, progress: Optional[float] = None):
        """Update task status and progress"""
        if task_id in self.tasks:
            self.tasks[task_id]["status"] = status
            self.tasks[task_id]["message"] = message
            if progress is not None:
                self.tasks[task_id]["progress"] = progress
            
            logger.info(f"Task {task_id} updated: {status} - {message}")
    
    def update_page_progress(self, task_id: str, pages_completed: int, total_pages: int):
        """Update progress based on pages completed"""
        logger.info(f"Attempting to update progress for task {task_id}: {pages_completed}/{total_pages}")
        
        if task_id in self.tasks:
            # Calculate progress: 10% start + 80% for pages + 10% for finalization
            page_progress = (pages_completed / total_pages) * 80
            total_progress = 10 + page_progress
            
            message = f"Processing page {pages_completed}/{total_pages}"
            self.tasks[task_id]["progress"] = total_progress
            self.tasks[task_id]["message"] = message
            
            logger.info(f"Task {task_id} progress updated: {total_progress:.1f}% - {message}")
        else:
            logger.error(f"Task {task_id} not found in task manager for progress update")
    
    def complete_task(self, task_id: str, result: Dict):
        """Mark task as completed with results"""
        if task_id in self.tasks:
            self.tasks[task_id].update({
                "status": TaskStatus.COMPLETED,
                "progress": 100.0,
                "message": "Processing completed successfully",
                "total_rows": result["total_rows"],
                "total_columns": len(result["columns"]),
                "columns": result["columns"],
                "processing_time": result["processing_time"],
                "statement_file_id": result["statement_file_id"]
            })
            
            logger.info(f"Task {task_id} completed successfully")
    
    def fail_task(self, task_id: str, error: str):
        """Mark task as failed with error"""
        if task_id in self.tasks:
            self.tasks[task_id].update({
                "status": TaskStatus.FAILED,
                "message": f"Processing failed: {error}",
                "error": error
            })
            
            logger.error(f"Task {task_id} failed: {error}")
    
    def get_task(self, task_id: str) -> Optional[TaskProgressResponse]:
        """Get task progress and results"""
        if task_id not in self.tasks:
            return None
        
        task_data = self.tasks[task_id]
        
        # Build response based on status
        response_data = {
            "task_id": task_id,
            "status": task_data["status"],
            "progress": task_data.get("progress", 0.0),
            "message": task_data["message"]
        }
        
        # Add results if completed
        if task_data["status"] == TaskStatus.COMPLETED:
            response_data.update({
                "filename": task_data["filename"],
                "total_rows": task_data.get("total_rows"),
                "total_columns": task_data.get("total_columns"),
                "columns": task_data.get("columns"),
                "processing_time": task_data.get("processing_time"),
                "statement_file_id": task_data.get('statement_file_id')
            })
        
        # Add error if failed
        if task_data["status"] == TaskStatus.FAILED:
            response_data["error"] = task_data.get("error")
        
        return TaskProgressResponse(**response_data)
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Clean up tasks older than specified hours"""
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
        
        tasks_to_remove = []
        for task_id, task_data in self.tasks.items():
            if task_data["created_at"].timestamp() < cutoff_time:
                tasks_to_remove.append(task_id)
        
        for task_id in tasks_to_remove:
            del self.tasks[task_id]
            logger.info(f"Cleaned up old task: {task_id}")


# Global task manager instance
task_manager = TaskManager()
