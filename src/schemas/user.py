from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class UserResponse(BaseModel):
    """User response schema for API endpoints"""
    id: int
    clerk_id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_image_url: Optional[str] = None
    credits_balance: int
    total_credits_used: int
    last_sign_in_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SubscriptionPlanSchema(BaseModel):
    """Subscription plan schema"""
    id: int
    name: str
    price: int
    currency: str
    interval: str
    monthly_credits: int
    
    class Config:
        from_attributes = True


class UserSubscriptionSchema(BaseModel):
    """User subscription schema"""
    id: int
    status: str
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    plan: SubscriptionPlanSchema
    
    class Config:
        from_attributes = True


class UserWithSubscriptionResponse(UserResponse):
    """User response with subscription details"""
    subscription: Optional[UserSubscriptionSchema] = None
