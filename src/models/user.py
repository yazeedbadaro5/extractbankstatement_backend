from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class User(BaseModel):
    """User model for Clerk authentication integration"""
    
    __tablename__ = "users"
    
    # Clerk Integration Fields
    clerk_id = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    
    # Stripe Integration Fields  
    stripe_customer_id = Column(String, nullable=True, index=True)
    
    # Profile Fields
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    
    # Credits System
    credits_balance = Column(Integer, default=0, nullable=False)
    
    # Relationships
    subscriptions = relationship("UserSubscription", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")
    processed_files = relationship("ProcessedFile", back_populates="user")
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', credits={self.credits_balance})>"
