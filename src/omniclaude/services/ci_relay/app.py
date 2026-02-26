# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""FastAPI application for the CI relay service.

Receives GH Actions workflow completion callbacks, validates bearer token,
applies rate limiting and idempotency, resolves PR numbers for push-triggered
workflows, and publishes events to Kafka.

See OMN-2826 Phase 2a for specification.
"""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from omniclaude.services.ci_relay.models import CICallbackPayload, PRStatusEvent
from omniclaude.services.ci_relay.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Topic for PR status events
PR_STATUS_TOPIC = "onex.evt.github.pr-status.v1"

# Module-level rate limiter (single instance per process)
_rate_limiter = RateLimiter()


def _reset_rate_limiter() -> None:
    """Reset the rate limiter. For testing only."""
    global _rate_limiter  # noqa: PLW0603
    _rate_limiter = RateLimiter()


# Security scheme
_bearer_scheme = HTTPBearer()


def _get_expected_token() -> str:
    """Read the expected bearer token from environment."""
    token = os.environ.get("CI_CALLBACK_TOKEN", "")
    if not token:
        raise RuntimeError(
            "CI_CALLBACK_TOKEN environment variable is not set. "
            "The relay cannot authenticate incoming requests."
        )
    return token


async def _verify_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> str:
    """Verify the bearer token matches CI_CALLBACK_TOKEN.

    Args:
        credentials: HTTP Bearer credentials from the request.

    Returns:
        The verified token string.

    Raises:
        HTTPException: If the token is missing or invalid.
    """
    expected = _get_expected_token()
    if credentials.credentials != expected:
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return credentials.credentials


def _resolve_pr_from_sha(repo: str, sha: str) -> int | None:
    """Resolve PR number from a commit SHA via GitHub API.

    Used when the callback has ``pr=0`` (push-triggered workflow).
    Results are cached by the caller for 5 minutes.

    Args:
        repo: Full repo slug (e.g. ``OmniNode-ai/omniclaude``).
        sha: Commit SHA to look up.

    Returns:
        PR number if found, None otherwise.
    """
    try:
        result = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{repo}/commits/{sha}/pulls",
                "--jq",
                ".[0].number",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        logger.warning("PR resolution failed for %s/%s: %s", repo, sha, exc)
    return None


# In-memory PR resolution cache: (repo, sha) -> (pr_number, timestamp)
_pr_cache: dict[tuple[str, str], tuple[int | None, float]] = {}
_PR_CACHE_TTL = 300  # 5 minutes


def _resolve_pr_cached(repo: str, sha: str) -> int | None:
    """Resolve PR number with 5-minute cache."""
    import time

    cache_key = (repo, sha)
    now = time.monotonic()

    cached = _pr_cache.get(cache_key)
    if cached is not None:
        pr_num, cached_at = cached
        if now - cached_at < _PR_CACHE_TTL:
            return pr_num

    pr_num = _resolve_pr_from_sha(repo, sha)
    _pr_cache[cache_key] = (pr_num, now)
    return pr_num


async def _publish_to_kafka(event: PRStatusEvent) -> None:
    """Publish a PRStatusEvent to Kafka.

    Uses the ONEX event bus infrastructure. Falls back to logging if
    Kafka is unavailable.

    Args:
        event: The event to publish.
    """
    try:
        # Import here to avoid hard dependency on Kafka at module load
        from omniclaude.services.ci_relay.publisher import publish_event

        await publish_event(PR_STATUS_TOPIC, event)
    except ImportError:
        logger.warning(
            "Kafka publisher not available. Event logged but not published: %s",
            event.dedupe_key,
        )
    except Exception:
        logger.exception("Failed to publish event %s to Kafka", event.dedupe_key)


def create_app() -> FastAPI:
    """Create and configure the CI relay FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    app = FastAPI(
        title="CI Relay",
        description=(
            "Receives GitHub Actions workflow completion callbacks and "
            "publishes PR status events to Kafka."
        ),
        version="1.0.0",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok", "service": "ci-relay"}

    @app.post("/callback")
    async def receive_callback(
        payload: CICallbackPayload,
        request: Request,
        _token: str = Depends(_verify_bearer),
    ) -> dict[str, Any]:
        """Receive a GH Actions workflow completion callback.

        Validates bearer token, applies rate limiting and idempotency,
        optionally resolves PR number, then publishes to Kafka.

        Args:
            payload: The callback payload from GH Actions.
            request: The FastAPI request object.
            _token: Verified bearer token (injected by dependency).

        Returns:
            Dict with status and event details.

        Raises:
            HTTPException: On rate limit or auth failure.
        """
        dedupe_key = f"{payload.repo}:{payload.sha}:{payload.run_id}"

        # Check repo rate limit
        if not _rate_limiter.check_repo_rate(payload.repo):
            logger.warning(
                "Rate limited: repo=%s dedupe_key=%s",
                payload.repo,
                dedupe_key,
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for repo {payload.repo}",
            )

        # Check idempotency (dedupe within 1 hour)
        if not _rate_limiter.check_dedupe(dedupe_key):
            logger.info("Duplicate dropped: %s", dedupe_key)
            return {
                "status": "duplicate",
                "dedupe_key": dedupe_key,
                "message": "Event already processed within deduplication window",
            }

        # Check per-sha notification rate limit
        if not _rate_limiter.check_sha_notification(
            payload.repo, payload.sha, payload.conclusion
        ):
            logger.info(
                "SHA notification suppressed: repo=%s sha=%s conclusion=%s",
                payload.repo,
                payload.sha,
                payload.conclusion,
            )
            return {
                "status": "suppressed",
                "dedupe_key": dedupe_key,
                "message": (
                    "Notification suppressed: same (repo, sha) within "
                    "cooldown and conclusion unchanged"
                ),
            }

        # Resolve PR number if pr=0 (push-triggered workflow)
        resolved_pr: int | None = None
        if payload.pr == 0:
            resolved_pr = _resolve_pr_cached(payload.repo, payload.sha)
            if resolved_pr is not None:
                logger.info(
                    "Resolved PR for push-triggered workflow: repo=%s sha=%s -> PR #%d",
                    payload.repo,
                    payload.sha,
                    resolved_pr,
                )

        # Build event
        event = PRStatusEvent.from_callback(
            payload,
            resolved_pr=resolved_pr,
            trace={
                "source": "ci-relay",
                "client_ip": request.client.host if request.client else "unknown",
            },
        )

        # Publish to Kafka
        await _publish_to_kafka(event)

        logger.info(
            "Published PR status event: repo=%s pr=%d conclusion=%s dedupe_key=%s",
            event.repo,
            event.resolved_pr or event.pr,
            event.conclusion,
            event.dedupe_key,
        )

        return {
            "status": "published",
            "dedupe_key": event.dedupe_key,
            "message_id": event.message_id,
            "pr": event.resolved_pr or event.pr,
            "conclusion": event.conclusion,
        }

    return app
