# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for contract generator module."""

import sys
from pathlib import Path

import pytest
import yaml

# Add the contract_generator package to the path so it can be imported directly
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

from generate_contract import generate_skeleton_contract


@pytest.mark.unit
class TestGenerateSkeletonContract:
    """Test skeleton contract generation from ticket metadata."""

    def test_generates_valid_yaml_for_simple_ticket(self) -> None:
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Add foo widget to bar service",
            is_seam_ticket=False,
        )
        parsed = yaml.safe_load(result)
        assert parsed["schema_version"] == "1.0.0"
        assert parsed["ticket_id"] == "OMN-9999"
        assert parsed["summary"] == "Add foo widget to bar service"
        assert parsed["is_seam_ticket"] is False
        assert parsed["interface_change"] is False
        assert parsed["interfaces_touched"] == []
        assert parsed["emergency_bypass"]["enabled"] is False

    def test_generates_seam_contract_with_interfaces(self) -> None:
        result = generate_skeleton_contract(
            ticket_id="OMN-8888",
            summary="Add Kafka topic for events",
            is_seam_ticket=True,
            interfaces_touched=["events", "topics"],
        )
        parsed = yaml.safe_load(result)
        assert parsed["is_seam_ticket"] is True
        assert parsed["interface_change"] is True
        assert "events" in parsed["interfaces_touched"]
        assert "topics" in parsed["interfaces_touched"]

    def test_validates_against_onex_cc_schema(self) -> None:
        """Generated YAML must parse into ModelTicketContract without errors."""
        result = generate_skeleton_contract(
            ticket_id="OMN-7777",
            summary="Test schema compliance",
            is_seam_ticket=False,
        )
        parsed = yaml.safe_load(result)
        from onex_change_control.models.model_ticket_contract import ModelTicketContract

        contract = ModelTicketContract.model_validate(parsed)
        assert contract.ticket_id == "OMN-7777"

    def test_output_is_idempotent(self) -> None:
        """Same inputs produce same YAML."""
        a = generate_skeleton_contract(
            ticket_id="OMN-1111", summary="Test", is_seam_ticket=False
        )
        b = generate_skeleton_contract(
            ticket_id="OMN-1111", summary="Test", is_seam_ticket=False
        )
        assert a == b

    def test_generate_contract_with_topics_populates_golden_path(self) -> None:
        """When interfaces_touched includes 'topics', golden_path should be populated."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test feature with Kafka topics",
            is_seam_ticket=True,
            interfaces_touched=["topics", "events"],
        )
        contract = yaml.safe_load(result)
        assert contract["golden_path"] is not None
        assert "input" in contract["golden_path"]
        assert "output" in contract["golden_path"]
        assert (
            contract["golden_path"]["input"]["topic"] == "onex.cmd.omn-9999.trigger.v1"
        )
        assert (
            contract["golden_path"]["output"]["topic"]
            == "onex.evt.omn-9999.completed.v1"
        )
        assert (
            contract["golden_path"]["input"]["fixture"]
            == "tests/fixtures/omn-9999_trigger.json"
        )
        assert contract["golden_path"]["output"]["schema_name"] == "ModelOmn9999Result"

    def test_generate_contract_without_topics_has_no_golden_path(self) -> None:
        """When interfaces_touched does not include topics/events, golden_path is absent."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Non-seam feature",
            is_seam_ticket=False,
        )
        contract = yaml.safe_load(result)
        assert "golden_path" not in contract

    def test_generate_contract_with_dod_items(self) -> None:
        """When dod_items are provided, dod_evidence should be populated."""
        dod_items = [
            "Unit tests pass for the new handler",
            "Kafka topic registered in topics.yaml",
            "Dashboard page renders real data",
        ]
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test feature",
            is_seam_ticket=True,
            interfaces_touched=["topics"],
            dod_items=dod_items,
        )
        contract = yaml.safe_load(result)
        assert len(contract["dod_evidence"]) == 3
        assert contract["dod_evidence"][0]["id"] == "dod-001"
        assert contract["dod_evidence"][0]["linear_dod_text"] == dod_items[0]
        assert len(contract["dod_evidence"][0]["checks"]) >= 1

    def test_dod_evidence_infers_test_check(self) -> None:
        """DoD item mentioning 'test' should infer test_passes check."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test",
            is_seam_ticket=False,
            dod_items=["Unit tests pass for handler"],
        )
        contract = yaml.safe_load(result)
        check = contract["dod_evidence"][0]["checks"][0]
        assert check["check_type"] == "test_passes"

    def test_dod_evidence_infers_topic_check(self) -> None:
        """DoD item mentioning 'topic' should infer grep check."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test",
            is_seam_ticket=False,
            dod_items=["Kafka topic registered"],
        )
        contract = yaml.safe_load(result)
        check = contract["dod_evidence"][0]["checks"][0]
        assert check["check_type"] == "grep"

    def test_dod_evidence_infers_dashboard_check(self) -> None:
        """DoD item mentioning 'dashboard' should infer endpoint check."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test",
            is_seam_ticket=False,
            dod_items=["Dashboard page renders data"],
        )
        contract = yaml.safe_load(result)
        check = contract["dod_evidence"][0]["checks"][0]
        assert check["check_type"] == "endpoint"

    def test_dod_evidence_default_check(self) -> None:
        """DoD item with no keywords should get a TODO command check."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test",
            is_seam_ticket=False,
            dod_items=["Something completely unrelated"],
        )
        contract = yaml.safe_load(result)
        check = contract["dod_evidence"][0]["checks"][0]
        assert check["check_type"] == "command"

    def test_published_events_included(self) -> None:
        """When published_events are provided, they appear in the contract."""
        result = generate_skeleton_contract(
            ticket_id="OMN-9999",
            summary="Test",
            is_seam_ticket=True,
            interfaces_touched=["events"],
            published_events=["onex.evt.test.completed.v1"],
        )
        contract = yaml.safe_load(result)
        assert contract["published_events"] == ["onex.evt.test.completed.v1"]
