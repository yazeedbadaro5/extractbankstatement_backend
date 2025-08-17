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



class PortalSessionRequest(BaseModel):
    """Request schema for creating a portal session"""
    return_url: str


class PortalSessionResponse(BaseModel):
    """Response schema for portal session creation"""
    url: str

