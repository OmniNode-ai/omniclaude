# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Structural tests for the Hostile Reviewer CI workflow — OMN-8603.

Asserts that ``.github/workflows/hostile-reviewer.yml`` is wired correctly:

- Triggers on the expected ``pull_request`` event types.
- Runs on the ``omnibase-ci`` self-hosted runner that reaches the voters'
  private network.
- Invokes ``omniintelligence.review_pairing.cli_review`` with the review
  voters contract overlay and names no voter endpoint or model (OMN-20910).
- Defines a ``hostile-review-gate`` job that depends on ``hostile-review``
  and exits non-zero when the review job reports ``failure``.
- Posts a PR summary comment via ``actions/github-script``.
- Does NOT require ``ANTHROPIC_API_KEY`` in any step's env block (regression
  guard for OMN-7467).

Wires the OMN-8524 implementation behind a permanent test so future edits to
the workflow cannot silently regress the gate semantics.
"""

from __future__ import annotations

import pathlib
import re
import subprocess

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[object, object]:
    """Parse the hostile-reviewer workflow YAML once per test module.

    Returns ``dict[object, object]`` because PyYAML can map the bare ``on:``
    key to Python boolean ``True`` (YAML 1.1 treats ``on`` as truthy), which
    forces the key type to be wider than ``str``.
    """
    assert WORKFLOW_PATH.is_file(), (
        f"hostile-reviewer workflow missing: {WORKFLOW_PATH}. "
        "OMN-8603 requires this CI gate to be wired."
    )
    with WORKFLOW_PATH.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    assert isinstance(loaded, dict), "workflow root must be a mapping"
    return loaded


def test_workflow_is_valid_yaml(workflow: dict[object, object]) -> None:
    """The workflow file must parse as a mapping with a name."""
    assert workflow.get("name"), "workflow must declare a top-level name"


def test_workflow_triggers_on_pull_request(workflow: dict[object, object]) -> None:
    """Workflow must run on PR open / synchronize / reopen against main.

    PyYAML maps the bare ``on:`` key to Python boolean ``True`` because YAML
    1.1 treats ``on`` as a truthy literal — accept either spelling.
    """
    triggers = workflow.get("on") or workflow.get(True)
    assert isinstance(triggers, dict), "workflow must declare a triggers mapping"

    pr_block = triggers.get("pull_request")
    assert isinstance(pr_block, dict), "pull_request trigger must be a mapping"

    types = pr_block.get("types") or []
    assert "opened" in types, "must trigger on PR opened"
    assert "synchronize" in types, "must trigger on PR synchronize"
    assert "reopened" in types, "must trigger on PR reopened"

    branches = pr_block.get("branches") or []
    assert "main" in branches, "must gate PRs targeting main"


def test_review_job_runs_on_self_hosted_runner(workflow: dict[object, object]) -> None:
    """The review job must run on the self-hosted ``omnibase-ci`` runner.

    The review voters sit on a private network and are LAN-only — GitHub-hosted
    runners cannot reach them. This is the fundamental constraint that drove
    OMN-8603 (runner toolchain) and pins the gate to the self-hosted fleet.
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), "workflow must define jobs"
    review_job = jobs.get("hostile-review")
    assert isinstance(review_job, dict), "hostile-review job must exist"

    runs_on = review_job.get("runs-on")
    assert runs_on is not None, "hostile-review must declare runs-on"
    if isinstance(runs_on, list):
        labels = set(runs_on)
        assert "self-hosted" in labels, "runner must be self-hosted"
        assert "omnibase-ci" in labels, (
            "runner label must include 'omnibase-ci' so the private-network voter "
            "endpoints are reachable"
        )
        return

    assert isinstance(runs_on, str), "runs-on must be labels or a routing expression"
    assert "OMNI_TRUSTED_CI_RUNS_ON_JSON" not in runs_on, (
        "this LAN-only job must not use the generic trusted runner variable; "
        "that variable can resolve to hosted runners in repos whose general CI "
        "does not require the LAN-only model path"
    )
    # OMN-18415: the fleet labels are now the FALLBACK of a dedicated per-job
    # variable rather than a bare literal. The operating value is unchanged --
    # the variable is deliberately unset at org and repo scope -- but the job is
    # no longer invisible to the routing audit, which reads Actions variables
    # and cannot see a label written straight into a workflow file.
    assert (
        "vars.OMNI_HOSTILE_REVIEW_RUNS_ON_JSON || "
        """'["self-hosted","omnibase-ci"]'""" in runs_on
    ), (
        "same-repo review runs must resolve to the self-hosted omnibase-ci "
        "labels so the LAN-only voter endpoints are reachable, through the "
        "dedicated OMNI_HOSTILE_REVIEW_RUNS_ON_JSON knob"
    )


