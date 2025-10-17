# Multi-Stage Dockerfile for OmniClaude
# Production-ready Python 3.12 application with Poetry dependency management
# Security-hardened with non-root user, minimal base image, and health checks

# ============================================================================
# Stage 1: Builder - Install dependencies and build application
# ============================================================================
FROM python:3.12-slim AS builder

# Set build arguments for metadata
ARG BUILD_DATE
ARG VCS_REF
ARG VERSION=0.1.0

# Metadata labels following OCI image spec
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.authors="OmniClaude Team" \
      org.opencontainers.image.url="https://github.com/omniclaude/omniclaude" \
      org.opencontainers.image.source="https://github.com/omniclaude/omniclaude" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.title="OmniClaude" \
      org.opencontainers.image.description="Multi-provider AI toolkit with agent framework"

# Install system dependencies required for building Python packages
# Combine commands to reduce layers and use --no-install-recommends for minimal footprint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry for dependency management
ENV POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_VIRTUALENVS_CREATE=true \
    POETRY_CACHE_DIR=/tmp/poetry_cache

RUN curl -sSL https://install.python-poetry.org | python3 - && \
    ln -s /opt/poetry/bin/poetry /usr/local/bin/poetry

# Set working directory
WORKDIR /app

# Copy dependency files first for optimal layer caching
# Changes to source code won't invalidate dependency layers
COPY pyproject.toml poetry.lock* ./

# Install dependencies
# --only main excludes dev dependencies for production
# --no-root prevents installing the package itself (done later with source)
RUN poetry install --only main --no-root && \
    rm -rf $POETRY_CACHE_DIR

# Copy application source code
COPY . .

# Install the application package
RUN poetry install --only-root

# ============================================================================
# Stage 2: Runtime - Minimal production image
# ============================================================================
FROM python:3.12-slim AS runtime

# Install runtime system dependencies only
# libpq5 for PostgreSQL client, ca-certificates for HTTPS
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
# --system creates a system user, --group creates a group with same name
RUN groupadd --system --gid 1000 omniclaude && \
    useradd --system --uid 1000 --gid omniclaude --shell /bin/bash --create-home omniclaude

# Set working directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder --chown=omniclaude:omniclaude /app/.venv /app/.venv

# Copy application code from builder stage
COPY --from=builder --chown=omniclaude:omniclaude /app /app

# Set environment variables for production
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    # Application-specific environment variables
    APP_ENV=production \
    LOG_LEVEL=info

# Switch to non-root user
USER omniclaude

# Expose application ports
# 8000: Main application API
# 8001: Metrics/health endpoint
EXPOSE 8000 8001

# Health check configuration
# Adjust the endpoint based on your application's health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Default command - can be overridden in docker-compose or at runtime
# Using exec form for proper signal handling
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
