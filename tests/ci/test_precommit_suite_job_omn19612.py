# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pin whole-tree CI coverage for staged-scoped pre-commit hooks (OMN-19612)."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

from scripts.ci.check_workflow_expression_contexts import check_workflow
from scripts.ci.ci_summary_gate import GATE_JOBS, SOFT_ALLOWLIST, STRICT_SUCCESS_JOBS

pytestmark = [pytest.mark.unit]

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"
JOB_ID = "precommit-suite"
JOB_NAME = "Pre-commit Suite (OMN-19612)"


def _load_yaml(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} did not parse to a mapping"
    return loaded


def _workflow() -> dict:
    return _load_yaml(CI_WORKFLOW)


def _job() -> dict:
    jobs = _workflow()["jobs"]
    assert JOB_ID in jobs, f"ci.yml has no `{JOB_ID}` job"
    return jobs[JOB_ID]


def _staged_scoped_hook_ids() -> set[str]:
    """Derive explicit filename-filtered hooks from the live configuration."""
    config = _load_yaml(PRECOMMIT_CONFIG)
    return {
        str(hook["id"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("pass_filenames") is True and bool(hook.get("files"))
    }


def test_every_staged_scoped_hook_has_a_whole_tree_counterpart() -> None:
    staged_scoped = _staged_scoped_hook_ids()
    assert staged_scoped, "expected at least one explicitly staged-scoped hook"

    commands = "\n".join(str(step.get("run", "")) for step in _job()["steps"])
    assert "SKIP=" not in commands
    for hook_id in staged_scoped:
        assert "pre-commit run --all-files" in commands, (
            f"{hook_id} has no whole-tree pre-commit counterpart"
        )


def _run_step() -> dict:
    steps = [
        step
        for step in _job()["steps"]
        if "pre-commit run --all-files" in str(step.get("run", ""))
    ]
    assert len(steps) == 1, "expected exactly one whole-tree pre-commit step"
    return steps[0]


def _locked_dev_dependencies() -> set[str]:
    pyproject = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dev = pyproject.get("dependency-groups", {}).get("dev", [])
    lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    locked = {str(package.get("name")) for package in lock["package"]}
    return {Requirement(req).name for req in dev if isinstance(req, str)} & locked


def test_pre_commit_is_installable_in_the_whole_tree_step() -> None:
    """The run step must be able to spawn pre-commit (the round-3 red).

    Either pre-commit is a locked dev dependency, or the step layers an
    exact-pinned pre-commit over the project venv with ``uv run --with``.
    """
    run = str(_run_step()["run"])
    pinned_tool = re.search(
        r"uv run\b[^\n]*--with\s+['\"]?pre-commit==\d+\.\d+\.\d+", run
    )
    assert pinned_tool or "pre-commit" in _locked_dev_dependencies(), (
        "pre-commit is neither a locked dev dependency nor an exact-pinned "
        "`uv run --with` tool in the whole-tree step: it cannot be spawned"
    )


def test_whole_tree_job_installs_the_dev_group() -> None:
    steps = _job()["steps"]
    install_index = next(
        index
        for index, step in enumerate(steps)
        if "uv sync" in str(step.get("run", ""))
        and "--group dev" in str(step.get("run", ""))
    )
    run_index = next(
        index
        for index, step in enumerate(steps)
        if "pre-commit run --all-files" in str(step.get("run", ""))
    )
    assert install_index < run_index


def test_whole_tree_job_runs_this_pin_itself() -> None:
    test_path = Path(__file__).relative_to(REPO_ROOT).as_posix()
    matching_steps = [
        step for step in _job()["steps"] if test_path in str(step.get("run", ""))
    ]
    assert matching_steps, f"no step runs {test_path}"
    for step in matching_steps:
        assert "if" not in step


def test_whole_tree_job_is_unconditional_and_fail_closed() -> None:
    job = _job()
    assert "if" not in job
    assert "needs" not in job
    assert "continue-on-error" not in job
    for step in job["steps"]:
        assert "if" not in step, f"conditional step: {step.get('name')}"
        assert "continue-on-error" not in step, f"advisory step: {step.get('name')}"


def test_whole_tree_job_is_required_by_ci_summary() -> None:
    assert JOB_NAME in GATE_JOBS
    assert JOB_NAME in STRICT_SUCCESS_JOBS
    assert JOB_NAME not in SOFT_ALLOWLIST


def test_workflow_has_no_pull_request_path_filter() -> None:
    workflow = _workflow()
    triggers = workflow[True] if True in workflow else workflow["on"]
    pull_request = triggers.get("pull_request") or {}
    assert "paths" not in pull_request
    assert "paths-ignore" not in pull_request
    required_types = {"opened", "synchronize", "reopened"}
    assert "types" not in pull_request or required_types <= set(pull_request["types"])


def test_ci_workflow_uses_only_contexts_available_at_each_key() -> None:
    assert check_workflow(CI_WORKFLOW) == []


def test_whole_tree_job_provides_omnimarket_nodes_at_the_lock_pin() -> None:
    """OMN-20560: the skill backing-node hook resolves omnimarket nodes here.

    verified_dispatch and shim_audit left the backing-node allowlist because
    their nodes live in omnimarket. The whole-tree run must therefore hand the
    hook the omnimarket node tree at the uv.lock pin through OMNI_HOME.
    """
    runs = "\n".join(str(step.get("run", "")) for step in _job()["steps"])
    # OMN-21900: uv.lock names a first-party source by a dev-merge tag, so the lock
    # pin reads `omnimarket.git?tag=<tag>#<sha>`; the resolver still accepts the
    # legacy `?rev=` spelling and takes the sha after the `#` in both.
    assert "omnimarket\\.git\\?(rev|tag)=" in runs
    assert "sparse-checkout set src/omnimarket/nodes" in runs
    assert '"$OMNI_HOME/omnimarket"' in runs


def _pre_push_only_hook_ids(*, among: set[str]) -> set[str]:
    config = _load_yaml(PRECOMMIT_CONFIG)
    return {
        str(hook["id"])
        for repo in config["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("stages") == ["pre-push"] and str(hook["id"]) in among
    }


def test_direct_model_call_gate_runs_whole_tree_in_ci_from_the_pre_push_stage() -> None:
    """OMN-17427: the gate left the commit stage, so `--all-files` no longer runs it.

    `pre-commit run --all-files` runs the default (pre-commit) stage only. The gate
    must therefore have its own whole-tree step in this job, or it runs nowhere on
    a pull request.
    """
    hook_id = "check-direct-model-call"
    assert _pre_push_only_hook_ids(among={hook_id}) == {hook_id}
    commands = [str(step.get("run", "")) for step in _job()["steps"]]
    assert any(
        f"pre-commit run {hook_id} --all-files --hook-stage pre-push" in command
        for command in commands
    ), f"{hook_id} is pre-push only and has no whole-tree step in {JOB_ID}"


_SIBLING_STEP_NAME = (
    "Provide the sibling clones the cross-repo hooks resolve through OMNI_HOME"
)
_OM_SHA = "6" * 40
_CORE_DEV_SHA = "c" * 40
_LOCK_OMNIMARKET = (
    '[[package]]\nname = "omnimarket"\nversion = "0.1.0"\n'
    'source = { git = "https://github.com/OmniNode-ai/omnimarket.git'
    f'?tag=dev-20261104002655-6335ba6fdcad#{_OM_SHA}" }}\n'
)


def _core_lock(version: str, source: str) -> str:
    return (
        '[[package]]\nname = "omnibase-core"\n'
        f'version = "{version}"\nsource = {source}\n\n' + _LOCK_OMNIMARKET
    )


def _run_sibling_step(tmp_path: Path, lock_text: str) -> tuple[int, list[str]]:
    """Run the sibling-clones step's own shell against a lock, with git/uv stubbed.

    ``git`` records its arguments instead of touching the network; ``uv`` answers
    the version query with the version the lock declares, as the installed
    metadata does. Returns the exit status and the recorded git calls.
    """
    step = next(s for s in _job()["steps"] if s.get("name") == _SIBLING_STEP_NAME)
    (tmp_path / "uv.lock").write_text(lock_text, encoding="utf-8")
    (tmp_path / "step.sh").write_text(str(step["run"]), encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "git.log"
    (bin_dir / "git").write_text(
        f'#!/bin/bash\necho "$*" >> "{log}"\n', encoding="utf-8"
    )
    (bin_dir / "uv").write_text(
        "#!/bin/bash\n"
        'awk \'$0 == "name = \\"omnibase-core\\"" {getline; print $3; exit}\' '
        "uv.lock | tr -d '\"'\n",
        encoding="utf-8",
    )
    for stub in bin_dir.iterdir():
        stub.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "RUNNER_TEMP": str(tmp_path / "runner"),
        "GITHUB_ENV": str(tmp_path / "github_env"),
    }
    result = subprocess.run(
        ["bash", "-e", "step.sh"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.returncode, calls


def test_sibling_core_clone_follows_a_dev_tag_git_source_by_locked_sha(
    tmp_path: Path,
) -> None:
    """OMN-19612: a dev-tag omnibase-core must not be cloned as ``v<version>``.

    uv.lock resolves omnibase-core from a dev merge tag (OMN-21282), whose
    metadata version (here 0.47.66) has no release tag until the release PR
    merges, so ``git clone --branch v0.47.66`` died with ``Remote branch
    v0.47.66 not found``. The step must fetch the locked sha instead.
    """
    lock = _core_lock(
        "0.47.66",
        "{ git = "
        '"https://github.com/OmniNode-ai/omnibase_core.git'
        f'?tag=dev-20261104014415-cefaf61fea4f#{_CORE_DEV_SHA}" }}',
    )
    status, calls = _run_sibling_step(tmp_path, lock)
    assert status == 0, calls
    assert not any("--branch" in call for call in calls), calls
    assert any(
        "omnibase_core" in call
        and "fetch" in call
        and call.endswith(f"omnibase_core.git {_CORE_DEV_SHA}")
        for call in calls
    ), calls
    assert any(
        call.endswith("checkout --quiet FETCH_HEAD") and "omnibase_core" in call
        for call in calls
    ), calls


def test_sibling_core_clone_keeps_the_release_tag_for_a_release_pin(
    tmp_path: Path,
) -> None:
    lock = _core_lock("0.47.62", '{ registry = "https://pypi.org/simple" }')
    status, calls = _run_sibling_step(tmp_path, lock)
    assert status == 0, calls
    assert any(
        "clone" in call and "--branch v0.47.62 " in call and "omnibase_core.git" in call
        for call in calls
    ), calls


def test_sibling_core_clone_fails_closed_on_a_git_source_with_no_locked_sha(
    tmp_path: Path,
) -> None:
    lock = _core_lock(
        "0.47.66",
        '{ git = "https://github.com/OmniNode-ai/omnibase_core.git?tag=dev-1" }',
    )
    status, calls = _run_sibling_step(tmp_path, lock)
    assert status != 0
    assert not any("omnibase_core" in call for call in calls), calls
