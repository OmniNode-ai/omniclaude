# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for generate-ticket-contract skill (OMN-2975).

Tests cover:
- Seam detection heuristics (keyword scan on title + description)
- interfaces_touched inference
- evidence_required: seam vs non-seam
- validate_contract.py exit codes (0 = valid, 1 = invalid)
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Import validate_contract.py directly (it lives in skills/, not src/)
# ---------------------------------------------------------------------------
_SKILL_DIR = (
    Path(__file__).parent.parent.parent.parent
    / "plugins/onex/skills/generate-ticket-contract"
)
_VALIDATOR_PATH = _SKILL_DIR / "validate_contract.py"

_spec = importlib.util.spec_from_file_location("validate_contract", _VALIDATOR_PATH)
assert _spec is not None and _spec.loader is not None
_validator_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_validator_module)  # type: ignore[union-attr]

_load_yaml = _validator_module._load_yaml  # type: ignore[attr-defined]
_validate = _validator_module._validate  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Seam detection logic (mirrored from prompt.md for pure-function testing)
# ---------------------------------------------------------------------------

_SEAM_SIGNALS: dict[str, list[str]] = {
    "topics": ["kafka", "topic", "consumer", "producer"],
    "events": ["schema", "payload", "event model", "modelhook"],
    "protocols": ["spi", "protocol", "interface"],
    "envelopes": ["envelope", "header"],
    "public_api": ["endpoint", "route", "api", "rest"],
}

_KNOWN_REPOS = [
    "omniclaude",
    "omnibase_core",
    "omnibase_infra",
    "omnibase_spi",
    "omnidash",
    "omniintelligence",
    "omnimemory",
    "omninode_infra",
    "omniweb",
    "onex_change_control",
]


def detect_seams(title: str, description: str) -> tuple[bool, list[str]]:
    """Detect interface seams from ticket title + description.

    Returns:
        (is_seam_ticket, interfaces_touched)
    """
    text = (title + " " + description).lower()
    interfaces: list[str] = []

    for iface, keywords in _SEAM_SIGNALS.items():
        if any(kw in text for kw in keywords):
            interfaces.append(iface)

    # Force seam if multiple repo names appear
    repo_count = sum(1 for repo in _KNOWN_REPOS if repo in text)
    if repo_count > 1:
        return True, interfaces

    return bool(interfaces), interfaces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_valid_contract(ticket_id: str = "OMN-0001") -> dict:
    """Return a minimal dict that passes ModelTicketContract.model_validate()."""
    return {
        "ticket_id": ticket_id,
        "title": "Test ticket",
        "description": "A minimal test ticket.",
        "phase": "intake",
        "requirements": [
            {
                "id": "REQ-001",
                "statement": "Do the thing.",
                "acceptance": ["Thing is done."],
            }
        ],
    }


