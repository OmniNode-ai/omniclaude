# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""PreToolUse skill-substitution guard (OMN-13835).

Enforces the skill-first doctrine at the tool boundary: raw manual commands
that have a node-backed skill equivalent are warned or blocked with the skill
suggestion. The raw-command -> skill map is data-driven from
``raw_command_to_skill.yaml`` (sibling of this module) so adding a rule is a
pure data change.

Enforcement tiers (mirrors pre_tool_use_dispatch_guard / pre_tool_use_workflow_guard):

    Hard block (exit 2): a ``severity: block`` rule matches for the first time.
                         The guard records the block in a per-command override
                         marker so a deliberate operator retry can proceed.
    Warn (exit 1):       a ``severity: warn`` rule matches — surface the skill
                         suggestion but pass the tool call through.
    Pass-through (exit 0): no rule matches, OR a previously-blocked command is
                         retried within the override window (operator
                         "proceed-anyway" fallback). On that fallback the guard
                         files a friction event via the record_friction skill's
                         shared recorder so the friction registry captures every
                         skill-substitution override.

Two-phase override semantics (block rules):
    1. First time a raw blocked command is seen -> exit 2 (block) and a marker
       file is written under $ONEX_STATE_DIR/skill_substitution_guard/ keyed by
       a fingerprint of (rule_id, command text), stamped with the current time.
    2. If the exact same command is retried while the marker is still fresh
       (within OVERRIDE_WINDOW_SEC), the operator is proceeding anyway: the
       guard records friction, clears the marker, and allows (exit 0).
    A stale marker (older than the window) is treated as a fresh attempt and
    re-blocks — an ancient override never silently green-lights a raw merge.

CLI usage (invoked by pre_tool_use_skill_substitution_guard.sh):

    python3 -m omniclaude.hooks.pre_tool_use_skill_substitution_guard < tool_input.json

Reads JSON from stdin (Claude Code PreToolUse hook format).
Exits 0 (allow/pass-through), 1 (warn), or 2 (block).

Related:
    - OMN-13835: skill-first enforcement guard (re-enable + skill substitution)
    - OMN-13244: measurement baseline that gutted hooks.json (reverted here)
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_RULES_FILENAME = "raw_command_to_skill.yaml"
_MARKER_SUBDIR = "skill_substitution_guard"

# How long a block marker stays "fresh". A retry inside this window is treated
# as an operator proceed-anyway fallback (allow + friction). Outside it, the
# marker is stale and the command is re-blocked.
OVERRIDE_WINDOW_SEC = 900  # 15 minutes

# Friction taxonomy for skill-substitution overrides.
_FRICTION_SKILL = "skill_substitution_guard"
_FRICTION_SURFACE = "tooling/skill-substitution-override"


@dataclass(frozen=True)
class SubstitutionRule:
    """A single raw-command -> skill mapping rule."""

    rule_id: str
    tools: frozenset[str]
    pattern: re.Pattern[str]
    skill: str
    severity: str  # "block" | "warn"
    reason: str


_RULES_CACHE: list[SubstitutionRule] | None = None


# ---------------------------------------------------------------------------
# Rule loading
# ---------------------------------------------------------------------------


def _rules_path() -> Path:
    """Return the path to the raw_command_to_skill.yaml data file."""
    return Path(__file__).resolve().parent / _RULES_FILENAME


def load_rules(path: Path | None = None) -> list[SubstitutionRule]:
    """Load and compile substitution rules from the YAML data file.

    Malformed rules are skipped (logged) rather than raising — a bad rule must
    never wedge every tool call. Returns an empty list on any load failure.
    """
    rules_path = path or _rules_path()
    try:
        raw = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        logger.debug("skill_substitution_guard: rules load failed: %s", exc)
        return []

    compiled: list[SubstitutionRule] = []
    for entry in raw.get("rules", []) or []:
        if not isinstance(entry, dict):
            continue
        try:
            rule_id = str(entry["id"])
            tools = frozenset(str(t) for t in entry["tools"])
            pattern = re.compile(str(entry["pattern"]), re.IGNORECASE)
            skill = str(entry["skill"])
            severity = str(entry.get("severity", "warn")).lower()
            reason = str(entry.get("reason", "")).strip()
        except (KeyError, re.error) as exc:
            logger.debug("skill_substitution_guard: skipping bad rule: %s", exc)
            continue
        if severity not in ("block", "warn"):
            severity = "warn"
        compiled.append(
            SubstitutionRule(
                rule_id=rule_id,
                tools=tools,
                pattern=pattern,
                skill=skill,
                severity=severity,
                reason=reason,
            )
        )
    return compiled