def test_same_repo_dev_prs_do_not_use_public_runner_branch(
    workflow: dict[object, object],
) -> None:
    """Same-repo dev PRs need the LAN-only voter endpoints on the trusted runner.

    Forks may still take the public-runner branch, but a same-repo PR targeting
    dev must not. That exact shape ran on ``ubuntu-latest`` for omniclaude#2181
    and made ``cli_review`` fail twice with no model reachable.
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    runs_on = review_job.get("runs-on")
    assert isinstance(runs_on, str), "runs-on must be a routing expression"

    assert "github.event.pull_request.base.ref == 'dev'" not in runs_on
    assert (
        "github.event.pull_request.head.repo.full_name != github.repository" in runs_on
    )
    assert "OMNI_PUBLIC_PR_RUNS_ON_JSON" in runs_on
    assert "OMNI_TRUSTED_CI_RUNS_ON_JSON" not in runs_on
    # OMN-18415: dedicated variable, fleet literal as the operating fallback.
    assert (
        "vars.OMNI_HOSTILE_REVIEW_RUNS_ON_JSON || "
        """'["self-hosted","omnibase-ci"]'""" in runs_on
    )


def _review_job_steps(workflow: dict[object, object]) -> list[dict[str, object]]:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps, "review job must have steps"
    return [step for step in steps if isinstance(step, dict)]


# OMN-20910: what a voter endpoint looks like when someone writes one into the
# workflow -- a URL with an explicit port, an endpoint variable, or a --model
# flag. Comment lines are skipped; the workflow keeps its history there.
_VOTER_ENDPOINT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://[A-Za-z0-9.\-]+:\d{2,5}"),
    re.compile(r"\bLLM_[A-Z0-9_]+_URL\b"),
    re.compile(r"vars\.LLM_"),
    re.compile(r"--model[\s=]"),
)

# OMN-20910: the voter's model is a field of the overlay, so a workflow names no
# model at all. A ``vars.<anything>MODEL`` reference and a model id literal are
# refused here; ``_env_model_literal_findings`` refuses a MODEL env key bound to
# a literal no pattern knows.
_VOTER_MODEL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bvars\.[A-Za-z0-9_]*MODEL", re.IGNORECASE),
    re.compile(
        r"\b(?:claude-(?:opus|sonnet|haiku|fable|instant|\d)|gpt-?\d|o[1-9]-(?:mini|preview)"
        r"|gemini-?\d|qwen-?\d|qwen-|glm-?\d|deepseek-|llama-?\d|mistral-|mixtral-"
        r"|codestral|gemma-?\d|grok-?\d|kimi-)",
        re.IGNORECASE,
    ),
)
# Positive control: the lines this workflow carried before the overlay.
_KNOWN_BAD = """\
          LLM_EXAMPLE_VOTER_B_URL: ${{ vars.LLM_EXAMPLE_VOTER_B_URL }}
              --model example-voter-a \\
              --model example-voter-b \\
          LLM_EXAMPLE_VOTER_B_URL: "http://voter-b.example.invalid:9002"
"""


def _env_model_literal_findings(text: str) -> list[str]:
    """Every job or step ``env:``/``with:`` key naming a MODEL bound to a literal.

    A literal is any non-empty value that is not a ``${{ ... }}`` expression, so
    a bare id that no pattern knows (``REVIEW_MODEL: my-voter``) is refused too.
    A readback such as ``steps.review.outputs.models_succeeded`` is an expression.
    """
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("jobs"), dict):
        return []
    findings: list[str] = []

    def scan(where: str, mapping: object) -> None:
        if not isinstance(mapping, dict):
            return
        for key, value in mapping.items():
            literal = str(value)
            if "MODEL" in str(key).upper() and literal and "${{" not in literal:
                findings.append(f"{where}: {key}={literal}")

    for job_id, job in parsed["jobs"].items():
        scan(f"{job_id}.env", job.get("env"))
        for step in job.get("steps") or []:
            name = str(step.get("name", ""))
            scan(f"{job_id}/{name}.env", step.get("env"))
            scan(f"{job_id}/{name}.with", step.get("with"))
    return findings


def voter_endpoint_findings(text: str) -> list[str]:
    """Every non-comment line of ``text`` that names a voter endpoint, model or model flag."""
    patterns = (*_VOTER_ENDPOINT_PATTERNS, *_VOTER_MODEL_PATTERNS)
    findings = [
        f"{number}: {line.strip()}"
        for number, line in enumerate(text.splitlines(), start=1)
        if not line.lstrip().startswith("#") and any(p.search(line) for p in patterns)
    ]
    return findings + _env_model_literal_findings(text)


def test_the_voter_endpoint_ratchet_finds_every_known_bad_line() -> None:
    """Positive control: the zero below is only evidence if this finds four."""
    assert len(voter_endpoint_findings(_KNOWN_BAD)) == 4
    # Each pattern needs its own control: a count alone survives a broken pattern
    # whenever another pattern matches the same line.
    lines = _KNOWN_BAD.splitlines()
    for pattern in _VOTER_ENDPOINT_PATTERNS:
        assert any(pattern.search(line) for line in lines), pattern.pattern


def test_workflow_names_no_voter_endpoint_or_model() -> None:
    """OMN-20910, RULING 2026-10-10T18:17:37Z: voters live in the contract overlay only."""
    findings = voter_endpoint_findings(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert findings == [], (
        "hostile-reviewer.yml names a review voter endpoint, port or model; "
        f"voters are declared only in the review voters overlay: {findings}"
    )
    assert "LLM_EXAMPLE_VOTER_B_URL" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_review_step_invokes_cli_review_with_the_voters_overlay(
    workflow: dict[object, object],
) -> None:
    """The review reads its voters from the overlay (OMN-20910).

    The two-voter count that OMN-18473 pinned here is now a property of the
    overlay and of cli_review: a required voter that does not vote exits 2,
    named, and fewer than two distinct voters is a degraded quorum that this
    gate fails closed on. The overlay is validated by omniintelligence's
    node_review_voters_overlay_compute before any voter is called.
    """
    review_step = next(
        s for s in _review_job_steps(workflow) if s.get("id") == "review"
    )
    run = str(review_step.get("run", ""))
    assert "omniintelligence.review_pairing.cli_review" in run
    assert '--voters-overlay "$REVIEW_VOTERS_OVERLAY"' in run
    assert "--pr" in run and "--repo" in run, (
        "review job must pass --pr and --repo to cli_review"
    )
    assert "REVIEW_JSON_FILE=\"$REVIEW_JSON_FILE\" python3 - <<'PYEOF'" in run, (
        "the review JSON's path must be passed through the environment because "
        "the heredoc occupies Python stdin"
    )
    assert "REVIEW_JSON=" not in run and 'os.environ["REVIEW_JSON"]' not in run, (
        "the review JSON itself must never ride in an environment variable: a "
        "Linux execve refuses an environment string over 128 KiB (E2BIG, bash "
        "exit 126), which a review with dozens of findings exceeds"
    )
    assert "echo \"$REVIEW_JSON\" | python3 - <<'PYEOF'" not in run, (
        "do not pipe review JSON into python3 - with a heredoc; Python reads "
        "the script from stdin and the JSON payload is lost"
    )
    env = review_step.get("env") or {}
    assert isinstance(env, dict)
    assert not [k for k in env if str(k).startswith("LLM_") and str(k).endswith("_URL")]


OVERLAY_ENV = (
    "${{ github.workspace }}/../ci-overlay/config/onex/overlays/"
    "node_review_voters_overlay_compute/overlay.yaml"
)
PINNED_REF = "0123456789abcdef0123456789abcdef01234567"


def _named_step(workflow: dict[object, object], name: str) -> dict[str, object]:
    matches = [s for s in _review_job_steps(workflow) if s.get("name") == name]
    assert len(matches) == 1, f"expected one step named {name!r}"
    return matches[0]


def test_voters_overlay_path_is_the_ci_overlay_outside_the_workspace(
    workflow: dict[object, object],
) -> None:
    """OMN-20923 (RULING 2026-10-10T21:57:38Z): the roster is a deployment fact
    no shipped repository carries. It is read from the private CI overlay,
    outside the checkout, so a pull request cannot supply its own voters."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    env = review_job.get("env")
    assert isinstance(env, dict)
    assert env["REVIEW_VOTERS_OVERLAY"] == OVERLAY_ENV
    clean = _named_step(workflow, "Clean stale dependency clones")
    assert "../ci-overlay" in str(clean.get("run", ""))


