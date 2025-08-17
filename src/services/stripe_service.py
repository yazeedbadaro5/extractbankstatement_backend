from typing import Optional
import stripe
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.configuration.config import settings
from src.models.user import User
from src.models.subscription_plan import SubscriptionPlan
from src.models.user_subscription import UserSubscription
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StripeService:
    """Service for handling Stripe payment operations"""
    
    def __init__(self):
        stripe.api_key = settings.stripe_secret_key
        logger.info("Stripe service initialized")
    
    async def get_or_create_customer(self, user: User) -> str:
        """Get existing or create new Stripe customer for portal access"""
        try:
            # Check if customer already exists with this email
            customers = stripe.Customer.list(email=user.email, limit=1)
            
            if customers.data:
                customer = customers.data[0]
                logger.info(f"Found existing Stripe customer {customer.id} for user {user.email}")
                return customer.id
            
            # Create new customer for portal access
            customer = stripe.Customer.create(
                email=user.email,
                name=f"{user.first_name or ''} {user.last_name or ''}".strip(),
                metadata={
                    "user_id": str(user.id),
                    "clerk_id": user.clerk_id
                }
            )
            
            logger.info(f"Created Stripe customer {customer.id} for user {user.email}")
            return customer.id
            
        except stripe.StripeError as e:
            logger.error(f"Failed to get/create Stripe customer for {user.email}: {e}")
            raise
    
    async def create_portal_session(self, customer_id: str, return_url: str) -> str:
        """Create a customer portal session for managing subscriptions"""
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url
            )
            
            logger.info(f"Created portal session for customer {customer_id}")
            return session.url
            
        except stripe.StripeError as e:
            logger.error(f"Failed to create portal session for {customer_id}: {e}")
            raise
    
    async def sync_subscription_from_stripe(
        self, 
        db: AsyncSession, 
        stripe_subscription: stripe.Subscription
    ) -> Optional[UserSubscription]:
        """Sync subscription data from Stripe to our database"""
        try:
            # Get the customer and find our user
            customer_id = stripe_subscription.customer
            customer = stripe.Customer.retrieve(customer_id)
            user_id = customer.metadata.get("user_id")
            
            if not user_id:
                logger.warning(f"No user_id in customer metadata for {customer_id}")
                return None
            
            # Get the user
            user_result = await db.execute(select(User).where(User.id == int(user_id)))
            user = user_result.scalar_one_or_none()
            
            if not user:
                logger.warning(f"User {user_id} not found in database")
                return None
            
            # Get the subscription plan by Stripe price ID
            price_id = stripe_subscription.items.data[0].price.id
            plan_result = await db.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == price_id)
            )
            plan = plan_result.scalar_one_or_none()
            
            if not plan:
                logger.warning(f"No plan found for Stripe price {price_id}")
                return None
            
            # Check if subscription already exists
            sub_result = await db.execute(
                select(UserSubscription).where(
                    UserSubscription.stripe_subscription_id == stripe_subscription.id
                )
            )
            user_sub = sub_result.scalar_one_or_none()
            
            if user_sub:
                # Update existing subscription
                user_sub.status = stripe_subscription.status
                user_sub.current_period_start = stripe_subscription.current_period_start
                user_sub.current_period_end = stripe_subscription.current_period_end
                user_sub.cancel_at_period_end = stripe_subscription.cancel_at_period_end or False
                user_sub.canceled_at = stripe_subscription.canceled_at
                
                logger.info(f"Updated subscription {stripe_subscription.id}")
            else:
                # Create new subscription
                user_sub = UserSubscription(
                    user_id=user.id,
                    plan_id=plan.id,
                    stripe_subscription_id=stripe_subscription.id,
                    stripe_customer_id=customer_id,
                    status=stripe_subscription.status,
                    current_period_start=stripe_subscription.current_period_start,
                    current_period_end=stripe_subscription.current_period_end,
                    cancel_at_period_end=stripe_subscription.cancel_at_period_end or False,
                    canceled_at=stripe_subscription.canceled_at
                )
                
                db.add(user_sub)
                logger.info(f"Created subscription record {stripe_subscription.id}")
            
            await db.commit()
            await db.refresh(user_sub)
            return user_sub
            
        except Exception as e:
            logger.error(f"Failed to sync subscription {stripe_subscription.id}: {e}")
            await db.rollback()
            raise


# Global instance
stripe_service = StripeService()

