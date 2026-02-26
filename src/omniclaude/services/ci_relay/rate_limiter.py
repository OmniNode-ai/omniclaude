# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Token-bucket rate limiter and idempotency store for the CI relay.

Two independent mechanisms:
1. Per-repo rate limit: token bucket, 10 requests/minute default.
2. Per-sha notification rate limit: at most 1 per (repo, sha) per 5 min
   unless ``conclusion`` changes.
3. Idempotency: dedupe key ``{repo}:{sha}:{run_id}``, drop retries within 1 hour.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class _TokenBucket:
    """Simple token bucket for rate limiting."""

    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = 0.0
    last_refill: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        self.tokens = self.capacity

    def try_consume(self, n: float = 1.0) -> bool:
        """Try to consume n tokens. Returns True if successful."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


@dataclass
class _ShaNotification:
    """Tracks the last notification for a (repo, sha) pair."""

    conclusion: str
    timestamp: float


class RateLimiter:
    """Combined rate limiter and idempotency store for the CI relay.

    Thread-safe for single-process use (GIL). For multi-process deployments,
    replace with Valkey-backed implementation.
    """

    def __init__(
        self,
        *,
        repo_rate_per_minute: int = 10,
        sha_cooldown_seconds: int = 300,
        dedupe_ttl_seconds: int = 3600,
    ) -> None:
        self._repo_rate_per_minute = repo_rate_per_minute
        self._sha_cooldown_seconds = sha_cooldown_seconds
        self._dedupe_ttl_seconds = dedupe_ttl_seconds

        # Per-repo token buckets
        self._repo_buckets: dict[str, _TokenBucket] = {}

        # Per-(repo, sha) notification tracking
        self._sha_notifications: dict[str, _ShaNotification] = {}

        # Dedupe key store: key -> expiry timestamp
        self._dedupe_keys: dict[str, float] = {}

    def _get_repo_bucket(self, repo: str) -> _TokenBucket:
        """Get or create a token bucket for a repo."""
        if repo not in self._repo_buckets:
            self._repo_buckets[repo] = _TokenBucket(
                capacity=float(self._repo_rate_per_minute),
                refill_rate=self._repo_rate_per_minute / 60.0,
            )
        return self._repo_buckets[repo]

    def check_repo_rate(self, repo: str) -> bool:
        """Check if a request from this repo is within rate limits.

        Args:
            repo: Repository slug.

        Returns:
            True if the request is allowed, False if rate-limited.
        """
        bucket = self._get_repo_bucket(repo)
        return bucket.try_consume()

    def check_sha_notification(self, repo: str, sha: str, conclusion: str) -> bool:
        """Check if a notification for this (repo, sha) should be sent.

        Rate-limited to 1 per (repo, sha) per sha_cooldown_seconds unless
        the conclusion has changed.

        Args:
            repo: Repository slug.
            sha: Commit SHA.
            conclusion: Workflow conclusion string.

        Returns:
            True if the notification should proceed, False if suppressed.
        """
        key = f"{repo}:{sha}"
        now = time.monotonic()

        existing = self._sha_notifications.get(key)
        if existing is not None:
            elapsed = now - existing.timestamp
            if elapsed < self._sha_cooldown_seconds:
                # Within cooldown -- only allow if conclusion changed
                if existing.conclusion == conclusion:
                    return False
            # Update with new conclusion
        self._sha_notifications[key] = _ShaNotification(
            conclusion=conclusion, timestamp=now
        )
        return True

    def check_dedupe(self, dedupe_key: str) -> bool:
        """Check if this dedupe key has been seen before.

        Args:
            dedupe_key: Idempotency key ``{repo}:{sha}:{run_id}``.

        Returns:
            True if this is a new key (should process), False if duplicate.
        """
        now = time.monotonic()

        # Lazy cleanup: remove expired entries
        expired = [k for k, v in self._dedupe_keys.items() if v < now]
        for k in expired:
            del self._dedupe_keys[k]

        if dedupe_key in self._dedupe_keys:
            return False

        self._dedupe_keys[dedupe_key] = now + self._dedupe_ttl_seconds
        return True

    def cleanup_stale(self) -> int:
        """Remove expired entries from all stores.

        Returns:
            Number of entries removed.
        """
        now = time.monotonic()
        removed = 0

        # Clean dedupe keys
        expired_dedupe = [k for k, v in self._dedupe_keys.items() if v < now]
        for k in expired_dedupe:
            del self._dedupe_keys[k]
            removed += 1

        # Clean sha notifications older than 2x cooldown
        stale_threshold = now - (self._sha_cooldown_seconds * 2)
        expired_sha = [
            k
            for k, v in self._sha_notifications.items()
            if v.timestamp < stale_threshold
        ]
        for k in expired_sha:
            del self._sha_notifications[k]
            removed += 1

        return removed
