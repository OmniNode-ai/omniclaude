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

# Default command
CMD ["uv", "run", "python", "-c", "print('OmniClaude package ready')"]
