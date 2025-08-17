from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe
from src.database import get_db
from src.middleware.auth import get_current_user
from src.models.user import User
from src.models.subscription_plan import SubscriptionPlan
from src.models.user_subscription import UserSubscription
from src.schemas.subscription import (
    SubscriptionPlanResponse,
    PortalSessionRequest,
    PortalSessionResponse
)
from src.services.stripe_service import stripe_service
from src.utils.logger import get_logger
from src.configuration.config import settings

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
        # Get or create Stripe customer for portal access
        customer_id = await stripe_service.get_or_create_customer(current_user)
        
        # Create portal session
        portal_url = await stripe_service.create_portal_session(
            customer_id=customer_id,
            return_url=request.return_url
        )
        
        logger.info(f"Created portal session for user {current_user.email}")
        
        return PortalSessionResponse(url=portal_url)
        
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
    """Get current user's subscription details"""
    
    result = await db.execute(
        select(UserSubscription)
        .where(UserSubscription.user_id == current_user.id)
        .where(UserSubscription.status.in_(["active", "trialing", "past_due"]))
        .order_by(UserSubscription.created_at.desc())
    )
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        return {"subscription": None}
    
    return {"subscription": subscription}





@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events"""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    if not sig_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe signature"
        )
    
    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except ValueError:
        logger.error("Invalid payload in webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload"
        )
    except stripe.SignatureVerificationError:
        logger.error("Invalid signature in webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature"
        )
    
    logger.info(f"Received webhook event: {event['type']}")
    
    # Handle important subscription events
    if event["type"] in ["customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"]:
        subscription = event["data"]["object"]
        await stripe_service.sync_subscription_from_stripe(db, subscription)
        logger.info(f"Synced subscription: {subscription['id']} ({event['type']})")
        
    elif event["type"] in ["invoice.payment_succeeded", "invoice.payment_failed"]:
        invoice = event["data"]["object"]
        subscription_id = invoice.get("subscription")
        if subscription_id:
            stripe_subscription = stripe.Subscription.retrieve(subscription_id)
            await stripe_service.sync_subscription_from_stripe(db, stripe_subscription)
            logger.info(f"Payment event for subscription: {subscription_id} ({event['type']})")
    
    else:
        logger.info(f"Unhandled webhook event: {event['type']}")
    
    return {"received": True}

