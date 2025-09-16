from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from typing import AsyncGenerator
from src.configuration.config import settings


class DatabaseManager:
    """Simple database manager for async operations"""
    
    def __init__(self):
        # Configure SSL for asyncpg based on environment
        connect_args = {
            "server_settings": {
                "application_name": "fastapi_async_app",
            }
        }

        # Add SSL for production (Digital Ocean requires SSL)
        if settings.environment == "production":
            connect_args["ssl"] = "require"

        self.engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            # Optimized for high-concurrency async operations
            pool_size=50,          # Base connection pool size
            max_overflow=100,      # Additional connections for bursts
            pool_pre_ping=True,    # Verify connections before use
            pool_recycle=1800,     # Recycle connections every 30min
            pool_timeout=30,       # Timeout for getting connection
            # Connection settings for FastAPI async operations
            connect_args=connect_args
        )
        
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        self.base = declarative_base()
    
    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session with transaction management"""
        async with self.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()


# Global database manager
db_manager = DatabaseManager()

# Export for easy access
Base = db_manager.base


# FastAPI dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Database dependency for FastAPI"""
    async for session in db_manager.get_session():
        yield session