def _write_yaml(data: dict, path: Path) -> None:
    path.write_text(yaml.dump(data, default_flow_style=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: seam detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSeamDetection:
    def test_kafka_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Implement Kafka consumer", "")
        assert is_seam is True
        assert "topics" in ifaces

    def test_topic_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Subscribe to agent topic", "")
        assert is_seam is True
        assert "topics" in ifaces

    def test_producer_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("", "Write a producer for events")
        assert is_seam is True
        assert "topics" in ifaces

    def test_schema_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Define schema for payload", "")
        assert is_seam is True
        assert "events" in ifaces

    def test_spi_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Implement SPI for session", "")
        assert is_seam is True
        assert "protocols" in ifaces

    def test_envelope_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Add envelope header fields", "")
        assert is_seam is True
        assert "envelopes" in ifaces

    def test_api_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Create REST endpoint", "")
        assert is_seam is True
        assert "public_api" in ifaces

    def test_route_signal_detected(self) -> None:
        is_seam, ifaces = detect_seams("Add route for /health", "")
        assert is_seam is True
        assert "public_api" in ifaces

    def test_no_seam_signals(self) -> None:
        is_seam, ifaces = detect_seams(
            "Fix typo in README", "Just update the documentation."
        )
        assert is_seam is False
        assert ifaces == []

    def test_multiple_repos_forces_seam(self) -> None:
        # Mentioning more than one repo triggers seam detection
        is_seam, _ = detect_seams(
            "Bridge omniclaude and omnibase_core", "Sync data between repos."
        )
        assert is_seam is True

    def test_single_repo_does_not_force_seam(self) -> None:
        is_seam, ifaces = detect_seams(
            "Fix bug in omniclaude plugin", "Only touches omniclaude."
        )
        # Only one repo mentioned — seam only if signal keyword also present
        assert is_seam is False
        assert ifaces == []

    def test_multiple_interfaces_from_same_ticket(self) -> None:
        is_seam, ifaces = detect_seams(
            "Kafka producer with REST endpoint",
            "Publishes events via topic and exposes an API route.",
        )
        assert is_seam is True
        assert "topics" in ifaces
        assert "public_api" in ifaces

    def test_case_insensitive_detection(self) -> None:
        is_seam, ifaces = detect_seams("KAFKA CONSUMER", "USES TOPIC")
        assert is_seam is True
        assert "topics" in ifaces

    def test_modelhook_signal(self) -> None:
        is_seam, ifaces = detect_seams("", "Implement ModelHook for session events")
        assert is_seam is True
        assert "events" in ifaces


# ---------------------------------------------------------------------------
# Tests: evidence_required inference
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEvidenceRequired:
    def test_seam_ticket_requires_integration(self) -> None:
        is_seam, _ = detect_seams("Kafka consumer", "")
        assert is_seam is True
        # Seam tickets require unit + ci + integration
        expected = ["unit", "ci", "integration"]
        evidence = expected if is_seam else ["unit", "ci"]
        assert evidence == ["unit", "ci", "integration"]

    def test_non_seam_ticket_requires_only_unit_ci(self) -> None:
        is_seam, _ = detect_seams("Fix typo", "minor fix")
        evidence = ["unit", "ci", "integration"] if is_seam else ["unit", "ci"]
        assert evidence == ["unit", "ci"]


# ---------------------------------------------------------------------------
# Tests: validate_contract.py _validate() function
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateFunction:
    def test_valid_minimal_contract_returns_no_errors(self) -> None:
        data = _minimal_valid_contract()
        errors = _validate(data)
        assert errors == []

    def test_missing_ticket_id_returns_error(self) -> None:
        data = _minimal_valid_contract()
        del data["ticket_id"]
        errors = _validate(data)
        assert len(errors) > 0
        assert any("ticket_id" in e for e in errors)

    def test_missing_title_returns_error(self) -> None:
        data = _minimal_valid_contract()
        del data["title"]
        errors = _validate(data)
        assert len(errors) > 0
        assert any("title" in e for e in errors)

    def test_non_dict_input_returns_error(self) -> None:
        errors = _validate("not a dict")
        assert len(errors) > 0
        assert any("mapping" in e or "Expected" in e for e in errors)

    def test_invalid_phase_returns_error(self) -> None:
        data = _minimal_valid_contract()
        data["phase"] = "completely_invalid_phase"
        errors = _validate(data)
        assert len(errors) > 0

    def test_requirement_missing_statement_returns_error(self) -> None:
        data = _minimal_valid_contract()
        data["requirements"] = [{"id": "REQ-001"}]  # missing required 'statement'
        errors = _validate(data)
        assert len(errors) > 0

    def test_extra_fields_allowed(self) -> None:
        """ModelTicketContract uses extra='allow', so extra fields should be OK."""
        data = _minimal_valid_contract()
        data["is_seam_ticket"] = True
        data["interfaces_touched"] = ["topics"]
        data["evidence_required"] = ["unit", "ci", "integration"]
        errors = _validate(data)
        assert errors == []


# ---------------------------------------------------------------------------
# Tests: validate_contract.py exit codes (via subprocess)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateExitCodes:
    def test_exit_0_on_valid_yaml(self) -> None:
        data = _minimal_valid_contract("OMN-9999")
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            tmp = Path(f.name)
        _write_yaml(data, tmp)
        try:
            result = subprocess.run(
                [sys.executable, str(_VALIDATOR_PATH), str(tmp)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
            assert "OK" in result.stdout
        finally:
            tmp.unlink(missing_ok=True)

    def test_exit_1_on_invalid_yaml_missing_ticket_id(self) -> None:
        data = _minimal_valid_contract()
        del data["ticket_id"]
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            tmp = Path(f.name)
        _write_yaml(data, tmp)
        try:
            result = subprocess.run(
                [sys.executable, str(_VALIDATOR_PATH), str(tmp)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 1, f"stdout: {result.stdout}"
            assert "ticket_id" in result.stderr
        finally:
            tmp.unlink(missing_ok=True)

    def test_exit_2_on_missing_file(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_VALIDATOR_PATH), "/tmp/nonexistent_contract.yaml"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2

    def test_exit_2_on_no_args(self) -> None:
        result = subprocess.run(
            [sys.executable, str(_VALIDATOR_PATH)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2

    def test_exit_0_with_seam_extra_fields(self) -> None:
        """Extra fields (is_seam_ticket, interfaces_touched) are allowed."""
        data = _minimal_valid_contract("OMN-1234")
        data["is_seam_ticket"] = True
        data["interfaces_touched"] = ["topics", "events"]
        data["evidence_required"] = ["unit", "ci", "integration"]
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            tmp = Path(f.name)
        _write_yaml(data, tmp)
        try:
            result = subprocess.run(
                [sys.executable, str(_VALIDATOR_PATH), str(tmp)],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0, f"stderr: {result.stderr}"
        finally:
            tmp.unlink(missing_ok=True)
