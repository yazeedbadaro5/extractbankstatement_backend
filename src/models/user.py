from sqlalchemy import Column, String, Boolean, DateTime, Integer
from sqlalchemy.orm import relationship
from src.models.base import BaseModel


class User(BaseModel):
    """User model for Clerk authentication integration"""
    
    __tablename__ = "users"
    
    # Clerk Integration Fields
    clerk_id = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    
    # Profile Fields  
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    profile_image_url = Column(String, nullable=True)
    
    # Credits System
    credits_balance = Column(Integer, default=0, nullable=False)
    total_credits_used = Column(Integer, default=0, nullable=False)
    
    # Status Fields
    last_sign_in_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    subscription = relationship("UserSubscription", back_populates="user", uselist=False)
    
    def __repr__(self):
        return f"<User(id={self.id}, email='{self.email}', credits={self.credits_balance})>"
