from typing import Optional
from fastapi import HTTPException, Depends, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import get_db
from src.services.clerk_service import clerk_service
from src.models.user import User
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Security schemes
security = HTTPBearer()  # Required auth
optional_security = HTTPBearer(auto_error=False)  # Optional auth


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """FastAPI dependency to get the current authenticated user"""
    
    # Verify token with Clerk
    jwt_data = clerk_service.verify_token(credentials.credentials)
    if not jwt_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token"
        )
    
    # Get or create user from JWT data
    user = await clerk_service.get_or_create_user_from_jwt(db, jwt_data)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing user ID"
        )
    
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Optional authentication - returns user if valid token provided, else None"""
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials, db)
    except HTTPException:
        return None


def get_client_ip(request: Request) -> str:
    """Extract client IP address from request, handling proxies"""
    # Check for forwarded IP first (common with reverse proxies)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, take the first one
        return forwarded_for.split(",")[0].strip()
    
    # Check for real IP header (some proxies use this)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    # Fall back to direct client IP
    return request.client.host if request.client else "unknown"
