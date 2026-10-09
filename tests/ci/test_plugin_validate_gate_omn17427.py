# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: ``claude plugin validate`` is a merge gate, not an option.

``claude plugin validate`` applies the harness's own loader schema to the plugin
manifests, hooks.json and the marketplace manifests. A hook handler it cannot
load -- for example a misspelt ``onFailure`` value on a guard -- is a hard error
there and invisible to every repo-local check. Detection that is not wired as a
gate gets ignored (rule 5), so these tests pin the wiring: the CI job exists,
cannot be skipped, installs the exact Claude Code release that defines
``onFailure: "block"``, and validates every manifest; the umbrella waits for it
and accepts nothing but success; and a change to a manifest runs it before the
commit lands.

``claude plugin test`` and ``claude plugin eval`` are not wired, and a test here
records why so the decision is not silently reversed: neither applies to a
plugin whose hooks.json names no hooks module and which ships no ``evals/``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

REPO_ROOT = Path(__file__).resolve().parents[2]

JOB_ID = "plugin-validate"
JOB_NAME = "Plugin Validate (OMN-17427)"
HOOK_ID = "claude-plugin-validate"
# The release that defines the hook handler setting onFailure: "block".
FIRST_RELEASE_WITH_ON_FAILURE = (2, 1, 295)
TARGETS = (
    "plugins/onex",
    "plugins/onex-delegate",
    "plugins/.claude-plugin/marketplace.json",
    ".claude-plugin/marketplace.json",
)

pytestmark = pytest.mark.unit


def _workflow() -> dict[str, Any]:
    return cast(
        "dict[str, Any]",
        yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text()),
    )


def _job() -> dict[str, Any]:
    return cast("dict[str, Any]", _workflow()["jobs"][JOB_ID])


def _commands(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in job["steps"])


def test_the_job_exists_under_its_registered_name() -> None:
    assert _job()["name"] == JOB_NAME


def test_the_job_cannot_be_skipped() -> None:
    job = _job()
    assert "needs" not in job, "a failed dependency would skip this gate silently"
    assert job.get("if") == "always()"
    for step in job["steps"]:
        assert "continue-on-error" not in step, step.get("name")
        assert "if" not in step, step.get("name")


def test_the_pinned_release_defines_on_failure() -> None:
    pin = _workflow()["env"]["CLAUDE_CODE_VERSION"]
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin), f"pin must be exact, got {pin!r}"
    assert tuple(int(p) for p in pin.split(".")) >= FIRST_RELEASE_WITH_ON_FAILURE


def test_the_job_installs_the_exact_pinned_release_and_checks_it() -> None:
    commands = _commands(_job())
    assert '@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}"' in commands
    assert "claude --version" in commands and "exit 1" in commands


def test_the_job_validates_every_manifest() -> None:
    commands = _commands(_job())
    assert "claude plugin validate" in commands
    for target in TARGETS:
        assert target in commands, f"{target} is not validated"
        assert (REPO_ROOT / target).exists(), f"{target} does not exist"


def test_the_job_does_not_soften_validate() -> None:
    commands = _commands(_job())
    assert "|| true" not in commands
    assert "set -euo pipefail" in commands


def test_the_umbrella_waits_for_it_and_accepts_only_success() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS


def _precommit_hook() -> dict[str, Any]:
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = {h["id"]: h for repo in config["repos"] for h in repo["hooks"]}
    return cast("dict[str, Any]", hooks[HOOK_ID])


def test_a_manifest_change_runs_it_before_the_commit() -> None:
    hook = _precommit_hook()
    for path in (
        "plugins/onex/hooks/hooks.json",
        "plugins/onex/.claude-plugin/plugin.json",
        "plugins/onex-delegate/.claude-plugin/plugin.json",
        "plugins/.claude-plugin/marketplace.json",
        ".claude-plugin/marketplace.json",
    ):
        assert re.search(hook["files"], path), f"{path} does not trigger the hook"
    assert hook["pass_filenames"] is False
    for target in TARGETS:
        assert target in str(hook["entry"])


def test_the_whole_tree_precommit_job_can_run_the_hook() -> None:
    """The precommit-suite job runs every hook; it needs the CLI on PATH."""
    job = _workflow()["jobs"]["precommit-suite"]
    steps = job["steps"]
    install = next(
        i
        for i, step in enumerate(steps)
        if "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" in str(step.get("run"))
    )
    run = next(
        i
        for i, step in enumerate(steps)
        if "pre-commit run --all-files" in str(step.get("run", ""))
    )
    assert install < run


def test_test_and_eval_are_not_applicable_to_these_plugins() -> None:
    """Recorded decision: neither command has anything to run here.

    ``claude plugin test`` runs a hooks module's ``*.test.ts`` files and refuses
    a plugin whose hooks.json names no module; ``claude plugin eval`` runs an
    ``evals/`` suite. If this test fails, a plugin gained one of them: wire the
    matching command into the job above and pre-commit, then delete this test.
    """
    hooks = json.loads((REPO_ROOT / "plugins/onex/hooks/hooks.json").read_text())
    assert "modules" not in hooks
    for plugin in ("plugins/onex", "plugins/onex-delegate"):
        assert not (REPO_ROOT / plugin / "evals").exists(), plugin
        assert not list((REPO_ROOT / plugin).rglob("*.test.ts")), plugin
