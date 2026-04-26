# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests for .github/workflows/auto-merge.yml (OMN-9353).

The workflow contains a Bash branch in the ``Resolve PR and author`` step that
must:

* set ``skip=true`` when the PR base ref does not match the repo default branch
  (stacked-PR no-op — GitHub cannot enable auto-merge on non-default bases),
* set ``skip=false`` when the PR targets the default branch.

These tests extract the actual Bash from the workflow YAML, stub the ``gh`` CLI
on PATH, run the script under a fixed event payload, and assert the
``GITHUB_OUTPUT`` contents. Pulling the snippet straight from the YAML keeps
the test bound to the deployed logic.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "auto-merge.yml"


def _extract_resolve_step_script() -> str:
    """Pull the inline Bash from the ``Resolve PR and author`` step.

    Failing to extract a valid script is itself a test failure -- it means the
    YAML structure drifted and the test is no longer bound to the workflow.
    """
    text = WORKFLOW_PATH.read_text()
    lines = text.splitlines(keepends=True)
    # Locate the start of the Resolve step's run block.
    in_step = False
    in_run = False
    body_lines: list[str] = []
    for line in lines:
        if not in_step:
            if "- name: Resolve PR and author" in line:
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
        "Could not extract Resolve step script from auto-merge.yml; "
        "workflow YAML structure changed. Test must be updated to match."
    )
    # Strip the 10-space YAML indent so Bash sees a normal script.
    return dedent("".join(body_lines))


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
    """YAML-level invariants that protect the ``--squash`` flag and the
    stacked-PR detection block from regressions (OMN-9353)."""

    def test_merge_command_passes_squash_flag(self) -> None:
        """OMN-9547 precedent: ``--squash`` must be explicit on the
        ``gh pr merge --auto`` invocation. The repo merge queue is
        configured for SQUASH and ``allow_merge_commit`` is ``false``,
        but ``enablePullRequestAutoMerge`` reads the repo default
        ``merge_method`` and may arm a PR as MERGE -- which the queue
        then silently drops. Naming the method removes the ambiguity."""
        text = WORKFLOW_PATH.read_text()
        assert 'gh pr merge "$PR" --repo "$GH_REPO" --auto --squash' in text, (
            "auto-merge.yml lost --squash flag (regression of OMN-9547)"
        )

    def test_resolve_step_compares_base_to_default_branch(self) -> None:
        """Stacked-PR detection must fetch ``baseRefName`` and
        ``defaultBranchRef.name`` and compare them, otherwise stacked
        PRs will fail the required Enable Auto-Merge check."""
        text = WORKFLOW_PATH.read_text()
        assert "--json baseRefName" in text
        assert "--json defaultBranchRef" in text
        assert 'if [ "$BASE_REF" != "$DEFAULT_BRANCH" ]' in text


if __name__ == "__main__":  # pragma: no cover - manual run helper
    sys.exit(pytest.main([__file__, "-v"]))