def _get_rules(rules: list[SubstitutionRule] | None) -> list[SubstitutionRule]:
    global _RULES_CACHE  # noqa: PLW0603
    if rules is not None:
        return rules
    if _RULES_CACHE is None:
        _RULES_CACHE = load_rules()
    return _RULES_CACHE


# ---------------------------------------------------------------------------
# Command-text extraction
# ---------------------------------------------------------------------------

_AGENT_TEXT_FIELDS = ("prompt", "description", "subagent_type", "name", "task")


def _extract_command_text(tool_name: str, tool_input: dict[str, object]) -> str:
    """Return the text to match rule patterns against for a given tool call."""
    if tool_name == "Bash":
        return str(tool_input.get("command", ""))
    if tool_name in ("Agent", "Task"):
        parts = [str(tool_input[f]) for f in _AGENT_TEXT_FIELDS if tool_input.get(f)]
        # Fall back to a stable serialization so the '.*' rule always matches.
        return " ".join(parts) if parts else json.dumps(tool_input, sort_keys=True)
    return ""


# ---------------------------------------------------------------------------
# Override marker state
# ---------------------------------------------------------------------------


def _state_dir(state_dir: Path | None) -> Path:
    """Resolve the base state directory for override markers.

    Prefers the injected value, then ONEX_STATE_DIR (via onex_state), then a
    deterministic temp dir so the two-phase override still works when
    ONEX_STATE_DIR is unset (guard degrades but never wedges).
    """
    if state_dir is not None:
        return state_dir
    try:
        from omniclaude.hooks.lib.onex_state import state_root

        return state_root()
    except Exception:  # noqa: BLE001 - fall back, never raise from a hook
        return Path(tempfile.gettempdir()) / "onex_state"


def _marker_path(base: Path, rule_id: str, command_text: str) -> Path:
    fingerprint = hashlib.sha256(f"{rule_id}\x00{command_text}".encode()).hexdigest()[
        :16
    ]
    return base / _MARKER_SUBDIR / f"{fingerprint}.override"


