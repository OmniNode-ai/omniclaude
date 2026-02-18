#!/usr/bin/env python3
"""PostToolUse pattern enforcement — advisory compliance checking.

Queries the OmniIntelligence pattern store API for applicable patterns,
checks session-scoped cooldown (TTL-based, 30min per pattern per session),
emits a single compliance.evaluate event to omniintelligence, and returns
metadata. Advisories arrive asynchronously on the next turn via the
advisory formatter. All failures are silent — enforcement never blocks
or degrades UX. Total budget: 300ms.

Feature flags:
    ENABLE_PATTERN_ENFORCEMENT=true  (primary gate)
    ENABLE_LOCAL_INFERENCE_PIPELINE=true  (parent gate)

Tickets: OMN-2263, OMN-2256
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid as _uuid
from pathlib import Path
from typing import Any, TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Authoritative values. config.yaml mirrors these for documentation but is not read at runtime.
_TOTAL_BUDGET_MS = 300
_HTTP_TIMEOUT_S = 0.25  # 250ms for HTTP calls, leaving 50ms for processing
try:
    _uid = os.getuid()
except (AttributeError, OSError):
    _uid = "unknown"
_COOLDOWN_DIR = Path(f"/tmp/omniclaude-enforcement-{_uid}")  # noqa: S108
_DEFAULT_MIN_CONFIDENCE = 0.7
_DEFAULT_PATTERN_LIMIT = 10
_COOLDOWN_TTL_S = 1800  # 30 minutes: re-eligible if intelligence fails silently
_CONTENT_MAX_BYTES = 32768  # 32KB cap (defense-in-depth, shell already caps)


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
    patterns_queried: int
    patterns_skipped_cooldown: int
    elapsed_ms: float
    error: str | None
    evaluation_submitted: bool


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
# Session cooldown (TTL-based)
# ---------------------------------------------------------------------------

# Throttle stale-file cleanup to at most once per 5 minutes.
# Module-level throttle state. Assumes short-lived CLI invocations (one hook call per process).
_last_cleanup: float = 0.0
_CLEANUP_INTERVAL_S = 300  # 5 minutes


def _cooldown_path(session_id: str) -> Path:
    """Return the cooldown state file path for a session."""
    # Sanitize session_id to prevent path traversal
    safe_id = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return _COOLDOWN_DIR / f"{safe_id}.json"


def _cleanup_stale_cooldown_files() -> None:
    """Remove cooldown files older than 24 hours.

    Best-effort sweep — silently ignores any failures.
    """
    max_age_s = 86400  # 24 hours
    try:
        if not _COOLDOWN_DIR.exists():
            return
        now = time.time()
        for entry in _COOLDOWN_DIR.iterdir():
            try:
                if entry.is_file() and (now - entry.stat().st_mtime) > max_age_s:
                    entry.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _load_cooldown(session_id: str) -> dict[str, float]:
    """Load the cooldown map {pattern_id -> emit_timestamp_s} for this session.

    Entries older than _COOLDOWN_TTL_S (30 minutes) are expired on load,
    allowing previously-submitted patterns to re-enter eligibility if
    omniintelligence failed silently.

    Also performs a throttled best-effort cleanup of stale cooldown files
    (>24h old), running at most once per 5 minutes.

    Returns an empty dict if the file doesn't exist or is corrupt.
    """
    global _last_cleanup  # noqa: PLW0603
    now = time.time()
    if now - _last_cleanup > _CLEANUP_INTERVAL_S:
        _cleanup_stale_cooldown_files()
        _last_cleanup = now

    path = _cooldown_path(session_id)
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Expire entries older than TTL
                return {
                    pid: ts
                    for pid, ts in data.items()
                    if isinstance(pid, str)
                    and isinstance(ts, (int, float))
                    and (now - float(ts)) < _COOLDOWN_TTL_S
                }
            # Legacy format (list of pattern IDs from previous version): discard
    except (json.JSONDecodeError, OSError, TypeError):
        pass
    return {}


def _save_cooldown(session_id: str, cooldown: dict[str, float]) -> None:
    """Persist the cooldown map {pattern_id -> emit_timestamp_s} for this session.

    Uses atomic temp-file-and-rename (os.replace) so concurrent subshells
    cannot corrupt the cooldown file.  Duplicate submissions from TOCTOU
    between _load_cooldown and _save_cooldown are a benign edge case --
    a pattern re-evaluated is harmless compared to file corruption.

    Silently ignores write failures.
    """
    path = _cooldown_path(session_id)
    try:
        _COOLDOWN_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Atomic write: write to temp file then rename so readers never
        # see a partially-written cooldown file.
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            os.write(tmp_fd, json.dumps(cooldown).encode())
            os.close(tmp_fd)
            Path(tmp_path).replace(path)
        except Exception:
            # Clean up temp file on failure; suppress all errors.
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
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
    # Clamp to [0.0, 1.0] to guard against inf/nan producing odd query strings.
    min_confidence = max(0.0, min(1.0, min_confidence))

    base_url = _get_intelligence_url()
    # Filter to validated patterns server-side so the limit budget isn't
    # consumed by provisional patterns that _is_eligible_pattern() would drop.
    params: list[str] = [
        f"min_confidence={min_confidence}",
        f"limit={limit}",
        "status=validated",
    ]
    if language:
        params.append(f"language={urllib.parse.quote(language)}")
    if domain:
        params.append(f"domain={urllib.parse.quote(domain)}")

    url = f"{base_url}/api/v1/patterns?{'&'.join(params)}"

    try:
        req = urllib.request.Request(url, method="GET")  # noqa: S310
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
            patterns: list[dict[str, Any]] = data.get("patterns", [])
            return patterns
    except (urllib.error.URLError, OSError, json.JSONDecodeError, KeyError):
        return []
    except Exception:
        # Catch-all: enforcement must never raise
        return []


# ---------------------------------------------------------------------------
# Structural eligibility filter
# ---------------------------------------------------------------------------


def _is_eligible_pattern(pattern: dict[str, Any]) -> bool:
    """Return True if pattern is structurally valid to include in compliance request.

    Checks structural validity only — semantic decisions (confidence thresholds,
    domain filtering) belong in omniintelligence. The API already filters by
    min_confidence and status=validated server-side, so these checks are
    defense-in-depth for malformed responses.

    Structural checks:
    - status == "validated" (filter out drafts/provisional)
    - Non-empty pattern_id and pattern_signature
    - confidence is numeric (not NaN/inf)
    """
    try:
        pattern_id = str(pattern.get("id", ""))
        signature = str(pattern.get("pattern_signature", ""))
        status = str(pattern.get("status", "unknown"))

        if not pattern_id or not signature:
            return False

        if status != "validated":
            return False

        try:
            confidence = float(pattern.get("confidence", 0.0))
        except (ValueError, TypeError):
            return False

        # Guard against NaN/inf which would be invalid in JSON payload
        import math  # noqa: PLC0415

        if not math.isfinite(confidence):
            return False

        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Compliance evaluate emitter
# ---------------------------------------------------------------------------


def _emit_compliance_evaluate(
    *,
    file_path: str,
    content: str,
    language: str,
    session_id: str,
    content_sha256: str,
    patterns: list[dict[str, Any]],
) -> bool:
    """Emit compliance.evaluate event. Returns True if accepted by daemon.

    Correlation ID is unique per request (not session_id) so that multiple
    compliance evaluations within one session are individually traceable.
    session_id is passed separately for routing and projection lookups.

    Content safety: non-empty and UTF-8 safe within the 32KB cap.
    Defense in depth — shell already caps at 32KB but Python layer enforces.
    """
    try:
        from emit_client_wrapper import emit_event  # noqa: PLC0415  # lazy import

        # Empty content: nothing to evaluate
        if not content.strip():
            return False

        # Enforce 32KB cap (shell already caps, but defense-in-depth)
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > _CONTENT_MAX_BYTES:
            content = content_bytes[:_CONTENT_MAX_BYTES].decode(
                "utf-8", errors="ignore"
            )

        payload: dict[str, Any] = {
            "correlation_id": str(_uuid.uuid4()),  # unique per request, not session
            "session_id": session_id,  # separate field for routing/projection
            "source_path": file_path,
            "content": content,
            "content_sha256": content_sha256,  # for idempotency, replay, metrics
            "language": language,
            "applicable_patterns": [
                {
                    "pattern_id": str(p.get("id", "")),
                    "pattern_signature": str(p.get("pattern_signature", "")),
                    "domain_id": str(p.get("domain_id", "")),
                    "confidence": float(p.get("confidence", 0.0)),
                }
                for p in patterns
            ],
        }
        result: bool = emit_event("compliance.evaluate", payload)
        return result
    except Exception:
        return False


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
    content_sha256: str = "",
) -> EnforcementResult:
    """Run pattern enforcement for a file modification.

    Queries applicable patterns, checks session cooldown, collects eligible
    patterns, and emits ONE compliance.evaluate event to omniintelligence.
    Advisories arrive asynchronously; this function always returns
    advisories=[]. All within 300ms budget.

    Args:
        file_path: Path to the modified file.
        session_id: Current session ID for cooldown scoping.
        language: Programming language of the file.
        domain: Domain filter for patterns.
        content_preview: File content (up to 32KB) for compliance.
        content_sha256: SHA-256 hash of content_preview for idempotency.

    Returns:
        EnforcementResult with evaluation_submitted and metadata.
        advisories is always empty — results arrive asynchronously.
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
                patterns_queried=0,
                patterns_skipped_cooldown=0,
                elapsed_ms=_elapsed_ms(),
                error=None,
                evaluation_submitted=False,
            )

        # Step 2: Load session cooldown (TTL-based dict)
        cooldown = _load_cooldown(session_id)
        if _budget_exceeded():
            return EnforcementResult(
                enforced=True,
                advisories=[],
                patterns_queried=len(patterns),
                patterns_skipped_cooldown=0,
                elapsed_ms=_elapsed_ms(),
                error=None,
                evaluation_submitted=False,
            )

        skipped = 0
        eligible_patterns: list[dict[str, Any]] = []
        seen_ids: set[str] = set()  # deduplicate within this batch

        # Step 3: Collect eligible patterns
        for pattern in patterns:
            if _budget_exceeded():
                break

            pattern_id = str(pattern.get("id", ""))
            if not pattern_id:
                continue

            # Session cooldown: skip if already submitted (and TTL not expired)
            if pattern_id in cooldown:
                skipped += 1
                continue

            # Structural eligibility check
            if _is_eligible_pattern(pattern) and pattern_id not in seen_ids:
                eligible_patterns.append(pattern)
                seen_ids.add(pattern_id)

        # Step 4: Emit single compliance.evaluate event with all eligible patterns
        evaluation_submitted = False
        if eligible_patterns and not _budget_exceeded():
            evaluation_submitted = _emit_compliance_evaluate(
                file_path=file_path,
                content=content_preview,
                language=language or "unknown",
                session_id=session_id,
                content_sha256=content_sha256,
                patterns=eligible_patterns,
            )
            if evaluation_submitted:
                # Update cooldown for all submitted patterns with current timestamp
                now = time.time()
                new_cooldown = {str(p.get("id", "")): now for p in eligible_patterns}
                _save_cooldown(session_id, {**cooldown, **new_cooldown})

        return EnforcementResult(
            enforced=True,
            advisories=[],  # always empty — results arrive asynchronously
            patterns_queried=len(patterns),
            patterns_skipped_cooldown=skipped,
            elapsed_ms=_elapsed_ms(),
            error=None,
            evaluation_submitted=evaluation_submitted,
        )

    except Exception as exc:
        # Silent failure: enforcement must never block
        return EnforcementResult(
            enforced=False,
            advisories=[],
            patterns_queried=0,
            patterns_skipped_cooldown=0,
            elapsed_ms=_elapsed_ms(),
            error=str(exc),
            evaluation_submitted=False,
        )


