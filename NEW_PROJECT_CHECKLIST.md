# ✅ New Project Quick Checklist

Use this checklist when creating a new project from your SaaS base app.

## 📋 **Quick Setup Checklist**

### **1. Copy & Clean**
- [ ] `cp -r base-saas-app your-new-project`
- [ ] `cd your-new-project/backend`
- [ ] `rm -f .env` (remove old environment)
- [ ] `rm -rf .git/` (remove git history - optional)
- [ ] **✅ Keep all `alembic/versions/*.py` files** (they're your foundation!)

### **2. Environment Setup**
- [ ] `cp env.example .env`
- [ ] `poetry install`

### **3. Clerk Setup** 
- [ ] Create new Clerk application at [dashboard.clerk.com](https://dashboard.clerk.com/)
- [ ] Copy `CLERK_SECRET_KEY` to `.env`
- [ ] Copy `CLERK_PUBLISHABLE_KEY` to `.env`

### **4. Stripe Setup**
- [ ] Login: `stripe login`
- [ ] Create products: `stripe products create --name="Your Plan"`
- [ ] Create prices: `stripe prices create --product="prod_xxx" --unit-amount=999 --currency=usd --recurring.interval=month`
- [ ] Add `STRIPE_SECRET_KEY` to `.env`
- [ ] Add `STRIPE_PUBLISHABLE_KEY` to `.env` 
- [ ] Add `STRIPE_WEBHOOK_SECRET` to `.env`

### **5. Database Setup**
- [ ] Update database credentials in `.env`
- [ ] Run base migrations: `poetry run alembic upgrade head`
- [ ] Create project plans migration: `poetry run alembic revision -m "seed_[project]_plans"`
- [ ] Edit migration file with your subscription plans
- [ ] Apply migration: `poetry run alembic upgrade head`

### **6. Customize App**
- [ ] Edit `src/main.py` - update title, description, root message
- [ ] Test server: `poetry run uvicorn src.main:app --reload`
- [ ] Test webhook forwarding: `stripe listen --forward-to localhost:8000/api/v1/subscriptions/webhook`
- [ ] Test API: `curl http://localhost:8000/api/v1/subscriptions/plans`

### **7. Git Setup**
- [ ] `git init`
- [ ] `git add .`
- [ ] `git commit -m "Initial commit - [Project Name] SaaS foundation"`

## 🎯 **What Stays the Same (Don't Touch)**
- ✅ All `alembic/versions/*.py` migrations (your reusable foundation)
- ✅ All source code architecture
- ✅ Database models and schemas
- ✅ API endpoints structure
- ✅ Authentication system
- ✅ Webhook handling logic

## 🔄 **What Changes Per Project**
- 🔄 Environment variables (`.env`)
- 🔄 Clerk application (new keys)
- 🔄 Stripe products/prices (project-specific)
- 🔄 App branding (`main.py`)
- 🔄 Subscription plans (new migration)
- 🔄 Git repository

## ⚡ **Time Estimate**
- **Setup:** ~15 minutes
- **Testing:** ~5 minutes
- **Total:** ~20 minutes to launch a new SaaS project!

## 🚨 **Common Mistakes to Avoid**
- ❌ **DON'T** delete base migration files
- ❌ **DON'T** reuse the same Clerk application
- ❌ **DON'T** forget to update app branding
- ❌ **DON'T** skip testing the webhook forwarding
