# Multi-Stage Dockerfile for OmniClaude
# Production-ready Python 3.12 application with uv dependency management
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

# Install uv for dependency management
# Using pip to install uv for simplicity and reliability
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

RUN pip install --no-cache-dir uv

# Set working directory
WORKDIR /app

# Copy dependency files first for optimal layer caching
# Changes to source code won't invalidate dependency layers
COPY pyproject.toml uv.lock ./

# Create virtual environment and install dependencies
# --frozen ensures lockfile is used exactly as-is
# --no-dev excludes development dependencies for production
RUN uv venv /app/.venv && \
    . /app/.venv/bin/activate && \
    uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY . .

# Install the application package itself
RUN . /app/.venv/bin/activate && \
    uv sync --frozen --no-dev

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
