from sqlalchemy import Column, String, Integer, Boolean
from src.models.base import BaseModel


class SubscriptionPlan(BaseModel):
    """Subscription plans available for users"""
    
    __tablename__ = "subscription_plans"
    
    # Plan Details
    name = Column(String, nullable=False)                    # "Basic", "Pro", "Enterprise"
    stripe_price_id = Column(String, unique=True, nullable=False, index=True)
    
    # Pricing
    price = Column(Integer, nullable=False)                  # Price in cents (e.g., 999 = $9.99)
    currency = Column(String, default="usd", nullable=False)
    interval = Column(String, default="month", nullable=False)  # "month" or "year"
    
    # Credits System
    monthly_credits = Column(Integer, nullable=False)        # Credits per billing period
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)  # Can users subscribe?
    
    def __repr__(self):
        return f"<SubscriptionPlan(id={self.id}, name='{self.name}', credits={self.monthly_credits})>"
