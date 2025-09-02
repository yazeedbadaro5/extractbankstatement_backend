from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
from dateutil.relativedelta import relativedelta
import stripe
import json
import time

from src.database import get_db
from src.configuration.config import settings
from src.services.transaction_service import transaction_service
from src.utils.logger import get_logger
from src.models.user import User
from src.models.user_subscription import UserSubscription
from src.models.subscription_plan import SubscriptionPlan

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["stripe-webhooks"])

# Configure Stripe
stripe.api_key = settings.stripe_secret_key


@router.post("/stripe")
async def handle_stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """Handle Stripe webhook events"""
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')
    
    try:
        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        
        logger.info(f"📨 Received Stripe webhook: {event['type']} - {event['id']}")
        
        # Log the full event structure for debugging
        logger.info(f"🔍 Full webhook event structure:")
        logger.info(f"   Event type: {event['type']}")
        logger.info(f"   Event ID: {event['id']}")
        logger.info(f"   Created: {event.get('created')}")
        logger.info(f"   Data object keys: {list(event['data']['object'].keys())}")
        
        # Handle invoice payment succeeded
        if event['type'] == 'invoice.payment_succeeded':
            await handle_payment_succeeded(db, event)
        
        # Handle invoice created (contains billing period dates)
        elif event['type'] == 'invoice.created':
            await handle_invoice_created(db, event)
        
        # Handle invoice finalized (when invoice is ready for payment)
        elif event['type'] == 'invoice.finalized':
            await handle_invoice_finalized(db, event)
        
        # Handle invoice paid (when payment is completed)
        elif event['type'] == 'invoice.paid':
            await handle_invoice_paid(db, event)
        
        # Handle checkout session completed
        elif event['type'] == 'checkout.session.completed':
            await handle_checkout_completed(db, event)
        
        # Handle other subscription events
        elif event['type'] == 'customer.subscription.created':
            await handle_subscription_created(db, event)
        
        elif event['type'] == 'customer.subscription.updated':
            await handle_subscription_updated(db, event)
        
        elif event['type'] == 'customer.subscription.deleted':
            await handle_subscription_deleted(db, event)
        
        else:
            logger.info(f"ℹ️  Unhandled webhook type: {event['type']}")
        
        return {"status": "success"}
        
    except stripe.error.SignatureVerificationError:
        logger.error("❌ Invalid Stripe webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")
    except Exception as e:
        logger.error(f"❌ Error processing Stripe webhook: {str(e)}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")


async def handle_payment_succeeded(db: AsyncSession, event):
    """Handle successful payment and award credits"""
    
    try:
        invoice_data = event['data']['object']
        invoice_id = invoice_data.get('id')
        
        logger.info(f"💰 Processing payment for invoice: {invoice_id}")
        
        # For subscription invoices, get subscription ID from the invoice
        # Check both direct subscription field and lines data
        subscription_id = invoice_data.get('subscription')
        
        # If no direct subscription, try to get it from invoice lines
        if not subscription_id:
            lines = invoice_data.get('lines', {}).get('data', [])
            if lines:
                line_item = lines[0]
                subscription_id = line_item.get('subscription')
                
                # If still no subscription, check the parent.subscription_item_details.subscription path
                if not subscription_id and line_item.get('parent', {}).get('subscription_item_details'):
                    subscription_id = line_item['parent']['subscription_item_details'].get('subscription')
                    logger.info(f"📋 Found subscription ID from parent.subscription_item_details: {subscription_id}")
                else:
                    logger.info(f"📋 Found subscription ID from lines: {subscription_id}")
        
        if not subscription_id:
            logger.error(f"No subscription ID found in invoice {invoice_id}")
            return
        
        logger.info(f"📋 Found subscription ID: {subscription_id}")
        
        # Get subscription details from Stripe
        subscription_data = None
        try:
            subscription_obj = stripe.Subscription.retrieve(subscription_id)
            # Convert Stripe object to dict for transaction service
            subscription_data = subscription_obj.to_dict() if subscription_obj else None
            logger.info(f"✅ Retrieved subscription data from Stripe")
        except Exception as e:
            logger.error(f"❌ Error retrieving subscription {subscription_id}: {str(e)}")
            return
        
        # Record the transaction and award credits
        transaction = await transaction_service.record_successful_payment(
            session=db,
            stripe_event_id=event['id'],
            stripe_invoice_data=invoice_data,
            stripe_subscription_data=subscription_data
        )
        
        if transaction:
            logger.info(
                f"✅ Payment processed successfully: "
                f"${transaction.amount/100:.2f} → {transaction.credits_awarded} credits"
            )
        else:
            logger.info("ℹ️  Payment already processed (duplicate webhook)")
            
    except Exception as e:
        logger.error(f"❌ Error handling payment succeeded: {str(e)}")
        raise e


