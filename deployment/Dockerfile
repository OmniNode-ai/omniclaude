# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Minimal Dockerfile for CI validation
# Full deployment Dockerfile pending codebase restructure
FROM python:3.12-slim

WORKDIR /app

# Install uv for fast dependency management
RUN pip install uv

# Copy package files
COPY pyproject.toml uv.lock ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --no-dev --frozen

# Verify package imports correctly
RUN uv run python -c "from omniclaude.hooks import schemas; print('Package validated')"

# Runtime service entrypoint (OMN-2801)
CMD ["uv", "run", "python", "-m", "omniclaude.runtime", "start"]
