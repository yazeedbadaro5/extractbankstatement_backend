from celery import Celery
from src.configuration.config import settings

# Create Celery app
celery_app = Celery(
    "pdf_extraction",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["src.services.celery_tasks"]
)

# Configure Celery
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    
    # Result backend settings
    result_expires=3600,  # 1 hour
    result_backend_transport_options={
        "master_name": "mymaster",
        "visibility_timeout": 3600,
    },
    
    # Worker settings optimized for 4x8 VM
    worker_prefetch_multiplier=1,  # Important for CPU-intensive tasks
    task_acks_late=True,  # Acknowledge tasks only after completion
    worker_max_tasks_per_child=10,  # Restart workers after 10 tasks to prevent memory leaks
    
    # Routing
    task_routes={
        "src.services.celery_tasks.process_pdf_task": {"queue": "pdf_processing"},
    },
    
    # Error handling
    task_reject_on_worker_lost=True,
    task_track_started=True,
    
    # Redis connection settings
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "visibility_timeout": 3600,
        "fanout_prefix": True,
        "fanout_patterns": True,
    },
)

# Configure queues
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_queues = {
    "default": {
        "exchange": "default",
        "routing_key": "default",
    },
    "pdf_processing": {
        "exchange": "pdf_processing", 
        "routing_key": "pdf_processing",
    },
}
