# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The deploy gate reads the caller's own contracts and no other source (OMN-20074).

The reusable deploy gate takes ``contract-source`` and accepts only ``caller``
(the default): ``contracts/OMN-<n>.yaml`` from the caller's pull request head,
the file repo-evidence / dod-verify reads. No other repository's tree is
checked out. The validator and its strictness are unchanged.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "deploy-gate-reusable.yml"
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "deploy-gate"
ACTION_PATH = ACTION_DIR / "action.yml"
_SPEC = importlib.util.spec_from_file_location(
    "validate_pr_deploy_required_omn20074",
    ACTION_DIR / "validate_pr_deploy_required.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_VALIDATOR = importlib.util.module_from_spec(_SPEC)
# dataclasses resolve their module through sys.modules.
sys.modules[_SPEC.name] = _VALIDATOR
_SPEC.loader.exec_module(_VALIDATOR)
validate_pr_deploy_gate = _VALIDATOR.validate_pr_deploy_gate

PR_HEAD_SHA = "${{ github.event.pull_request.head.sha }}"
CONTRACTS_DIR = ".pr-head/contracts"
RUNTIME_PATH = "src/omnibase_infra/nodes/node_example/handlers/handler_example.py"
DEPLOY_CHECK = (
    "gh api repos/OmniNode-ai/omnibase_infra/contents/"
    f"{RUNTIME_PATH}?ref=0123456789abcdef0123456789abcdef01234567 --jq .sha"
)
TEST_CHECK = "uv run pytest tests/unit/nodes/node_example -q"


def _job() -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(workflow, dict)
    return cast("dict[str, Any]", workflow["jobs"]["deploy-gate"])


def _inputs() -> dict[str, Any]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    # PyYAML reads the bare `on:` key as True.
    trigger = workflow.get("on", workflow.get(True))
    return cast("dict[str, Any]", trigger["workflow_call"]["inputs"])


def _step(name: str) -> dict[str, Any]:
    steps = _job()["steps"]
    matches = [s for s in steps if isinstance(s, dict) and s.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}"
    return cast("dict[str, Any]", matches[0])


def test_contract_source_input_defaults_to_caller() -> None:
    contract_source = _inputs()["contract-source"]
    assert contract_source["type"] == "string"
    assert contract_source["required"] is False
    assert contract_source["default"] == "caller"


def test_any_contract_source_but_caller_fails_closed() -> None:
    step = _step("Resolve the deploy-gate contract source")
    assert step["env"]["CONTRACT_SOURCE"] == "${{ inputs.contract-source }}"
    run = step["run"]
    assert '"$CONTRACT_SOURCE" != "caller"' in run
    assert "exit 1" in run
    steps = _job()["steps"]
    gate = _step("Run deploy gate (canonical composite action)")
    assert steps.index(step) < steps.index(gate)


def test_no_change_control_step_remains() -> None:
    names = [str(s.get("name", "")) for s in _job()["steps"]]
    assert not [n for n in names if "OCC" in n or "onex_change_control" in n], names
    assert not (
        REPO_ROOT / "scripts" / "deploy-gate" / "checkout-occ-contracts.sh"
    ).exists()


def test_caller_source_checks_out_the_caller_pr_head_contracts() -> None:
    step = _step("Checkout the caller's pull request head contracts")
    assert step["if"] == "github.event_name != 'merge_group'"
    assert str(step["uses"]).startswith("actions/checkout@")
    options = step["with"]
    assert "repository" not in options, "the caller's own repository only"
    assert options["ref"] == PR_HEAD_SHA
    assert options["path"] == ".pr-head"
    assert options["persist-credentials"] is False
    assert str(options["sparse-checkout"]).split() == ["/contracts/"]
    assert options["sparse-checkout-cone-mode"] is False


def test_gate_reads_the_caller_contracts_directory() -> None:
    gate = _step("Run deploy gate (canonical composite action)")
    assert gate["with"]["contracts-dir"] == CONTRACTS_DIR
    assert "contract-source" not in gate["with"]


def test_composite_action_defaults_to_the_caller_contracts() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    assert action["inputs"]["contracts-dir"]["default"] == "contracts"
    assert "contract-source" not in action["inputs"]
    run_step = next(
        s for s in action["runs"]["steps"] if s.get("name") == "Run deploy gate"
    )
    assert "CONTRACT_SOURCE" not in run_step["env"]
    assert "--contract-source" not in run_step["run"]


def test_repository_deploy_gate_workflow_reads_its_own_contracts() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "deploy-gate.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["deploy-gate"]["steps"]
    gate = next(s for s in steps if s.get("name") == "Run deploy gate")
    assert gate["with"]["contracts-dir"] == "contracts"
    assert "onex_change_control" not in yaml.safe_dump(workflow)


def _contract(path: Path, ticket: str, check_value: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{ticket}.yaml").write_text(
        yaml.safe_dump(
            {
                "ticket_id": ticket,
                "dod_evidence": [
                    {"id": "dod-1", "checks": [{"check_value": check_value}]}
                ],
            }
        ),
        encoding="utf-8",
    )


def _gate(workspace: Path, ticket: str) -> tuple[bool, str]:
    result = validate_pr_deploy_gate(
        changed_files=[RUNTIME_PATH],
        pr_body=f"Ticket: {ticket}",
        contracts_dir=workspace / CONTRACTS_DIR,
        repository="OmniNode-ai/omnibase_infra",
    )
    return result.passed, result.message


def test_caller_contract_with_deploy_evidence_passes(tmp_path: Path) -> None:
    _contract(tmp_path / CONTRACTS_DIR, "OMN-99001", DEPLOY_CHECK)
    passed, message = _gate(tmp_path, "OMN-99001")
    assert passed, message


def test_caller_contract_without_deploy_evidence_fails(tmp_path: Path) -> None:
    _contract(tmp_path / CONTRACTS_DIR, "OMN-99002", TEST_CHECK)
    passed, message = _gate(tmp_path, "OMN-99002")
    assert not passed
    assert "onex_change_control" not in message, message


def test_a_contract_outside_the_caller_directory_does_not_count(
    tmp_path: Path,
) -> None:
    _contract(tmp_path / CONTRACTS_DIR, "OMN-99003", TEST_CHECK)
    _contract(tmp_path / "_occ" / "contracts", "OMN-99003", DEPLOY_CHECK)
    passed, _ = _gate(tmp_path, "OMN-99003")
    assert not passed


def test_missing_caller_contract_names_the_caller_path(tmp_path: Path) -> None:
    (tmp_path / CONTRACTS_DIR).mkdir(parents=True)
    passed, message = _gate(tmp_path, "OMN-99004")
    assert not passed
    assert "onex_change_control" not in message, message
    assert "contracts/OMN-99004.yaml" in message, message
