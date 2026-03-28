# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for contract enricher module."""

import sys
from pathlib import Path

import pytest
import yaml

# Add the contract_generator package to the path
_lib_dir = (
    Path(__file__).resolve().parents[4]
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "contract_generator"
)
if str(_lib_dir) not in sys.path:
    sys.path.insert(0, str(_lib_dir))

from enrich_contract import enrich_contract_with_evidence


@pytest.mark.unit
class TestEnrichContract:
    """Test enriching skeleton contracts with dod_evidence."""

    SKELETON: dict[str, object] = {
        "schema_version": "1.0.0",
        "ticket_id": "OMN-9999",
        "summary": "Test ticket",
        "is_seam_ticket": False,
        "interface_change": False,
        "interfaces_touched": [],
        "evidence_requirements": [{"kind": "tests", "description": "Tests pass"}],
        "emergency_bypass": {
            "enabled": False,
            "justification": "",
            "follow_up_ticket_id": "",
        },
        "dod_evidence": [],
    }

    def test_adds_test_file_evidence(self) -> None:
        result = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(self.SKELETON),
            test_files=["tests/unit/test_foo.py"],
            repo="omniclaude",
        )
        parsed = yaml.safe_load(result)
        assert len(parsed["dod_evidence"]) == 3  # test_exists + test_pass + lint
        test_ev = [
            e
            for e in parsed["dod_evidence"]
            if e["checks"][0]["check_type"] == "test_exists"
        ]
        assert len(test_ev) == 1
        assert "tests/unit/test_foo.py" in test_ev[0]["checks"][0]["check_value"]

    def test_adds_test_pass_evidence(self) -> None:
        result = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(self.SKELETON),
            test_files=["tests/unit/test_foo.py"],
            test_command="uv run pytest tests/unit/test_foo.py -v",
            repo="omniclaude",
        )
        parsed = yaml.safe_load(result)
        pass_ev = [
            e for e in parsed["dod_evidence"] if "pass" in e["description"].lower()
        ]
        assert len(pass_ev) >= 1
        assert pass_ev[0]["checks"][0]["check_type"] == "command"

    def test_adds_lint_evidence(self) -> None:
        result = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(self.SKELETON),
            test_files=[],
            include_lint=True,
            repo="omniclaude",
        )
        parsed = yaml.safe_load(result)
        lint_ev = [
            e for e in parsed["dod_evidence"] if "lint" in e["description"].lower()
        ]
        assert len(lint_ev) == 1
        assert lint_ev[0]["checks"][0]["check_type"] == "command"
        assert "pre-commit" in lint_ev[0]["checks"][0]["check_value"]

    def test_validates_contract_fields_against_schema(self) -> None:
        """Contract base fields must still validate against ModelTicketContract."""
        result = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(self.SKELETON),
            test_files=["tests/unit/test_bar.py"],
            repo="omniclaude",
        )
        parsed = yaml.safe_load(result)
        from onex_change_control.models.model_ticket_contract import (
            ModelTicketContract,
        )

        # Validate contract fields (dod_evidence is extra data ignored by the model)
        contract = ModelTicketContract.model_validate(parsed)
        assert contract.ticket_id == "OMN-9999"
        # dod_evidence exists in the YAML dict even though the model ignores it
        assert len(parsed["dod_evidence"]) >= 1

    def test_idempotent_on_rerun(self) -> None:
        """Running enrichment twice with same inputs produces no duplicates."""
        first = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(self.SKELETON),
            test_files=["tests/unit/test_foo.py"],
            repo="omniclaude",
        )
        second = enrich_contract_with_evidence(
            contract_yaml=first,
            test_files=["tests/unit/test_foo.py"],
            repo="omniclaude",
        )
        parsed = yaml.safe_load(second)
        first_parsed = yaml.safe_load(first)
        assert len(parsed["dod_evidence"]) == len(first_parsed["dod_evidence"])

    def test_preserves_existing_dod_evidence(self) -> None:
        skeleton = dict(self.SKELETON)
        skeleton["dod_evidence"] = [
            {
                "id": "dod-existing",
                "description": "Existing",
                "source": "manual",
                "checks": [],
                "status": "verified",
            }
        ]
        result = enrich_contract_with_evidence(
            contract_yaml=yaml.dump(skeleton),
            test_files=["tests/unit/test_new.py"],
            repo="omniclaude",
        )
        parsed = yaml.safe_load(result)
        ids = [e["id"] for e in parsed["dod_evidence"]]
        assert "dod-existing" in ids
