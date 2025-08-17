"""Add Stripe subscription models and user credits

Revision ID: ac6b03077891
Revises: fd48b57b324c
Create Date: 2025-08-16 02:59:08.036819

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ac6b03077891'
down_revision: Union[str, Sequence[str], None] = 'fd48b57b324c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add credits columns to users table
    op.add_column('users', sa.Column('credits_balance', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('total_credits_used', sa.Integer(), nullable=False, server_default='0'))
    
    # Create subscription_plans table
    op.create_table('subscription_plans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('stripe_price_id', sa.String(), nullable=False),
        sa.Column('price', sa.Integer(), nullable=False),
        sa.Column('currency', sa.String(), nullable=False, server_default='usd'),
        sa.Column('interval', sa.String(), nullable=False, server_default='month'),
        sa.Column('monthly_credits', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_price_id')
    )
    
    # Create user_subscriptions table
    op.create_table('user_subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('stripe_subscription_id', sa.String(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('canceled_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stripe_subscription_id')
    )
    
    # Create indexes
    op.create_index('ix_subscription_plans_stripe_price_id', 'subscription_plans', ['stripe_price_id'], unique=False)
    op.create_index('ix_user_subscriptions_user_id', 'user_subscriptions', ['user_id'], unique=False)
    op.create_index('ix_user_subscriptions_plan_id', 'user_subscriptions', ['plan_id'], unique=False)
    op.create_index('ix_user_subscriptions_stripe_subscription_id', 'user_subscriptions', ['stripe_subscription_id'], unique=False)
    op.create_index('ix_user_subscriptions_stripe_customer_id', 'user_subscriptions', ['stripe_customer_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_user_subscriptions_stripe_customer_id', table_name='user_subscriptions')
    op.drop_index('ix_user_subscriptions_stripe_subscription_id', table_name='user_subscriptions')
    op.drop_index('ix_user_subscriptions_plan_id', table_name='user_subscriptions')
    op.drop_index('ix_user_subscriptions_user_id', table_name='user_subscriptions')
    op.drop_index('ix_subscription_plans_stripe_price_id', table_name='subscription_plans')
    
    # Drop tables
    op.drop_table('user_subscriptions')
    op.drop_table('subscription_plans')
    
    # Remove credits columns from users table
    op.drop_column('users', 'total_credits_used')
    op.drop_column('users', 'credits_balance')