def test_the_ci_overlay_repository_comes_from_an_org_variable(
    workflow: dict[object, object],
) -> None:
    step = _named_step(workflow, "Resolve the CI overlay")
    step_env = step.get("env")
    assert isinstance(step_env, dict)
    assert step_env["CI_OVERLAY_REPO"] == "${{ vars.OMNI_CI_OVERLAY_REPO }}"
    assert step_env["CI_OVERLAY_REF"] == "${{ vars.OMNI_CI_OVERLAY_REF }}"
    fetch = _named_step(workflow, "Fetch the CI overlay")
    with_ = fetch.get("with")
    assert isinstance(with_, dict)
    assert with_["repository"] == (
        "${{ github.repository_owner }}/${{ steps.ci-overlay.outputs.name }}"
    )
    assert with_["persist-credentials"] is False
    assert with_["ref"] == "${{ steps.ci-overlay.outputs.ref }}"
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "lane-overlays" not in text
    assert "github.com/OmniNode-ai/omnibase_infra.git" not in text


def _run_resolve(
    workflow: dict[object, object],
    repo_var: str,
    tmp_path: pathlib.Path,
    ref_var: str = PINNED_REF,
) -> tuple[int, str, str]:
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    proc = subprocess.run(
        ["bash", "-c", str(_named_step(workflow, "Resolve the CI overlay")["run"])],
        env={
            "CI_OVERLAY_REPO": repo_var,
            "CI_OVERLAY_REF": ref_var,
            "GITHUB_OUTPUT": str(output),
            "PATH": "/usr/bin:/bin",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, output.read_text(encoding="utf-8"), proc.stdout


def test_a_fork_with_no_ci_overlay_gets_the_neutral_default(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    """Unset variable: the gate fails closed, naming "no review voters configured"."""
    rc, out, stdout = _run_resolve(workflow, "", tmp_path)
    assert rc == 1
    assert "no review voters configured" in stdout
    assert "name=" not in out


def test_our_ci_resolves_the_named_overlay_repository(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    rc, out, _ = _run_resolve(workflow, "deploy-config", tmp_path)
    assert rc == 0
    assert "name=deploy-config" in out
    assert f"ref={PINNED_REF}" in out
    rc, _, _ = _run_resolve(workflow, "owner/repo", tmp_path)
    assert rc == 1


def test_the_resolve_step_never_interpolates_a_variable_into_echo(
    workflow: dict[object, object],
) -> None:
    """OMN-20910 (blocking Hostile Reviewer finding): OMNI_CI_OVERLAY_REPO is an
    org-level variable. The step passes it through ``env:`` and must only ever
    reference it as a quoted shell variable handed to ``printf '%s'`` as data,
    never as text in an ``echo`` program line, and must write its outputs with
    ``printf '%s\\n'`` so a value can never be read as an echo option or format."""
    run = str(_named_step(workflow, "Resolve the CI overlay")["run"])
    assert "${{" not in run, "inputs reach the script through env:, not expressions"
    echoes = [line.strip() for line in run.splitlines() if re.match(r"\s*echo\b", line)]
    assert echoes == [], f"the resolve step must write with printf, not echo: {echoes}"
    assert "printf '%s\\n' \"name=${CI_OVERLAY_REPO}\"" in run
    assert "printf '%s\\n' \"ref=${CI_OVERLAY_REF}\"" in run


@pytest.mark.parametrize("variable", ["CI_OVERLAY_REPO", "CI_OVERLAY_REF"])
def test_a_rejected_value_cannot_inject_a_workflow_command_into_the_log(
    workflow: dict[object, object], tmp_path: pathlib.Path, variable: str
) -> None:
    """A rejected value is never echoed back: a newline in it would start a line
    of its own in the job log, and a line beginning ``::`` is a workflow command."""
    hostile = "x\n::add-mask::injected\n::set-output name=ref::deadbeef"
    if variable == "CI_OVERLAY_REPO":
        rc, out, stdout = _run_resolve(workflow, hostile, tmp_path)
    else:
        rc, out, stdout = _run_resolve(
            workflow, "deploy-config", tmp_path, ref_var=hostile
        )
    assert rc == 1
    assert out == ""
    assert "injected" not in stdout
    assert "deadbeef" not in stdout
    # Positive control: the rejection itself is still reported, as an error line.
    assert any(line.startswith("::error::") for line in stdout.splitlines())


def test_the_fork_default_does_not_ask_for_a_pin(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    """The no-overlay reason takes precedence over a missing pin."""
    rc, out, stdout = _run_resolve(workflow, "", tmp_path, ref_var="")
    assert rc == 1
    assert "no review voters configured" in stdout
    assert "OMNI_CI_OVERLAY_REF" not in stdout
    assert out == ""


def test_an_unset_overlay_ref_fails_closed_naming_the_variable(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    """A configured overlay requires an explicit commit pin."""
    rc, out, stdout = _run_resolve(workflow, "deploy-config", tmp_path, ref_var="")
    assert rc == 1
    assert "OMNI_CI_OVERLAY_REF is unset" in stdout
    assert "name=" not in out
    assert "ref=" not in out


@pytest.mark.parametrize(
    "ref_var",
    [
        "main",
        "refs/heads/main",
        PINNED_REF[:8],
        PINNED_REF.upper(),
        PINNED_REF + "0",
        PINNED_REF[:-1] + "g",
        f"{PINNED_REF}\nmain",
        " " + PINNED_REF,
    ],
)
def test_an_overlay_ref_that_is_not_a_full_sha_fails_closed(
    workflow: dict[object, object], tmp_path: pathlib.Path, ref_var: str
) -> None:
    """Branches, tags, short shas and malformed pins are refused."""
    rc, out, stdout = _run_resolve(workflow, "deploy-config", tmp_path, ref_var=ref_var)
    assert rc == 1
    assert "must be a full 40-hex" in stdout
    assert "name=" not in out
    assert "ref=" not in out


def _run_place(
    workflow: dict[object, object],
    tmp_path: pathlib.Path,
    expected_ref: str | None,
) -> tuple[int, str, str]:
    """Run the placement script against a real local overlay commit."""
    workspace = tmp_path / "ws"
    checkout = workspace / ".ci-overlay-checkout"
    checkout.mkdir(parents=True)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(tmp_path),
        "GIT_AUTHOR_NAME": "Overlay test",
        "GIT_AUTHOR_EMAIL": "overlay@example.invalid",
        "GIT_COMMITTER_NAME": "Overlay test",
        "GIT_COMMITTER_EMAIL": "overlay@example.invalid",
    }
    subprocess.run(
        ["git", "init"],
        cwd=checkout,
        env=scrub_git_location_env(env),
        capture_output=True,
        check=True,
    )
    overlay_path = pathlib.Path(
        "config/onex/overlays/node_review_voters_overlay_compute/overlay.yaml"
    )
    overlay = checkout / overlay_path
    overlay.parent.mkdir(parents=True)
    overlay.write_text("schema: review_voters_overlay.v1\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", str(overlay_path)],
        cwd=checkout,
        env=scrub_git_location_env(env),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Add voters overlay"],
        cwd=checkout,
        env=scrub_git_location_env(env),
        capture_output=True,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=checkout,
        env=scrub_git_location_env(env),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    proc = subprocess.run(
        [
            "bash",
            "-c",
            str(
                _named_step(workflow, "Place the CI overlay outside the workspace")[
                    "run"
                ]
            ),
        ],
        cwd=workspace,
        env={
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OVERLAY_SOURCE": "OmniNode-ai/overlay",
            "EXPECTED_OVERLAY_REF": sha if expected_ref is None else expected_ref,
            "REVIEW_VOTERS_OVERLAY": str(
                workspace / ".." / "ci-overlay" / overlay_path
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, sha


def test_the_overlay_is_read_only_at_the_pinned_commit(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    """The fetched HEAD must match the pin before voters can be read."""
    rc, stdout, sha = _run_place(workflow, tmp_path / "matching", expected_ref=None)
    assert rc == 0
    assert sha in stdout
    rc, stdout, _ = _run_place(
        workflow, tmp_path / "mismatching", expected_ref="0" * 40
    )
    assert rc == 1
    assert "not the pinned OMNI_CI_OVERLAY_REF" in stdout


def test_the_place_step_has_no_expression_interpolation(
    workflow: dict[object, object],
) -> None:
    """The placement script runs as plain bash with environment inputs."""
    step = _named_step(workflow, "Place the CI overlay outside the workspace")
    assert "${{" not in str(step["run"])


def test_dependency_clones_are_pinned_and_review_install_excludes_rl(
    workflow: dict[object, object],
) -> None:
    """Reviewer support repos are read at the uv.lock pin and avoid the RL install path."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)

    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps
    # The voters overlay is fetched from the private CI overlay (OMN-20923) by
    # an actions/checkout step, not a run block; it is data, not a sibling.
    run_blocks = [
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    combined = "\n".join(run_blocks)

    for repo in ("omniintelligence", "omnibase_core", "omnibase_compat"):
        repo_url = f"https://github.com/OmniNode-ai/{repo}.git"
        assert repo_url in combined, f"{repo} clone must be present"
    # A sibling is read at the pin this repo's uv.lock records, never a live branch
    # (ruling 2026-10-01): omniintelligence by rev, core and compat by release tag.
    assert "--branch dev" not in combined, "dependency clones must not track dev"
    assert "--branch main" not in combined, "dependency clones must not track main"
    assert "omniintelligence\\.git\\?rev=" in combined, (
        "omniintelligence must be fetched at the rev uv.lock pins"
    )
    for pinned in ("omnibase-core", "omnibase-compat"):
        assert f"n={pinned}" in combined, f"{pinned} version must be read from uv.lock"
    assert combined.count('--branch "v${pin_version}"') == 2, (
        "omnibase_core and omnibase_compat must be cloned at v<uv.lock version>"
    )

    assert "uv sync --locked --all-extras --python 3.12" in combined, (
        "reviewer dependency install must use the locked review path"
    )
    assert "uv sync --all-extras" not in combined, (
        "bare all-extras install can pull stale main/lock behavior and CUDA wheels"
    )
    assert "--group rl" not in combined, (
        "hostile reviewer must not install the opt-in RL/Torch dependency group"
    )


def _review_step_run_text(workflow: dict[object, object]) -> str:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    steps = review_job.get("steps") or []
    review_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("id") == "review"
        ),
        None,
    )
    assert isinstance(review_step, dict), "review step must exist"
    run_text = review_step.get("run")
    assert isinstance(run_text, str)
    return run_text


def test_review_exit_captured_from_command_not_if_statement(
    workflow: dict[object, object],
) -> None:
    """OMN-18409: ``REVIEW_EXIT=$?`` must capture the real exit status of the
    ``cli_review`` invocation, never the exit status of the enclosing
    ``if``/``fi`` block.

    In bash, ``if COND; then BODY; fi`` with no matching branch and no
    ``else`` clause itself returns exit status 0 — so reading ``$?``
    immediately after a bare ``fi`` captures the if-statement's own status,
    not the failed command's. That silently zeroed out ``REVIEW_EXIT`` on
    every ``cli_review`` failure, so the ``if [ "$REVIEW_EXIT" -ne 0 ]``
    infra_error fail-closed path never fired and the script fell through to
    parse an empty ``$REVIEW_JSON`` as JSON.

    Observed on omniclaude#2180 (run 35017674790): two retry attempts both
    logged "(exit 0)" despite genuinely failing, followed by
    ``json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)``.
    """
    run_text = _review_step_run_text(workflow)

    lines = [line.strip() for line in run_text.splitlines()]
    for index, line in enumerate(lines):
        if line == "fi" and index + 1 < len(lines):
            assert lines[index + 1] != "REVIEW_EXIT=$?", (
                "REVIEW_EXIT=$? must not be read immediately after a bare "
                "`fi` with no `else` -- that captures the if-statement's own "
                "exit status (always 0 in that shape), not the real exit "
                "code of the cli_review command substitution (OMN-18409)"
            )

    assert "REVIEW_EXIT=$?" in run_text, (
        "the retry loop must still capture a real exit code from the "
        "cli_review invocation"
    )


def test_degraded_quorum_exit_code_fails_the_gate_closed(
    workflow: dict[object, object],
) -> None:
    """OMN-18479: exit 2 is DEGRADED QUORUM and is not a verdict.

    cli_review's exit contract is 0 when a verdict was produced, 2 when
    fewer models succeeded than cross-model agreement requires, and 1 when
    every model failed. The earlier revision of this workflow accepted exit
    2 as "a real, valid verdict" from a single model -- which is exactly
    what let one model's rotating finding block a merge, measured at 24
    blocked runs out of 40 on this repository.

    The retry loop must therefore break only on exit 0, and a persistent
    exit 2 must fail the gate closed under its own name rather than being
    accepted or folded into infra_error. This step consequently requires at
    least two ``--model`` flags (OMN-18473) for any run to pass.
    """
    run_text = _review_step_run_text(workflow)

    assert '[ "$REVIEW_EXIT" -eq 0 ] || [ "$REVIEW_EXIT" -eq 2 ]' not in run_text, (
        "the retry loop must NOT break on exit 2 -- a degraded quorum is the "
        "absence of a verdict, not a valid one (OMN-18479)"
    )
    assert 'if [ "$REVIEW_EXIT" -eq 2 ]; then' in run_text, (
        "a persistent exit 2 must be classified as degraded_quorum under its "
        "own name, not folded into infra_error"
    )
    assert 'echo "verdict=degraded_quorum"' in run_text
    assert '[ "$VERDICT" = "degraded_quorum" ]' in run_text, (
        "degraded_quorum must fail the step closed alongside blocked -- the "
        "absence of a verdict is not a passing one"
    )


def test_verdict_parser_blocks_only_on_cross_model_agreement(
    workflow: dict[object, object],
) -> None:
    """OMN-18479: the blocking count comes from the reviewer's quorum.

    The parser used to sum critical/error findings across every succeeded
    model, so any single model's finding produced ``verdict=blocked``. The
    reviewer now resolves agreement itself; this workflow reads the result
    and must not re-derive one, because a second aggregation rule in a
    caller is how the fleet ended up with four different ones.
    """
    run_text = _review_step_run_text(workflow)

    assert 'quorum.get("blocking_count", 0)' in run_text, (
        "blocking_count must come from the reviewer's quorum block"
    )
    assert 'for f in r.get("findings", []):' not in run_text, (
        "the per-model severity sum must be gone -- it is the rule that let "
        "one model block a merge (OMN-18479)"
    )
    assert 'quorum_verdict == "blocked"' in run_text
    assert 'quorum_verdict in ("degraded_quorum", "no_models")' in run_text


def test_verdict_parser_treats_empty_diff_as_a_real_passed_verdict(
    workflow: dict[object, object],
) -> None:
    """OMN-18409: cli_review reports ``skipped_reason=="empty_diff"`` for a
    PR with no diff (e.g. a merge/ancestry commit whose tree matches the base
    branch). The workflow's verdict parser must treat that as a real,
    non-blocking ``passed`` verdict -- not fall through to ``degraded``,
    whose PR-comment framing ("all reviewer models failed or were
    unavailable") misdescribes a diff that was never sent to any model.
    """
    run_text = _review_step_run_text(workflow)

    assert 'data.get("skipped_reason")' in run_text, (
        "verdict parser must read the skipped_reason field cli_review emits "
        "for an empty-diff PR"
    )
    assert 'skipped_reason == "empty_diff"' in run_text
    assert 'verdict = "passed"' in run_text


def test_dependency_install_failure_fails_closed(
    workflow: dict[object, object],
) -> None:
    """OMN-16000: dependency install / CLI-crash failures must fail the REQUIRED
    'Hostile Review Gate' closed, not manufacture a self-reported degraded/exit-0
    verdict.

    Prior contract (now retired — see git history for the pinned-bug version):
    the install step carried `continue-on-error: true` and the review step
    branched on `$INSTALL_DEPS_OUTCOME` to emit `verdict=degraded` + `exit 0`
    on install failure. That let the required context go green with zero
    adversarial review having actually run. Fixed 2026-08-13: no
    continue-on-error (a real install failure now fails the step, and the
    step's own default `if:` skips the rest of the job); a CLI crash retries
    once then reports `verdict=infra_error` and exits 1.
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)

    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps, "review job must have steps"

    install_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict)
            and step.get("name") == "Install omniintelligence dependencies"
        ),
        None,
    )
    assert isinstance(install_step, dict), "dependency install step must exist"
    assert "continue-on-error" not in install_step, (
        "dependency install failures must fail this REQUIRED job closed, not "
        "be swallowed into a manufactured degraded/exit-0 verdict (OMN-16000)"
    )

    review_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict) and step.get("id") == "review"
        ),
        None,
    )
    assert isinstance(review_step, dict), "review step must exist"
    env = review_step.get("env") or {}
    assert "INSTALL_DEPS_OUTCOME" not in env, (
        "review step must no longer branch on a manually-read install outcome "
        "-- an install failure now fails the step itself (no continue-on-error)"
    )

    run_text = review_step.get("run")
    assert isinstance(run_text, str)
    assert 'if [ "$INSTALL_DEPS_OUTCOME" != "success" ]; then' not in run_text
    assert "verdict=infra_error" in run_text
    assert "cli_review failed after 2 attempts" in run_text
    # A crash must fail the step (exit 1), not report success.
    assert "exit 1" in run_text
    # The retired fail-open verdict string must not reappear.
    assert "omniintelligence dependency install failed" not in run_text


def test_summary_comment_step_present(workflow: dict[object, object]) -> None:
    """A step must post a summary PR comment via actions/github-script."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)
    steps = review_job.get("steps") or []

    script_step = next(
        (
            step
            for step in steps
            if isinstance(step, dict)
            and isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/github-script@")
        ),
        None,
    )
    assert script_step is not None, (
        "must include an actions/github-script step that posts the verdict comment"
    )
    # Comment posting must run regardless of review outcome so degraded /
    # blocked verdicts still surface to the PR author.
    script_if = script_step.get("if")
    assert isinstance(script_if, str), "summary comment step must declare if"
    assert script_if.startswith("always()"), (
        "summary comment step must run with if: always()"
    )
    assert (
        "github.event.pull_request.head.repo.full_name == github.repository"
        in script_if
    ), "summary comment step must avoid write attempts for forked PRs"


def test_gate_job_depends_on_review_and_fails_on_failure(
    workflow: dict[object, object],
) -> None:
    """The ``hostile-review-gate`` job must be the merge-blocking aggregator.

    It must:
    - declare ``needs: [hostile-review]``
    - run with ``if: always()`` so it surfaces verdict even on review crash
    - exit non-zero when ``needs.hostile-review.result == 'failure'``
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    gate_job = jobs.get("hostile-review-gate")
    assert isinstance(gate_job, dict), "hostile-review-gate job must exist"

    needs = gate_job.get("needs")
    needs_list = [needs] if isinstance(needs, str) else list(needs or [])
    assert "hostile-review" in needs_list, "gate must depend on the hostile-review job"

    assert gate_job.get("if") == "always()", (
        "gate job must use if: always() so degraded review still produces a verdict"
    )

    steps = gate_job.get("steps") or []
    run_text = "\n".join(
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and step.get("run")
    )
    assert "needs.hostile-review.result" in run_text, (
        "gate must read needs.hostile-review.result"
    )
    assert "exit 1" in run_text, (
        "gate must exit non-zero when the review reports failure"
    )


def test_no_anthropic_api_key_required(workflow: dict[object, object]) -> None:
    """ANTHROPIC_API_KEY must NOT appear in any env block (OMN-7467 guard).

    Claude Code authenticates via OAuth; requiring ANTHROPIC_API_KEY in CI
    has regressed 6+ times across the org and is an explicit anti-pattern in
    ``~/.claude/CLAUDE.md``.
    """
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Match the env-var name as a required key, not as a sanitizer regex or
    # commented documentation. The simplest robust check is "no occurrence
    # at all" in this file — there is no legitimate reason to mention the
    # variable in this workflow.
    assert "ANTHROPIC_API_KEY" not in raw, (
        "ANTHROPIC_API_KEY must not be referenced in the hostile-reviewer "
        "workflow — Claude Code uses OAuth (OMN-7467)"
    )


def test_workflow_has_pr_write_permission(workflow: dict[object, object]) -> None:
    """The workflow must grant ``pull-requests: write`` so it can post comments."""
    permissions = workflow.get("permissions")
    assert isinstance(permissions, dict), "workflow must declare permissions"
    assert permissions.get("pull-requests") == "write", (
        "workflow must request pull-requests: write to post the verdict comment"
    )
    assert permissions.get("contents") == "read", (
        "workflow should request only contents: read (least privilege)"
    )


def _extract_verdict_snippet(workflow: dict[object, object]) -> str:
    """Return the review step's inline verdict parser, ready to execute."""
    run_text = _review_step_run_text(workflow)
    start = run_text.index(
        'VERDICT_DATA=$(REVIEW_JSON_FILE="$REVIEW_JSON_FILE" python3 - '
    )
    return run_text[run_text.index("\n", start) + 1 : run_text.index("PYEOF\n", start)]


def _run_verdict_snippet(
    workflow: dict[object, object], payload: dict[str, object]
) -> dict[str, str]:
    import json
    import subprocess
    import sys
    import tempfile

    with tempfile.TemporaryDirectory() as scratch:
        review_json = pathlib.Path(scratch) / "hostile-review-result.json"
        review_json.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-c", _extract_verdict_snippet(workflow)],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            env={"REVIEW_JSON_FILE": str(review_json), "PATH": "/usr/bin:/bin"},
        )
    return dict(
        line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line
    )


def test_verdict_parser_behaviour_on_quorum_payloads(
    workflow: dict[object, object],
) -> None:
    """OMN-18479: run the parser, do not grep it.

    A text assertion that the word ``quorum`` appears passes on a comment
    mentioning it. These fixtures exercise the four cases that matter, and
    each zero has its positive control beside it.
    """
    two_models = ["example-voter-a", "example-voter-b"]

    # One model raised a finding, the other did not: reported, not blocking.
    below = _run_verdict_snippet(
        workflow,
        {
            "models_succeeded": two_models,
            "total_findings": 1,
            "results": [],
            "quorum": {"verdict": "passed", "blocking_count": 0, "warning_count": 1},
        },
    )
    assert below["verdict"] == "passed"
    assert below["blocking_count"] == "0"
    assert below["below_quorum_count"] == "1"

    # Positive control: both models raised it, so it blocks.
    agreed = _run_verdict_snippet(
        workflow,
        {
            "models_succeeded": two_models,
            "total_findings": 2,
            "results": [],
            "quorum": {"verdict": "blocked", "blocking_count": 1, "warning_count": 0},
        },
    )
    assert agreed["verdict"] == "blocked"
    assert agreed["blocking_count"] == "1"

    # Too few models succeeded to establish agreement: no verdict.
    degraded = _run_verdict_snippet(
        workflow,
        {
            "models_succeeded": ["example-voter-a"],
            "total_findings": 1,
            "results": [],
            "quorum": {
                "verdict": "degraded_quorum",
                "blocking_count": 0,
                "warning_count": 1,
            },
        },
    )
    assert degraded["verdict"] == "degraded_quorum"

    # A reviewer with no quorum block cannot be read by this gate at all,
    # and must fail closed rather than have a verdict invented for it.
    absent = _run_verdict_snippet(
        workflow,
        {"models_succeeded": two_models, "total_findings": 0, "results": []},
    )
    assert absent["verdict"] == "degraded_quorum"
    assert absent["quorum_verdict"] == "absent"


def test_verdict_artifact_preserves_voter_attribution(
    workflow: dict[object, object], tmp_path: pathlib.Path
) -> None:
    """OMN-18473 AC3: pin the artifact attribution half.

    OMN-18479's quorum rule superseded the original AC3 wording (flat sum,
    no dedup): two attributed findings can represent one blocking finding.
    """
    import json
    import sys

    run_text = _review_step_run_text(workflow)
    start = run_text.index("import json\nimport os\n\nfields = {}")
    snippet = run_text[start : run_text.index("\nPY\n", start)]
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("", encoding="utf-8")
    artifact_path = tmp_path / "hostile-review-verdict.json"
    review_json = tmp_path / "hostile-review-result.json"
    two_models = ["example-voter-a", "example-voter-b"]
    finding = {
        "severity": "error",
        "rule_id": "example-rule",
        "normalized_message": "Shared finding",
        "file_path": "example.py",
        "line_start": 12,
    }

    for second_succeeded in (True, False):
        models_succeeded = two_models if second_succeeded else two_models[:1]
        verdict = "blocked" if second_succeeded else "degraded_quorum"
        blocking_count = 1 if second_succeeded else 0
        payload = {
            "results": [
                {"model": two_models[0], "success": True, "findings": [finding]},
                {
                    "model": two_models[1],
                    "success": second_succeeded,
                    "findings": [finding],
                },
            ],
            "quorum": {
                "verdict": verdict,
                "blocking_count": blocking_count,
                "warning_count": 0 if second_succeeded else 1,
            },
        }
        review_json.write_text(json.dumps(payload), encoding="utf-8")
        subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
            env={
                "PATH": "/usr/bin:/bin",
                "VERDICT_DATA": (
                    f"verdict={verdict}\n"
                    f"blocking_count={blocking_count}\n"
                    f"below_quorum_count={0 if second_succeeded else 1}\n"
                    f"total_findings={len(models_succeeded)}\n"
                    f"models_succeeded={','.join(models_succeeded)}\n"
                ),
                "STDERR_LOG": str(stderr_log),
                "REVIEW_EXIT": "0",
                "REVIEW_JSON_FILE": str(review_json),
                "VERDICT_ARTIFACT": str(artifact_path),
                "NAMED_CAUSE": "",
            },
        )
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["models_succeeded"] == models_succeeded
        assert artifact["review_exit"] == 0
        if second_succeeded:
            assert {f["model"] for f in artifact["findings"]} == set(two_models)
            assert len(artifact["findings"]) == 2
            assert artifact["blocking_count"] == 1
        else:
            # Positive control: a failed voter's finding must be excluded.
            assert [f["model"] for f in artifact["findings"]] == [two_models[0]]


# --- OMN-20910 widening: the voter's MODEL is a field of the overlay ----------
# These cases drive the same ``voter_endpoint_findings`` entry point as the
# ratchet above, so a pattern missing from it fails them.
_KNOWN_BAD_MODEL = """\
      REVIEW_MODEL: ${{ vars.REVIEW_MODEL }}
          VOTER_B_MODEL_NAME: ${{ vars.VOTER_B_MODEL_NAME }}
      REVIEW_VOTER_MODEL: claude-opus-5-5
          MODEL: qwen3-coder-30b
            run: ./vote --engine gpt-4o
"""
_KNOWN_BAD_ENV_WORKFLOW = """\
jobs:
  hostile-review:
    env:
      REVIEW_VOTER_MODEL: my-voter-model
    steps:
      - name: Run adversarial review
        env:
          MODEL: voter-b
          REVIEW_MODELS: ${{ steps.review.outputs.models_succeeded }}
"""


def test_voter_model_from_overlay_ratchet_finds_every_known_bad_line() -> None:
    """Positive control: a zero on the real workflows is only evidence if this finds five."""
    assert len(voter_endpoint_findings(_KNOWN_BAD_MODEL)) == 5
    # One control per pattern: a count alone survives a broken pattern whenever
    # another pattern matches the same line.
    lines = _KNOWN_BAD_MODEL.splitlines()
    assert _VOTER_MODEL_PATTERNS
    for pattern in _VOTER_MODEL_PATTERNS:
        assert any(pattern.search(line) for line in lines), pattern.pattern


@pytest.mark.parametrize(
    "line",
    [
        "          REVIEW_MODEL: ${{ vars.REVIEW_MODEL }}",
        "          X: ${{ vars.VOTER_B_MODEL_NAME }}",
        "          X: ${{ vars.model }}",
        "          X: ${{ vars.LLM_MODEL_ID }}",
        "          VOTER: claude-sonnet-5-5",
        "          VOTER: Qwen3.8-27B",
        "          VOTER: glm-5.3",
        "          VOTER: gpt-4o",
    ],
)
def test_voter_model_from_overlay_ratchet_refuses_each_shape(line: str) -> None:
    assert voter_endpoint_findings(line + "\n"), line


def test_voter_model_from_overlay_ratchet_ignores_comments_and_overlay_reads() -> None:
    clean = (
        "      # a voter's model lives in the overlay, e.g. vars.X_MODEL is retired\n"
        '          --voters-overlay "$REVIEW_VOTERS_OVERLAY" \\\n'
        "          REVIEW_MODELS: ${{ steps.review.outputs.models_succeeded }}\n"
    )
    assert voter_endpoint_findings(clean) == []


def test_voter_model_from_overlay_env_literal_has_a_positive_control() -> None:
    """A bare id no pattern knows is refused by its ``env:`` key; an expression is not."""
    findings = voter_endpoint_findings(_KNOWN_BAD_ENV_WORKFLOW)
    assert len(findings) == 2, findings
    assert any("REVIEW_VOTER_MODEL=my-voter-model" in f for f in findings)
    assert any("MODEL=voter-b" in f for f in findings)
    assert not any("REVIEW_MODELS" in f for f in findings)


def test_voter_model_from_overlay_workflow_names_no_model() -> None:
    findings = voter_endpoint_findings(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert findings == [], (
        "hostile-reviewer.yml names a review voter model, endpoint or port; a "
        f"voter's model is declared only in the overlay (OMN-20910): {findings}"
    )


_THIS_TEST = "tests/hooks/test_hostile_reviewer_workflow.py"


def test_voter_model_from_overlay_ratchet_is_wired_as_ci_step_and_hook() -> None:
    """The ratchet runs in a job the required ``CI Summary`` context covers, and in pre-commit."""
    ci = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    ci_steps = ci["jobs"]["refusal-surface"]["steps"]
    assert any(_THIS_TEST in str(step.get("run", "")) for step in ci_steps)
    # CI Summary polls every ci.yml job's conclusion, the refusal-surface job included.
    required = yaml.safe_load(
        (REPO_ROOT / ".github" / "required-checks.yaml").read_text(encoding="utf-8")
    )
    assert any(
        gate["name"] == "CI Summary"
        and gate["mode"] == "REQUIRED"
        and gate["workflow"] == "ci.yml"
        for gate in required["gates"]
    )
    hooks = [
        hook
        for repo in yaml.safe_load(
            (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        )["repos"]
        for hook in repo["hooks"]
    ]
    assert any(_THIS_TEST in str(hook.get("entry", "")) for hook in hooks)
