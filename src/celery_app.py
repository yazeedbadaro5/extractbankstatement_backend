import os
from celery import Celery
from src.configuration.config import settings

# Configure gRPC for optimal performance in Celery workers
os.environ['GRPC_POLL_STRATEGY'] = 'poll'
os.environ['GRPC_ENABLE_FORK_SUPPORT'] = '1'
os.environ['GRPC_VERBOSITY'] = 'NONE'
os.environ['GRPC_TRACE'] = ''

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
    
    # Worker settings optimized for process-based workers
    worker_prefetch_multiplier=1,  # Fair distribution - each worker takes one task at a time
    task_acks_late=True,  # Acknowledge tasks only after completion
    worker_max_tasks_per_child=5,  # Restart workers frequently to prevent memory leaks
    
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

# Configure queue for PDF processing tasks
celery_app.conf.task_default_queue = "pdf_processing"
celery_app.conf.task_queues = {
    "pdf_processing": {
        "exchange": "pdf_processing", 
        "routing_key": "pdf_processing",
    },
}
