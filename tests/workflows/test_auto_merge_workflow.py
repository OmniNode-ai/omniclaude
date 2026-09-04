# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for .github/workflows/auto-merge.yml (OMN-9353, OMN-17875).

The workflow contains a Bash branch in the ``Resolve PR and author`` step that
must:

* set ``skip=true`` when the PR base ref does not match the repo default branch
  (stacked-PR no-op — GitHub cannot enable auto-merge on non-default bases),
* set ``skip=false`` when the PR targets the default branch.

These tests extract the actual Bash from the workflow YAML, stub the ``gh`` CLI
on PATH, run the script under a fixed event payload, and assert the
``GITHUB_OUTPUT`` contents. Pulling the snippet straight from the YAML keeps
the test bound to the deployed logic.

:class:`TestAutoMergeArmingTokenOmn17875` additionally pins the *credential*
each step authenticates with — see that class's docstring for the measurement
that made it necessary.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "auto-merge.yml"


def _extract_step_script(step_name_marker: str) -> str:
    """Pull the inline Bash ``run:`` body from a named workflow step.

    Failing to extract a valid script is itself a test failure -- it means the
    YAML structure drifted and the test is no longer bound to the workflow.
    """
    text = WORKFLOW_PATH.read_text()
    lines = text.splitlines(keepends=True)
    # Locate the start of the named step's run block.
    in_step = False
    in_run = False
    body_lines: list[str] = []
    for line in lines:
        if not in_step:
            if step_name_marker in line:
                in_step = True
            continue
        if not in_run:
            if line.strip() == "run: |":
                in_run = True
            continue
        # We are inside the run block. The body is indented to 10 spaces.
        # The block ends at the first line that is a non-blank, less-indented
        # line (i.e. the next YAML sibling).
        if line.strip() == "":
            body_lines.append(line)
            continue
        if line.startswith("          "):  # 10 spaces
            body_lines.append(line)
            continue
        break
    assert body_lines, (
        f"Could not extract '{step_name_marker}' step script from "
        "auto-merge.yml; workflow YAML structure changed. Test must be "
        "updated to match."
    )
    # Strip the 10-space YAML indent so Bash sees a normal script.
    return dedent("".join(body_lines))


def _extract_resolve_step_script() -> str:
    """Pull the inline Bash from the ``Resolve PR and author`` step."""
    return _extract_step_script("- name: Resolve PR and author")


def _extract_enable_auto_merge_step_script() -> str:
    """Pull the inline Bash from the ``Enable auto-merge`` step."""
    return _extract_step_script("- name: Enable auto-merge")


