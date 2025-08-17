from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class UserSubscription(BaseModel):
    """User's current subscription details"""
    
    __tablename__ = "user_subscriptions"
    
    # Relationships
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"), nullable=False, index=True)
    
    # Stripe Integration
    stripe_subscription_id = Column(String, unique=True, nullable=False, index=True)
    stripe_customer_id = Column(String, nullable=False, index=True)
    
    # Subscription Status
    status = Column(String, nullable=False)  # "active", "canceled", "past_due", "unpaid"
    
    # Billing Period
    current_period_start = Column(DateTime(timezone=True), nullable=False)
    current_period_end = Column(DateTime(timezone=True), nullable=False)
    
    # Cancellation
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    user = relationship("User", back_populates="subscription")
    plan = relationship("SubscriptionPlan")
    
    def __repr__(self):
        return f"<UserSubscription(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
