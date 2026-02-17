#!/usr/bin/env python3
"""PostToolUse pattern enforcement — advisory compliance checking.

Queries the OmniIntelligence pattern store API for applicable patterns,
checks session-scoped cooldown (one advisory per pattern per session),
calls the compliance compute node, and outputs advisory JSON.

All failures are silent — enforcement never blocks or degrades UX.
Total budget: 300ms.

Feature flags:
    ENABLE_PATTERN_ENFORCEMENT=true  (primary gate)
    ENABLE_LOCAL_INFERENCE_PIPELINE=true  (parent gate)

Ticket: OMN-2263
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOTAL_BUDGET_MS = 300
_HTTP_TIMEOUT_S = 0.25  # 250ms for HTTP calls, leaving 50ms for processing
_COOLDOWN_DIR = Path("/tmp/omniclaude-enforcement")  # noqa: S108
_DEFAULT_MIN_CONFIDENCE = 0.7
_DEFAULT_PATTERN_LIMIT = 10


# ---------------------------------------------------------------------------
# TypedDicts for structured output
# ---------------------------------------------------------------------------


class PatternAdvisory(TypedDict):
    """Single pattern advisory entry."""

    pattern_id: str
    pattern_signature: str
    domain_id: str
    confidence: float
    status: str
    message: str


class EnforcementResult(TypedDict):
    """Result of pattern enforcement check."""

    enforced: bool
    advisories: list[PatternAdvisory]
    patterns_checked: int
    patterns_skipped_cooldown: int
    elapsed_ms: float
    error: str | None


# ---------------------------------------------------------------------------
# Feature flag check
# ---------------------------------------------------------------------------


def is_enforcement_enabled() -> bool:
    """Check whether pattern enforcement is enabled via feature flags.

    Both ENABLE_LOCAL_INFERENCE_PIPELINE and ENABLE_PATTERN_ENFORCEMENT
    must be truthy ("true", "1", "yes" case-insensitive).
    """
    parent_flag = os.environ.get("ENABLE_LOCAL_INFERENCE_PIPELINE", "").lower()
    enforcement_flag = os.environ.get("ENABLE_PATTERN_ENFORCEMENT", "").lower()
    truthy = {"true", "1", "yes"}
    return parent_flag in truthy and enforcement_flag in truthy


# ---------------------------------------------------------------------------
# Session cooldown
# ---------------------------------------------------------------------------


def _cooldown_path(session_id: str) -> Path:
    """Return the cooldown state file path for a session."""
    # Sanitize session_id to prevent path traversal
    safe_id = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return _COOLDOWN_DIR / f"{safe_id}.json"


def _load_cooldown(session_id: str) -> set[str]:
    """Load the set of pattern IDs already advised in this session.

    Returns an empty set if the file doesn't exist or is corrupt.
    """
    path = _cooldown_path(session_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return set()


def _save_cooldown(session_id: str, pattern_ids: set[str]) -> None:
    """Persist the set of advised pattern IDs for this session.

    Silently ignores write failures.
    """
    path = _cooldown_path(session_id)
    try:
        _COOLDOWN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(pattern_ids)), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pattern store query
# ---------------------------------------------------------------------------


def _get_intelligence_url() -> str:
    """Resolve the OmniIntelligence API base URL from environment."""
    url = os.environ.get("INTELLIGENCE_SERVICE_URL", "")
    if url:
        return url.rstrip("/")
    host = os.environ.get("INTELLIGENCE_SERVICE_HOST", "localhost")
    port = os.environ.get("INTELLIGENCE_SERVICE_PORT", "8053")
    return f"http://{host}:{port}"


def query_patterns(
    *,
    language: str | None = None,
    domain: str | None = None,
    min_confidence: float = _DEFAULT_MIN_CONFIDENCE,
    limit: int = _DEFAULT_PATTERN_LIMIT,
    timeout_s: float = _HTTP_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Query the pattern store API for applicable patterns.

    Args:
        language: Programming language filter (e.g., "python").
        domain: Domain filter.
        min_confidence: Minimum confidence threshold.
        limit: Maximum number of patterns to return.
        timeout_s: HTTP timeout in seconds.

    Returns:
        List of pattern dicts from the API, or empty list on any failure.
    """
    base_url = _get_intelligence_url()
    params: list[str] = [
        f"min_confidence={min_confidence}",
        f"limit={limit}",
    ]
    if language:
        params.append(f"language={urllib.request.quote(language)}")
    if domain:
        params.append(f"domain={urllib.request.quote(domain)}")

    url = f"{base_url}/api/v1/patterns?{'&'.join(params)}"

    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("patterns", [])
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return []
    except Exception:
        # Catch-all: enforcement must never raise
        return []


# ---------------------------------------------------------------------------
# Compliance check (stub for OMN-2256)
# ---------------------------------------------------------------------------


