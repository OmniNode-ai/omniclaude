# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""End-to-end friction observer test — signal through to NDJSON roundtrip."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SHARED_PATH = str(
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "skills"
    / "_shared"
)
if _SHARED_PATH not in sys.path:
    sys.path.insert(0, _SHARED_PATH)

from friction_classifier import load_rules_from_yaml, match_signal
from friction_recorder import FrictionEvent, FrictionSeverity, record_friction
from friction_signal import FrictionSignal

_CONTRACT_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "src"
    / "omniclaude"
    / "nodes"
    / "node_friction_observer_compute"
    / "contract.yaml"
)


@pytest.mark.unit
class TestFrictionObserverE2E:
    def test_skill_blocked_full_chain(self, tmp_path: Path):
        """Full chain: signal -> classify -> FrictionEvent -> NDJSON -> read back."""
        registry = tmp_path / "friction.ndjson"

        # 1. Construct signal
        signal = FrictionSignal(
            source="claude_code_hook",
            event_type="skill.completed",
            payload={
                "status": "blocked",
                "skill_name": "deploy",
                "blocked_reason": "merge conflict",
            },
            timestamp=datetime.now(UTC),
            session_id="e2e-session",
            ticket_id="OMN-9999",
        )

        # 2. Classify using real contract rules
        rules = load_rules_from_yaml(_CONTRACT_PATH)
        result = match_signal(signal, rules)
        assert result is not None
        assert result.surface == "tooling/skill-blocked"
        assert result.severity == FrictionSeverity.HIGH

        # 3. Create FrictionEvent from classification
        event = FrictionEvent(
            skill=f"observer/{signal.source}",
            surface=result.surface,
            severity=result.severity,
            description=result.description,
            context_ticket_id=signal.ticket_id,
            session_id=signal.session_id or "",
            timestamp=signal.timestamp,
        )

        # 4. Record to NDJSON
        record_friction(event, registry_path=registry, emit_kafka=False)

        # 5. Read back and verify roundtrip
        lines = registry.read_text().strip().split("\n")
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["skill"] == "observer/claude_code_hook"
        assert record["surface"] == "tooling/skill-blocked"
        assert record["severity"] == "high"
        assert record["context_ticket_id"] == "OMN-9999"
        assert record["session_id"] == "e2e-session"
        assert "deploy" in record["description"]
        assert "merge conflict" in record["description"]

    def test_circuit_breaker_full_chain(self, tmp_path: Path):
        registry = tmp_path / "friction.ndjson"

        signal = FrictionSignal(
            source="kafka_consumer",
            event_type="circuit.breaker.tripped",
            payload={"failure_count": "10", "threshold": "3"},
            timestamp=datetime.now(UTC),
            session_id="e2e-kafka",
        )

        rules = load_rules_from_yaml(_CONTRACT_PATH)
        result = match_signal(signal, rules)
        assert result is not None

        event = FrictionEvent(
            skill=f"observer/{signal.source}",
            surface=result.surface,
            severity=result.severity,
            description=result.description,
            context_ticket_id=None,
            session_id=signal.session_id or "",
            timestamp=signal.timestamp,
        )
        record_friction(event, registry_path=registry, emit_kafka=False)

        record = json.loads(registry.read_text().strip())
        assert record["surface"] == "kafka/circuit-breaker"
        assert record["severity"] == "high"
        assert "10" in record["description"]
