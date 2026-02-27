# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Tests for CI relay rate limiter and idempotency store."""

from __future__ import annotations

import pytest

from omniclaude.services.ci_relay.rate_limiter import RateLimiter


@pytest.mark.unit
class TestRateLimiterRepoRate:
    """Tests for per-repo token bucket rate limiting."""

    def test_allows_within_limit(self) -> None:
        """Test that requests within rate limit are allowed."""
        limiter = RateLimiter(repo_rate_per_minute=10)
        repo = "OmniNode-ai/omniclaude"

        for _ in range(10):
            assert limiter.check_repo_rate(repo) is True

    def test_rejects_over_limit(self) -> None:
        """Test that requests exceeding rate limit are rejected."""
        limiter = RateLimiter(repo_rate_per_minute=3)
        repo = "OmniNode-ai/omniclaude"

        for _ in range(3):
            assert limiter.check_repo_rate(repo) is True

        # Fourth request should be rate-limited
        assert limiter.check_repo_rate(repo) is False

    def test_independent_per_repo(self) -> None:
        """Test that rate limits are independent per repo."""
        limiter = RateLimiter(repo_rate_per_minute=2)

        # Exhaust repo A
        assert limiter.check_repo_rate("repo-a") is True
        assert limiter.check_repo_rate("repo-a") is True
        assert limiter.check_repo_rate("repo-a") is False

        # Repo B should still be allowed
        assert limiter.check_repo_rate("repo-b") is True


@pytest.mark.unit
class TestRateLimiterShaCooldown:
    """Tests for per-sha notification rate limiting."""

    def test_first_notification_allowed(self) -> None:
        """Test that the first notification for a sha is always allowed."""
        limiter = RateLimiter(sha_cooldown_seconds=300)
        assert limiter.check_sha_notification("repo", "sha1", "success") is True

    def test_duplicate_suppressed(self) -> None:
        """Test that same (repo, sha, conclusion) within cooldown is suppressed."""
        limiter = RateLimiter(sha_cooldown_seconds=300)
        assert limiter.check_sha_notification("repo", "sha1", "success") is True
        assert limiter.check_sha_notification("repo", "sha1", "success") is False

    def test_conclusion_change_allowed(self) -> None:
        """Test that a conclusion change within cooldown is allowed."""
        limiter = RateLimiter(sha_cooldown_seconds=300)
        assert limiter.check_sha_notification("repo", "sha1", "success") is True
        assert limiter.check_sha_notification("repo", "sha1", "failure") is True

    def test_different_sha_independent(self) -> None:
        """Test that different SHAs have independent cooldowns."""
        limiter = RateLimiter(sha_cooldown_seconds=300)
        assert limiter.check_sha_notification("repo", "sha1", "success") is True
        assert limiter.check_sha_notification("repo", "sha2", "success") is True


@pytest.mark.unit
class TestRateLimiterDedupe:
    """Tests for idempotency dedupe checking."""

    def test_first_key_allowed(self) -> None:
        """Test that a new dedupe key is allowed."""
        limiter = RateLimiter(dedupe_ttl_seconds=3600)
        assert limiter.check_dedupe("repo:sha:123") is True

    def test_duplicate_key_rejected(self) -> None:
        """Test that a duplicate dedupe key is rejected."""
        limiter = RateLimiter(dedupe_ttl_seconds=3600)
        assert limiter.check_dedupe("repo:sha:123") is True
        assert limiter.check_dedupe("repo:sha:123") is False

    def test_different_keys_independent(self) -> None:
        """Test that different dedupe keys are independent."""
        limiter = RateLimiter(dedupe_ttl_seconds=3600)
        assert limiter.check_dedupe("repo:sha:123") is True
        assert limiter.check_dedupe("repo:sha:456") is True

    def test_cleanup_stale(self) -> None:
        """Test that cleanup removes expired entries."""
        limiter = RateLimiter(dedupe_ttl_seconds=3600)
        limiter.check_dedupe("repo:sha:123")
        removed = limiter.cleanup_stale()
        # Nothing should be expired yet (TTL is 1 hour)
        assert removed == 0