async def handle_invoice_created(db: AsyncSession, event):
    """Handle invoice creation to record billing period dates"""
    
    try:
        invoice_data = event['data']['object']
        invoice_id = invoice_data.get('id')
        
        logger.info(f"📅 Recording billing period for invoice: {invoice_id}")
        
        # Log the raw timestamp data from Stripe
        # The invoice has period_start and period_end directly, not nested under 'period'
        current_period_start_ts = invoice_data.get('period_start')
        current_period_end_ts = invoice_data.get('period_end')
        
        logger.info(f"📅 Stripe timestamp data for invoice {invoice_id}:")
        logger.info(f"   current_period_start timestamp: {current_period_start_ts}")
        logger.info(f"   current_period_end timestamp: {current_period_end_ts}")
        
        # Convert timestamps to datetime objects
        if current_period_start_ts:
            current_period_start = datetime.fromtimestamp(current_period_start_ts)
            # Use Stripe's actual period_end timestamp if available
            if current_period_end_ts:
                current_period_end = datetime.fromtimestamp(current_period_end_ts)
            else:
                # Fallback: add 1 month to period_start
                current_period_end = current_period_start + relativedelta(months=1)
        else:
            current_period_start = datetime(1970, 1, 1, 2, 0, 0)  # Epoch fallback
            current_period_end = datetime(1970, 1, 1, 2, 0, 0)   # Epoch fallback
            
        # Find the user associated with the invoice
        customer_id = invoice_data.get('customer')
        if not customer_id:
            logger.error(f"No customer ID found in invoice {invoice_id}")
            return
        
        user_result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"No user found for customer ID: {customer_id}")
            return
        
        # Find the subscription associated with the invoice
        # Check both direct subscription field and lines data
        subscription_id = invoice_data.get('subscription')
        
        # If no direct subscription, try to get it from invoice lines
        if not subscription_id:
            lines = invoice_data.get('lines', {}).get('data', [])
            if lines:
                line_item = lines[0]
                subscription_id = line_item.get('subscription')
                
                # If still no subscription, check the parent.subscription_item_details.subscription path
                if not subscription_id and line_item.get('parent', {}).get('subscription_item_details'):
                    subscription_id = line_item['parent']['subscription_item_details'].get('subscription')
                    logger.info(f"📋 Found subscription ID from parent.subscription_item_details: {subscription_id}")
                else:
                    logger.info(f"📋 Found subscription ID from lines: {subscription_id}")
        
        if not subscription_id:
            logger.error(f"No subscription ID found in invoice {invoice_id}")
            return
        
        logger.info(f"📋 Found subscription ID: {subscription_id}")
        
        user_subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = user_subscription_result.scalar_one_or_none()
        
        if user_subscription:
            user_subscription.current_period_start = current_period_start
            user_subscription.current_period_end = current_period_end
            logger.info(f"✅ Updated billing period for existing subscription {user_subscription.id}")
            logger.info(f"   Set current_period_start: {current_period_start}")
            logger.info(f"   Set current_period_end: {current_period_end}")
        else:
            logger.error(f"No subscription found for user {user.email} and subscription ID {subscription_id}")
        
        await db.commit()
        
    except Exception as e:
        logger.error(f"Error handling invoice created: {e}")
        await db.rollback()
        raise


