# 📋 Clerk Setup Checklist

Since Clerk doesn't have CLI support, follow this checklist for each new project:

## 🔧 Manual Setup Steps

### 1. Create New Clerk Application
- [ ] Go to [Clerk Dashboard](https://dashboard.clerk.com/)
- [ ] Click "Create Application" 
- [ ] Enter your project name
- [ ] Choose authentication methods (Email, Google, etc.)

### 2. Configure Authentication
- [ ] Set up sign-in/sign-up methods
- [ ] Configure social providers if needed
- [ ] Set up custom domains (for production)

### 3. Get API Keys
- [ ] Copy `CLERK_PUBLISHABLE_KEY` (starts with `pk_`)
- [ ] Copy `CLERK_SECRET_KEY` (starts with `sk_`)
- [ ] Add both to your `.env` file

### 4. Configure Webhooks (Optional)
- [ ] Go to Webhooks section
- [ ] Add endpoint: `https://yourapp.com/api/v1/clerk/webhook`
- [ ] Select events: `user.created`, `user.updated`, `user.deleted`

### 5. Test Configuration
- [ ] Start your backend server
- [ ] Test JWT validation with a sample token
- [ ] Verify user creation/updates work

## 🔄 Per-Project Customization

Each project needs its own Clerk application because:
- Different domains/URLs
- Different branding
- Separate user bases
- Independent billing (if using Clerk's paid features)

## 📝 Quick Copy-Paste

```env
# Add to your .env file:
CLERK_SECRET_KEY=sk_test_your_new_key_here
CLERK_PUBLISHABLE_KEY=pk_test_your_new_key_here
```

## ⚡ Pro Tip

Create a naming convention for your Clerk apps:
- `myproject-dev` (development)
- `myproject-staging` (staging)  
- `myproject-prod` (production)
