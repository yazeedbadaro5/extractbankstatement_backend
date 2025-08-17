#!/bin/bash

# 🚀 Stripe Setup Script for New Projects
# This script automates the Stripe setup process using Stripe CLI

set -e  # Exit on any error

echo "🚀 Setting up Stripe for your new project..."

# Check if Stripe CLI is installed
if ! command -v stripe &> /dev/null; then
    echo "❌ Stripe CLI is not installed. Please install it first:"
    echo "   macOS: brew install stripe/stripe-cli/stripe"
    echo "   Other: https://stripe.com/docs/stripe-cli"
    exit 1
fi

# Check if user is logged in
if ! stripe config --list &> /dev/null; then
    echo "🔐 Please login to Stripe first:"
    echo "   stripe login"
    exit 1
fi

echo "📦 Creating subscription products and prices..."

# Create Basic Plan
echo "Creating Basic Plan..."
BASIC_PRODUCT=$(stripe products create \
    --name="Basic Plan" \
    --description="Basic subscription with essential features" \
    --format=json | jq -r '.id')

BASIC_PRICE=$(stripe prices create \
    --product="$BASIC_PRODUCT" \
    --unit-amount=999 \
    --currency=usd \
    --recurring.interval=month \
    --format=json | jq -r '.id')

echo "✅ Basic Plan: $BASIC_PRICE ($9.99/month)"

# Create Pro Plan
echo "Creating Pro Plan..."
PRO_PRODUCT=$(stripe products create \
    --name="Pro Plan" \
    --description="Professional subscription with advanced features" \
    --format=json | jq -r '.id')

PRO_PRICE=$(stripe prices create \
    --product="$PRO_PRODUCT" \
    --unit-amount=2999 \
    --currency=usd \
    --recurring.interval=month \
    --format=json | jq -r '.id')

echo "✅ Pro Plan: $PRO_PRICE ($29.99/month)"

# Create Enterprise Plan
echo "Creating Enterprise Plan..."
ENTERPRISE_PRODUCT=$(stripe products create \
    --name="Enterprise Plan" \
    --description="Enterprise subscription with unlimited features" \
    --format=json | jq -r '.id')

ENTERPRISE_PRICE=$(stripe prices create \
    --product="$ENTERPRISE_PRODUCT" \
    --unit-amount=9999 \
    --currency=usd \
    --recurring.interval=month \
    --format=json | jq -r '.id')

echo "✅ Enterprise Plan: $ENTERPRISE_PRICE ($99.99/month)"

# Get API keys
echo "🔑 Getting your API keys..."
STRIPE_CONFIG=$(stripe config --list)
SECRET_KEY=$(echo "$STRIPE_CONFIG" | grep "test_mode_api_key" | cut -d'=' -f2 | tr -d ' ')
PUBLIC_KEY=$(echo "$STRIPE_CONFIG" | grep "test_mode_pub_key" | cut -d'=' -f2 | tr -d ' ')

# Create migration file content
cat > migration_template.py << EOF
"""Add your project subscription plans

Revision ID: $(date +%s)
Create Date: $(date)
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    """Add subscription plans for this project."""
    connection = op.get_bind()
    
    # Basic Plan
    connection.execute(
        sa.text("""
            INSERT INTO subscription_plans (name, stripe_price_id, price, currency, interval, monthly_credits, is_active, created_at, updated_at)
            VALUES (:name, :stripe_price_id, :price, :currency, :interval, :monthly_credits, :is_active, NOW(), NOW())
        """),
        {
            "name": "Basic Plan",
            "stripe_price_id": "$BASIC_PRICE",
            "price": 999,
            "currency": "usd",
            "interval": "month",
            "monthly_credits": 100,
            "is_active": True
        }
    )
    
    # Pro Plan  
    connection.execute(
        sa.text("""
            INSERT INTO subscription_plans (name, stripe_price_id, price, currency, interval, monthly_credits, is_active, created_at, updated_at)
            VALUES (:name, :stripe_price_id, :price, :currency, :interval, :monthly_credits, :is_active, NOW(), NOW())
        """),
        {
            "name": "Pro Plan",
            "stripe_price_id": "$PRO_PRICE",
            "price": 2999,
            "currency": "usd",
            "interval": "month",
            "monthly_credits": 500,
            "is_active": True
        }
    )
    
    # Enterprise Plan
    connection.execute(
        sa.text("""
            INSERT INTO subscription_plans (name, stripe_price_id, price, currency, interval, monthly_credits, is_active, created_at, updated_at)
            VALUES (:name, :stripe_price_id, :price, :currency, :interval, :monthly_credits, :is_active, NOW(), NOW())
        """),
        {
            "name": "Enterprise Plan", 
            "stripe_price_id": "$ENTERPRISE_PRICE",
            "price": 9999,
            "currency": "usd",
            "interval": "month",
            "monthly_credits": 10000,
            "is_active": True
        }
    )

def downgrade() -> None:
    """Remove subscription plans."""
    connection = op.get_bind()
    connection.execute(
        sa.text("""
            DELETE FROM subscription_plans 
            WHERE stripe_price_id IN (
                '$BASIC_PRICE',
                '$PRO_PRICE',
                '$ENTERPRISE_PRICE'
            )
        """)
    )
EOF

echo ""
echo "🎉 Stripe setup complete!"
echo ""
echo "📋 Summary:"
echo "   Basic Plan:      $BASIC_PRICE ($9.99/month)"
echo "   Pro Plan:        $PRO_PRICE ($29.99/month)" 
echo "   Enterprise Plan: $ENTERPRISE_PRICE ($99.99/month)"
echo ""
echo "🔑 Add these to your .env file:"
echo "   STRIPE_SECRET_KEY=$SECRET_KEY"
echo "   STRIPE_PUBLISHABLE_KEY=$PUBLIC_KEY"
echo ""
echo "📝 Next steps:"
echo "   1. Copy the API keys to your .env file"
echo "   2. Create a new migration: alembic revision -m 'add_subscription_plans'"
echo "   3. Use the migration_template.py content created in this directory"
echo "   4. Run: alembic upgrade head"
echo "   5. Start webhook forwarding: stripe listen --forward-to localhost:8000/api/v1/subscriptions/webhook"
echo ""
echo "✨ Happy coding!"