async def handle_invoice_finalized(db: AsyncSession, event):
    """Handle invoice finalized event"""
    try:
        invoice_data = event['data']['object']
        invoice_id = invoice_data.get('id')
        logger.info(f"📅 Invoice {invoice_id} finalized.")

        # Find the user associated with the invoice
        customer_id = invoice_data.get('customer')
        if not customer_id:
            logger.error(f"No customer ID found in invoice {invoice_id}")
            return

        user_result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"No user found for customer ID: {customer_id}")
            return

        # Find the subscription associated with the invoice
        # Check both direct subscription field and lines data
        subscription_id = invoice_data.get('subscription')
        
        # If no direct subscription, try to get it from invoice lines
        if not subscription_id:
            lines = invoice_data.get('lines', {}).get('data', [])
            if lines:
                line_item = lines[0]
                subscription_id = line_item.get('subscription')
                
                # If still no subscription, check the parent.subscription_item_details.subscription path
                if not subscription_id and line_item.get('parent', {}).get('subscription_item_details'):
                    subscription_id = line_item['parent']['subscription_item_details'].get('subscription')
                    logger.info(f"📋 Found subscription ID from parent.subscription_item_details: {subscription_id}")
                else:
                    logger.info(f"📋 Found subscription ID from lines: {subscription_id}")
        
        if not subscription_id:
            logger.error(f"No subscription ID found in invoice {invoice_id}")
            return

        user_subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = user_subscription_result.scalar_one_or_none()

        if user_subscription:
            # The current_period_start and current_period_end are already set by handle_invoice_created
            # or handle_subscription_created. No need to update here unless specific logic is needed.
            logger.info(f"✅ Invoice {invoice_id} finalized for existing subscription {user_subscription.id}")
        else:
            logger.error(f"No subscription found for user {user.email} and subscription ID {subscription_id}")

        await db.commit()
    except Exception as e:
        logger.error(f"Error handling invoice finalized: {e}")
        await db.rollback()
        raise


async def handle_invoice_paid(db: AsyncSession, event):
    """Handle invoice paid event"""
    try:
        invoice_data = event['data']['object']
        invoice_id = invoice_data.get('id')
        logger.info(f"📅 Invoice {invoice_id} paid.")

        # Find the user associated with the invoice
        customer_id = invoice_data.get('customer')
        if not customer_id:
            logger.error(f"No customer ID found in invoice {invoice_id}")
            return

        # Find the subscription associated with the invoice
        # Check both direct subscription field and lines data
        subscription_id = invoice_data.get('subscription')
        
        # If no direct subscription, try to get it from invoice lines
        if not subscription_id:
            lines = invoice_data.get('lines', {}).get('data', [])
            if lines:
                line_item = lines[0]
                subscription_id = line_item.get('subscription')
                
                # If still no subscription, check the parent.subscription_item_details.subscription path
                if not subscription_id and line_item.get('parent', {}).get('subscription_item_details'):
                    subscription_id = line_item['parent']['subscription_item_details'].get('subscription')
                    logger.info(f"📋 Found subscription ID from parent.subscription_item_details: {subscription_id}")
                else:
                    logger.info(f"📋 Found subscription ID from lines: {subscription_id}")
        
        if not subscription_id:
            logger.error(f"No subscription ID found in invoice {invoice_id}")
            return

        user_result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"No user found for customer ID: {customer_id}")
            return

        user_subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = user_subscription_result.scalar_one_or_none()

        if user_subscription:
            # The current_period_start and current_period_end are already set by handle_invoice_created
            # or handle_subscription_created. No need to update here unless specific logic is needed.
            logger.info(f"✅ Invoice {invoice_id} paid for existing subscription {user_subscription.id}")
        else:
            logger.error(f"No subscription found for user {user.email} and subscription ID {subscription_id}")

        await db.commit()
    except Exception as e:
        logger.error(f"Error handling invoice paid: {e}")
        await db.rollback()
        raise


