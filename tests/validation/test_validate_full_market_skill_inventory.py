# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for full-market Onex skill inventory gate (OMN-12326)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))

from validate_full_market_skill_inventory import (  # noqa: E402
    FindingKind,
    SurfaceClass,
    build_combined_report,
    build_report,
    discover_skill_files,
    report_to_dict,
    scan_skill_surface,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "full_market_skill_inventory"
SKILLS_ROOT = FIXTURES_ROOT / "skills"
NODES_ROOT = FIXTURES_ROOT / "nodes"


@pytest.mark.unit
def test_discovers_top_level_and_nested_skill_surfaces() -> None:
    skill_names = [
        path.parent.relative_to(SKILLS_ROOT).as_posix()
        for path in discover_skill_files(SKILLS_ROOT)
    ]

    assert skill_names == [
        "dispatch_good",
        "pure_guidance",
        "retired_skill",
        "stubbed_dispatch",
        "system_status",
        "system_status/check_database_health",
    ]


@pytest.mark.unit
def test_build_report_classifies_all_surface_types() -> None:
    report = build_report(SKILLS_ROOT, NODES_ROOT)

    assert report.total_surfaces == 6
    assert report.class_counts[str(SurfaceClass.DISPATCH)] == 2
    assert report.class_counts[str(SurfaceClass.PURE_SKILL)] == 1
    assert report.class_counts[str(SurfaceClass.RETIRED)] == 1
    assert report.class_counts[str(SurfaceClass.STUB_SCAFFOLD)] == 1
    assert report.class_counts[str(SurfaceClass.SUB_SKILL)] == 1


@pytest.mark.unit
def test_dispatch_surface_reports_node_contract_and_bypass_findings() -> None:
    skill = scan_skill_surface(
        SKILLS_ROOT / "dispatch_good" / "SKILL.md",
        skills_root=SKILLS_ROOT,
        nodes_root=NODES_ROOT,
    )

    kinds = {finding.kind for finding in skill.findings}
    assert str(FindingKind.MISSING_CONTRACT) in kinds
    assert str(FindingKind.MISSING_NODE) in kinds
    assert str(FindingKind.DIRECT_HANDLER_IMPORT) in kinds
    assert str(FindingKind.DIRECT_HTTP_CLI_API_BYPASS) in kinds
    assert {node.name for node in skill.backing_nodes} == {
        "node_missing",
        "node_no_contract",
        "node_real",
    }


@pytest.mark.unit
def test_stub_surface_reports_not_implemented_contract_and_handler() -> None:
    skill = scan_skill_surface(
        SKILLS_ROOT / "stubbed_dispatch" / "SKILL.md",
        skills_root=SKILLS_ROOT,
        nodes_root=NODES_ROOT,
    )

    assert skill.class_ == str(SurfaceClass.STUB_SCAFFOLD)
    kinds = {finding.kind for finding in skill.findings}
    assert str(FindingKind.NODE_NOT_IMPLEMENTED) in kinds
    assert str(FindingKind.NOT_IMPLEMENTED_HANDLER) in kinds
    assert str(FindingKind.PLACEHOLDER_DISPATCH) in kinds


@pytest.mark.unit
def test_report_dict_uses_class_key_for_serialized_report() -> None:
    report = build_report(SKILLS_ROOT, NODES_ROOT)
    raw = report_to_dict(report)

    assert "class_" not in raw["skills"][0]
    assert "class" in raw["skills"][0]
    assert raw["skills"][0]["source_root"] == str(SKILLS_ROOT)
    yaml.safe_dump(raw)


@pytest.mark.unit
def test_build_combined_report_aggregates_multiple_skill_roots(tmp_path: Path) -> None:
    other_root = tmp_path / "other_skills"
    other_skill = other_root / "external_dispatch"
    other_skill.mkdir(parents=True)
    (other_skill / "SKILL.md").write_text(
        "# External Dispatch\n\nRun through node_real.\n",
        encoding="utf-8",
    )

    report = build_combined_report([SKILLS_ROOT, other_root], NODES_ROOT)
    external = next(
        skill for skill in report.skills if skill.name == "external_dispatch"
    )

    assert report.total_surfaces == 7
    assert report.class_counts[str(SurfaceClass.DISPATCH)] == 3
    assert external.source_root == str(other_root)
    assert report.skills_root == f"{SKILLS_ROOT};{other_root}"
