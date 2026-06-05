# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for validate_golden_chain_integrity.py [OMN-7389]."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestGoldenChainIntegrityScript:
    """Tests that the validation script runs and passes."""

    def test_script_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/validation/validate_golden_chain_integrity.py"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"Script failed:\n{result.stdout}\n{result.stderr}"
        )
        assert "PASS" in result.stdout


class TestGoldenChainIntegrityValidation:
    """Tests for the validate() function directly."""

    def test_validate_returns_no_errors(self) -> None:
        from scripts.validation.validate_golden_chain_integrity import validate

        errors = validate()
        assert errors == [], f"Unexpected errors: {errors}"

    def test_expected_chains_matches_registry(self) -> None:
        from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
            GOLDEN_CHAIN_METADATA,
        )

        assert {c.name for c in GOLDEN_CHAIN_METADATA} == {
            "registration",
            "pattern_learning",
            "delegation",
            "routing",
            "evaluation",
            "sea_acceptance",
            "d3_local_routing",
            "d1_d2_scaffold",
            "d4_blank_content",
            "d9_wheel_module",
            "f1_publish_loop",
            "delegation_inference_round_trip",
            "delegation_projection_materialization",
        }

    def test_validate_accepts_matching_canonical_registry(self, tmp_path: Path) -> None:
        from scripts.validation.validate_golden_chain_integrity import validate

        canonical = _write_canonical_registry_from_metadata(tmp_path)

        errors = validate(canonical)

        assert errors == []

    def test_validate_rejects_canonical_registry_drift(self, tmp_path: Path) -> None:
        from scripts.validation.validate_golden_chain_integrity import validate

        canonical = _write_canonical_registry_from_metadata(
            tmp_path,
            replace="tail_table: delegation_events",
            with_text="tail_table: drifted_events",
        )

        errors = validate(canonical)

        assert any("Metadata mismatch" in error for error in errors)


def _write_canonical_registry_from_metadata(
    directory: Path,
    *,
    replace: str | None = None,
    with_text: str | None = None,
) -> Path:
    from omniclaude.nodes.node_golden_chain_payload_compute.chain_registry import (
        GOLDEN_CHAIN_METADATA,
    )

    path = directory / "golden_chains.yaml"
    lines = ["chains:"]
    for chain in GOLDEN_CHAIN_METADATA:
        data = chain.model_dump(mode="json")
        lines.extend(
            [
                f"  - name: {data['name']}",
                f"    head_topic: {data['head_topic']}",
                f"    tail_table: {data['tail_table']}",
            ]
        )
        expected_fields = data.get("expected_fields") or []
        if expected_fields:
            lines.append("    expected_fields:")
            lines.extend(f"      - {field}" for field in expected_fields)
        if data.get("proof_classification") != "diagnostic":
            lines.append(f"    proof_classification: {data['proof_classification']}")
        if data.get("replay_status") != "replay-not-applicable":
            lines.append(f"    replay_status: {data['replay_status']}")
        stages = data.get("stages") or []
        if stages:
            lines.append("    stages:")
            for stage in stages:
                lines.append(f"      - name: {stage['name']}")
                if "handler" in stage:
                    lines.append(f"        handler: {stage['handler']}")
                if "topic" in stage:
                    lines.append(f"        topic: {stage['topic']}")
                if "table" in stage:
                    lines.append(f"        table: {stage['table']}")
    text = "\n".join(lines) + "\n"
    if replace is not None and with_text is not None:
        text = text.replace(replace, with_text, 1)
    path.write_text(text, encoding="utf-8")
    return path
