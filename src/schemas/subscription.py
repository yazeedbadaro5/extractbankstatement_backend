from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class SubscriptionPlanResponse(BaseModel):
    """Response schema for subscription plans"""
    id: int
    name: str
    stripe_price_id: str
    price: int  # Price in cents
    currency: str
    interval: str
    monthly_credits: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True



class CreateSubscriptionRequest(BaseModel):
    """Request schema for creating a subscription"""
    price_id: str
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None


class CreateSubscriptionResponse(BaseModel):
    """Response schema for subscription creation"""
    checkout_url: str
    session_id: str
    customer_id: str
    message: str


class CancelSubscriptionResponse(BaseModel):
    """Response schema for subscription cancellation"""
    message: str
    access_ends_at: datetime
    current_credits: int
    plan_name: str