# ---------------------------------------------------------------------------
# CLI entry point (called from post-tool-use-quality.sh)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for pattern enforcement.

    Reads JSON from stdin with file_path, session_id, language, content_preview,
    content_sha256. Writes EnforcementResult JSON to stdout. Always exits 0.
    """
    try:
        if not is_enforcement_enabled():
            json.dump(
                EnforcementResult(
                    enforced=False,
                    advisories=[],
                    patterns_queried=0,
                    patterns_skipped_cooldown=0,
                    elapsed_ms=0.0,
                    error=None,
                    evaluation_submitted=False,
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
                    patterns_queried=0,
                    patterns_skipped_cooldown=0,
                    elapsed_ms=0.0,
                    error="empty stdin",
                    evaluation_submitted=False,
                ),
                sys.stdout,
            )
            return

        params = json.loads(raw)
        session_id = params.get("session_id", "") or os.urandom(8).hex()
        result = enforce_patterns(
            file_path=params.get("file_path", ""),
            session_id=session_id,
            language=params.get("language"),
            domain=params.get("domain"),
            content_preview=params.get("content_preview", ""),
            content_sha256=params.get("content_sha256", ""),
        )
        json.dump(result, sys.stdout)

    except Exception as exc:
        # Absolute last resort: never crash
        json.dump(
            EnforcementResult(
                enforced=False,
                advisories=[],
                patterns_queried=0,
                patterns_skipped_cooldown=0,
                elapsed_ms=0.0,
                error=f"fatal: {exc}",
                evaluation_submitted=False,
            ),
            sys.stdout,
        )


if __name__ == "__main__":
    main()
