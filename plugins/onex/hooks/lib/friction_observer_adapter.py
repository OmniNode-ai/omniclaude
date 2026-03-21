# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Friction observer hook adapter — thin delegate to contract-driven classifier.

Constructs FrictionSignal from hook event data, classifies via rules loaded
from the FrictionObserverNode contract YAML, and records friction via the
existing friction_recorder. This module is called from stop.sh and post-tool-use hooks.

The adapter owns the side effects (NDJSON append, optional Kafka emit).
The classifier is pure computation.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Add _shared to sys.path for friction imports
_SHARED_PATH = str(Path(__file__).resolve().parent.parent.parent / "skills" / "_shared")
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_classifier import (  # noqa: E402
    ClassificationRule,
    load_rules_from_yaml,
    match_signal,
)
from friction_recorder import FrictionEvent, record_friction  # noqa: E402
from friction_signal import FrictionSignal  # noqa: E402

logger = logging.getLogger(__name__)

# Contract path — the single source of classification rules
_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_friction_observer_compute"
    / "contract.yaml"
)

# Lazy-loaded rules (avoid reading YAML on every hook invocation)
_RULES: list[ClassificationRule] | None = None


def _get_rules() -> list[ClassificationRule]:
    global _RULES  # noqa: PLW0603
    if _RULES is None:
        _RULES = load_rules_from_yaml(_CONTRACT_PATH)
    return _RULES


def observe_friction(
    *,
    event_type: str,
    payload: dict[str, Any],
    session_id: str,
    source: str = "claude_code_hook",
    ticket_id: str | None = None,
    registry_path: Path | None = None,
) -> bool:
    """Classify and record a friction event. Returns True if friction was recorded.

    Args:
        event_type: Semantic event key (e.g. "skill.completed", "circuit.breaker.tripped")
        payload: Raw event data dict
        session_id: Claude Code session ID
        source: Origin identifier (default: "claude_code_hook")
        ticket_id: Associated Linear ticket ID, if known
        registry_path: Override NDJSON path (used in tests)

    Returns:
        True if a friction event was classified and recorded, False otherwise.
    """
    try:
        signal = FrictionSignal(
            source=source,
            event_type=event_type,
            payload=payload,
            timestamp=datetime.now(UTC),
            session_id=session_id,
            ticket_id=ticket_id,
        )

        try:
            rules = _get_rules()
        except Exception:
            logger.warning(
                "friction_observer: contract_load_failed — rules could not be loaded from %s",
                _CONTRACT_PATH,
            )
            return False

        result = match_signal(signal, rules)
        if result is None:
            logger.debug(
                "friction_observer: classification_no_match — event_type=%s source=%s",
                event_type,
                source,
            )
            return False

        event = FrictionEvent(
            skill=f"observer/{source}",
            surface=result.surface,
            severity=result.severity,
            description=result.description,
            context_ticket_id=ticket_id,
            session_id=session_id,
            timestamp=signal.timestamp,
        )

        try:
            record_friction(event, registry_path=registry_path, emit_kafka=False)
        except Exception:
            logger.warning(
                "friction_observer: friction_record_failed — surface=%s severity=%s",
                result.surface,
                result.severity.value,
            )
            return False

        # Opportunistic Kafka emission (separate from record_friction's own emit)
        try:
            from emit_client_wrapper import emit_event  # noqa: E402

            emit_event(
                "friction.observed",
                {
                    "session_id": session_id,
                    "surface": result.surface,
                    "severity": result.severity.value,
                    "event_pattern": result.event_pattern,
                    "source": source,
                    "description": result.description,
                },
            )
        except Exception:
            logger.debug(
                "friction_observer: telemetry_emit_failed — best-effort, non-blocking"
            )

        return True
    except Exception:
        # WARNING not DEBUG — broken friction capture must be diagnosable
        # from normal hook logs without requiring invasive debug tracing
        logger.warning(
            "friction_observer: unexpected_failure — capture disabled for this event",
            exc_info=True,
        )
        return False