async def handle_checkout_completed(db: AsyncSession, event):
    """Handle checkout session completed event to capture subscription details"""
    try:
        checkout_session_data = event['data']['object']
        checkout_session_id = checkout_session_data.get('id')
        customer_id = checkout_session_data.get('customer')
        subscription_id = checkout_session_data.get('subscription')

        logger.info(f"📦 Checkout session completed: {checkout_session_id} for customer: {customer_id}")

        if not customer_id:
            logger.error(f"No customer ID found in checkout session {checkout_session_id}")
            return

        if not subscription_id:
            logger.error(f"No subscription ID found in checkout session {checkout_session_id}")
            return

        # Find the user associated with the customer ID
        user_result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user_result.scalar_one_or_none()

        if not user:
            logger.error(f"No user found for customer ID: {customer_id}")
            return

        # Find the subscription plan associated with the subscription ID
        # This assumes the price ID in the checkout session is the same as the subscription plan's price ID
        # and that the subscription plan exists.
        price_id = checkout_session_data.get('display_items', [{}])[0].get('price', {}).get('id')
        if not price_id:
            logger.error(f"No price ID found in checkout session {checkout_session_id}")
            return

        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == price_id)
        )
        plan = plan_result.scalar_one_or_none()

        if not plan:
            logger.error(f"No subscription plan found for price ID: {price_id}")
            return

        # Cancel any existing active subscriptions (user can only have 1 active at a time)
        existing_active_subscriptions = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.status.in_(["active", "trialing", "past_due"]),
                UserSubscription.stripe_subscription_id != subscription_id
            )
        )
        for existing_sub in existing_active_subscriptions.scalars():
            existing_sub.status = "canceled"
            existing_sub.canceled_at = datetime.now()
            logger.info(f"🔄 Canceled previous subscription {existing_sub.id} for user {user.email}")

        # Check if this specific subscription already exists
        existing_subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        existing_subscription = existing_subscription_result.scalar_one_or_none()

        # Log the raw timestamp data from Stripe
        current_period_start_ts = checkout_session_data.get('subscription_data', {}).get('current_period_start')
        current_period_end_ts = checkout_session_data.get('subscription_data', {}).get('current_period_end')

        logger.info(f"📅 Stripe timestamp data for checkout session {checkout_session_id}:")
        logger.info(f"   current_period_start timestamp: {current_period_start_ts}")
        logger.info(f"   current_period_end timestamp: {current_period_end_ts}")

        if current_period_start_ts:
            current_period_start_dt = datetime.fromtimestamp(current_period_start_ts)
            logger.info(f"   current_period_start datetime: {current_period_start_dt}")
        else:
            current_period_start_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_start timestamp, using epoch: {current_period_start_dt}")

        if current_period_end_ts:
            current_period_end_dt = datetime.fromtimestamp(current_period_end_ts)
            logger.info(f"   current_period_end datetime: {current_period_end_dt}")
        else:
            current_period_end_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_end timestamp, using epoch: {current_period_end_dt}")

        if existing_subscription:
            # Update existing subscription
            existing_subscription.status = "active" # Assuming active status for new subscriptions
            existing_subscription.current_period_start = current_period_start_dt
            existing_subscription.current_period_end = current_period_end_dt

            logger.info(f"✅ Updated existing subscription: {existing_subscription.id}")
            logger.info(f"   Set current_period_start: {current_period_start_dt}")
            logger.info(f"   Set current_period_end: {current_period_end_dt}")
        else:
            # Create new subscription
            user_subscription = UserSubscription(
                user_id=user.id,
                subscription_plan_id=plan.id,
                stripe_subscription_id=subscription_id,
                status="active", # Assuming active status for new subscriptions
                current_period_start=current_period_start_dt,
                current_period_end=current_period_end_dt
            )
            
            db.add(user_subscription)
            logger.info(f"✅ Created new subscription for user {user.email}: {plan.name}")
            logger.info(f"   Set current_period_start: {current_period_start_dt}")
            logger.info(f"   Set current_period_end: {current_period_end_dt}")
        
        await db.commit()
        
    except Exception as e:
        logger.error(f"Error handling checkout completed: {e}")
        await db.rollback()
        raise


