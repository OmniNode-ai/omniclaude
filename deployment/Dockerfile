# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Minimal Dockerfile for CI validation
# Full deployment Dockerfile pending codebase restructure
FROM python:3.12-slim

ENV UV_NO_CACHE=1
ENV UV_HTTP_TIMEOUT=600
ENV GIT_HTTP_LOW_SPEED_LIMIT=0
ENV GIT_HTTP_LOW_SPEED_TIME=999999
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install git (required for git+https:// dependencies like onex-change-control)
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency management
RUN pip install --default-timeout=300 --retries 5 --no-cache-dir uv

# Copy package files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies. GitHub-side git dependencies occasionally reset during
# container builds; retry the bounded install instead of failing a clean build.
RUN for attempt in 1 2 3 4; do \
        uv sync --no-dev --frozen && break; \
        [ "$attempt" -lt 4 ] || exit 1; \
        sleep $((attempt * 10)); \
    done

# Run the service as an unprivileged user.
RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

# Verify package imports correctly
RUN uv run python -c "from omniclaude.hooks import schemas; print('Package validated')"

# Runtime service entrypoint (OMN-2801)
CMD ["uv", "run", "python", "-m", "omniclaude.runtime", "start"]
