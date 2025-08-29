from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import stripe

from src.models.transaction import Transaction, StripeEvent
from src.models.user import User
from src.models.user_subscription import UserSubscription
from src.models.subscription_plan import SubscriptionPlan
from src.services.redis_credit_service import redis_credit_service
from src.utils.logger import get_logger
from src.configuration.config import settings

logger = get_logger(__name__)

# Configure Stripe
stripe.api_key = settings.stripe_secret_key


class TransactionService:
    """Service for handling Stripe payment transactions and credit allocation"""
    
    @staticmethod
    async def record_successful_payment(
        session: AsyncSession,
        stripe_event_id: str,
        stripe_invoice_data: Dict[str, Any],
        stripe_subscription_data: Dict[str, Any]
    ) -> Optional[Transaction]:
        """
        Record a successful Stripe payment and award credits to user
        
        Args:
            session: Database session
            stripe_event_id: Stripe event ID for deduplication
            stripe_invoice_data: Stripe invoice data from webhook
            stripe_subscription_data: Stripe subscription data from webhook
            
        Returns:
            Created Transaction object or None if already processed
        """
        
        try:
            # Check if this event was already processed
            existing_event = await session.execute(
                select(StripeEvent).where(StripeEvent.stripe_event_id == stripe_event_id)
            )
            if existing_event.scalar_one_or_none():
                logger.info(f"Stripe event {stripe_event_id} already processed, skipping")
                return None
            
            # Extract data from Stripe invoice
            customer_id = stripe_invoice_data.get('customer')
            
            # Get subscription ID from the correct path (same logic as webhook handlers)
            subscription_id = stripe_invoice_data.get('subscription')
            if not subscription_id:
                lines = stripe_invoice_data.get('lines', {}).get('data', [])
                if lines:
                    line_item = lines[0]
                    subscription_id = line_item.get('subscription')
                    if not subscription_id and line_item.get('parent', {}).get('subscription_item_details'):
                        subscription_id = line_item['parent']['subscription_item_details'].get('subscription')
            
            logger.info(f"📋 Subscription ID found: {subscription_id}")
            
            invoice_id = stripe_invoice_data.get('id')
            amount = stripe_invoice_data.get('amount_paid', 0)
            currency = stripe_invoice_data.get('currency', 'usd')
            
            # Get the price ID from the subscription
            price_id = None
            if stripe_subscription_data and 'items' in stripe_subscription_data:
                items = stripe_subscription_data['items']
                if hasattr(items, 'data'):
                    items_data = items.data
                elif isinstance(items, dict) and 'data' in items:
                    items_data = items['data']
                else:
                    items_data = items
                
                if items_data:
                    if hasattr(items_data[0], 'price'):
                        price_id = items_data[0].price.id
                    elif isinstance(items_data[0], dict) and 'price' in items_data[0]:
                        price_id = items_data[0]['price']['id']
            
            if not price_id:
                logger.error(f"No price ID found in subscription data for event {stripe_event_id}")
                return None
            
            # Find the user by Stripe customer ID
            user_result = await session.execute(
                select(User).where(User.stripe_customer_id == customer_id)
            )
            user = user_result.scalar_one_or_none()
            
            if not user:
                logger.error(f"User not found for Stripe customer {customer_id}")
                logger.error(f"This means the subscription was created outside our app flow")
                logger.error(f"You need to ensure users are connected to Stripe customers during subscription creation")
                return None
            
            # Find the subscription plan by Stripe price ID
            plan_result = await session.execute(
                select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == price_id)
            )
            plan = plan_result.scalar_one_or_none()
            
            if not plan:
                logger.error(f"Subscription plan not found for Stripe price {price_id}")
                return None
            
            # Find user's subscription record
            user_subscription_result = await session.execute(
                select(UserSubscription).where(
                    UserSubscription.user_id == user.id,
                    UserSubscription.stripe_subscription_id == subscription_id
                )
            )
            user_subscription = user_subscription_result.scalar_one_or_none()
            
            # Create transaction record
            transaction = Transaction(
                user_id=user.id,
                subscription_id=user_subscription.id if user_subscription else None,
                stripe_invoice_id=invoice_id,
                stripe_subscription_id=subscription_id,
                amount=amount,
                currency=currency,
                credits_awarded=plan.monthly_credits,
                plan_name=plan.name,
                billing_period=plan.interval,
                description=f"{plan.name} {plan.interval}ly subscription",
                stripe_processed_at=datetime.fromtimestamp(stripe_invoice_data.get('created', 0))
            )
            
            session.add(transaction)
            await session.flush()  # Get the transaction ID
            
            # Create Stripe event record for deduplication
            stripe_event = StripeEvent(
                stripe_event_id=stripe_event_id,
                event_type="invoice.payment_succeeded",
                processed=True,
                transaction_id=transaction.id,
                processed_at=datetime.now(),
                error_message=None
            )
            
            session.add(stripe_event)
            
            # Award credits to user via Redis
            await redis_credit_service.add_credits(user.id, plan.monthly_credits)
            
            # Update user's database credit balance for consistency
            user.credits_balance = await redis_credit_service.get_user_credits(user.id)
            
            await session.commit()
            
            logger.info(
                f"✅ Payment processed: User {user.email} paid ${amount/100:.2f} "
                f"for {plan.name} {plan.interval}ly, awarded {plan.monthly_credits} credits"
            )
            
            return transaction
            
        except Exception as e:
            await session.rollback()
            logger.error(f"❌ Error processing payment for event {stripe_event_id}: {str(e)}")
            raise e
    
    @staticmethod
    async def get_user_transactions(
        session: AsyncSession,
        user_id: int,
        limit: int = 10,
        offset: int = 0
    ) -> list[Transaction]:
        """Get transaction history for a user"""
        
        result = await session.execute(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        
        return result.scalars().all()
    
    @staticmethod
    async def get_transaction_by_stripe_invoice(
        session: AsyncSession,
        stripe_invoice_id: str
    ) -> Optional[Transaction]:
        """Find transaction by Stripe invoice ID"""
        
        result = await session.execute(
            select(Transaction).where(Transaction.stripe_invoice_id == stripe_invoice_id)
        )
        
        return result.scalar_one_or_none()
    
    @staticmethod
    async def get_or_create_stripe_customer(
        session: AsyncSession,
        user: User
    ) -> str:
        """
        Get or create a Stripe customer for the user and store the customer ID
        
        Args:
            session: Database session
            user: User object
            
        Returns:
            Stripe customer ID
        """
        
        # If user already has a Stripe customer ID, return it
        if user.stripe_customer_id:
            return user.stripe_customer_id
        
        try:
            # Create new Stripe customer
            stripe_customer = stripe.Customer.create(
                email=user.email,
                name=f"{user.first_name} {user.last_name}".strip() or user.email,
                metadata={
                    'user_id': str(user.id),
                    'clerk_id': user.clerk_id
                }
            )
            
            # Store the customer ID in our database
            user.stripe_customer_id = stripe_customer.id
            await session.commit()
            
            logger.info(f"✅ Created Stripe customer {stripe_customer.id} for user {user.email}")
            
            return stripe_customer.id
            
        except Exception as e:
            logger.error(f"❌ Error creating Stripe customer for user {user.email}: {str(e)}")
            raise e
    
    @staticmethod
    async def create_subscription_for_user(
        session: AsyncSession,
        user: User,
        price_id: str
    ) -> Dict[str, Any]:
        """
        Create a Stripe subscription for a user
        
        Args:
            session: Database session
            user: User object  
            price_id: Stripe price ID to subscribe to
            
        Returns:
            Dictionary with subscription details
        """
        
        try:
            # Get or create Stripe customer
            customer_id = await TransactionService.get_or_create_stripe_customer(session, user)
            
            # Create the subscription in Stripe
            subscription = stripe.Subscription.create(
                customer=customer_id,
                items=[{'price': price_id}],
                payment_behavior='default_incomplete',
                payment_settings={'save_default_payment_method': 'on_subscription'},
                expand=['latest_invoice.payment_intent'],
            )
            
            logger.info(f"✅ Created subscription {subscription.id} for user {user.email}")
            
            return {
                'subscription_id': subscription.id,
                'customer_id': customer_id,
                'client_secret': subscription.latest_invoice.payment_intent.client_secret,
                'status': subscription.status
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating subscription for user {user.email}: {str(e)}")
            raise e


# Create instance for import
transaction_service = TransactionService()
