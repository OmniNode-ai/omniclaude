#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Combined injector — OMN-4383 performance optimisation.

Merges architecture_handshake_injector and skill_suggestion_injector into a
single Python process to eliminate one cold-start (~64 ms) from the
SessionStart hook.

CLI contract (called from session-start.sh):
    Input  (stdin):  JSON object with optional ``project_path``/``cwd`` fields
    Argv[1]:         session_id string (optional, forwarded to skill suggestions)
    Output (stdout): single-line JSON object:
        {
            "handshake_context":  str,   # "" when not found
            "handshake_path":     str|null,
            "retrieval_ms":       int,
            "skill_suggestions":  str    # "" when no suggestions
        }

Always exits 0 — callers treat this as fire-and-forget.
"""

from __future__ import annotations

import json
import sys
import time

# ---------------------------------------------------------------------------
# Inline the two modules rather than importing them so this script remains
# self-contained even if the lib directory is not on PYTHONPATH.
# ---------------------------------------------------------------------------

# ── architecture_handshake_injector logic ───────────────────────────────────

import logging
import os
from pathlib import Path

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
_log_file = os.environ.get("LOG_FILE")
if _log_file:
    try:
        _handlers.append(logging.FileHandler(_log_file))
    except OSError:
        pass

logging.basicConfig(
    level=logging.WARNING,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)

HANDSHAKE_FILENAME = "architecture-handshake.md"
CLAUDE_DIR = ".claude"


def _find_handshake(project_path: str | Path | None = None) -> Path | None:
    try:
        search_path = Path(project_path) if project_path else Path.cwd()
        if not search_path.exists() or not search_path.is_dir():
            return None
        candidate = search_path / CLAUDE_DIR / HANDSHAKE_FILENAME
        return candidate if candidate.is_file() else None
    except Exception as exc:
        logger.warning("Error finding handshake: %s", exc)
        return None


def _read_handshake(handshake_path: Path) -> str:
    try:
        if not handshake_path.is_file():
            return ""
        return handshake_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Error reading handshake: %s", exc)
        return ""


# ── skill_suggestion_injector logic ─────────────────────────────────────────

from collections import Counter  # noqa: E402
from typing import Any  # noqa: E402

_PLUGIN_DIR = Path(__file__).parent.parent  # hooks/lib -> hooks -> plugin root
_DEFAULT_USAGE_LOG = Path.home() / ".claude" / "onex-skill-usage.log"
_DEFAULT_PROGRESSION_PATH = _PLUGIN_DIR.parent / "skills" / "progression.yaml"
_MAX_SUGGESTIONS = 2


def _normalize_skill_name(name: str) -> str:
    return name.removeprefix("onex:")


def _load_counts_from_log(log_path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    try:
        if not log_path.exists():
            return counts
        for raw in log_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            try:
                entry: dict[str, Any] = json.loads(line)
                skill = entry.get("skill_name", "")
                if skill:
                    counts[_normalize_skill_name(skill)] += 1
            except (json.JSONDecodeError, AttributeError):
                continue
    except OSError:
        pass
    return counts


def _load_counts_from_db(*, session_id: str) -> Counter[str] | None:
    try:
        import psycopg2  # type: ignore[import-untyped]

        db_url = os.getenv("OMNIBASE_INFRA_DB_URL", os.getenv("DATABASE_URL", ""))
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


def _load_usage_counts(
    *, log_path: Path, session_id: str, db_enabled: bool | None
) -> Counter[str]:
    if db_enabled is None:
        db_enabled = os.getenv("ENABLE_POSTGRES", "").lower() in {"1", "true", "yes"}
    if db_enabled:
        db_counts = _load_counts_from_db(session_id=session_id)
        if db_counts is not None:
            return db_counts
    return _load_counts_from_log(log_path)


def _load_progressions(progression_path: Path) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore[import-untyped]

        if not progression_path.exists():
            return []
        data = yaml.safe_load(progression_path.read_text(encoding="utf-8")) or {}
        return list(data.get("progressions", []))
    except Exception:  # noqa: BLE001
        return []


def _find_candidates(
    *, counts: Counter[str], progressions: list[dict[str, Any]]
) -> list[tuple[str, str]]:
    eligible: list[tuple[int, str, str]] = []
    for edge in progressions:
        from_skill = str(edge.get("from", ""))
        to_skill = str(edge.get("to", ""))
        after_uses = int(edge.get("after_uses", 1))
        if not from_skill or not to_skill:
            continue
        if counts[from_skill] >= after_uses and counts[to_skill] == 0:
            eligible.append((after_uses, from_skill, to_skill))
    eligible.sort(key=lambda t: t[0])
    return [(frm, to) for _, frm, to in eligible]


def _fallback_basic_skills(
    *, counts: Counter[str], progression_path: Path
) -> list[tuple[str, str]]:
    try:
        import yaml  # type: ignore[import-untyped]

        if not progression_path.exists():
            return []
        data = yaml.safe_load(progression_path.read_text(encoding="utf-8")) or {}
        progressions: list[dict[str, Any]] = data.get("progressions", [])
        from_skills: dict[str, int] = {}
        for edge in progressions:
            fs = str(edge.get("from", ""))
            au = int(edge.get("after_uses", 1))
            if fs and (fs not in from_skills or au < from_skills[fs]):
                from_skills[fs] = au
        unused_sorted = sorted(
            ((au, fs) for fs, au in from_skills.items() if counts[fs] == 0),
            key=lambda t: t[0],
        )
        return [("", fs) for _, fs in unused_sorted[:_MAX_SUGGESTIONS]]
    except Exception:  # noqa: BLE001
        return []


def _format_one(*, to_skill: str, from_skill: str) -> str:
    if from_skill:
        return (
            f"Based on your usage, you might want to try: "
            f"/onex:{to_skill} (builds on {from_skill})"
        )
    return f"You might want to try: /onex:{to_skill}"


def _get_skill_suggestions(session_id: str) -> str:
    try:
        counts = _load_usage_counts(
            log_path=_DEFAULT_USAGE_LOG,
            session_id=session_id,
            db_enabled=None,
        )
        progressions = _load_progressions(_DEFAULT_PROGRESSION_PATH)
        candidates = _find_candidates(counts=counts, progressions=progressions)
        if not candidates:
            candidates = _fallback_basic_skills(
                counts=counts, progression_path=_DEFAULT_PROGRESSION_PATH
            )
        selected = candidates[:_MAX_SUGGESTIONS]
        suggestions = [_format_one(to_skill=to, from_skill=frm) for frm, to in selected]
        return "\n".join(suggestions)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Combined CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run both injectors in one process; emit a single JSON line to stdout."""
    start_time = time.monotonic()

    session_id = sys.argv[1] if len(sys.argv) > 1 else ""

    # ── Architecture handshake ───────────────────────────────────────────────
    handshake_context = ""
    handshake_path_str: str | None = None

    try:
        raw_input = sys.stdin.read().strip()
        input_json: dict[str, str] = {}
        if raw_input:
            try:
                input_json = json.loads(raw_input)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid JSON input to combined_injector: %s", exc)

        project_path_str = input_json.get("project_path") or input_json.get("cwd") or ""
        handshake_path = _find_handshake(project_path_str or None)
        if handshake_path:
            handshake_context = _read_handshake(handshake_path)
            handshake_path_str = str(handshake_path)
    except Exception as exc:
        logger.error("Unexpected error in handshake phase: %s", exc)

    retrieval_ms = int((time.monotonic() - start_time) * 1000)

    # ── Skill suggestions ────────────────────────────────────────────────────
    skill_suggestions = _get_skill_suggestions(session_id)

    # ── Emit combined JSON ───────────────────────────────────────────────────
    output = {
        "handshake_context": handshake_context,
        "handshake_path": handshake_path_str,
        "retrieval_ms": retrieval_ms,
        "skill_suggestions": skill_suggestions,
    }
    print(json.dumps(output), flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
