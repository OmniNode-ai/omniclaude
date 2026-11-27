# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Workflow invariants for the public-repo hygiene gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REUSABLE = WORKFLOWS / "public-repo-hygiene-reusable.yml"
AUDIT = WORKFLOWS / "public-repo-hygiene-audit.yml"
CALLER = WORKFLOWS / "public-repo-hygiene.yml"


def _workflow(path: Path) -> dict[str, object]:
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh)
    assert isinstance(loaded, dict)
    return loaded


def _step(workflow_path: Path, job_name: str, step_name: str) -> dict[str, object]:
    workflow = _workflow(workflow_path)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    job = jobs[job_name]
    assert isinstance(job, dict)
    steps = job["steps"]
    assert isinstance(steps, list)
    for candidate in steps:
        assert isinstance(candidate, dict)
        if candidate.get("name") == step_name:
            return candidate
    raise AssertionError(
        f"{workflow_path} job {job_name} has no step named {step_name!r}"
    )


def test_public_repo_hygiene_reusable_uses_org_wide_onexbot_credentials() -> None:
    """Public callers do not all receive the selected OCC app secrets."""
    step = _step(
        REUSABLE, "public-repo-hygiene", "Mint token for the private vocabulary repo"
    )
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in REUSABLE.read_text(encoding="utf-8")


def test_public_repo_hygiene_audit_uses_org_wide_onexbot_credentials() -> None:
    """The org audit has the same public governance credential boundary."""
    step = _step(AUDIT, "audit", "Mint org-read token")
    with_block = step["with"]
    assert isinstance(with_block, dict)

    assert with_block["app-id"] == "${{ secrets.ONEXBOT_APP_ID }}"
    assert with_block["private-key"] == "${{ secrets.ONEXBOT_APP_PRIVATE_KEY }}"
    assert "ONEXBOT_OCC_APP_ID" not in AUDIT.read_text(encoding="utf-8")


def test_public_repo_hygiene_caller_still_inherits_secrets() -> None:
    workflow = _workflow(CALLER)
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    caller = jobs["public-repo-hygiene"]
    assert isinstance(caller, dict)

    assert caller["secrets"] == "inherit"


def test_public_repo_hygiene_reusable_fetches_and_passes_the_lab_vocabulary() -> None:
    """OMN-19766: the lab-config class reads a second private file.

    It resolves its repository from an org variable (never named in public
    source), fetches it with the same app token, and the gate is handed its
    path; a missing file is a refusal before the gate runs.
    """
    text = REUSABLE.read_text(encoding="utf-8")
    resolve = _step(
        REUSABLE, "public-repo-hygiene", "Resolve the private lab vocabulary repo"
    )
    env = resolve["env"]
    assert isinstance(env, dict)
    assert env["FROM_VARS"] == "${{ vars.OMNI_HYGIENE_LAB_VOCAB_REPO }}"
    assert "exit 1" in str(resolve["run"])

    mint = _step(
        REUSABLE, "public-repo-hygiene", "Mint token for the private vocabulary repo"
    )
    with_block = mint["with"]
    assert isinstance(with_block, dict)
    assert "steps.lab-vocab-repo.outputs.name" in str(with_block["repositories"])

    fetch = _step(REUSABLE, "public-repo-hygiene", "Fetch the private lab vocabulary")
    fetch_with = fetch["with"]
    assert isinstance(fetch_with, dict)
    assert fetch_with["path"] == ".public-repo-hygiene-lab-vocabulary"
    assert "steps.vocab-files.outputs.lab_vocabulary" in str(
        fetch_with["sparse-checkout"]
    )

    gate_step = _step(
        REUSABLE, "public-repo-hygiene", "Run the public-repo hygiene gate"
    )
    run = str(gate_step["run"])
    assert '--lab-vocabulary "${LAB_VOCAB_PATH}"' in run
    assert 'if [ ! -f "${LAB_VOCAB_PATH}" ]' in run
    assert "OMNI_HYGIENE_LAB_VOCAB_REPO" in text


