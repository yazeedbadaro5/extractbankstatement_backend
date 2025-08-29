from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class UserSubscription(BaseModel):
    """User's current subscription details"""
    
    __tablename__ = "user_subscriptions"
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    
    # Stripe Integration
    stripe_subscription_id = Column(String, nullable=True, index=True)
    
    # Subscription Status
    status = Column(String, default="active", nullable=False)  # "active", "canceled", "past_due", "unpaid"
    
    # Billing Period
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    
    # Cancellation
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="subscriptions")
    subscription_plan = relationship("SubscriptionPlan")
    
    def __repr__(self):
        return f"<UserSubscription(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
