# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Skill Suggestion Injector — OMN-3455

Reads ~/.claude/onex-skill-usage.log (or queries Postgres when available),
loads the static progression graph from progression.yaml, and returns 1-2
"next skill" suggestions to inject into the session context on SessionStart.

Privacy guarantee: suggestion messages contain only skill names — no prompt
content, no personal data, no file paths, no code.

Callers must treat this module as fire-and-forget; it never raises.

Public API
----------
    get_skill_suggestions(session_id, *, log_path, progression_path, db_enabled)
        -> list[str]   — 0, 1, or 2 suggestion strings, ready to inject

    format_suggestions(suggestions: list[str]) -> str
        -> multiline injection block, or "" when empty
"""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Default paths
# ---------------------------------------------------------------------------


def _default_usage_log() -> Path:
    from omniclaude.hooks.lib.onex_state import state_path  # noqa: PLC0415

    return state_path("onex-skill-usage.log")


DEFAULT_USAGE_LOG: Path = _default_usage_log()

# progression.yaml lives alongside the skills/ directory in the plugin
_PLUGIN_DIR = Path(__file__).parent.parent  # hooks/lib -> hooks -> plugin root
DEFAULT_PROGRESSION_PATH: Path = _PLUGIN_DIR.parent / "skills" / "progression.yaml"

_MAX_SUGGESTIONS: int = 2

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_skill_suggestions(
    session_id: str,
    *,
    log_path: Path | None = None,
    progression_path: Path | None = None,
    db_enabled: bool | None = None,
) -> list[str]:
    """Return 0-2 skill suggestion strings for injection.

    Parameters
    ----------
    session_id:
        Current Claude session identifier (used for Postgres query if enabled).
    log_path:
        Override for ~/.claude/onex-skill-usage.log (mainly for tests).
    progression_path:
        Override for skills/progression.yaml (mainly for tests).
    db_enabled:
        Override for ENABLE_POSTGRES env-var detection.  None = read env.

    Returns
    -------
    list[str]
        Ready-to-inject suggestion strings, e.g.:
        ["💡 Based on your usage, you might want to try: /onex:pr-polish "
         "(builds on local-review)"]
    """
    try:
        return _compute_suggestions(
            session_id=session_id,
            log_path=log_path or DEFAULT_USAGE_LOG,
            progression_path=progression_path or DEFAULT_PROGRESSION_PATH,
            db_enabled=db_enabled,
        )
    except Exception:  # noqa: BLE001
        return []


def format_suggestions(suggestions: list[str]) -> str:
    """Format suggestion list into a multiline injection block.

    Returns an empty string when *suggestions* is empty so callers can
    short-circuit: ``if block := format_suggestions(suggestions): inject(block)``
    """
    if not suggestions:
        return ""
    return "\n".join(suggestions)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_suggestions(
    *,
    session_id: str,
    log_path: Path,
    progression_path: Path,
    db_enabled: bool | None,
) -> list[str]:
    counts = _load_usage_counts(
        log_path=log_path,
        session_id=session_id,
        db_enabled=db_enabled,
    )
    progressions = _load_progressions(progression_path)
    candidates = _find_candidates(counts=counts, progressions=progressions)

    # Fallback: suggest basic skills never used
    if not candidates:
        candidates = _fallback_basic_skills(
            counts=counts,
            progression_path=progression_path,
        )

    # Pick top N by priority (lowest after_uses threshold met first)
    selected = candidates[:_MAX_SUGGESTIONS]
    return [_format_one(to_skill=to, from_skill=frm) for frm, to in selected]


def _load_usage_counts(
    *,
    log_path: Path,
    session_id: str,
    db_enabled: bool | None,
) -> Counter[str]:
    """Return per-skill usage counts, preferring Postgres when available."""
    if db_enabled is None:
        db_enabled = os.getenv(  # ONEX_FLAG_EXEMPT: migration
            "ENABLE_POSTGRES", ""
        ).lower() in {"1", "true", "yes"}

    if db_enabled:
        db_counts = _load_counts_from_db(session_id=session_id)
        if db_counts is not None:
            return db_counts

    return _load_counts_from_log(log_path)


def _load_counts_from_log(log_path: Path) -> Counter[str]:
    """Parse JSONL usage log and count per-skill invocations."""
    counts: Counter[str] = Counter()
    try:
        if not log_path.exists():
            return counts
        for raw_line in log_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                entry: dict[str, Any] = json.loads(line)
                skill = entry.get("skill_name", "")
                if skill:
                    # Normalize: strip "onex:" prefix for matching against progression
                    skill = _normalize_skill_name(skill)
                    counts[skill] += 1
            except (json.JSONDecodeError, AttributeError):
                continue
    except OSError:
        pass
    return counts


def _normalize_skill_name(name: str) -> str:
    """Strip the ``onex:`` namespace prefix for progression graph lookups."""
    return name.removeprefix("onex:")


def _load_counts_from_db(*, session_id: str) -> Counter[str] | None:
    """Query ``skill_usage`` table; returns None on any error (non-fatal)."""
    try:
        import psycopg2

        db_url = os.getenv(
            "OMNIBASE_INFRA_DB_URL",
            os.getenv("DATABASE_URL", ""),
        )
        if not db_url:
            return None

        conn = psycopg2.connect(db_url)
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT skill_name, COUNT(*) FROM skill_usage GROUP BY skill_name"
                    )
                    rows = cur.fetchall()
        finally:
            conn.close()

        counts: Counter[str] = Counter()
        for skill_name, count in rows:
            counts[_normalize_skill_name(skill_name)] += int(count)
        return counts
    except Exception:  # noqa: BLE001
        return None


def _load_progressions(progression_path: Path) -> list[dict[str, Any]]:
    """Load and parse progression.yaml; returns [] on any error."""
    try:
        import yaml

        if not progression_path.exists():
            return []
        data = yaml.safe_load(progression_path.read_text(encoding="utf-8")) or {}
        return list(data.get("progressions", []))
    except Exception:  # noqa: BLE001
        return []


def _find_candidates(
    *,
    counts: Counter[str],
    progressions: list[dict[str, Any]],
) -> list[tuple[str, str]]:
    """Return (from_skill, to_skill) pairs the user is ready for.

    Prioritizes progressions with the *lowest* ``after_uses`` threshold that has
    been met, so the most immediately actionable suggestions appear first.
    """
    eligible: list[tuple[int, str, str]] = []  # (after_uses, from, to)
    for edge in progressions:
        from_skill = str(edge.get("from", ""))
        to_skill = str(edge.get("to", ""))
        after_uses = int(edge.get("after_uses", 1))

        if not from_skill or not to_skill:
            continue

        # User has used `from` skill enough times AND hasn't yet used `to` skill
        if counts[from_skill] >= after_uses and counts[to_skill] == 0:
            eligible.append((after_uses, from_skill, to_skill))

    # Sort by ascending after_uses (most immediately obvious suggestions first)
    eligible.sort(key=lambda t: t[0])
    return [(frm, to) for _, frm, to in eligible]


def _fallback_basic_skills(
    *,
    counts: Counter[str],
    progression_path: Path,
) -> list[tuple[str, str]]:
    """Suggest basic `from` skills the user has never used.

    Used when no progression edges are ready (new user with no usage history).
    Returns at most _MAX_SUGGESTIONS entries with a sentinel from_skill of "".
    """
    try:
        import yaml

        if not progression_path.exists():
            return []
        data = yaml.safe_load(progression_path.read_text(encoding="utf-8")) or {}
        progressions: list[dict[str, Any]] = data.get("progressions", [])

        # Collect unique from-skills; use lowest after_uses per skill for ordering
        from_skills: dict[str, int] = {}
        for edge in progressions:
            fs = str(edge.get("from", ""))
            au = int(edge.get("after_uses", 1))
            if fs and (fs not in from_skills or au < from_skills[fs]):
                from_skills[fs] = au

        # Pick from-skills that have never been used, ordered by after_uses
        unused_sorted = sorted(
            ((au, fs) for fs, au in from_skills.items() if counts[fs] == 0),
            key=lambda t: t[0],
        )
        # Return ("", skill) tuples — "" sentinel signals fallback in _format_one
        return [("", fs) for _, fs in unused_sorted[:_MAX_SUGGESTIONS]]
    except Exception:  # noqa: BLE001
        return []


def _format_one(*, to_skill: str, from_skill: str) -> str:
    """Format a single suggestion string."""
    if from_skill:
        return (
            f"Based on your usage, you might want to try: "
            f"/onex:{to_skill} (builds on {from_skill})"
        )
    # Fallback format (no prior `from` skill usage)
    return f"You might want to try: /onex:{to_skill}"


# ---------------------------------------------------------------------------
# CLI entry-point (called from session-start.sh)
# ---------------------------------------------------------------------------


def _main() -> None:
    """Print injection block to stdout; exit 0 always (fire-and-forget)."""
    import sys

    # Read optional session_id from first argument
    session_id = sys.argv[1] if len(sys.argv) > 1 else ""

    suggestions = get_skill_suggestions(session_id)
    block = format_suggestions(suggestions)
    if block:
        print(block, flush=True)
    sys.exit(0)


if __name__ == "__main__":
    _main()