def _run_vocab_files_step(
    tmp_path: Path, env_overrides: dict[str, str]
) -> tuple[int, str, dict[str, str]]:
    """Run the reusable's vocab-file resolution step in a subprocess.

    All six EXPLICIT_*/FROM_VARS_* variables default to empty; the step's
    own GITHUB_OUTPUT lines are parsed back into an outputs dict.
    """
    run = _step(
        REUSABLE, "public-repo-hygiene", "Resolve the private vocabulary file locations"
    )["run"]
    assert isinstance(run, str)
    script = tmp_path / "vocab_files.sh"
    script.write_text(run, encoding="utf-8")
    github_output = tmp_path / "github_output.txt"
    env = {
        "PATH": "/usr/bin:/bin",
        "GITHUB_OUTPUT": str(github_output),
        "EXPLICIT_VOCAB": "",
        "FROM_VARS_VOCAB": "",
        "EXPLICIT_LAB": "",
        "FROM_VARS_LAB": "",
        "EXPLICIT_MODEL": "",
        "FROM_VARS_MODEL": "",
    }
    env.update(env_overrides)
    result = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, check=False
    )
    outputs: dict[str, str] = {}
    if github_output.exists():
        for line in github_output.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                outputs[key] = value
    return result.returncode, result.stdout + result.stderr, outputs


def test_public_repo_hygiene_reusable_names_no_vocabulary_location() -> None:
    """No private vocabulary file location may appear in public source."""
    text = REUSABLE.read_text(encoding="utf-8")
    assert "docs/workflows/_shared" not in text
    assert "vocabularies/public_repo_hygiene" not in text
    assert "OMNI_HYGIENE_VOCAB_FILE" in text
    assert "OMNI_HYGIENE_LAB_VOCAB_FILE" in text
    assert "OMNI_HYGIENE_MODEL_VOCAB_FILE" in text


def test_vocab_files_step_resolves_all_three_from_variables(
    tmp_path: Path,
) -> None:
    """All three locations resolve from the org Actions variables."""
    returncode, _, outputs = _run_vocab_files_step(
        tmp_path,
        {
            "FROM_VARS_VOCAB": "a/one.yaml",
            "FROM_VARS_LAB": "b/two.yaml",
            "FROM_VARS_MODEL": "c/three.yaml",
        },
    )
    assert returncode == 0
    assert outputs == {
        "vocabulary": "a/one.yaml",
        "lab_vocabulary": "b/two.yaml",
        "model_vocabulary": "c/three.yaml",
    }


def test_vocab_files_step_input_wins_over_variable(tmp_path: Path) -> None:
    """An explicit input value beats the org variable it shadows."""
    returncode, _, outputs = _run_vocab_files_step(
        tmp_path,
        {
            "EXPLICIT_VOCAB": "a/one.yaml",
            "FROM_VARS_VOCAB": "zz/z.yaml",
            "FROM_VARS_LAB": "b/two.yaml",
            "FROM_VARS_MODEL": "c/three.yaml",
        },
    )
    assert returncode == 0
    assert outputs["vocabulary"] == "a/one.yaml"


@pytest.mark.parametrize(
    ("missing_variable", "present"),
    [
        (
            "OMNI_HYGIENE_VOCAB_FILE",
            {"FROM_VARS_LAB": "b/two.yaml", "FROM_VARS_MODEL": "c/three.yaml"},
        ),
        (
            "OMNI_HYGIENE_LAB_VOCAB_FILE",
            {"FROM_VARS_VOCAB": "a/one.yaml", "FROM_VARS_MODEL": "c/three.yaml"},
        ),
        (
            "OMNI_HYGIENE_MODEL_VOCAB_FILE",
            {"FROM_VARS_VOCAB": "a/one.yaml", "FROM_VARS_LAB": "b/two.yaml"},
        ),
    ],
)
def test_vocab_files_step_refuses_when_one_location_is_missing(
    tmp_path: Path, missing_variable: str, present: dict[str, str]
) -> None:
    """Blank exactly one location; only that one is named as missing."""
    returncode, combined, _ = _run_vocab_files_step(tmp_path, present)
    assert returncode != 0
    assert missing_variable in combined
    assert "THE GATE DID NOT RUN" in combined
    for other in (
        "OMNI_HYGIENE_VOCAB_FILE",
        "OMNI_HYGIENE_LAB_VOCAB_FILE",
        "OMNI_HYGIENE_MODEL_VOCAB_FILE",
    ):
        if other != missing_variable:
            assert other not in combined


