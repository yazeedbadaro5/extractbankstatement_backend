from pydantic_settings import BaseSettings
from pydantic import computed_field
from typing import Literal


class Settings(BaseSettings):
    """Base configuration settings for all projects"""
    
    # Environment - only development or production allowed
    environment: Literal["development", "production"] = "development"
    
    # Clerk Authentication
    clerk_secret_key: str
    clerk_publishable_key: str
    
    # Stripe Configuration
    stripe_secret_key: str
    stripe_publishable_key: str
    stripe_webhook_secret: str
    
    # Google Gemini Configuration
    gemini_api_key: str
    
    # Redis Configuration
    redis_url: str = "redis://localhost:6379"
    
    # Rate Limiting Configuration
    free_tier_max_pages: int = 1
    
    # Azure Blob Storage Configuration
    azure_storage_account_name: str
    azure_storage_account_key: str
    
    # Database Configuration
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "password"
    db_name: str = "database"
    
    @computed_field
    @property
    def database_url(self) -> str:
        """Construct database URL from components"""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    class Config:
        env_file = ".env"


settings = Settings()