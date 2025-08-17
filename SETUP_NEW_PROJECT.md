# 🚀 Setting Up a New Project with This Base App

This base app provides a complete SaaS foundation with user authentication (Clerk) and subscription management (Stripe). Follow these steps to set up a new project:

## 📋 Prerequisites

- Python 3.11+
- PostgreSQL database
- Stripe account
- Clerk account

## 🔧 Setup Steps

### 1. **Clone and Setup Environment**

```bash
# Copy the base app to your new project directory
cp -r base-saas-app your-new-project
cd your-new-project/backend

# Clean up project-specific files (keep base schema migrations)
rm -f .env                      # Remove old environment file
rm -rf .git/                    # Remove git history (optional)

# Install dependencies
poetry install

# Copy environment template
cp env.example .env
```

### 2. **Create New Clerk Application**

1. Go to [Clerk Dashboard](https://dashboard.clerk.com/)
2. Create a new application for your project
3. Copy the API keys to your `.env` file:
   ```env
   CLERK_SECRET_KEY=sk_test_your_new_key
   CLERK_PUBLISHABLE_KEY=pk_test_your_new_key
   ```

### 3. **Setup Stripe for Your Project**

#### Option A: New Stripe Account (Recommended for separate projects)
1. Create new Stripe account at [stripe.com](https://stripe.com)
2. Get your API keys from the dashboard

#### Option B: Use Existing Stripe Account
1. Use your existing Stripe account
2. Create new products for this project

#### Add Stripe Keys to .env:
```env
STRIPE_SECRET_KEY=sk_test_your_key
STRIPE_PUBLISHABLE_KEY=pk_test_your_key
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret
```

### 4. **Create Your Subscription Plans**

```bash
# Login to Stripe CLI
stripe login

# Create your products and prices
stripe products create --name="Starter Plan" --description="Basic features"
stripe prices create --product="prod_YOUR_PRODUCT_ID" --unit-amount=999 --currency=usd --recurring.interval=month

# Repeat for other plans...
```

### 5. **Set Up Database**

The base app includes core schema migrations that you should keep:

```bash
# Run base schema migrations (creates users, subscription_plans, user_subscriptions tables)
poetry run alembic upgrade head
```

### 6. **Add Your Project-Specific Subscription Plans**

Create a new migration for your project's subscription plans:

```bash
# Create project-specific seeding migration
poetry run alembic revision -m "seed_[your_project_name]_subscription_plans"
```

Edit the migration file to add your specific plans:

```python
def upgrade() -> None:
    """Add subscription plans for [your project name]."""
    connection = op.get_bind()
    
    # Basic Plan
    connection.execute(
        sa.text("""
            INSERT INTO subscription_plans (name, stripe_price_id, price, currency, interval, monthly_credits, is_active, created_at, updated_at)
            VALUES (:name, :stripe_price_id, :price, :currency, :interval, :monthly_credits, :is_active, NOW(), NOW())
        """),
        {
            "name": "Basic Plan",
            "stripe_price_id": "price_YOUR_STRIPE_PRICE_ID",
            "price": 999,  # in cents
            "currency": "usd",
            "interval": "month",
            "monthly_credits": 100,
            "is_active": True
        }
    )
    
    # Add more plans as needed...

def downgrade() -> None:
    """Remove project-specific subscription plans."""
    connection = op.get_bind()
    connection.execute(
        sa.text("""
            DELETE FROM subscription_plans 
            WHERE stripe_price_id IN (
                'price_YOUR_STRIPE_PRICE_ID_1',
                'price_YOUR_STRIPE_PRICE_ID_2'
            )
        """)
    )
```

Run the new migration:

```bash
# Apply your project-specific data migration
poetry run alembic upgrade head
```

### 7. **Update Project Identity**

Customize the app for your project:

```python
# Edit src/main.py
app = FastAPI(
    title="Your Project Name API", 
    version="1.0.0",
    description="Description of your new project"
)

@app.get("/")
def read_root():
    logger.info("🚀 Root endpoint accessed")
    return {"message": "Your Project Name API - Ready!"}
```

### 8. **Test Your Setup**

```bash
# Start the server
poetry run uvicorn src.main:app --reload --port 8000

# In another terminal, start webhook forwarding
stripe listen --forward-to localhost:8000/api/v1/subscriptions/webhook

# Test the API
curl http://localhost:8000/api/v1/subscriptions/plans
```

### 9. **Initialize Git Repository (Optional)**

```bash
git init
git add .
git commit -m "Initial commit - [Your Project Name] based on SaaS foundation"
```

## 🎯 **What You Get Out of the Box**

- ✅ User authentication with Clerk
- ✅ Subscription management with Stripe
- ✅ Database models for users and subscriptions
- ✅ API endpoints for all subscription operations
- ✅ Webhook handling for Stripe events
- ✅ Credit-based usage tracking
- ✅ Customer portal integration

## 🔄 **For Each New Project**

1. **New Clerk App** - Each project should have its own Clerk application
2. **Stripe Setup** - Can reuse account but create new products/prices
3. **Database** - New database for each project (base schema stays the same)
4. **Environment Variables** - Project-specific keys and configuration
5. **Migration Strategy** - Keep base schema, add project-specific data migrations

## 📚 **API Endpoints Available**

- `GET /api/v1/subscriptions/plans` - List subscription plans
- `POST /api/v1/subscriptions/create` - Create subscription
- `GET /api/v1/subscriptions/current` - Get user's current subscription
- `POST /api/v1/subscriptions/portal` - Create customer portal session
- `POST /api/v1/subscriptions/{id}/cancel` - Cancel subscription
- `POST /api/v1/subscriptions/webhook` - Stripe webhook handler
- `GET /api/v1/users/me` - Get current user info

## 🚨 **Important Notes**

- **Keep Base Migrations:** Don't delete the core schema migrations - they're your reusable foundation
- **Separate Clerk Apps:** Always use separate Clerk applications for different projects
- **Stripe Strategy:** Can reuse Stripe account but create project-specific products/prices
- **Migration Pattern:** Base schema + project-specific data migrations
- **Database Per Project:** Each project should have its own database instance
- **Update Branding:** Customize the `main.py` title and description for your project

## 📊 **Migration Strategy Explained**

Your base app includes these **reusable migrations** (keep for all projects):

```
alembic/versions/
├── b7994129e4d1_initial_migration.py              # Core database setup
├── fd48b57b324c_add_users_table.py               # User management tables  
├── ac6b03077891_add_stripe_subscription_models.py # Subscription system tables
└── 1e2158bd6e61_seed_subscription_plans.py       # Empty placeholder (generic)
```

For each **new project**, add:

```
alembic/versions/
└── [timestamp]_seed_[project_name]_subscription_plans.py  # Your specific plans
└── [timestamp]_add_[project_name]_custom_tables.py        # Any custom tables
```

This approach gives you:
- ✅ **Consistent foundation** across all projects
- ✅ **Project-specific customization** without conflicts  
- ✅ **Easy maintenance** of core functionality
- ✅ **Clean separation** between base and custom features
