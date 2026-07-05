# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Minimal Dockerfile for CI validation
# Full deployment Dockerfile pending codebase restructure
FROM python:3.12-slim

ENV UV_NO_CACHE=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install git (required for git+https:// dependencies like onex-change-control)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install --default-timeout=300 --retries 5 --no-cache-dir uv

# Copy package files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --no-dev --frozen

# Run the service as an unprivileged user.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Verify package imports correctly
RUN uv run python -c "from omniclaude.hooks import schemas; print('Package validated')"

# Runtime service entrypoint (OMN-2801)
CMD ["uv", "run", "python", "-m", "omniclaude.runtime", "start"]
