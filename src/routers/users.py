from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy import select
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.models.user_subscription import UserSubscription
from src.schemas.user import UserResponse, UserWithSubscriptionResponse
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user)
):
    """Get current user's basic information"""
    logger.info(f"Getting user info for: {current_user.email}")
    return current_user


@router.get("/me/detailed", response_model=UserWithSubscriptionResponse)
async def get_current_user_detailed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's detailed information including subscription"""
    # Reload user with subscription data
    result = await db.execute(
        select(User)
        .options(joinedload(User.subscription).joinedload(UserSubscription.plan))
        .where(User.id == current_user.id)
    )
    user_with_subscription = result.scalar_one()
    
    logger.info(f"Getting detailed user info for: {user_with_subscription.email}")
    return user_with_subscription


@router.get("/me/credits")
async def get_user_credits(
    current_user: User = Depends(get_current_user)
):
    """Get current user's credits information"""
    return {
        "credits_balance": current_user.credits_balance,
        "total_credits_used": current_user.total_credits_used,
        "user_id": current_user.id
    }



