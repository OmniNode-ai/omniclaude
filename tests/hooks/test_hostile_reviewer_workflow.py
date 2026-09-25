# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Structural tests for the Hostile Reviewer CI workflow — OMN-8603.

Asserts that ``.github/workflows/hostile-reviewer.yml`` is wired correctly:

- Triggers on the expected ``pull_request`` event types.
- Runs on the ``omnibase-ci`` self-hosted runner that exposes the local
  DeepSeek-R1 endpoint.
- Invokes ``omniintelligence.review_pairing.cli_review`` with at least TWO
  ``--model`` flags, naming both fleet-standard keys (OMN-18473).
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

import pytest
import yaml

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

    The DeepSeek-R1 endpoint at .201:8001 is LAN-only — GitHub-hosted
    runners cannot reach it. This is the fundamental constraint that drove
    OMN-8603 (runner toolchain) and pins the gate to .201.
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
            "runner label must include 'omnibase-ci' so the .201 LAN endpoints "
            "(LLM_DEEPSEEK_URL) are reachable"
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
        "labels so the LAN-only DeepSeek endpoint is reachable, through the "
        "dedicated OMNI_HOSTILE_REVIEW_RUNS_ON_JSON knob"
    )


def test_same_repo_dev_prs_do_not_use_public_runner_branch(
    workflow: dict[object, object],
) -> None:
    """Same-repo dev PRs need the LAN-only DeepSeek endpoint on the trusted runner.

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


def test_review_step_invokes_cli_review_with_model(
    workflow: dict[object, object],
) -> None:
    """A step must invoke ``cli_review`` with AT LEAST TWO ``--model`` flags.

    OMN-18473 pins the model COUNT, and both keys by name, mirroring
    ``omnibase_infra`` ``tests/ci/test_hostile_reviewer_ci_gate.py``
    (``test_hostile_review_job_uses_live_local_models``), which asserts its own
    two keys the same way.

    Why the count is load-bearing rather than a style preference: cli_review
    returns 0 only when >= 2 models succeed and 2 ("DEGRADED -- a minimum of 2
    models is required for a full pass") when exactly one does. From 2026-04-11
    (71d816a99) to 2026-09-16 this workflow passed exactly one ``--model``, so
    exit 0 was unreachable and every verdict it produced was DEGRADED by
    construction. Nothing caught that, because the assertion this replaces
    accepted "at least one ``--model``".

    Both keys are named because the pair is a deliberate choice, not an
    arbitrary one. ``deepseek-r1`` and ``qwen3-review`` are two registry keys
    for ONE backend (same endpoint, same ``api_model_id``, OMN-16481), so
    pairing THOSE two would satisfy a naive count while passing one backend
    twice under two spellings -- exactly the defect a count-only assertion
    cannot see.
    """
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)

    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps, "review job must have steps"

    run_blocks = [
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and step.get("run")
    ]
    combined = "\n".join(run_blocks)

    assert "omniintelligence.review_pairing.cli_review" in combined, (
        "review job must invoke omniintelligence.review_pairing.cli_review"
    )
    model_flag_count = combined.count("--model ")
    assert model_flag_count >= 2, (
        "review job must pass at least TWO --model flags to cli_review "
        f"(found {model_flag_count}) -- cli_review returns 0 only when >= 2 "
        "models succeed, so a single-model invocation is DEGRADED by "
        "construction on every run (OMN-18473)"
    )
    # Only real flags: a key followed by a line continuation, never the word
    # after "--model" in a comment inside the run block.
    models = re.findall(r"--model\s+([A-Za-z0-9_.-]+)\s*\\\n", combined)
    assert models == ["qwen3-review", "gpt-oss-review"], (
        "review job must pass exactly the two DIFFERENT lab models, "
        f"qwen3-review and gpt-oss-review, each on its own lab host; found {models}. "
        "deepseek-r1, qwen3-review and qwen3-review-b were three keys for one "
        "backend (OMN-16481), so the old pair reviewed with a single model "
        "twice, and a cloud reviewer would send a private diff off the lab "
        "(OMN-17492)"
    )
    for not_a_voter in ("deepseek-r1", "qwen3-review-b", "glm-review"):
        assert not_a_voter not in models
    assert "--pr" in combined and "--repo" in combined, (
        "review job must pass --pr and --repo to cli_review"
    )
    assert "REVIEW_JSON=\"$REVIEW_JSON\" python3 - <<'PYEOF'" in combined, (
        "review JSON must be passed through the environment because the "
        "heredoc occupies Python stdin"
    )
    assert "echo \"$REVIEW_JSON\" | python3 - <<'PYEOF'" not in combined, (
        "do not pipe review JSON into python3 - with a heredoc; Python reads "
        "the script from stdin and the JSON payload is lost"
    )


def test_dependency_clones_track_dev_and_review_install_excludes_rl(
    workflow: dict[object, object],
) -> None:
    """Reviewer support repos must track dev and avoid the Torch/RL install path."""
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    review_job = jobs["hostile-review"]
    assert isinstance(review_job, dict)

    steps = review_job.get("steps") or []
    assert isinstance(steps, list) and steps
    run_blocks = [
        step.get("run", "")
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    combined = "\n".join(run_blocks)

    for repo in ("omniintelligence", "omnibase_core", "omnibase_compat"):
        repo_url = f"https://github.com/OmniNode-ai/{repo}.git"
        assert repo_url in combined, f"{repo} clone must be present"
        assert "--branch dev" in combined, "dependency clones must track dev"
        assert "--branch main" not in combined, f"{repo} clone must not track main"

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
    start = run_text.index('VERDICT_DATA=$(REVIEW_JSON="$REVIEW_JSON" python3 - ')
    return run_text[run_text.index("\n", start) + 1 : run_text.index("PYEOF\n", start)]


def _run_verdict_snippet(
    workflow: dict[object, object], payload: dict[str, object]
) -> dict[str, str]:
    import json
    import subprocess
    import sys

    completed = subprocess.run(
        [sys.executable, "-c", _extract_verdict_snippet(workflow)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
        env={"REVIEW_JSON": json.dumps(payload), "PATH": "/usr/bin:/bin"},
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
    two_models = ["qwen3-review", "gpt-oss-review"]

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
            "models_succeeded": ["qwen3-review"],
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
