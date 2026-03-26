# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Integration tests for the auto-ticket-from-findings skill.

Tests verify skill spec completeness via static analysis.
All tests are @pytest.mark.unit (no live Linear API calls or network access).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SKILLS_ROOT = _REPO_ROOT / "plugins" / "onex" / "skills"
_SKILL_DIR = _SKILLS_ROOT / "auto_ticket_from_findings"
_SKILL_MD = _SKILL_DIR / "SKILL.md"


def _read(path: Path) -> str:
    if not path.exists():
        pytest.skip(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


@pytest.mark.unit
class TestSkillMd:
    """Verify SKILL.md spec completeness for auto_ticket_from_findings."""

    def test_skill_md_exists(self) -> None:
        assert _SKILL_MD.exists(), "SKILL.md must exist for auto_ticket_from_findings"

    def test_dry_run_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--dry-run" in content

    def test_source_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--source" in content

    def test_findings_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--findings" in content

    def test_parent_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--parent" in content

    def test_severity_threshold_arg_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "--severity-threshold" in content

    def test_dedup_strategy_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "dedup" in content.lower() or "Dedup" in content

    def test_source_types_documented(self) -> None:
        content = _read(_SKILL_MD)
        for source in ("contract-sweep", "dod-sweep", "hostile-review"):
            assert source in content, f"SKILL.md missing source type: {source}"

    def test_severity_buckets_documented(self) -> None:
        content = _read(_SKILL_MD)
        for bucket in ("critical", "major", "minor", "nit"):
            assert bucket in content.lower(), (
                f"SKILL.md missing severity bucket: {bucket}"
            )

    def test_priority_mapping_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "Priority" in content
        assert "Urgent" in content or "1" in content

    def test_findings_input_format_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "findings" in content.lower()
        assert "description" in content
        assert "file" in content

    def test_ticket_title_format_documented(self) -> None:
        content = _read(_SKILL_MD)
        assert "Title" in content or "title" in content

    def test_adapter_formats_documented(self) -> None:
        """Skill must document adapters for hostile-review and contract-sweep formats."""
        content = _read(_SKILL_MD)
        assert "Adapter" in content or "adapter" in content
        assert "Hostile Review" in content or "hostile-review" in content


@pytest.mark.unit
class TestNodeContract:
    """Verify the orchestrator node contract is valid."""

    _CONTRACT = (
        _REPO_ROOT
        / "src"
        / "omniclaude"
        / "nodes"
        / "node_skill_auto_ticket_from_findings_orchestrator"
        / "contract.yaml"
    )

    def test_contract_exists(self) -> None:
        assert self._CONTRACT.exists(), "contract.yaml must exist"

    def test_contract_parses(self) -> None:
        import yaml

        with open(self._CONTRACT) as f:
            data = yaml.safe_load(f)
        assert data is not None
        assert data["name"] == "node_skill_auto_ticket_from_findings_orchestrator"

    def test_contract_has_event_bus_config(self) -> None:
        import yaml

        with open(self._CONTRACT) as f:
            data = yaml.safe_load(f)
        event_bus = data.get("event_bus", {})
        assert "subscribe" in event_bus
        assert "publish" in event_bus
        assert "topic" in event_bus["subscribe"]
        assert "success_topic" in event_bus["publish"]
        assert "failure_topic" in event_bus["publish"]

    def test_contract_node_type(self) -> None:
        import yaml

        with open(self._CONTRACT) as f:
            data = yaml.safe_load(f)
        assert data["node_type"] == "ORCHESTRATOR_GENERIC"

    def test_contract_io_models(self) -> None:
        import yaml

        with open(self._CONTRACT) as f:
            data = yaml.safe_load(f)
        assert data["input_model"]["name"] == "ModelSkillRequest"
        assert data["output_model"]["name"] == "ModelSkillResult"


@pytest.mark.unit
class TestNodeClass:
    """Verify the node class is importable and correctly structured."""

    def test_node_class_importable(self) -> None:
        from omniclaude.nodes.node_skill_auto_ticket_from_findings_orchestrator import (
            NodeSkillAutoTicketFromFindingsOrchestrator,
        )

        assert NodeSkillAutoTicketFromFindingsOrchestrator is not None

    def test_node_inherits_orchestrator(self) -> None:
        from omnibase_core.nodes.node_orchestrator import NodeOrchestrator

        from omniclaude.nodes.node_skill_auto_ticket_from_findings_orchestrator import (
            NodeSkillAutoTicketFromFindingsOrchestrator,
        )

        assert issubclass(NodeSkillAutoTicketFromFindingsOrchestrator, NodeOrchestrator)

    def test_exports(self) -> None:
        import omniclaude.nodes.node_skill_auto_ticket_from_findings_orchestrator as mod

        assert "NodeSkillAutoTicketFromFindingsOrchestrator" in mod.__all__
