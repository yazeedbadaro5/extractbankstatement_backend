from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class Transaction(BaseModel):
    """Records of successful Stripe payments and credit awards"""
    
    __tablename__ = "transactions"
    
    # User and Subscription References
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    subscription_id = Column(Integer, ForeignKey("user_subscriptions.id"), nullable=True, index=True)
    
    # Stripe References
    stripe_invoice_id = Column(String, nullable=False, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)  # Can be null for one-time payments
    
    # Payment Details
    amount = Column(Integer, nullable=False)  # Amount in cents
    currency = Column(String, default="usd", nullable=False)
    credits_awarded = Column(Integer, nullable=False)
    
    # Plan Information
    plan_name = Column(String, nullable=False)  # "Starter", "Professional", "Business"
    billing_period = Column(String, nullable=False)  # "month" or "year"
    
    # Metadata
    description = Column(String, nullable=False)  # "Monthly subscription", "Annual subscription"
    stripe_processed_at = Column(DateTime(timezone=True), nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    subscription = relationship("UserSubscription")
    
    def __repr__(self):
        return f"<Transaction(id={self.id}, user_id={self.user_id}, amount={self.amount}, credits={self.credits_awarded})>"


class StripeEvent(BaseModel):
    """Track processed Stripe webhook events to prevent duplicates"""
    
    __tablename__ = "stripe_events"
    
    # Stripe Event Details
    stripe_event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)  # "invoice.payment_succeeded"
    
    # Processing Status
    processed = Column(Boolean, default=False, nullable=False)
    transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True, index=True)
    
    # Processing metadata
    processed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(String, nullable=True)
    
    # Relationships
    transaction = relationship("Transaction")
    
    def __repr__(self):
        return f"<StripeEvent(id={self.id}, stripe_event_id='{self.stripe_event_id}', type='{self.event_type}')>"
