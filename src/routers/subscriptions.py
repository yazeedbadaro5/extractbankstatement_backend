from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
import stripe
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.models.subscription_plan import SubscriptionPlan
from src.models.user_subscription import UserSubscription
from src.schemas.subscription import (
    SubscriptionPlanResponse,
    PortalSessionRequest,
    PortalSessionResponse,
    CreateSubscriptionRequest,
    CreateSubscriptionResponse
)
from src.services.stripe_service import stripe_service
from src.services.transaction_service import transaction_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@router.get("/plans", response_model=List[SubscriptionPlanResponse])
async def get_subscription_plans(db: AsyncSession = Depends(get_db)):
    """Get all available subscription plans"""
    result = await db.execute(
        select(SubscriptionPlan).where(SubscriptionPlan.is_active == True)
    )
    plans = result.scalars().all()
    
    logger.info(f"Retrieved {len(plans)} active subscription plans")
    return plans



@router.post("/portal", response_model=PortalSessionResponse)
async def create_portal_session(
    request: PortalSessionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe customer portal session for subscription management"""
    
    try:
        # Check if user has an active paid subscription
        result = await db.execute(
            select(UserSubscription)
            .join(SubscriptionPlan)
            .where(UserSubscription.user_id == current_user.id)
            .where(UserSubscription.status.in_(["active", "trialing", "past_due"]))
            .where(SubscriptionPlan.name != "Free")  # Exclude free plan
        )
        subscription = result.scalar_one_or_none()
        
        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Portal access requires an active paid subscription. Please upgrade your plan first."
            )
        
        # Get or create Stripe customer for portal access
        customer_id = await stripe_service.get_or_create_customer(current_user)
        
        # Create portal session
        portal_url = await stripe_service.create_portal_session(
            customer_id=customer_id,
            return_url=request.return_url
        )
        
        logger.info(f"Created portal session for user {current_user.email}")
        
        return PortalSessionResponse(url=portal_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create portal session for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create portal session"
        )


@router.get("/current")
async def get_current_subscription(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get current user's subscription details (including Free plan)"""
    
    result = await db.execute(
        select(UserSubscription)
        .join(SubscriptionPlan)
        .options(joinedload(UserSubscription.subscription_plan))
        .where(UserSubscription.user_id == current_user.id)
        .where(UserSubscription.status.in_(["active", "trialing", "past_due"]))
        .order_by(UserSubscription.created_at.desc())
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return {"subscription": None}
    
    return {"subscription": subscription}


@router.post("/create", response_model=CreateSubscriptionResponse)
async def create_subscription(
    request: CreateSubscriptionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a subscription and redirect user to Stripe Checkout"""
    
    try:
        # Validate the price ID exists in our database
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == request.price_id)
        )
        plan = plan_result.scalar_one_or_none()
        
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription plan not found for price ID: {request.price_id}"
            )
        
        if not plan.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This subscription plan is not available"
            )
        
        # Get or create Stripe customer for this user
        customer_id = await transaction_service.get_or_create_stripe_customer(db, current_user)
        
        # Set default URLs if not provided  
        success_url = request.success_url or "http://localhost:3000/subscription/success?session_id={CHECKOUT_SESSION_ID}"
        cancel_url = request.cancel_url or "http://localhost:3000/subscription/cancel"
        
        # Create Stripe Checkout Session
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': request.price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                'user_id': str(current_user.id),
                'subscription_plan_id': str(plan.id),
                'plan_name': plan.name
            }
        )
        
        logger.info(
            f"✅ Created checkout session {checkout_session.id} for user {current_user.email} "
            f"subscribing to {plan.name} ({plan.interval}ly)"
        )
        
        return CreateSubscriptionResponse(
            checkout_url=checkout_session.url,
            session_id=checkout_session.id,
            customer_id=customer_id,
            message=f"Checkout session created for {plan.name} plan. Credits will be added after payment."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating subscription for user {current_user.email}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create subscription. Please try again."
        )