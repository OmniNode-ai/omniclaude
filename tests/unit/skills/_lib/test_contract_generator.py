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
