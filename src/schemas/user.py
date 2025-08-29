from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, computed_field


class UserResponse(BaseModel):
    """User response schema for API endpoints"""
    id: int
    clerk_id: str
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    credits_balance: int
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
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    subscription_plan: SubscriptionPlanSchema
    
    class Config:
        from_attributes = True


class UserWithSubscriptionResponse(UserResponse):
    """User response with subscription details"""
    subscriptions: List[UserSubscriptionSchema] = []
    
    @computed_field
    @property
    def subscription(self) -> Optional[UserSubscriptionSchema]:
        """Return the active paid subscription (excluding Free plans)"""
        for sub in self.subscriptions:
            if (sub.status in ["active", "trialing", "past_due"] and 
                sub.subscription_plan.name != "Free"):
                return sub
        return None
