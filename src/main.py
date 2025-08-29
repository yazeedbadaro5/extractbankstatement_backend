import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from src.utils.logger import get_logger
from src.routers import users, subscriptions, pdf, stripe_webhooks
from src.configuration.config import settings

# Get logger for this module
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown"""
    # Startup
    try:
        redis_connection = redis.from_url(
            settings.redis_url, 
            encoding="utf-8", 
            decode_responses=True
        )
        await FastAPILimiter.init(redis_connection)
        logger.info(f"✅ Redis connected and FastAPI-Limiter initialized: {settings.redis_url}")
    except Exception as e:
        logger.error(f"❌ Failed to initialize Redis/FastAPI-Limiter: {e}")
        raise
    
    yield
    
    # Shutdown
    try:
        await FastAPILimiter.close()
        logger.info("✅ FastAPI-Limiter closed successfully")
    except Exception as e:
        logger.error(f"❌ Error closing FastAPI-Limiter: {e}")


app = FastAPI(
    title="Bank Statement Extraction API", 
    version="1.0.0",
    description="Universal bank statement extraction service - Extract and process bank statements with AI-powered processing",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",  # Keep for local development
        "http://localhost:5173",  # Keep for local development
        "https://extractbankstatement.com",  # Your production domain
        "https://www.extractbankstatement.com"  # With www subdomain
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(users.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")
app.include_router(pdf.router, prefix="/api/v1")
app.include_router(stripe_webhooks.router, prefix="/api/v1")


@app.get("/")
def read_root():
    logger.info("🚀 Root endpoint accessed")
    return {"message": "Bank Statement Extraction API - Universal bank statement processing service ready!"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",  # Allow external connections
        port=8000,
        reload=False  # Disable reload in production
    )