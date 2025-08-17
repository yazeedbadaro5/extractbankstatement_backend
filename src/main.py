from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.utils.logger import get_logger
from src.routers import users, subscriptions

# Get logger for this module
logger = get_logger(__name__)

app = FastAPI(
    title="SaaS Base API", 
    version="1.0.0",
    description="A complete SaaS foundation with authentication and subscription management"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],  # React/Vite
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(users.router, prefix="/api/v1")
app.include_router(subscriptions.router, prefix="/api/v1")

@app.get("/")
def read_root():
    logger.info("🚀 Root endpoint accessed")
    return {"message": "SaaS Base API - Ready for your next project!"}