def check_compliance(
    *,
    file_path: str,
    content_preview: str,
    pattern: dict[str, Any],
    timeout_s: float = _HTTP_TIMEOUT_S,
) -> PatternAdvisory | None:
    """Check file content against a pattern for compliance.

    Currently returns a basic advisory based on pattern metadata.
    Will be enhanced to call the compliance compute node when
    OMN-2256 lands.

    Args:
        file_path: Path to the file being checked.
        content_preview: First N chars of file content.
        pattern: Pattern dict from the store API.
        timeout_s: HTTP timeout in seconds (reserved for future use).

    Returns:
        A PatternAdvisory if the pattern is applicable, None otherwise.
    """
    # Extract fields with safe defaults
    pattern_id = str(pattern.get("id", ""))
    signature = str(pattern.get("pattern_signature", ""))
    domain_id = str(pattern.get("domain_id", ""))
    confidence = float(pattern.get("confidence", 0.0))
    status = str(pattern.get("status", "unknown"))

    if not pattern_id or not signature:
        return None

    # Basic applicability: pattern is relevant if it's validated/provisional
    # and has a confidence above threshold. Full compliance checking
    # will be added when the compliance compute node (OMN-2256) is ready.
    return PatternAdvisory(
        pattern_id=pattern_id,
        pattern_signature=signature,
        domain_id=domain_id,
        confidence=confidence,
        status=status,
        message=f"Pattern '{signature[:80]}' (confidence: {confidence:.2f}) may apply to this file.",
    )


# ---------------------------------------------------------------------------
# Main enforcement entry point
# ---------------------------------------------------------------------------


def enforce_patterns(
    *,
    file_path: str,
    session_id: str,
    language: str | None = None,
    domain: str | None = None,
    content_preview: str = "",
) -> EnforcementResult:
    """Run pattern enforcement for a file modification.

    Queries applicable patterns, checks session cooldown, runs compliance
    checks, and returns advisory results. All within 300ms budget.

    Args:
        file_path: Path to the modified file.
        session_id: Current session ID for cooldown scoping.
        language: Programming language of the file.
        domain: Domain filter for patterns.
        content_preview: First N chars of file content for compliance.

    Returns:
        EnforcementResult with advisories and metadata.
    """
    start = time.monotonic()

    def _elapsed_ms() -> float:
        return (time.monotonic() - start) * 1000

    def _budget_exceeded() -> bool:
        return _elapsed_ms() >= _TOTAL_BUDGET_MS

    try:
        # Step 1: Query pattern store
        patterns = query_patterns(
            language=language,
            domain=domain,
        )

        if not patterns or _budget_exceeded():
            return EnforcementResult(
                enforced=True,
                advisories=[],
                patterns_checked=0,
                patterns_skipped_cooldown=0,
                elapsed_ms=_elapsed_ms(),
                error=None,
            )

        # Step 2: Load session cooldown
        cooldown_set = _load_cooldown(session_id)
        skipped = 0
        advisories: list[PatternAdvisory] = []
        new_pattern_ids: set[str] = set()

        # Step 3: Check each pattern
        for pattern in patterns:
            if _budget_exceeded():
                break

            pattern_id = str(pattern.get("id", ""))
            if not pattern_id:
                continue

            # Session cooldown: skip if already advised
            if pattern_id in cooldown_set:
                skipped += 1
                continue

            # Step 4: Compliance check
            advisory = check_compliance(
                file_path=file_path,
                content_preview=content_preview,
                pattern=pattern,
            )
            if advisory is not None:
                advisories.append(advisory)
                new_pattern_ids.add(pattern_id)

        # Step 5: Update cooldown
        if new_pattern_ids:
            _save_cooldown(session_id, cooldown_set | new_pattern_ids)

        return EnforcementResult(
            enforced=True,
            advisories=advisories,
            patterns_checked=len(patterns),
            patterns_skipped_cooldown=skipped,
            elapsed_ms=_elapsed_ms(),
            error=None,
        )

    except Exception as exc:
        # Silent failure: enforcement must never block
        return EnforcementResult(
            enforced=False,
            advisories=[],
            patterns_checked=0,
            patterns_skipped_cooldown=0,
            elapsed_ms=_elapsed_ms(),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# CLI entry point (called from post-tool-use-quality.sh)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for pattern enforcement.

    Reads JSON from stdin with file_path, session_id, language, content_preview.
    Writes EnforcementResult JSON to stdout.
    Always exits 0.
    """
    try:
        if not is_enforcement_enabled():
            json.dump(
                EnforcementResult(
                    enforced=False,
                    advisories=[],
                    patterns_checked=0,
                    patterns_skipped_cooldown=0,
                    elapsed_ms=0.0,
                    error=None,
                ),
                sys.stdout,
            )
            return

        raw = sys.stdin.read()
        if not raw.strip():
            json.dump(
                EnforcementResult(
                    enforced=False,
                    advisories=[],
                    patterns_checked=0,
                    patterns_skipped_cooldown=0,
                    elapsed_ms=0.0,
                    error="empty stdin",
                ),
                sys.stdout,
            )
            return

        params = json.loads(raw)
        result = enforce_patterns(
            file_path=params.get("file_path", ""),
            session_id=params.get("session_id", ""),
            language=params.get("language"),
            domain=params.get("domain"),
            content_preview=params.get("content_preview", ""),
        )
        json.dump(result, sys.stdout)

    except Exception as exc:
        # Absolute last resort: never crash
        json.dump(
            EnforcementResult(
                enforced=False,
                advisories=[],
                patterns_checked=0,
                patterns_skipped_cooldown=0,
                elapsed_ms=0.0,
                error=f"fatal: {exc}",
            ),
            sys.stdout,
        )


if __name__ == "__main__":
    main()
