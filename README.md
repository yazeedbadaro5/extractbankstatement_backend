# 📄 Bank Statement Extraction API

A production-ready bank statement extraction service built with FastAPI and AI-powered processing. Extracts and processes bank statements from various formats with intelligent data extraction capabilities.

## ✨ Features

- 📄 **PDF Processing** - Extract data from bank statement PDFs using PyMuPDF
- 🤖 **AI-Powered Extraction** - LangChain with Google Gemini AI for intelligent data processing
- 🔐 **User Authentication** - Complete Clerk integration with JWT validation
- 💳 **Subscription Management** - Full Stripe integration with webhook handling
- 📊 **Credit System** - Built-in usage tracking and limits
- 📋 **Multiple Formats** - Support for PDF, Excel (XLSX), and other document formats
- ⚡ **Async Processing** - Celery with Redis for background task processing
- 🛡️ **Rate Limiting** - Built-in API rate limiting with Redis
- 🗄️ **Database Ready** - PostgreSQL with SQLAlchemy and Alembic migrations
- ☁️ **Cloud Storage** - Azure Blob Storage integration for file handling
- 🔧 **Production Ready** - Docker containerization, proper logging, and error handling
- 📚 **API Documentation** - Auto-generated OpenAPI/Swagger docs

## 🏗️ Architecture

```
src/
├── configuration/     # App configuration and settings
├── database.py       # Database connection and session management
├── celery_app.py     # Celery configuration for async tasks
├── middleware/       # Custom middleware (auth, CORS, etc.)
├── models/          # SQLAlchemy database models
├── routers/         # FastAPI route handlers
│   ├── users.py     # User management endpoints
│   ├── subscriptions.py # Subscription management
│   ├── pdf.py       # Bank statement processing
│   └── stripe_webhooks.py # Webhook handlers
├── schemas/         # Pydantic models for API validation
├── services/        # Business logic (AI, Stripe, Clerk, Azure)
└── utils/           # Utilities (logging, etc.)
```

## 🚀 Quick Start

### For Development
```bash
# Install dependencies
poetry install

# Set up environment
cp env.example .env
# Edit .env with your keys (see Configuration section)

# Start services (PostgreSQL, Redis)
docker-compose up -d postgres redis

# Run migrations
poetry run alembic upgrade head

# Start Celery worker (for async tasks)
poetry run celery -A src.celery_app worker --loglevel=info

# Start server
poetry run uvicorn src.main:app --reload
```

### Using Docker
```bash
# Development environment
docker-compose -f docker-compose.dev.yml up

# Production environment
docker-compose up
```

## 📋 API Endpoints

### Authentication
- All endpoints require Clerk JWT token in Authorization header
- Format: `Authorization: Bearer <your-clerk-jwt-token>`

### Bank Statement Processing
- `POST /api/v1/pdf/upload` - Upload and process bank statement
- `GET /api/v1/pdf/status/{task_id}` - Check processing status
- `GET /api/v1/pdf/result/{task_id}` - Get extraction results

### Subscriptions
- `GET /api/v1/subscriptions/plans` - List available plans
- `POST /api/v1/subscriptions/create` - Create new subscription
- `GET /api/v1/subscriptions/current` - Get user's subscription
- `POST /api/v1/subscriptions/portal` - Customer portal access
- `POST /api/v1/subscriptions/{id}/cancel` - Cancel subscription

### Users
- `GET /api/v1/users/me` - Get current user profile

### Webhooks
- `POST /api/v1/stripe/webhook` - Stripe webhook handler

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

# Redis (for rate limiting & Celery)
REDIS_URL=redis://localhost:6379

# Google AI (for document processing)
GOOGLE_API_KEY=your_gemini_api_key

# Azure Blob Storage
AZURE_STORAGE_CONNECTION_STRING=your_azure_connection_string
AZURE_STORAGE_CONTAINER_NAME=your_container_name

# Application
ENVIRONMENT=development  # or production
LOG_LEVEL=INFO
```

## 🏭 Production Deployment

1. **Environment Variables** - Set all required env vars (see Configuration)
2. **Database** - Run migrations: `alembic upgrade head`
3. **Redis** - Configure Redis for rate limiting and Celery
4. **Celery Workers** - Start background workers for document processing
5. **Webhooks** - Configure Stripe webhook endpoint
6. **Azure Storage** - Set up blob storage for file uploads
7. **CORS** - Update allowed origins in `main.py`
8. **Logging** - Configure appropriate log levels

## 🛠️ Tech Stack

### Core Framework
- **FastAPI** - Modern Python web framework with auto-generated docs
- **Uvicorn** - ASGI server for production deployment
- **Pydantic** - Data validation and serialization with type hints

### AI & Document Processing
- **LangChain** - AI framework for document processing workflows
- **Google Gemini AI** - Large language model for intelligent extraction
- **PyMuPDF** - PDF parsing and text extraction
- **Pillow** - Image processing capabilities
- **Pandas** - Data manipulation and analysis
- **OpenPyXL** - Excel file processing

### Database & Storage
- **PostgreSQL** - Primary relational database
- **SQLAlchemy** - Modern Python ORM with async support
- **Alembic** - Database migration management
- **Azure Blob Storage** - Cloud file storage for uploads

### Authentication & Payments
- **Clerk** - User authentication and management
- **Stripe** - Payment processing and subscription management
- **PyJWT** - JWT token validation with cryptographic support

### Background Processing & Caching
- **Celery** - Distributed task queue for async processing
- **Redis** - In-memory cache and message broker
- **FastAPI-Limiter** - API rate limiting

### Development & Deployment
- **Poetry** - Modern dependency management and packaging
- **Docker** - Containerization for consistent deployments
- **Tenacity** - Retry logic for resilient operations

## 📈 Scaling Considerations

The bank statement extraction service is designed to scale:

- **Database** - PostgreSQL with proper indexing and connection pooling
- **Authentication** - Stateless JWT tokens via Clerk
- **Background Processing** - Celery workers can be horizontally scaled
- **Caching** - Redis for rate limiting and session storage
- **File Storage** - Azure Blob Storage for scalable document handling
- **API Rate Limiting** - Prevents abuse and ensures fair usage
- **Monitoring** - Structured logging throughout the application
- **Containerization** - Docker for consistent deployments across environments

## 🔒 Security Features

- **JWT Authentication** - Secure token-based authentication via Clerk
- **Rate Limiting** - API rate limiting to prevent abuse
- **Input Validation** - Comprehensive request validation using Pydantic
- **Environment Isolation** - Separate configurations for dev/prod environments
- **Secure File Handling** - Validated file uploads with type checking
- **Database Security** - Parameterized queries to prevent SQL injection

## 📄 License

Proprietary - All rights reserved.