@pytest.fixture
def gh_stub_dir(tmp_path: Path) -> Path:
    """Create a directory holding a stubbed ``gh`` CLI on PATH.

    The stub honours two query shapes used by the workflow:

    * ``gh pr view <PR> --repo <repo> --json baseRefName --jq .baseRefName``
    * ``gh repo view <repo> --json defaultBranchRef --jq .defaultBranchRef.name``

    Return values are sourced from environment variables ``STUB_BASE_REF`` and
    ``STUB_DEFAULT_BRANCH`` so each test can vary them independently.
    """
    stub = tmp_path / "gh"
    stub.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            args="$*"
            case "$args" in
              *"--json baseRefName"*)
                echo "${STUB_BASE_REF:-main}"
                ;;
              *"--json defaultBranchRef"*)
                echo "${STUB_DEFAULT_BRANCH:-main}"
                ;;
              *)
                echo "unexpected gh invocation: $args" >&2
                exit 99
                ;;
            esac
            """
        )
    )
    stub.chmod(0o755)
    return tmp_path


def _run_resolve(
    *,
    gh_stub_dir: Path,
    event_name: str,
    pr_payload: str,
    pr_author: str,
    base_ref: str,
    default_branch: str,
) -> dict[str, str]:
    """Run the extracted Bash and return the parsed GITHUB_OUTPUT mapping."""
    script = _extract_resolve_step_script()
    output_file = gh_stub_dir / "github_output"
    output_file.touch()
    env = {
        # Force PATH to contain only our stub + system essentials so the
        # script cannot accidentally hit the real `gh` binary.
        "PATH": f"{gh_stub_dir}:/usr/bin:/bin",
        "GH_TOKEN": "stub-token",
        "GH_REPO": "OmniNode-ai/omniclaude",
        "EVENT_NAME": event_name,
        "PR_FROM_PAYLOAD": pr_payload,
        "PR_FROM_DISPATCH": "",
        "CHECK_SUITE_PRS": "[]",
        "PR_AUTHOR_FROM_PAYLOAD": pr_author,
        "GITHUB_OUTPUT": str(output_file),
        "STUB_BASE_REF": base_ref,
        "STUB_DEFAULT_BRANCH": default_branch,
    }
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, (
        f"resolve script exited {result.returncode}\n"
        f"stdout: {result.stdout}\n"
        f"stderr: {result.stderr}"
    )
    parsed: dict[str, str] = {}
    for line in output_file.read_text().splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            parsed[key] = value
    return parsed


@pytest.mark.unit
class TestAutoMergeStackedPrDetection:
    """Verify the stacked-PR no-op carried over from omnibase_infra."""

    def test_stacked_pr_sets_skip_true(self, gh_stub_dir: Path) -> None:
        """A PR whose base ref differs from the default branch is a stacked
        PR. The workflow must short-circuit with ``skip=true`` so the
        required Enable Auto-Merge check passes without calling
        ``enablePullRequestAutoMerge`` (which GitHub rejects on
        non-default bases)."""
        outputs = _run_resolve(
            gh_stub_dir=gh_stub_dir,
            event_name="pull_request",
            pr_payload="42",
            pr_author="jonahgabriel",
            base_ref="feature/parent-branch",
            default_branch="main",
        )
        assert outputs.get("skip") == "true"
        assert outputs.get("pr") == "42"
        assert outputs.get("actor") == "jonahgabriel"

    def test_default_branch_pr_sets_skip_false(self, gh_stub_dir: Path) -> None:
        """A PR targeting the default branch must proceed to enrollment."""
        outputs = _run_resolve(
            gh_stub_dir=gh_stub_dir,
            event_name="pull_request",
            pr_payload="100",
            pr_author="jonahgabriel",
            base_ref="main",
            default_branch="main",
        )
        assert outputs.get("skip") == "false"
        assert outputs.get("pr") == "100"
        assert outputs.get("actor") == "jonahgabriel"

    def test_stacked_pr_short_circuit_for_non_jonah_actor(
        self, gh_stub_dir: Path
    ) -> None:
        """The stacked-PR check runs before the actor gate. Non-jonahgabriel
        PRs that happen to be stacked should still receive ``skip=true``;
        the downstream merge step is additionally gated on the actor."""
        outputs = _run_resolve(
            gh_stub_dir=gh_stub_dir,
            event_name="pull_request",
            pr_payload="7",
            pr_author="dependabot[bot]",
            base_ref="release/v2",
            default_branch="main",
        )
        assert outputs.get("skip") == "true"
        assert outputs.get("actor") == "dependabot[bot]"


@pytest.mark.unit
class TestAutoMergeWorkflowYaml:
    """YAML-level invariants that protect queue enrollment behavior and the
    stacked-PR detection block from regressions (OMN-9353, OMN-16501)."""

    def test_merge_command_tries_bare_auto_first(self) -> None:
        """OMN-13214: queue-controlled branches reject an explicit merge
        method, so the workflow's first attempt must still arm auto-merge
        without ``--squash`` before falling back (queue picks the method,
        then calls enqueuePullRequest explicitly)."""
        text = WORKFLOW_PATH.read_text()
        assert 'gh pr merge "$PR" --repo "$GH_REPO" --auto 2>&1' in text, (
            "auto-merge.yml must still try bare --auto first (queue-controlled path)"
        )

    def test_merge_command_has_squash_fallback_for_no_queue(self) -> None:
        """OMN-16501: two-strike defect (omniclaude#2029, #2030) — gh's CLI
        refuses a method-less --auto non-interactively when no merge queue is
        active, even on a squash-only repo. The workflow must retry with
        --squash gated on that specific gh-CLI-side error string, so a
        genuine queue-controlled rejection ("merge strategy ... set by the
        merge queue") is never retried with an explicit method."""
        text = WORKFLOW_PATH.read_text()
        assert 'gh pr merge "$PR" --repo "$GH_REPO" --auto --squash 2>&1' in text, (
            "auto-merge.yml must retry with --squash when no merge queue is active"
        )
        assert "required when not running interactively" in text, (
            "the --squash retry must be gated on gh's specific "
            "non-interactive-method error, not a blanket catch-all"
        )

    def test_resolve_step_compares_base_to_default_branch(self) -> None:
        """Stacked-PR detection must fetch ``baseRefName`` and
        ``defaultBranchRef.name`` and compare them, otherwise stacked
        PRs will fail the required Enable Auto-Merge check."""
        text = WORKFLOW_PATH.read_text()
        assert "--json baseRefName" in text
        assert "--json defaultBranchRef" in text
        assert 'if [ "$BASE_REF" != "$DEFAULT_BRANCH" ]' in text


@pytest.fixture
def gh_merge_stub_dir(tmp_path: Path) -> Path:
    """Stub ``gh`` CLI for the ``Enable auto-merge`` step's two possible
    ``gh pr merge`` invocations (bare ``--auto`` and the ``--auto --squash``
    fallback), each independently scripted to succeed or fail via env vars.
    """
    stub = tmp_path / "gh"
    stub.write_text(
        dedent(
            """\
            #!/usr/bin/env bash
            set -euo pipefail
            args="$*"
            case "$args" in
              *"--auto --squash"*)
                if [ "${STUB_SQUASH_RESULT:-success}" = "success" ]; then
                  echo "${STUB_SQUASH_OUTPUT:-auto-merge enabled}"
                  exit 0
                else
                  echo "${STUB_SQUASH_OUTPUT:-squash attempt failed}" >&2
                  exit 1
                fi
                ;;
              *"--auto"*)
                if [ "${STUB_BARE_RESULT:-success}" = "success" ]; then
                  echo "${STUB_BARE_OUTPUT:-auto-merge enabled}"
                  exit 0
                else
                  echo "${STUB_BARE_OUTPUT:-bare attempt failed}" >&2
                  exit 1
                fi
                ;;
              *)
                echo "unexpected gh invocation: $args" >&2
                exit 99
                ;;
            esac
            """
        )
    )
    stub.chmod(0o755)
    return tmp_path


def _run_enable_auto_merge(
    *,
    gh_merge_stub_dir: Path,
    bare_result: str = "success",
    bare_output: str = "",
    squash_result: str = "success",
    squash_output: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the extracted ``Enable auto-merge`` Bash against the stub."""
    script = _extract_enable_auto_merge_step_script()
    env = {
        "PATH": f"{gh_merge_stub_dir}:/usr/bin:/bin",
        "GH_TOKEN": "stub-token",
        "GH_REPO": "OmniNode-ai/omniclaude",
        "PR": "2029",
        "STUB_BARE_RESULT": bare_result,
        "STUB_BARE_OUTPUT": bare_output,
        "STUB_SQUASH_RESULT": squash_result,
        "STUB_SQUASH_OUTPUT": squash_output,
    }
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.unit
class TestAutoMergeEnableStep:
    """Behavioral coverage for the ``Enable auto-merge`` step's retry logic
    (OMN-16501). Extracts the live Bash from the YAML so the tests are bound
    to the deployed logic, not a re-implementation of it."""

    def test_bare_auto_success_does_not_retry(self, gh_merge_stub_dir: Path) -> None:
        """Queue-controlled regime (OMN-13214): bare --auto succeeding must
        not trigger the --squash fallback at all."""
        result = _run_enable_auto_merge(
            gh_merge_stub_dir=gh_merge_stub_dir,
            bare_result="success",
            bare_output="Auto-merge enabled",
        )
        assert result.returncode == 0, result.stderr
        assert "auto-merge enabled:" in result.stdout
        assert "(squash)" not in result.stdout

    def test_already_enqueued_is_benign_no_retry(self, gh_merge_stub_dir: Path) -> None:
        """A benign 'already enqueued' race must exit 0 without invoking the
        --squash retry (the squash stub is set to fail, proving it was never
        called)."""
        result = _run_enable_auto_merge(
            gh_merge_stub_dir=gh_merge_stub_dir,
            bare_result="failure",
            bare_output="pull request already enqueued",
            squash_result="failure",
            squash_output="must not be invoked",
        )
        assert result.returncode == 0, result.stderr
        assert "not newly enabled (expected)" in result.stdout

    def test_no_active_queue_retries_with_squash(self, gh_merge_stub_dir: Path) -> None:
        """OMN-16501 reproduction: bare --auto rejected non-interactively
        (no active merge queue) must retry with --squash and succeed."""
        result = _run_enable_auto_merge(
            gh_merge_stub_dir=gh_merge_stub_dir,
            bare_result="failure",
            bare_output=(
                "--merge, --rebase, or --squash required when not running interactively"
            ),
            squash_result="success",
            squash_output="Auto-merge enabled",
        )
        assert result.returncode == 0, result.stderr
        assert "bare --auto rejected" in result.stdout
        assert "auto-merge enabled (squash):" in result.stdout

    def test_squash_retry_failure_still_propagates(
        self, gh_merge_stub_dir: Path
    ) -> None:
        """If the --squash retry itself fails for a real reason, the step
        must still fail loudly rather than swallow the error."""
        result = _run_enable_auto_merge(
            gh_merge_stub_dir=gh_merge_stub_dir,
            bare_result="failure",
            bare_output=(
                "--merge, --rebase, or --squash required when not running interactively"
            ),
            squash_result="failure",
            squash_output="some unrelated permanent error",
        )
        assert result.returncode == 1
        assert "auto-merge failed:" in result.stdout

    def test_queue_controlled_rejection_is_not_retried_with_squash(
        self, gh_merge_stub_dir: Path
    ) -> None:
        """A genuine queue-controlled rejection ('merge strategy ... set by
        the merge queue') is a DIFFERENT error than gh's non-interactive
        method requirement and must NOT trigger the --squash retry — passing
        an explicit method on a queue-controlled branch is itself rejected
        (OMN-13214). The squash stub is set to succeed, proving it was never
        reached."""
        result = _run_enable_auto_merge(
            gh_merge_stub_dir=gh_merge_stub_dir,
            bare_result="failure",
            bare_output="The merge strategy for dev is set by the merge queue",
            squash_result="success",
        )
        assert result.returncode == 1
        assert "auto-merge failed:" in result.stdout
        assert "(squash)" not in result.stdout


# --------------------------------------------------------------------------
# OMN-17875: arming-token guard
# --------------------------------------------------------------------------

# The steps that cause a commit to be attributed to the token: arming the
# squash merge, and update-branch/enqueue. Both must carry the non-suppressing
# identity.
MUTATING_STEP_NAMES: tuple[str, ...] = (
    "Enable auto-merge",
    "Enqueue armed PR and verify it entered the queue",
)

# The step that only reads PR/repo metadata. Safe under the default token
# because it creates no commit.
READ_ONLY_STEP_NAME = "Resolve PR and author"

REQUIRED_TOKEN_EXPR = "${{ secrets.CROSS_REPO_PAT }}"

# Substrings that would reintroduce the suppression on a different credential.
APP_TOKEN_MARKERS: tuple[str, ...] = (
    "create-github-app-token",
    "ONEXBOT_OCC_APP_ID",
    "ONEXBOT_OCC_PRIVATE_KEY",
)


def _workflow_steps() -> list[dict[str, Any]]:
    loaded = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    steps = loaded["jobs"]["auto-merge"]["steps"]
    assert isinstance(steps, list)
    return [step for step in steps if isinstance(step, dict)]


def _step_by_name(name: str) -> dict[str, Any]:
    matches = [step for step in _workflow_steps() if step.get("name") == name]
    assert len(matches) == 1, (
        f"expected exactly one step named {name!r}, got {len(matches)}"
    )
    return matches[0]


@pytest.mark.unit
class TestAutoMergeArmingTokenOmn17875:
    """The credential the workflow arms with is load-bearing (OMN-17875).

    Root cause, measured live on this repo 2026-09-04T15:25-15:35Z over the
    last 40 merged dev PRs (#2060-#2103): this workflow armed
    ``gh pr merge --auto`` with ``secrets.GITHUB_TOKEN``. GitHub completes an
    armed auto-merge as the identity that armed it, and fires no ``push``
    event for ``GITHUB_TOKEN``-authored commits (documented Actions-recursion
    prevention). The split was total, with no overlap::

        mergedBy github-actions[bot] : 21 merges, ALL 0 push-event runs
        mergedBy jonahgabriel (User) : 19 merges, ALL 3-6 push-event runs

    (``gh api "repos/OmniNode-ai/omniclaude/actions/runs?head_sha=<full-sha>&event=push"
    --jq .total_count`` — a short sha returns a false 0 from that endpoint.)
    The 19 user merges are the positive control for the 21 zeros. Four
    push-on-``dev`` workflows carry no ``paths:`` filter and were therefore
    owed a run on every one of those 21 merges and got none: Hook Edge Lane
    Gate, Required-Check Manifest Reconcile, Validate Validator Requirements
    and Runtime Profiles.

    Fix: arm with ``secrets.CROSS_REPO_PAT`` — an existing org secret
    (``visibility: all``) this repo already consumes in ``ci.yml``,
    ``release.yml``, ``required-check-manifest-reconcile.yml`` and
    ``sibling-lock-refresh.yml``, and the same credential
    ``omninode_infra``'s auto-merge.yml deliberately retained for this exact
    property (OMN-15769, re-affirmed by OMN-16373). Ported from
    omnibase_infra#3178 (merged b71159f3e0b1fb59a26c593fa4be2f78118ff51c).

    These tests are the mechanical guard (CLAUDE.md rule 5: enforcement, not
    detection) so the swap cannot be silently reverted to ``GITHUB_TOKEN`` --
    or "modernised" to an ``onexbot-occ-writer`` App installation token, which
    the OMN-16373 controlled probe proved suppresses push events identically.
    """

    @pytest.mark.parametrize("step_name", MUTATING_STEP_NAMES)
    def test_merge_state_mutating_steps_arm_with_cross_repo_pat(
        self, step_name: str
    ) -> None:
        """The arming/enqueue steps must authenticate as CROSS_REPO_PAT.

        A GITHUB_TOKEN- or App-token-authored merge commit fires no push
        event, so this assertion is the difference between the four
        unfiltered push-on-dev gates running on every dev merge and running
        on none of the bot-merged ones.
        """
        step = _step_by_name(step_name)
        token = step.get("env", {}).get("GH_TOKEN")
        assert token == REQUIRED_TOKEN_EXPR, (
            f"{step_name!r} must arm with {REQUIRED_TOKEN_EXPR}; found {token!r}. "
            "GITHUB_TOKEN- and GitHub-App-token-authored merges suppress "
            "push-triggered workflow runs on dev (OMN-17875 / OMN-16373)."
        )

    @pytest.mark.parametrize("step_name", MUTATING_STEP_NAMES)
    def test_mutating_steps_have_no_github_token_fallback(self, step_name: str) -> None:
        """No ``|| secrets.GITHUB_TOKEN`` fallback on the mutating steps.

        A fallback would restore the defect silently on any run where the PAT
        is unavailable, which is exactly the invisible-failure shape this
        ticket exists to remove: the job would report success while starving
        every downstream push workflow.
        """
        step = _step_by_name(step_name)
        token = str(step.get("env", {}).get("GH_TOKEN", ""))
        assert "GITHUB_TOKEN" not in token, (
            f"{step_name!r} must not fall back to GITHUB_TOKEN; found {token!r}"
        )

    def test_read_only_resolve_step_stays_on_default_token(self) -> None:
        """The read-only step keeps GITHUB_TOKEN — it creates no commit.

        Narrow blast radius is deliberate: the PAT is only granted to the
        steps that actually need the non-suppressing identity.
        """
        step = _step_by_name(READ_ONLY_STEP_NAME)
        assert step.get("env", {}).get("GH_TOKEN") == "${{ secrets.GITHUB_TOKEN }}"
        run = step.get("run", "")
        for mutating_verb in (
            "gh pr merge",
            "gh pr update-branch",
            "enqueuePullRequest",
            "git push",
        ):
            assert mutating_verb not in run, (
                f"{READ_ONLY_STEP_NAME!r} performs {mutating_verb!r} but runs "
                "under GITHUB_TOKEN; move it to a CROSS_REPO_PAT step or the "
                "suppression returns."
            )

    def test_no_app_token_mint_is_introduced(self) -> None:
        """An onexbot-occ-writer App token is not a valid substitute here.

        The OMN-16373 controlled probe pushed commit ``38ffe1f4`` under the
        App identity and the push-triggered marker workflow did not fire,
        while the ``jonahgabriel`` control push (``fd534b2a``) fired run
        32562988366.
        """
        raw = WORKFLOW_PATH.read_text(encoding="utf-8")
        body = raw.split("name: Auto-Merge", 1)[1]
        for marker in APP_TOKEN_MARKERS:
            assert marker not in body, (
                f"auto-merge.yml must not mint a GitHub App token ({marker!r}); "
                "App-token pushes suppress push-triggered runs identically to "
                "GITHUB_TOKEN (OMN-16373)."
            )

    def test_header_documents_the_defect_and_cites_the_evidence_tickets(
        self,
    ) -> None:
        """The in-file rationale must survive, so the next reader does not
        revert it."""
        header = WORKFLOW_PATH.read_text(encoding="utf-8").split("name: Auto-Merge", 1)[
            0
        ]
        for citation in ("OMN-17875", "OMN-16373", "OMN-15769", "CROSS_REPO_PAT"):
            assert citation in header, f"auto-merge.yml header must cite {citation}"


if __name__ == "__main__":  # pragma: no cover - manual run helper
    sys.exit(pytest.main([__file__, "-v"]))