async def handle_subscription_created(db: AsyncSession, event):
    """Handle subscription creation"""
    
    try:
        subscription_data = event['data']['object']
        customer_id = subscription_data.get('customer')
        subscription_id = subscription_data.get('id')
        status = subscription_data.get('status')
        
        logger.info(f"🆕 Creating subscription: {subscription_id} for customer: {customer_id}")
        
        # Find user by Stripe customer ID
        user_result = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            logger.error(f"No user found for customer ID: {customer_id}")
            return
        
        # Get price ID from subscription items
        items = subscription_data.get('items', {}).get('data', [])
        if not items:
            logger.error(f"No items found in subscription {subscription_id}")
            return
        
        price_id = items[0].get('price', {}).get('id')
        if not price_id:
            logger.error(f"No price ID found in subscription {subscription_id}")
            return
        
        # Find the subscription plan
        plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.stripe_price_id == price_id)
        )
        plan = plan_result.scalar_one_or_none()
        
        if not plan:
            logger.error(f"No subscription plan found for price ID: {price_id}")
            return
        
        # Cancel any existing active subscriptions (user can only have 1 active at a time)
        existing_active_subscriptions = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.status.in_(["active", "trialing", "past_due"]),
                UserSubscription.stripe_subscription_id != subscription_id
            )
        )
        for existing_sub in existing_active_subscriptions.scalars():
            existing_sub.status = "canceled"
            existing_sub.canceled_at = datetime.now()
            logger.info(f"🔄 Canceled previous subscription {existing_sub.id} for user {user.email}")
        
        # Check if this specific subscription already exists
        existing_subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.user_id == user.id,
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        existing_subscription = existing_subscription_result.scalar_one_or_none()
        
        # Log the raw timestamp data from Stripe
        current_period_start_ts = subscription_data.get('current_period_start')
        current_period_end_ts = subscription_data.get('current_period_end')
        
        logger.info(f"📅 Stripe timestamp data for subscription {subscription_id}:")
        logger.info(f"   current_period_start timestamp: {current_period_start_ts}")
        logger.info(f"   current_period_end timestamp: {current_period_end_ts}")
        
        if current_period_start_ts:
            current_period_start_dt = datetime.fromtimestamp(current_period_start_ts)
            logger.info(f"   current_period_start datetime: {current_period_start_dt}")
        else:
            current_period_start_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_start timestamp, using epoch: {current_period_start_dt}")
            
        if current_period_end_ts:
            current_period_end_dt = datetime.fromtimestamp(current_period_end_ts)
            logger.info(f"   current_period_end datetime: {current_period_end_dt}")
        else:
            current_period_end_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_end timestamp, using epoch: {current_period_end_dt}")
        
        if existing_subscription:
            # Update existing subscription
            existing_subscription.status = status
            existing_subscription.current_period_start = current_period_start_dt
            existing_subscription.current_period_end = current_period_end_dt

            logger.info(f"✅ Updated existing subscription: {existing_subscription.id}")
            logger.info(f"   Set current_period_start: {current_period_start_dt}")
            logger.info(f"   Set current_period_end: {current_period_end_dt}")
        else:
            # Create new subscription
            user_subscription = UserSubscription(
                user_id=user.id,
                subscription_plan_id=plan.id,
                stripe_subscription_id=subscription_id,
                status=status,
                current_period_start=current_period_start_dt,
                current_period_end=current_period_end_dt
            )
            
            db.add(user_subscription)
            logger.info(f"✅ Created new subscription for user {user.email}: {plan.name}")
            logger.info(f"   Set current_period_start: {current_period_start_dt}")
            logger.info(f"   Set current_period_end: {current_period_end_dt}")
        
        await db.commit()
        
    except Exception as e:
        logger.error(f"Error handling subscription created: {e}")
        await db.rollback()
        raise


