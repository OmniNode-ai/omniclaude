# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Regression tests for the canonical deploy-gate validator (OMN-9685 / DGM-Phase6).

Tests live here (omniclaude) because the validator is the canonical single source
of truth since DGM-Phase6 (OMN-9734). Covers:
- Enum/model/protocol-only diffs do NOT trigger the gate
- Runtime diffs (nodes, handlers, runtime kernel) DO trigger the gate
- skip-token in PR body is NOT a bypass (gate still fires)
- Real dod_evidence with deploy check_value -> gate passes
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# The validator lives in the composite action directory.
ACTION_DIR = Path(__file__).parent.parent.parent / ".github" / "actions" / "deploy-gate"
sys.path.insert(0, str(ACTION_DIR))

import validate_pr_deploy_required as validator  # noqa: E402
from validate_pr_deploy_required import (  # noqa: E402
    find_runtime_paths,
    resolve_occ_evidence_source,
    validate_pr_deploy_gate,
)

# ---------------------------------------------------------------------------
# find_runtime_paths — unit tests for pattern matching
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindRuntimePaths:
    def test_enum_only_diff_not_matched(self) -> None:
        files = [
            "src/omnibase_core/enums/enum_node_kind.py",
            "src/omnibase_core/enums/enum_hook_bit.py",
        ]
        assert find_runtime_paths(files) == []

    def test_model_only_diff_not_matched(self) -> None:
        files = [
            "src/omnibase_core/models/model_event_envelope.py",
            "src/omnibase_core/models/core/model_deployment_topology.py",
        ]
        assert find_runtime_paths(files) == []

    def test_protocol_only_diff_not_matched(self) -> None:
        files = [
            "src/omnibase_core/protocols/protocol_event_bus.py",
            "src/omnibase_spi/protocols/protocol_logger.py",
        ]
        assert find_runtime_paths(files) == []

    def test_dto_only_diff_not_matched(self) -> None:
        files = ["src/omnibase_compat/dto/dto_event_wire.py"]
        assert find_runtime_paths(files) == []

    def test_tests_not_matched(self) -> None:
        files = [
            "tests/unit/models/test_model_foo.py",
            "tests/integration/test_service_bar.py",
        ]
        assert find_runtime_paths(files) == []

    def test_docs_not_matched(self) -> None:
        files = [
            "docs/architecture/ONEX_FOUR_NODE_ARCHITECTURE.md",
            "README.md",
        ]
        assert find_runtime_paths(files) == []

    def test_node_handler_matched(self) -> None:
        files = ["src/omnibase_core/nodes/node_merge_sweep/handlers/handler_merge.py"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1
        assert hits[0] == files[0]

    def test_runtime_kernel_matched(self) -> None:
        files = ["src/omnibase_infra/runtime/service_kernel.py"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1

    def test_docker_file_matched(self) -> None:
        assert find_runtime_paths(["docker/Dockerfile.runtime"]) != []

    def test_contract_yaml_matched(self) -> None:
        files = ["src/omnibase_core/nodes/node_x/contract.yaml"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1

    def test_cli_file_matched(self) -> None:
        files = ["src/omnibase_core/cli/cli_commands.py"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1

    def test_services_file_matched(self) -> None:
        files = ["src/omnibase_core/services/service_handler_registry.py"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1

    def test_mixed_diff_returns_only_runtime_hits(self) -> None:
        files = [
            "src/omnibase_core/enums/enum_node_kind.py",
            "src/omnibase_core/nodes/node_x/handlers/handler_x.py",
        ]
        hits = find_runtime_paths(files)
        assert len(hits) == 1
        assert "handler" in hits[0]

    def test_top_level_node_module_matched(self) -> None:
        files = ["src/omnibase_core/nodes/node_contract_resolve_compute.py"]
        hits = find_runtime_paths(files)
        assert len(hits) == 1


# ---------------------------------------------------------------------------
# validate_pr_deploy_gate — integration tests using tmp contracts dir
# ---------------------------------------------------------------------------


def _write_contract(contracts_dir: Path, ticket_id: str, has_deploy: bool) -> None:
    data: dict = {"dod_evidence": []}
    if has_deploy:
        data["dod_evidence"] = [
            {"checks": [{"check_value": "deploy omnibase_core to .201"}]}
        ]
    (contracts_dir / f"{ticket_id}.yaml").write_text(yaml.dump(data))


@pytest.mark.unit
class TestValidatePrDeployGate:
    def test_enum_only_diff_gate_skipped(self, tmp_path: Path) -> None:
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/enums/enum_node_kind.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert result.passed
        assert result.skipped

    def test_model_only_diff_gate_skipped(self, tmp_path: Path) -> None:
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/models/model_event_envelope.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert result.passed
        assert result.skipped

    def test_protocol_only_diff_gate_skipped(self, tmp_path: Path) -> None:
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/protocols/protocol_event_bus.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert result.passed
        assert result.skipped

    def test_runtime_diff_without_dod_fails(self, tmp_path: Path) -> None:
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "DEPLOY GATE FAILED" in result.message

    def test_skip_token_in_body_does_not_bypass(self, tmp_path: Path) -> None:
        """skip-deploy-gate token must NOT be a bypass (OMN-9685)."""
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="[skip-deploy-gate: emergency hotfix] Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "DEPLOY GATE FAILED" in result.message

    def test_real_deploy_evidence_passes(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "OMN-9000", has_deploy=True)
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert result.passed
        assert not result.skipped
        assert "DEPLOY GATE PASSED" in result.message

    def test_ticket_without_deploy_evidence_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "OMN-9000", has_deploy=False)
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "DEPLOY GATE FAILED" in result.message
        assert "OMN-9000" in result.message

    def test_error_message_does_not_suggest_skip_token(self, tmp_path: Path) -> None:
        """Error message must not teach the skip-token bypass (OMN-9685)."""
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="Closes OMN-9000",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "skip-deploy-gate" not in result.message

    def test_no_ticket_cited_fails(self, tmp_path: Path) -> None:
        result = validate_pr_deploy_gate(
            changed_files=["src/omnibase_core/nodes/node_x/handlers/handler_x.py"],
            pr_body="Fix the thing without a ticket reference",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "cites no OMN-XXXX ticket" in result.message

    def test_runtime_diff_with_open_occ_evidence_source_passes(
        self, tmp_path: Path
    ) -> None:
        _write_contract(tmp_path, "OMN-12889", has_deploy=True)
        result = validate_pr_deploy_gate(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body=(
                "Ticket: OMN-12889\n"
                "Evidence-Source: OCC#2408\n"
                "Evidence-Ticket: OMN-12889\n"
            ),
            contracts_dir=tmp_path,
        )
        assert result.passed
        assert result.tickets_checked == ["OMN-12889"]

    def test_evidence_source_requires_evidence_ticket(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "OMN-12889", has_deploy=True)
        result = validate_pr_deploy_gate(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body="Ticket: OMN-12889\nEvidence-Source: OCC#2408\n",
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert "missing Evidence-Ticket" in result.message

    def test_missing_contract_at_pinned_occ_source_fails(self, tmp_path: Path) -> None:
        _write_contract(tmp_path, "OMN-1111", has_deploy=True)
        result = validate_pr_deploy_gate(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body=(
                "Ticket: OMN-1111\n"
                "Evidence-Source: OCC#2408\n"
                "Evidence-Ticket: OMN-12889\n"
            ),
            contracts_dir=tmp_path,
        )
        assert not result.passed
        assert result.tickets_checked == ["OMN-12889"]
        assert "OMN-12889" in result.message


@pytest.mark.unit
class TestResolveOccEvidenceSource:
    def test_no_runtime_paths_skip_before_resolving_bad_source(self) -> None:
        result = resolve_occ_evidence_source(
            changed_files=["docs/architecture.md"],
            pr_body="Evidence-Source: not-an-occ-source",
        )
        assert result.passed
        assert result.skipped
        assert not result.deploy_gate_required
        assert result.occ_ref == "dev"

    def test_runtime_paths_without_evidence_source_use_canonical_ref(self) -> None:
        result = resolve_occ_evidence_source(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body="Ticket: OMN-12889",
        )
        assert result.passed
        assert result.deploy_gate_required
        assert result.occ_ref == "dev"
        assert result.source_kind == "canonical"

    def test_open_occ_pr_source_resolves_to_head_sha(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        expected_sha = "8684a96935323e1b2990180ef053dd2da1bc03b0"

        def fake_run_gh_json(args: list[str]) -> dict[str, object]:
            assert args[:4] == [
                "pr",
                "view",
                "2408",
                "--repo",
            ]
            return {
                "state": "OPEN",
                "headRefOid": expected_sha,
                "mergeCommit": None,
            }

        monkeypatch.setattr(validator, "_run_gh_json", fake_run_gh_json)
        result = resolve_occ_evidence_source(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body=(
                "Ticket: OMN-12889\n"
                "Evidence-Source: OCC#2408\n"
                "Evidence-Ticket: OMN-12889\n"
            ),
        )
        assert result.passed
        assert result.occ_ref == expected_sha
        assert result.source_kind == "open-pr"
        assert result.evidence_ticket == "OMN-12889"

    def test_evidence_source_without_evidence_ticket_fails(self) -> None:
        result = resolve_occ_evidence_source(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body="Ticket: OMN-12889\nEvidence-Source: OCC#2408\n",
        )
        assert not result.passed
        assert "missing Evidence-Ticket" in result.message

    def test_invalid_evidence_source_fails_hard(self) -> None:
        result = resolve_occ_evidence_source(
            changed_files=["src/omnimarket/services/delegation_quality.py"],
            pr_body=(
                "Ticket: OMN-12889\n"
                "Evidence-Source: onex_change_control/main\n"
                "Evidence-Ticket: OMN-12889\n"
            ),
        )
        assert not result.passed
        assert "not valid" in result.message
