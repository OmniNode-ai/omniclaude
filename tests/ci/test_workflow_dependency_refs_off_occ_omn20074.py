# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""omniclaude's workflows and dependencies name no change control repository (OMN-20074).

A live reference is a non-comment line in a workflow, action or manifest that
names the repository or its package. This file pins the ones the workflow and
dependency pass removed:

* ci.yml (boundary parity peers, the pre-commit sibling clone, agent config
  validation), contract-validation.yml, the deploy gate workflows, the deploy
  gate action and its validator carry no such line;
* the deploy gate reads the caller's own contracts only;
* nothing in the tree imports the ``onex_change_control`` package, which is the
  precondition for dropping it from pyproject.toml and uv.lock.

The two OCC companion reusables other repositories still call are not covered
here: they stay hosted until their last caller is gone.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OCC_RE = re.compile(r"onex[_-]change[_-]control", re.IGNORECASE)

LIVE_FILES = (
    ".github/workflows/ci.yml",
    ".github/workflows/contract-validation.yml",
    ".github/workflows/deploy-gate.yml",
    ".github/workflows/deploy-gate-reusable.yml",
    ".github/actions/deploy-gate/action.yml",
    ".github/actions/deploy-gate/deploy_gate_legacy_grandfather.yaml",
    ".github/actions/deploy-gate/validate_pr_deploy_required.py",
    ".github/actions/required-check-skip-guard/_workflow_model.py",
)


def _live_lines(path: Path) -> list[str]:
    return [
        f"{path.name}:{n}: {line.strip()}"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if OCC_RE.search(line) and not line.lstrip().startswith("#")
    ]


@pytest.mark.parametrize("relative", LIVE_FILES)
def test_file_names_no_change_control_repository(relative: str) -> None:
    assert _live_lines(REPO_ROOT / relative) == []


def test_positive_control_the_matcher_sees_a_reference() -> None:
    assert OCC_RE.search("repository: OmniNode-ai/onex_change_control")
    assert OCC_RE.search('name = "onex-change-control"')
    assert not OCC_RE.search("omnibase_core")


def test_the_deleted_checkout_script_stays_gone() -> None:
    assert not (
        REPO_ROOT / "scripts" / "deploy-gate" / "checkout-occ-contracts.sh"
    ).exists()


def test_nothing_imports_the_change_control_package() -> None:
    import_re = re.compile(r"^\s*(?:from|import)\s+onex_change_control\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for root in ("src", "plugins", "scripts", "tests")
        for path in (REPO_ROOT / root).rglob("*.py")
        if import_re.search(path.read_text(encoding="utf-8", errors="ignore"))
        and path != Path(__file__).resolve()
    ]
    assert offenders == []


def test_deploy_gate_workflow_reads_the_repository_contracts() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/deploy-gate.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["deploy-gate"]["steps"]
    names = [str(step.get("name", "")) for step in steps]
    assert not [name for name in names if "OCC" in name]
    gate = next(step for step in steps if step.get("name") == "Run deploy gate")
    assert gate["with"]["contracts-dir"] == "contracts"


def test_agent_config_validation_runs_the_omnibase_core_model() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["validate-agent-configs"]["steps"]
    run = next(s for s in steps if s.get("name") == "Validate agent configs")["run"]
    assert "omnibase_core.models.agents.model_agent_yaml_config" in run
    assert "validate-agent-yaml" not in run