async def handle_subscription_updated(db: AsyncSession, event):
    """Handle subscription updates"""
    
    try:
        subscription_data = event['data']['object']
        subscription_id = subscription_data.get('id')
        status = subscription_data.get('status')
        
        logger.info(f"🔄 Updating subscription: {subscription_id} to status: {status}")
        
        # Find existing subscription
        subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = subscription_result.scalar_one_or_none()
        
        if not user_subscription:
            logger.error(f"No subscription found for ID: {subscription_id}")
            return
        
        # Log the raw timestamp data from Stripe
        current_period_start_ts = subscription_data.get('current_period_start')
        current_period_end_ts = subscription_data.get('current_period_end')
        canceled_at_ts = subscription_data.get('canceled_at')
        
        logger.info(f"📅 Stripe timestamp data for subscription update {subscription_id}:")
        logger.info(f"   current_period_start timestamp: {current_period_start_ts}")
        logger.info(f"   current_period_end timestamp: {current_period_end_ts}")
        logger.info(f"   canceled_at timestamp: {canceled_at_ts}")
        
        if current_period_start_ts:
            current_period_start_dt = datetime.fromtimestamp(current_period_start_ts)
            logger.info(f"   current_period_start datetime: {current_period_start_dt}")
        else:
            current_period_start_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_start timestamp, using epoch: {current_period_start_dt}")
            
        if current_period_end_ts:
            current_period_end_dt = datetime.fromtimestamp(current_period_end_ts)
            logger.info(f"   current_period_end datetime: {current_period_end_dt}")
        else:
            current_period_end_dt = datetime.fromtimestamp(0)
            logger.warning(f"⚠️  No current_period_end timestamp, using epoch: {current_period_end_dt}")
        
        # Update subscription details
        user_subscription.status = status
        user_subscription.current_period_start = current_period_start_dt
        user_subscription.current_period_end = current_period_end_dt

        if canceled_at_ts:
            canceled_at_dt = datetime.fromtimestamp(canceled_at_ts)
            user_subscription.canceled_at = canceled_at_dt
            logger.info(f"   Set canceled_at: {canceled_at_dt}")
        
        await db.commit()
        logger.info(f"✅ Updated subscription: {user_subscription.id}")
        logger.info(f"   Set current_period_start: {current_period_start_dt}")
        logger.info(f"   Set current_period_end: {current_period_end_dt}")
        
    except Exception as e:
        logger.error(f"Error handling subscription updated: {e}")
        await db.rollback()
        raise


async def handle_subscription_deleted(db: AsyncSession, event):
    """Handle subscription cancellation"""
    
    try:
        subscription_data = event['data']['object']
        subscription_id = subscription_data.get('id')
        
        logger.info(f"❌ Canceling subscription: {subscription_id}")
        
        # Find existing subscription
        subscription_result = await db.execute(
            select(UserSubscription).where(
                UserSubscription.stripe_subscription_id == subscription_id
            )
        )
        user_subscription = subscription_result.scalar_one_or_none()
        
        if not user_subscription:
            logger.error(f"No subscription found for ID: {subscription_id}")
            return
        
        # Update subscription status
        user_subscription.status = 'canceled'
        user_subscription.canceled_at = datetime.fromtimestamp(subscription_data.get('canceled_at', time.time()))
        
        # Get the user ID for creating a new Free subscription
        user_id = user_subscription.user_id
        
        # Find the Free plan
        free_plan_result = await db.execute(
            select(SubscriptionPlan).where(SubscriptionPlan.name == "Free")
        )
        free_plan = free_plan_result.scalar_one_or_none()
        
        if free_plan:
            # Create a new Free subscription for the user
            free_subscription = UserSubscription(
                user_id=user_id,
                subscription_plan_id=free_plan.id,
                stripe_subscription_id=f"free_{user_id}_{int(time.time())}",
                status="active",
                current_period_start=datetime.now(),
                current_period_end=datetime(2099, 12, 31)  # Far future date for free plan
            )
            
            db.add(free_subscription)
            logger.info(f"✅ Auto-created Free subscription for user {user_id} after paid subscription cancellation")
        else:
            logger.error("❌ Could not find Free plan to create fallback subscription")
        
        await db.commit()
        logger.info(f"✅ Canceled subscription: {user_subscription.id} and created Free subscription")
        
    except Exception as e:
        logger.error(f"Error handling subscription deleted: {e}")
        await db.rollback()
        raise