def test_vocab_files_step_refuses_an_escaping_path(tmp_path: Path) -> None:
    """A location that escapes the fetched repository is refused."""
    base = {
        "FROM_VARS_VOCAB": "a/one.yaml",
        "FROM_VARS_LAB": "b/two.yaml",
        "FROM_VARS_MODEL": "c/three.yaml",
    }
    for escaping in ("../x.yaml", "/etc/x.yaml"):
        returncode, _, _ = _run_vocab_files_step(
            tmp_path, {**base, "FROM_VARS_VOCAB": escaping}
        )
        assert returncode != 0


def test_public_repo_hygiene_reusable_hands_the_gate_a_pull_request_diff_base() -> None:
    """OMN-19835: the added-lines scope needs the merge ref's first parent.

    Depth 2 fetches exactly that parent. The resolve step refuses a checkout
    that is not a two-parent merge ref of the pull request head from the
    event's shas, and the gate is handed the first parent as --diff-base.
    """
    checkout = _step(REUSABLE, "public-repo-hygiene", "Checkout caller repo")
    checkout_with = checkout["with"]
    assert isinstance(checkout_with, dict)
    assert checkout_with["fetch-depth"] == 2

    resolve = _step(REUSABLE, "public-repo-hygiene", "Resolve the diff base")
    assert resolve["if"] == "github.event_name == 'pull_request'"
    env = resolve["env"]
    assert isinstance(env, dict)
    assert env["PR_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    body = str(resolve["run"])
    assert "git rev-list --parents -n 1 HEAD" in body
    assert env["PR_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"

    gate_step = _step(
        REUSABLE, "public-repo-hygiene", "Run the public-repo hygiene gate"
    )
    gate_env = gate_step["env"]
    assert isinstance(gate_env, dict)
    assert gate_env["DIFF_BASE"] == "${{ steps.diff-base.outputs.sha }}"
    run = str(gate_step["run"])
    assert 'diff_args=(--diff-base "${DIFF_BASE}")' in run
    assert "${diff_args[@]+" in run


_DIFF_BASE_JOBS = ("public-repo-hygiene", "deployment-config")


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(cwd),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "GIT_CONFIG_NOSYSTEM": "1",
        },
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def _run_diff_base_step(
    tmp_path: Path, job: str, workspace: Path, head: str, base: str
) -> tuple[int, str, dict[str, str]]:
    run = _step(REUSABLE, job, "Resolve the diff base")["run"]
    assert isinstance(run, str)
    script = tmp_path / "diff_base.sh"
    script.write_text(run, encoding="utf-8")
    github_output = tmp_path / "diff_base_output.txt"
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GITHUB_OUTPUT": str(github_output),
        "PR_HEAD_SHA": head,
        "PR_BASE_SHA": base,
    }
    result = subprocess.run(
        ["bash", str(script)],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    outputs: dict[str, str] = {}
    if github_output.exists():
        for line in github_output.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            outputs[key] = value
    return result.returncode, result.stdout + result.stderr, outputs


def _pull_request_remote(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A remote holding a base line and a pull request branch off its middle."""
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _git(remote, "config", "uploadpack.allowAnySHA1InWant", "true")
    _commit(remote, "a.txt", "a\n")
    fork_point = _commit(remote, "b.txt", "b\n")
    _git(remote, "checkout", "-q", "-b", "pr")
    head = _commit(remote, "pr.txt", "added by the pull request\n")
    _git(remote, "checkout", "-q", "main")
    base = _commit(remote, "c.txt", "c\n")
    return remote, fork_point, base, head


@pytest.mark.parametrize("job", _DIFF_BASE_JOBS)
def test_diff_base_step_keeps_the_two_parent_merge_ref_behaviour(
    tmp_path: Path, job: str
) -> None:
    """A merge ref whose second parent is the head resolves its first parent."""
    remote, _, base, head = _pull_request_remote(tmp_path)
    _git(remote, "checkout", "-q", "--detach", base)
    _git(remote, "merge", "-q", "--no-ff", "-m", "merge", head)
    merge_ref = _git(remote, "rev-parse", "HEAD")
    returncode, combined, outputs = _run_diff_base_step(
        tmp_path, job, remote, head, "0" * 40
    )
    assert returncode == 0, combined
    assert outputs == {"sha": base}
    assert _git(remote, "rev-parse", "HEAD") == merge_ref


@pytest.mark.parametrize("job", _DIFF_BASE_JOBS)
def test_diff_base_step_scans_the_pull_request_head_on_a_one_parent_checkout(
    tmp_path: Path, job: str
) -> None:
    """A rerun after the merge checks out the base tip, one parent.

    The step fetches the head and base by the event's shas, moves HEAD to the
    pull request head, and hands the gate the event's base: the scan runs on
    the pull request's content, never skipped and never vacuous.
    """
    remote, _, base, head = _pull_request_remote(tmp_path)
    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", "--depth", "2", f"file://{remote}", str(workspace))
    assert _git(workspace, "rev-parse", "HEAD") == base
    assert len(_git(workspace, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 2
    returncode, combined, outputs = _run_diff_base_step(
        tmp_path, job, workspace, head, base
    )
    assert returncode == 0, combined
    assert "THE GATE DID NOT RUN" not in combined
    assert outputs == {"sha": base}
    assert _git(workspace, "rev-parse", "HEAD") == head
    added = _git(workspace, "diff", "--name-only", f"{base}...HEAD")
    assert added == "pr.txt"


@pytest.mark.parametrize("job", _DIFF_BASE_JOBS)
def test_diff_base_step_refuses_a_head_that_cannot_be_fetched(
    tmp_path: Path, job: str
) -> None:
    """Known bad: a head sha the remote does not hold is a refusal, not a skip."""
    remote, _, base, _ = _pull_request_remote(tmp_path)
    workspace = tmp_path / "workspace"
    _git(tmp_path, "clone", "-q", "--depth", "2", f"file://{remote}", str(workspace))
    returncode, combined, outputs = _run_diff_base_step(
        tmp_path, job, workspace, "f" * 40, base
    )
    assert returncode != 0
    assert "THE GATE DID NOT RUN" in combined
    assert outputs == {}


def test_public_repo_hygiene_hook_runs_on_every_commit_with_the_staged_diff() -> None:
    """OMN-19835: the exported hook hands the gate the staged diff, and runs on
    every commit. OMN-18777 had narrowed it to workflow files by mistake, so a
    commit adding a private name to any other file never ran it.
    """
    hooks = yaml.safe_load(
        (REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    )
    hook = next(h for h in hooks if h["id"] == "public-repo-hygiene")
    assert "scripts/public_repo_hygiene_gate.py" in hook["entry"]
    assert "--diff-staged" in hook["entry"]
    assert hook["always_run"] is True
    assert "files" not in hook
    assert hook["pass_filenames"] is False


def test_deployment_ratchet_is_required_by_ci_summary() -> None:
    from scripts.ci.ci_summary_gate import EXPECTED_EXTERNAL_CONTEXTS

    assert "public-repo-hygiene / deployment-config" in EXPECTED_EXTERNAL_CONTEXTS
    assert "public-repo-hygiene / public-repo-hygiene" in EXPECTED_EXTERNAL_CONTEXTS


def test_deployment_ci_and_hook_enforce_whole_tree_ratchet() -> None:
    workflow = _workflow(REUSABLE)
    step = _step(REUSABLE, "deployment-config", "Run the deployment-config class")
    assert "--enforce-scope whole-tree" in step["run"]
    assert "--ratchet" in step["run"]
    assert "--enforce-scope added-lines" not in step["run"]
    caller = _workflow(CALLER)["jobs"]["public-repo-hygiene"]
    assert caller["with"]["deployment_config_ratchet"] is True
    config = REPO_ROOT / ".pre-commit-config.yaml"
    hooks = [
        hook for repo in _workflow(config)["repos"] for hook in repo.get("hooks", [])
    ]
    hook = next(hook for hook in hooks if hook["id"] == "deployment-config")
    assert "--enforce-scope whole-tree --diff-staged" in hook["entry"]
    assert hook["args"] == ["--ratchet"]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False
    assert (REPO_ROOT / ".public-repo-hygiene.yaml").is_file()
