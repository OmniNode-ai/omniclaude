# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A cut-over caller's deploy gate reads the caller's own contracts (OMN-20074).

The reusable deploy gate takes ``contract-source``. ``occ`` (the default) keeps
today's behaviour for callers not yet cut over: the cited ticket's contract is
read from onex_change_control. ``caller`` reads ``contracts/OMN-<n>.yaml`` from
the caller's pull request head, the file repo-evidence / dod-verify reads, and
checks out no change control tree. The validator and its strictness are the
same in both modes; only the directory it reads, and the wording that names
that directory, change.
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
OCC_ONLY = "inputs.contract-source == 'occ'"
CALLER_ONLY = "inputs.contract-source == 'caller'"
CONTRACTS_DIR_EXPR = "${{ inputs.contract-source == 'caller' && '.pr-head/contracts' || '_occ/contracts' }}"
MODE_DIRS = {"caller": ".pr-head/contracts", "occ": "_occ/contracts"}
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


def test_contract_source_input_defaults_to_occ() -> None:
    contract_source = _inputs()["contract-source"]
    assert contract_source["type"] == "string"
    assert contract_source["required"] is False
    assert contract_source["default"] == "occ"


def test_unknown_contract_source_fails_closed() -> None:
    step = _step("Resolve the deploy-gate contract source")
    assert step["env"]["CONTRACT_SOURCE"] == "${{ inputs.contract-source }}"
    run = step["run"]
    assert "occ|caller)" in run
    assert "exit 1" in run
    steps = _job()["steps"]
    gate = _step("Run deploy gate (canonical composite action)")
    assert steps.index(step) < steps.index(gate)


def test_occ_steps_run_only_for_the_occ_source() -> None:
    resolve = _step("Resolve deploy-gate OCC evidence source")
    assert resolve["if"] == f"github.event_name != 'merge_group' && {OCC_ONLY}"
    checkout = _step(
        "Checkout onex_change_control contracts (canonical contract source)"
    )
    assert checkout["if"] == (
        f"github.event_name != 'merge_group' && {OCC_ONLY} && "
        "steps.resolve_occ_evidence.outputs.deploy_gate_required == 'true'"
    )


def test_caller_source_checks_out_the_caller_pr_head_contracts() -> None:
    step = _step("Checkout the caller's pull request head contracts")
    assert step["if"] == f"github.event_name != 'merge_group' && {CALLER_ONLY}"
    assert str(step["uses"]).startswith("actions/checkout@")
    options = step["with"]
    assert "repository" not in options, "the caller's own repository, never OCC"
    assert options["ref"] == PR_HEAD_SHA
    assert options["path"] == ".pr-head"
    assert options["persist-credentials"] is False
    assert str(options["sparse-checkout"]).split() == ["/contracts/"]
    assert options["sparse-checkout-cone-mode"] is False


def test_gate_reads_the_directory_of_its_source() -> None:
    gate = _step("Run deploy gate (canonical composite action)")
    assert gate["with"]["contracts-dir"] == CONTRACTS_DIR_EXPR
    assert gate["with"]["contract-source"] == "${{ inputs.contract-source }}"


def test_composite_action_threads_the_source_to_the_validator() -> None:
    action = yaml.safe_load(ACTION_PATH.read_text(encoding="utf-8"))
    assert action["inputs"]["contract-source"]["default"] == "occ"
    run_step = next(
        s for s in action["runs"]["steps"] if s.get("name") == "Run deploy gate"
    )
    assert run_step["env"]["CONTRACT_SOURCE"] == "${{ inputs.contract-source }}"
    assert '--contract-source "$CONTRACT_SOURCE"' in run_step["run"]


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


def _gate(workspace: Path, mode: str, ticket: str) -> tuple[bool, str]:
    result = validate_pr_deploy_gate(
        changed_files=[RUNTIME_PATH],
        pr_body=f"Ticket: {ticket}",
        contracts_dir=workspace / MODE_DIRS[mode],
        repository="OmniNode-ai/omnibase_infra",
        contract_source=mode,
    )
    return result.passed, result.message


def test_caller_contract_with_deploy_evidence_passes(tmp_path: Path) -> None:
    _contract(tmp_path / ".pr-head" / "contracts", "OMN-99001", DEPLOY_CHECK)
    passed, message = _gate(tmp_path, "caller", "OMN-99001")
    assert passed, message


def test_caller_contract_without_deploy_evidence_fails(tmp_path: Path) -> None:
    _contract(tmp_path / ".pr-head" / "contracts", "OMN-99002", TEST_CHECK)
    passed, message = _gate(tmp_path, "caller", "OMN-99002")
    assert not passed
    assert "onex_change_control/contracts/" not in message, message
    assert "onex_change_control repo" not in message, message


def test_occ_companion_evidence_does_not_count_for_a_caller_source(
    tmp_path: Path,
) -> None:
    _contract(tmp_path / ".pr-head" / "contracts", "OMN-99003", TEST_CHECK)
    _contract(tmp_path / "_occ" / "contracts", "OMN-99003", DEPLOY_CHECK)
    passed, _ = _gate(tmp_path, "caller", "OMN-99003")
    assert not passed
    # Control: the same tree under the occ source still passes, unchanged.
    passed_occ, message_occ = _gate(tmp_path, "occ", "OMN-99003")
    assert passed_occ, message_occ


def test_caller_source_names_the_caller_contract_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".pr-head" / "contracts").mkdir(parents=True)
    passed, message = _gate(tmp_path, "caller", "OMN-99004")
    assert not passed
    assert "onex_change_control/contracts/" not in message, message
    assert "onex_change_control repo" not in message, message
    assert "contracts/OMN-99004.yaml" in message, message


def test_occ_source_wording_is_unchanged(tmp_path: Path) -> None:
    (tmp_path / "_occ" / "contracts").mkdir(parents=True)
    passed, message = _gate(tmp_path, "occ", "OMN-99005")
    assert not passed
    assert "Tickets with no contract file in onex_change_control/contracts/" in message