def _read_marker_ts(marker: Path) -> float | None:
    try:
        return float(marker.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _write_marker(marker: Path, now: float) -> None:
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"{now}\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("skill_substitution_guard: marker write failed: %s", exc)


def _clear_marker(marker: Path) -> None:
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        logger.debug("skill_substitution_guard: marker clear failed: %s", exc)


# ---------------------------------------------------------------------------
# Friction recording (via the record_friction skill's shared recorder)
# ---------------------------------------------------------------------------


def _record_override_friction(
    rule: SubstitutionRule, command_text: str, session_id: str, ts: float
) -> None:
    """File a friction event for a skill-substitution override (proceed-anyway).

    Uses the record_friction skill's shared recorder when importable; otherwise
    falls back to a direct append to the same NDJSON registry. Never raises.
    """
    description = (
        f"Operator proceeded with raw command despite skill suggestion "
        f"'{rule.skill}' (rule {rule.rule_id}): {command_text[:120]}"
    )
    try:
        import importlib
        from datetime import UTC, datetime

        _shared = (
            Path(__file__).resolve().parents[3]
            / "plugins"
            / "onex"
            / "skills"
            / "_shared"
        )
        if str(_shared) not in sys.path:
            sys.path.insert(0, str(_shared))
        # Dynamic import: friction_recorder lives under plugins/onex/skills/_shared
        # and is only importable after the sys.path insertion above, so it is
        # resolved by name rather than a static import statement.
        recorder = importlib.import_module("friction_recorder")

        recorder.record_friction(
            recorder.FrictionEvent(
                skill=_FRICTION_SKILL,
                surface=_FRICTION_SURFACE,
                severity=recorder.FrictionSeverity.MEDIUM,
                description=description,
                context_ticket_id=None,
                session_id=session_id,
                timestamp=datetime.fromtimestamp(ts, tz=UTC),
            )
        )
    except Exception as exc:  # noqa: BLE001 - friction must never block a hook
        logger.debug("skill_substitution_guard: friction record failed: %s", exc)


# ---------------------------------------------------------------------------
# Advisory / block payloads
# ---------------------------------------------------------------------------


def _suggestion(rule: SubstitutionRule) -> str:
    reason = f" {rule.reason}" if rule.reason else ""
    return (
        f"[skill-substitution-guard] {rule.severity.upper()} — a skill covers "
        f"this raw command. Use `{rule.skill}` instead.{reason}"
    )


def _is_skill_originated_dispatch(
    tool_name: str, tool_input: dict[str, object]
) -> bool:
    if tool_name not in ("Agent", "Task"):
        return False
    fields = (
        "origin_skill",
        "source_skill",
        "skill",
        "onex_skill",
        "prompt",
        "description",
        "task",
    )
    text = " ".join(str(tool_input.get(field, "")) for field in fields)
    return "onex:self_healing_dispatch" in text or "onex:dispatch_worker" in text


# ---------------------------------------------------------------------------
# Core guard logic
# ---------------------------------------------------------------------------


def run_guard(
    stdin_json: str,
    *,
    rules: list[SubstitutionRule] | None = None,
    state_dir: Path | None = None,
    now: float | None = None,
    record_fn: Callable[[SubstitutionRule, str, str, float], None] | None = None,
) -> tuple[int, str]:
    """Run the skill-substitution guard against hook JSON from stdin.

    Args:
        stdin_json: Raw JSON string from Claude Code PreToolUse hook.
        rules: Optional injected rule set (defaults to the cached YAML load).
        state_dir: Optional base state dir for override markers (test seam).
        now: Optional epoch seconds override (test seam).
        record_fn: Optional friction recorder override (test seam).

    Returns:
        Tuple of (exit_code, output_string).
        exit_code 0: allow (output is original JSON).
        exit_code 1: warn (output is advisory JSON).
        exit_code 2: block (output is block JSON).
    """
    try:
        hook_data: dict[str, object] = json.loads(stdin_json)
    except json.JSONDecodeError:
        return 0, stdin_json

    tool_name = str(hook_data.get("tool_name", ""))
    raw_input = hook_data.get("tool_input", {})
    tool_input: dict[str, object] = raw_input if isinstance(raw_input, dict) else {}
    session_id = str(hook_data.get("session_id") or hook_data.get("sessionId") or "")

    command_text = _extract_command_text(tool_name, tool_input)
    if not command_text:
        return 0, stdin_json
    if _is_skill_originated_dispatch(tool_name, tool_input):
        return 0, stdin_json

    active_rules = _get_rules(rules)
    matched: SubstitutionRule | None = None
    for rule in active_rules:
        if tool_name in rule.tools and rule.pattern.search(command_text):
            matched = rule
            break

    if matched is None:
        return 0, stdin_json

    # --- Warn tier: surface suggestion, pass through ---
    if matched.severity == "warn":
        return 1, json.dumps({"decision": "warn", "reason": _suggestion(matched)})

    # --- Block tier: two-phase override ---
    ts = now if now is not None else time.time()
    base = _state_dir(state_dir)
    marker = _marker_path(base, matched.rule_id, command_text)
    marker_ts = _read_marker_ts(marker)

    if marker_ts is not None and (ts - marker_ts) <= OVERRIDE_WINDOW_SEC:
        # Operator is proceeding anyway (fallback) — record friction and allow.
        recorder = record_fn or _record_override_friction
        recorder(matched, command_text, session_id, ts)
        _clear_marker(marker)
        return 0, stdin_json

    # First hit (or stale marker) — block and (re)stamp the marker.
    _write_marker(marker, ts)
    return 2, json.dumps(
        {
            "decision": "block",
            "reason": (
                f"{_suggestion(matched)}\n\n"
                f"If you must run the raw command, re-issue it to proceed "
                f"anyway — the guard will allow the retry and record a friction "
                f"event for '{_FRICTION_SURFACE}'."
            ),
        }
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the skill-substitution guard."""
    stdin_data = sys.stdin.read()
    exit_code, output = run_guard(stdin_data)
    print(output)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
