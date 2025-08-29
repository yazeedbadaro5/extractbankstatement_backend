FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and Poetry in one layer
RUN apt-get update && apt-get install -y \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && /root/.local/bin/poetry config virtualenvs.create false \
    && apt-get clean \
    && rm -rf /var/cache/apt

# Add Poetry to PATH
ENV PATH="/root/.local/bin:$PATH"

# Copy Poetry files first for better caching
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry install --only main --no-interaction --no-ansi

# Copy application code
COPY . .

# Create non-root user
RUN useradd --create-home --shell /bin/bash app && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
