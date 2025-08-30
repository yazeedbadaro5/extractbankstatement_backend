"""initial_schema_seed_and_optimized_indexes

Revision ID: 0e3ab92a39ce
Revises: 
Create Date: 2025-08-26 12:12:23.095244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


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
    # 2. SEED SUBSCRIPTION PLANS DATA
    # ============================================================================
    
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
    
    # Seed data - All subscription plans
    plans_data = [
        # Free Plan
        {
            'name': 'Free',
            'stripe_price_id': 'free_plan',
            'price': 0,
            'currency': 'usd',
            'interval': 'month',
            'monthly_credits': 10,
            'is_active': True
        },
        
        # Starter Plans
        {
            'name': 'Starter',
            'stripe_price_id': 'price_1S1rEcLcJ2elVE4ir1pQyVH1',
            'price': 1500,  # $15.00
            'currency': 'usd',
            'interval': 'month',
            'monthly_credits': 400,
            'is_active': True
        },
        {
            'name': 'Starter',
            'stripe_price_id': 'price_1S1rFcLcJ2elVE4iJIjZMyrz',
            'price': 9000,  # $90.00
            'currency': 'usd',
            'interval': 'year',
            'monthly_credits': 4800,  # 12 months worth
            'is_active': True
        },
        
        # Professional Plans
        {
            'name': 'Professional',
            'stripe_price_id': 'price_1S1rG4LcJ2elVE4iP87WPTfe',
            'price': 3000,  # $30.00
            'currency': 'usd',
            'interval': 'month',
            'monthly_credits': 1000,
            'is_active': True
        },
        {
            'name': 'Professional',
            'stripe_price_id': 'price_1S1rGLLcJ2elVE4irpTTpkVy',
            'price': 18000,  # $180.00
            'currency': 'usd',
            'interval': 'year',
            'monthly_credits': 12000,  # 12 months worth
            'is_active': True
        },
        
        # Business Plans
        {
            'name': 'Business',
            'stripe_price_id': 'price_1S1rGoLcJ2elVE4iLm8qPt0n',
            'price': 5000,  # $50.00
            'currency': 'usd',
            'interval': 'month',
            'monthly_credits': 4000,
            'is_active': True
        },
        {
            'name': 'Business',
            'stripe_price_id': 'price_1S1rH2LcJ2elVE4i3HoEGuWq',
            'price': 30000,  # $300.00
            'currency': 'usd',
            'interval': 'year',
            'monthly_credits': 48000,  # 12 months worth
            'is_active': True
        }
    ]
    
    # Insert the plans using ORM bulk insert
    op.bulk_insert(subscription_plans, plans_data)


def downgrade() -> None:
    """Drop all tables (seed data and indexes will be removed automatically)."""
    op.drop_table('stripe_events')
    op.drop_table('transactions')
    op.drop_table('user_subscriptions')
    op.drop_table('subscription_plans')
    op.drop_table('users')
