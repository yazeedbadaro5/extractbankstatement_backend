"""initial_schema_seed_and_optimized_indexes

Revision ID: 0e3ab92a39ce
Revises: 
Create Date: 2025-08-26 12:12:23.095244

"""
from typing import Sequence, Union
import stripe

from alembic import op
import sqlalchemy as sa
from src.configuration.config import settings


# revision identifiers, used by Alembic.
revision: str = '0e3ab92a39ce'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables, seed essential data, and add optimized indexes using pure ORM."""
    
    # ============================================================================
    # 1. CREATE ALL TABLES
    # ============================================================================
    
    # Users table
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('clerk_id', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('first_name', sa.String(), nullable=True),
        sa.Column('last_name', sa.String(), nullable=True),
        sa.Column('credits_balance', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('stripe_customer_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_clerk_id'), 'users', ['clerk_id'], unique=True)
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_stripe_customer_id'), 'users', ['stripe_customer_id'], unique=False)

    # Subscription Plans table
    op.create_table('subscription_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('stripe_price_id', sa.String(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), server_default=sa.text("'usd'"), nullable=False),
        sa.Column('interval', sa.String(), nullable=False),
        sa.Column('monthly_credits', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subscription_plans_stripe_price_id'), 'subscription_plans', ['stripe_price_id'], unique=True)
    # Performance index for plan filtering (exclude "Free" plans)
    op.create_index('ix_subscription_plans_name', 'subscription_plans', ['name'])

    # User Subscriptions table
    op.create_table('user_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subscription_plan_id', sa.Integer(), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), server_default=sa.text("'active'"), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['subscription_plan_id'], ['subscription_plans.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_user_subscriptions_stripe_subscription_id'), 'user_subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index(op.f('ix_user_subscriptions_user_id'), 'user_subscriptions', ['user_id'], unique=False)
    # Performance indexes for subscription queries
    op.create_index('ix_user_subscriptions_status', 'user_subscriptions', ['status'])
    op.create_index('ix_user_subscriptions_user_status', 'user_subscriptions', ['user_id', 'status'])
    op.create_index('ix_user_subscriptions_user_created', 'user_subscriptions', ['user_id', 'created_at'])

    # Transactions table
    op.create_table('transactions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=True),
        sa.Column('stripe_payment_intent_id', sa.String(), nullable=True),
        sa.Column('stripe_invoice_id', sa.String(), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(), nullable=True),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), server_default=sa.text("'usd'"), nullable=False),
        sa.Column('credits_awarded', sa.Integer(), nullable=False),
        sa.Column('plan_name', sa.String(), nullable=False),
        sa.Column('billing_period', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=False),
        sa.Column('stripe_processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['subscription_id'], ['user_subscriptions.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_transactions_stripe_invoice_id'), 'transactions', ['stripe_invoice_id'], unique=False)
    op.create_index(op.f('ix_transactions_stripe_payment_intent_id'), 'transactions', ['stripe_payment_intent_id'], unique=False)
    op.create_index(op.f('ix_transactions_stripe_subscription_id'), 'transactions', ['stripe_subscription_id'], unique=False)
    op.create_index(op.f('ix_transactions_subscription_id'), 'transactions', ['subscription_id'], unique=False)
    op.create_index(op.f('ix_transactions_user_id'), 'transactions', ['user_id'], unique=False)
    # Performance indexes for transaction queries
    op.create_index('ix_transactions_stripe_processed_at', 'transactions', ['stripe_processed_at'])
    op.create_index('ix_transactions_user_processed', 'transactions', ['user_id', 'stripe_processed_at'])

    # Stripe Events table
    op.create_table('stripe_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('stripe_event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('processed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('transaction_id', sa.Integer(), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_stripe_events_stripe_event_id'), 'stripe_events', ['stripe_event_id'], unique=True)
    op.create_index(op.f('ix_stripe_events_transaction_id'), 'stripe_events', ['transaction_id'], unique=False)

    # ============================================================================
    # 2. SEED SUBSCRIPTION PLANS DATA (Environment-Aware)
    # ============================================================================
    
    # Get environment from settings
    environment = settings.environment
    
    # Define table structure for subscription_plans seeding
    metadata = sa.MetaData()
    subscription_plans = sa.Table(
        'subscription_plans',
        metadata,
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True)),
        sa.Column('name', sa.String),
        sa.Column('stripe_price_id', sa.String),
        sa.Column('price', sa.Integer),
        sa.Column('currency', sa.String),
        sa.Column('interval', sa.String),
        sa.Column('monthly_credits', sa.Integer),
        sa.Column('is_active', sa.Boolean),
    )
    
    def get_stripe_plans():
        """Fetch real Stripe products and prices"""
        try:
            stripe.api_key = settings.stripe_secret_key
            if not stripe.api_key or stripe.api_key == 'your_stripe_secret_key':
                print("⚠️  No valid Stripe API key found, using fallback data")
                return None
                
            print("🔄 Fetching products from Stripe...")
            products = stripe.Product.list(active=True, limit=100)
            prices = stripe.Price.list(active=True, limit=100)
            
            # Create a mapping of product_id to product
            products_map = {p.id: p for p in products.data}
            
            plans = []
            
            # Always add Free plan first (not in Stripe)
            plans.append({
                'name': 'Free',
                'stripe_price_id': 'free_plan',
                'price': 0,
                'currency': 'usd',
                'interval': 'month',
                'monthly_credits': 10,
                'is_active': True
            })
            
            # Add Stripe plans
            for price in prices.data:
                if price.product in products_map:
                    product = products_map[price.product]
                    
                    # Extract credits from product metadata or use defaults based on price
                    if price.unit_amount:
                        if price.unit_amount <= 1500:  # $15 or less
                            default_credits = 400
                        elif price.unit_amount <= 3000:  # $30 or less  
                            default_credits = 1000
                        else:  # More than $30
                            default_credits = 4000
                    else:
                        default_credits = 100
                        
                    monthly_credits = int(product.metadata.get('monthly_credits', default_credits))
                    
                    # For yearly plans, multiply by 12
                    if price.recurring and price.recurring.interval == 'year':
                        monthly_credits = monthly_credits * 12
                    
                    plans.append({
                        'name': product.name,
                        'stripe_price_id': price.id,
                        'price': price.unit_amount or 0,
                        'currency': price.currency,
                        'interval': price.recurring.interval if price.recurring else 'month',
                        'monthly_credits': monthly_credits,
                        'is_active': True
                    })
            
            print(f"✅ Fetched {len(plans)} plans from Stripe (including Free plan)")
            return plans
            
        except Exception as e:
            print(f"❌ Error fetching from Stripe: {e}")
            return None
    
    # Get live Stripe data - no fallback
    plans_data = get_stripe_plans()
    
    if not plans_data:
        raise Exception(f"❌ Failed to fetch Stripe data for {environment} environment. Migration cannot proceed without valid subscription plans.")
    
    print(f"🚀 Seeding {len(plans_data)} subscription plans for {environment} environment")
    
    # Insert the plans using ORM bulk insert
    op.bulk_insert(subscription_plans, plans_data)


def downgrade() -> None:
    """Drop all tables (seed data and indexes will be removed automatically)."""
    op.drop_table('stripe_events')
    op.drop_table('transactions')
    op.drop_table('user_subscriptions')
    op.drop_table('subscription_plans')
    op.drop_table('users')
