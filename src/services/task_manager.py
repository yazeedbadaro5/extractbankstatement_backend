import uuid
import asyncio
import json
import redis
from typing import Dict, Optional
from datetime import datetime
from src.schemas.pdf import TaskStatus, TaskProgressResponse
from src.utils.logger import get_logger
from src.configuration.config import settings

logger = get_logger(__name__)


class TaskManager:
    """Redis-backed task manager for PDF processing jobs (works across processes)"""
    
    def __init__(self):
        self.redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        self.task_prefix = "task:"
    
    def create_task(self, filename: str, user_id: Optional[str], page_count: Optional[int] = None, client_ip: Optional[str] = None) -> str:
        """Create a new task and return task ID"""
        task_id = str(uuid.uuid4())
        
        task_data = {
            "task_id": task_id,
            "status": TaskStatus.PENDING.value,
            "filename": filename,
            "user_id": user_id,
            "page_count": page_count,
            "client_ip": client_ip,
            "created_at": datetime.now().isoformat(),
            "progress": 0,
            "message": "Task created, waiting to start processing"
        }
        
        # Store in Redis with 24 hour expiration
        self.redis_client.setex(
            f"{self.task_prefix}{task_id}",
            86400,  # 24 hours
            json.dumps(task_data)
        )
        
        logger.info(f"Created task {task_id} for user {user_id}, file: {filename}, pages: {page_count}")
        return task_id
    
    def update_task_status(self, task_id: str, status: TaskStatus, message: str, progress: Optional[float] = None):
        """Update task status and progress"""
        task_key = f"{self.task_prefix}{task_id}"
        task_json = self.redis_client.get(task_key)
        
        if task_json:
            task_data = json.loads(task_json)
            task_data["status"] = status.value
            task_data["message"] = message
            if progress is not None:
                task_data["progress"] = round(progress)
            
            # Update in Redis
            self.redis_client.setex(task_key, 86400, json.dumps(task_data))
            logger.info(f"Task {task_id} updated: {status} - {message}")
        else:
            logger.error(f"Task {task_id} not found in Redis for status update")
    
    def update_page_progress(self, task_id: str, pages_completed: int, total_pages: int):
        """Update progress based on pages completed"""
        logger.info(f"Attempting to update progress for task {task_id}: {pages_completed}/{total_pages}")
        
        task_key = f"{self.task_prefix}{task_id}"
        task_json = self.redis_client.get(task_key)
        
        if task_json:
            task_data = json.loads(task_json)
            # Calculate progress: 10% start + 80% for pages + 10% for finalization
            page_progress = (pages_completed / total_pages) * 80
            total_progress = 10 + page_progress
            
            message = f"Processing page {pages_completed}/{total_pages}"
            task_data["progress"] = round(total_progress)
            task_data["message"] = message
            
            # Update in Redis
            self.redis_client.setex(task_key, 86400, json.dumps(task_data))
            logger.info(f"Task {task_id} progress updated: {total_progress:.1f}% - {message}")
        else:
            logger.error(f"Task {task_id} not found in Redis for progress update")
    
    def complete_task(self, task_id: str, result: Dict):
        """Mark task as completed with results"""
        task_key = f"{self.task_prefix}{task_id}"
        task_json = self.redis_client.get(task_key)
        
        if task_json:
            task_data = json.loads(task_json)
            task_data.update({
                "status": TaskStatus.COMPLETED.value,
                "progress": 100,
                "message": "Processing completed successfully",
                "total_rows": result["total_rows"],
                "total_columns": len(result["columns"]),
                "columns": result["columns"],
                "processing_time": result["processing_time"],
                "statement_file_id": result["statement_file_id"]
            })
            
            # Update in Redis
            self.redis_client.setex(task_key, 86400, json.dumps(task_data))
            logger.info(f"Task {task_id} completed successfully")
        else:
            logger.error(f"Task {task_id} not found in Redis for completion")
    
    def fail_task(self, task_id: str, error: str):
        """Mark task as failed with error"""
        task_key = f"{self.task_prefix}{task_id}"
        task_json = self.redis_client.get(task_key)
        
        if task_json:
            task_data = json.loads(task_json)
            task_data.update({
                "status": TaskStatus.FAILED.value,
                "message": f"Processing failed: {error}",
                "error": error
            })
            
            # Update in Redis
            self.redis_client.setex(task_key, 86400, json.dumps(task_data))
            logger.error(f"Task {task_id} failed: {error}")
        else:
            logger.error(f"Task {task_id} not found in Redis for failure update")
    
    def get_task(self, task_id: str) -> Optional[TaskProgressResponse]:
        """Get task progress and results"""
        task_key = f"{self.task_prefix}{task_id}"
        task_json = self.redis_client.get(task_key)
        
        if not task_json:
            return None
        
        task_data = json.loads(task_json)
        
        # Build response based on status
        response_data = {
            "task_id": task_id,
            "status": TaskStatus(task_data["status"]),
            "progress": task_data.get("progress", 0),
            "message": task_data["message"]
        }
        
        # Add results if completed
        if task_data["status"] == TaskStatus.COMPLETED.value:
            response_data.update({
                "filename": task_data["filename"],
                "total_rows": task_data.get("total_rows"),
                "total_columns": task_data.get("total_columns"),
                "columns": task_data.get("columns"),
                "processing_time": task_data.get("processing_time"),
                "statement_file_id": task_data.get('statement_file_id')
            })
        
        # Add error if failed
        if task_data["status"] == TaskStatus.FAILED.value:
            response_data["error"] = task_data.get("error")
        
        return TaskProgressResponse(**response_data)
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Clean up tasks older than specified hours"""
        # Redis TTL handles cleanup automatically, but we can implement manual cleanup if needed
        pattern = f"{self.task_prefix}*"
        task_keys = self.redis_client.keys(pattern)
        
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
        cleaned_count = 0
        
        for task_key in task_keys:
            task_json = self.redis_client.get(task_key)
            if task_json:
                task_data = json.loads(task_json)
                created_at = datetime.fromisoformat(task_data["created_at"])
                
                if created_at.timestamp() < cutoff_time:
                    self.redis_client.delete(task_key)
                    cleaned_count += 1
        
        if cleaned_count > 0:
            logger.info(f"Cleaned up {cleaned_count} old tasks")


# Global task manager instance
task_manager = TaskManager()
