# 🚀 SaaS Base App - Complete Foundation for Your Next Project

A production-ready SaaS backend foundation built with FastAPI, featuring user authentication (Clerk) and subscription management (Stripe). Perfect for quickly launching new SaaS projects.

## ✨ Features

- 🔐 **User Authentication** - Complete Clerk integration with JWT validation
- 💳 **Subscription Management** - Full Stripe integration with webhook handling
- 📊 **Credit System** - Built-in usage tracking and limits
- 🗄️ **Database Ready** - PostgreSQL with Alembic migrations
- 🔧 **Production Ready** - Proper logging, error handling, and configuration
- 📚 **API Documentation** - Auto-generated OpenAPI/Swagger docs
- 🎯 **Modular Architecture** - Clean separation of concerns

## 🏗️ Architecture

```
src/
├── configuration/     # App configuration and settings
├── database.py       # Database connection and session management
├── middleware/       # Custom middleware (auth, etc.)
├── models/          # SQLAlchemy database models
├── routers/         # FastAPI route handlers
├── schemas/         # Pydantic models for API
├── services/        # Business logic (Stripe, Clerk)
└── utils/           # Utilities (logging, etc.)
```

## 🚀 Quick Start

### For New Projects
See [SETUP_NEW_PROJECT.md](./SETUP_NEW_PROJECT.md) for detailed setup instructions.

### For Development
```bash
# Install dependencies
poetry install

# Set up environment
cp env.example .env
# Edit .env with your keys

# Run migrations
poetry run alembic upgrade head

# Start server
poetry run uvicorn src.main:app --reload
```

## 📋 API Endpoints

### Authentication
- All endpoints require Clerk JWT token in Authorization header
- Format: `Authorization: Bearer <your-clerk-jwt-token>`

### Subscriptions
- `GET /api/v1/subscriptions/plans` - List available plans
- `POST /api/v1/subscriptions/create` - Create new subscription
- `GET /api/v1/subscriptions/current` - Get user's subscription
- `POST /api/v1/subscriptions/portal` - Customer portal access
- `POST /api/v1/subscriptions/{id}/cancel` - Cancel subscription
- `POST /api/v1/subscriptions/webhook` - Stripe webhook handler

### Users
- `GET /api/v1/users/me` - Get current user profile

## 🔧 Configuration

Key environment variables:

```env
# Database
DB_HOST=localhost
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=your_database

# Clerk Authentication
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...

# Stripe Payments
STRIPE_SECRET_KEY=sk_test_...
STRIPE_PUBLISHABLE_KEY=pk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

## 🏭 Production Deployment

1. **Environment Variables** - Set all required env vars
2. **Database** - Run migrations: `alembic upgrade head`
3. **Webhooks** - Configure Stripe webhook endpoint
4. **CORS** - Update allowed origins in `main.py`
5. **Logging** - Configure appropriate log levels

## 🛠️ Tech Stack

- **FastAPI** - Modern Python web framework
- **SQLAlchemy** - ORM with async support
- **Alembic** - Database migrations
- **PostgreSQL** - Primary database
- **Clerk** - User authentication and management
- **Stripe** - Payment processing and subscriptions
- **Pydantic** - Data validation and serialization
- **Poetry** - Dependency management

## 📈 Scaling Considerations

This base app is designed to scale:

- **Database** - PostgreSQL with proper indexing
- **Authentication** - Stateless JWT tokens
- **Caching** - Ready for Redis integration
- **Monitoring** - Structured logging throughout
- **Testing** - Modular architecture for easy testing

## 🤝 Contributing

This is a base template - fork it for your projects and customize as needed!

## 📄 License

MIT License - feel free to use for commercial projects.
