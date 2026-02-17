#!/usr/bin/env python3
"""Pattern violation advisory formatter and persistence.

Bridges PostToolUse pattern enforcement (OMN-2263) with UserPromptSubmit
context injection (OMN-2269). Advisories detected in PostToolUse are
persisted to a temp file; UserPromptSubmit reads and clears them, then
formats as advisory markdown in additionalContext.

Strictly informational -- Claude can act on advisories or not.
Session cooldown is handled upstream by pattern_enforcement.py.

Persistence: /tmp/omniclaude-advisory-{uid}/{session_hash}.json

All failures are silent -- advisory injection never blocks or degrades UX.

Ticket: OMN-2269
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_uid: int | str
try:
    _uid = os.getuid()
except (AttributeError, OSError):
    _uid = "unknown"
_ADVISORY_DIR = Path(f"/tmp/omniclaude-advisory-{_uid}")  # noqa: S108
_MAX_ADVISORIES_PER_TURN = 5
_STALE_THRESHOLD_S = 3600  # 1 hour -- advisories older than this are discarded
_CLEANUP_MAX_AGE_S = 86400  # 24 hours -- files older than this are cleaned up


# ---------------------------------------------------------------------------
# Advisory file path
# ---------------------------------------------------------------------------


def _advisory_path(session_id: str) -> Path:
    """Return the advisory file path for a session.

    Uses SHA-256 hash of session_id to prevent path traversal.
    """
    safe_id = hashlib.sha256(session_id.encode()).hexdigest()[:16]
    return _ADVISORY_DIR / f"{safe_id}.json"


# ---------------------------------------------------------------------------
# Persistence: write advisories (called from PostToolUse)
# ---------------------------------------------------------------------------


def save_advisories(session_id: str, advisories: list[dict[str, Any]]) -> bool:
    """Persist advisory results for later consumption by UserPromptSubmit.

    Appends to any existing advisories for this session (multiple tool uses
    between prompts). Uses atomic temp-file-and-rename for safety.

    Race note: save_advisories (PostToolUse, async background) and
    load_and_clear_advisories (UserPromptSubmit, sync) can race on the same
    advisory file. An advisory written between load_and_clear's read and
    unlink may be lost. This is acceptable per design: data loss is
    tolerable, UI freeze is not. See CLAUDE.md Failure Modes.

    Args:
        session_id: Current session ID.
        advisories: List of PatternAdvisory dicts from pattern_enforcement.

    Returns:
        True if saved successfully, False on any failure.
    """
    if not advisories:
        return True

    try:
        _ADVISORY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = _advisory_path(session_id)

        # Load existing advisories (if any, from earlier tool uses in same turn).
        # Race note: path may have been unlinked by load_and_clear_advisories
        # between our exists() check and read. This is benign -- we just start
        # with an empty list and the new advisories are saved normally.
        existing: list[dict[str, Any]] = []
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("advisories"), list):
                    existing = data["advisories"]
        except (json.JSONDecodeError, OSError, TypeError):
            pass

        # Merge: append new advisories, deduplicate by pattern_id.
        # Empty/missing pattern_ids are always kept (can't be deduped meaningfully).
        seen_ids: set[str] = {
            a.get("pattern_id", "") for a in existing if a.get("pattern_id")
        }
        for advisory in advisories:
            pid = advisory.get("pattern_id", "")
            if not pid:
                existing.append(advisory)
            elif pid not in seen_ids:
                existing.append(advisory)
                seen_ids.add(pid)

        # Cap total advisories to prevent unbounded growth.
        # Allow 2x on save since multiple PostToolUse calls accumulate between
        # UserPromptSubmit reads. The load path trims to _MAX_ADVISORIES_PER_TURN.
        capped = existing[-_MAX_ADVISORIES_PER_TURN * 2 :]

        payload = {
            "advisories": capped,
            "written_at": time.time(),
        }

        # Atomic write
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(_ADVISORY_DIR), suffix=".tmp")
        try:
            os.write(tmp_fd, json.dumps(payload).encode())
            os.close(tmp_fd)
            Path(tmp_path).replace(path)
        except Exception:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            return False

        return True

    except OSError:
        return False


# ---------------------------------------------------------------------------
# Persistence: read + clear advisories (called from UserPromptSubmit)
# ---------------------------------------------------------------------------


def load_and_clear_advisories(session_id: str) -> list[dict[str, Any]]:
    """Read pending advisories and clear the file.

    Returns advisories accumulated since the last UserPromptSubmit.
    Discards stale advisories (older than 1 hour).

    Race note: save_advisories (PostToolUse, async background) and this
    function (UserPromptSubmit, sync) can race on the same advisory file.
    An advisory written between read and unlink may be lost. This is
    acceptable per design: data loss is tolerable, UI freeze is not.
    See CLAUDE.md Failure Modes.

    Args:
        session_id: Current session ID.

    Returns:
        List of PatternAdvisory dicts, or empty list on any failure.
    """
    path = _advisory_path(session_id)

    try:
        if not path.exists():
            return []

        data = json.loads(path.read_text(encoding="utf-8"))

        # Clear immediately after reading (atomic unlink)
        try:
            path.unlink()
        except OSError:
            pass

        if not isinstance(data, dict):
            return []

        # Check staleness
        written_at = data.get("written_at", 0)
        if isinstance(written_at, (int, float)) and (
            time.time() - written_at > _STALE_THRESHOLD_S
        ):
            return []

        advisories = data.get("advisories", [])
        if not isinstance(advisories, list):
            return []

        return advisories[:_MAX_ADVISORIES_PER_TURN]

    except (json.JSONDecodeError, OSError, TypeError):
        # Clean up corrupt file
        try:
            path.unlink()
        except OSError:
            pass
        return []


# ---------------------------------------------------------------------------
# Formatting: advisories -> markdown
# ---------------------------------------------------------------------------

_ADVISORY_HEADER = (
    "## Pattern Advisory\n\n"
    "The following patterns may apply to your recent changes. "
    "These are informational suggestions -- use your judgment.\n"
)


def format_advisories_markdown(advisories: list[dict[str, Any]]) -> str:
    """Format advisory list as markdown for additionalContext injection.

    Produces a compact, readable advisory block that Claude can act on
    (or ignore). Format:

        ## Pattern Advisory

        The following patterns may apply to your recent changes.
        These are informational suggestions -- use your judgment.

        - **Pattern Name** (85% confidence): Description of the pattern.
        - **Another Pattern** (72% confidence): Another description.

    Args:
        advisories: List of PatternAdvisory dicts.

    Returns:
        Formatted markdown string, or empty string if no advisories.
    """
    if not advisories:
        return ""

    lines: list[str] = [_ADVISORY_HEADER]

    for advisory in advisories[:_MAX_ADVISORIES_PER_TURN]:
        signature = advisory.get("pattern_signature", "Unknown Pattern")
        confidence = advisory.get("confidence", 0.0)
        message = advisory.get("message", "")

        # Truncate long signatures
        if len(signature) > 80:
            signature = signature[:77] + "..."

        confidence_pct = f"{confidence * 100:.0f}%"

        if message:
            lines.append(f"- **{signature}** ({confidence_pct} confidence): {message}")
        else:
            lines.append(f"- **{signature}** ({confidence_pct} confidence)")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Combined entry point for UserPromptSubmit
# ---------------------------------------------------------------------------


def get_advisory_context(session_id: str) -> str:
    """Load pending advisories and return formatted markdown.

    This is the main entry point called from UserPromptSubmit. It:
    1. Reads pending advisories from the advisory file
    2. Clears the file (so advisories are shown once)
    3. Formats as markdown

    Args:
        session_id: Current session ID.

    Returns:
        Formatted markdown string for additionalContext, or empty string.
    """
    if not session_id:
        return ""

    advisories = load_and_clear_advisories(session_id)
    if not advisories:
        return ""

    return format_advisories_markdown(advisories)


# ---------------------------------------------------------------------------
# Cleanup stale advisory files
# ---------------------------------------------------------------------------


def cleanup_stale_files() -> None:
    """Remove advisory files older than 24 hours.

    Best-effort sweep -- silently ignores any failures.
    """
    try:
        if not _ADVISORY_DIR.exists():
            return
        now = time.time()
        for entry in _ADVISORY_DIR.iterdir():
            try:
                if entry.is_file() and (
                    now - entry.stat().st_mtime > _CLEANUP_MAX_AGE_S
                ):
                    entry.unlink()
            except OSError:
                pass
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLI entry point (for shell script integration)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for advisory formatting.

    Modes:
        save: Read JSON from stdin, save advisories.
            stdin: {"session_id": "...", "advisories": [...]}
        load: Read session_id from stdin, output formatted markdown.
            stdin: {"session_id": "..."}
        cleanup: Remove stale advisory files.

    Always exits 0.
    """
    import sys

    try:
        if len(sys.argv) < 2:
            print(
                "Usage: pattern_advisory_formatter.py <save|load|cleanup>",
                file=sys.stderr,
            )
            sys.exit(0)

        mode = sys.argv[1]

        if mode == "save":
            raw = sys.stdin.read()
            if not raw.strip():
                sys.exit(0)
            params = json.loads(raw)
            session_id = params.get("session_id", "")
            advisories = params.get("advisories", [])
            if session_id and advisories:
                save_advisories(session_id, advisories)

        elif mode == "load":
            raw = sys.stdin.read()
            if not raw.strip():
                print("")
                sys.exit(0)
            params = json.loads(raw)
            session_id = params.get("session_id", "")
            result = get_advisory_context(session_id)
            print(result, end="")

        elif mode == "cleanup":
            cleanup_stale_files()

        else:
            print(f"Unknown mode: {mode}", file=sys.stderr)

    except Exception as exc:
        # Silent failure -- never crash
        print(f"pattern_advisory_formatter error: {exc}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
