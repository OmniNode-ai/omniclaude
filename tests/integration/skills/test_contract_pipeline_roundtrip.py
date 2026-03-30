# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration test: contract generation round-trip.

Verifies that the generate -> enrich -> validate pipeline produces
contracts that integration-sweep can consume.
"""

import sys
import tempfile
from pathlib import Path

import pytest
import yaml

# Resolve path relative to this file's location (works from any cwd)
_lib_path = str(
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "onex"
    / "skills"
    / "_lib"
    / "contract_generator"
)
if _lib_path not in sys.path:
    sys.path.insert(0, _lib_path)

from enrich_contract import enrich_contract_with_evidence
from generate_contract import generate_skeleton_contract


@pytest.mark.unit
class TestContractPipelineRoundtrip:
    """End-to-end contract generation and validation."""

    def test_generate_enrich_validate_roundtrip(self) -> None:
        """Generate skeleton, enrich with evidence, validate against schema."""
        # Step 1: Generate skeleton
        skeleton = generate_skeleton_contract(
            ticket_id="OMN-TEST-001",
            summary="Integration test ticket",
            is_seam_ticket=False,
        )

        # Step 2: Enrich with evidence
        enriched = enrich_contract_with_evidence(
            contract_yaml=skeleton,
            test_files=["tests/unit/test_example.py", "tests/unit/test_other.py"],
            test_command="uv run pytest tests/unit/ -v",
            include_lint=True,
            repo="test-repo",
        )

        # Step 3: Validate contract base fields against onex_change_control schema
        from onex_change_control.models.model_ticket_contract import (
            ModelTicketContract,
        )

        parsed = yaml.safe_load(enriched)
        contract = ModelTicketContract.model_validate(parsed)

        # Step 4: Verify contract fields
        assert contract.ticket_id == "OMN-TEST-001"
        assert contract.schema_version == "1.0.0"
        assert contract.is_seam_ticket is False

        # Step 5: Verify dod_evidence in the YAML dict
        # (dod_evidence is not yet a first-class field on ModelTicketContract v0.1.0;
        #  it exists as extra YAML data that integration-sweep reads from the dict)
        dod_evidence = parsed["dod_evidence"]
        assert len(dod_evidence) == 4  # 2x test_exists + test_pass + lint
        assert all(e["status"] == "pending" for e in dod_evidence)
        check_types = [
            e["checks"][0]["check_type"] for e in dod_evidence if e["checks"]
        ]
        assert "test_exists" in check_types
        assert "command" in check_types

    def test_write_and_read_from_disk(self) -> None:
        """Contract can be written to YAML file and read back identically."""
        yaml_str = generate_skeleton_contract(
            ticket_id="OMN-TEST-002",
            summary="Disk round-trip test",
            is_seam_ticket=True,
            interfaces_touched=["events"],
        )

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_str)
            path = Path(f.name)

        try:
            from onex_change_control.models.model_ticket_contract import (
                ModelTicketContract,
            )

            loaded = yaml.safe_load(path.read_text())
            contract = ModelTicketContract.model_validate(loaded)
            assert contract.ticket_id == "OMN-TEST-002"
            assert contract.is_seam_ticket is True
            assert "events" in [s.value for s in contract.interfaces_touched]
        finally:
            path.unlink()
