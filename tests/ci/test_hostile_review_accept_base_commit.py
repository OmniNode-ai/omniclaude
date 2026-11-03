# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22293: the gate-accept step runs the node from a trusted revision, and fails closed.

A pull request cannot supply the code that accepts itself: the step runs the node from
the omnimarket clone beside the workspace, which the "Clone omnimarket" step reads at the
newest ``dev-<UTC>-<sha12>`` tag whose commit starts with that sha12 and is an ancestor of
omnimarket's dev branch. When that clone does not carry the node (the tag that carries it
is not out yet), or the node does not run, the step reports ``decision=unchanged`` and the
voters' verdict stands. Neither the accept step nor the clone step ever fails the job by
itself.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.ci.hostile_review_job import (
    DEGRADED_CASES,
    REVIEW_JOB,
    Run,
    required_context_names,
    simulate,
    step_named,
)

pytestmark = pytest.mark.unit


def _run(
    tmp_path: Path,
    name: str,
    *,
    case: str,
    decision: str = "pass_agent",
    trusted_has_node: bool = True,
    workspace_has_node: bool = False,
    node_exit: int = 0,
) -> Run:
    work = tmp_path / name
    work.mkdir()
    return simulate(
        work,
        case=case,
        decision=decision,
        trusted_has_node=trusted_has_node,
        workspace_has_node=workspace_has_node,
        node_exit=node_exit,
    )


def _all(run: Run, *, green: bool) -> None:
    for context in required_context_names():
        assert run.green(context) is green, (context, run.exits, run.skipped)


@pytest.mark.parametrize("case", DEGRADED_CASES)
def test_the_node_is_run_from_the_trusted_clone_with_this_attempts_files(
    tmp_path: Path, case: str
) -> None:
    run = _run(tmp_path, case, case=case)
    assert len(run.node_calls) == 1
    assert run.outputs["accept"]["decision"] == "pass_agent"
    assert run.exits["accept"] == 0
    _all(run, green=True)


@pytest.mark.parametrize("case", ["passed", *DEGRADED_CASES, "blocked"])
def test_a_clone_without_the_node_leaves_the_voters_verdict_to_decide(
    tmp_path: Path, case: str
) -> None:
    run = _run(tmp_path, case, case=case, trusted_has_node=False)
    assert run.node_calls == [], "no node may run when the trusted clone has none"
    assert run.exits["accept"] == 0
    assert run.outputs["accept"] == {"decision": "unchanged"}
    _all(run, green=case == "passed")


@pytest.mark.parametrize("case", DEGRADED_CASES)
def test_a_node_in_the_pull_requests_checkout_is_never_run(
    tmp_path: Path, case: str
) -> None:
    run = _run(
        tmp_path,
        case,
        case=case,
        trusted_has_node=False,
        workspace_has_node=True,
    )
    assert run.node_calls == [], "the pull request's own node must never run"
    assert run.outputs["accept"] == {"decision": "unchanged"}
    _all(run, green=False)


@pytest.mark.parametrize("case", ["passed", *DEGRADED_CASES])
def test_a_node_that_does_not_run_never_fails_the_job_by_itself(
    tmp_path: Path, case: str
) -> None:
    run = _run(tmp_path, case, case=case, node_exit=2)
    assert len(run.node_calls) == 1
    assert run.exits["accept"] == 0
    assert run.outputs["accept"] == {"decision": "unchanged"}
    _all(run, green=case == "passed")


# -- the clone step: a trusted revision or nothing, and never a failure -------------

_GIT_STUB = """#!/usr/bin/env bash
echo "$*" >> "$GIT_STUB_LOG"
args=("$@")
if [ "${args[0]}" = "-C" ]; then args=("${args[@]:2}"); fi
case "${args[0]}" in
  init) mkdir -p "${@: -1}" ;;
  ls-remote) printf '%s' "$STUB_LS_REMOTE" ;;
  rev-parse) echo "$STUB_REV_PARSE" ;;
  merge-base) exit "${STUB_ANCESTOR_RC:-0}" ;;
  fetch) exit "${STUB_FETCH_RC:-0}" ;;
esac
exit 0
"""

_TAG_SHA12 = "abcdef012345"
_TAG_NAME = f"dev-20261103120000-{_TAG_SHA12}"
_TAG_REF = f"{_TAG_SHA12}{'0' * 28}\trefs/tags/{_TAG_NAME}\n"


def _clone(
    tmp_path: Path,
    *,
    ls_remote: str,
    rev_parse: str,
    ancestor_rc: int = 0,
    fetch_rc: int = 0,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    run = str(step_named(REVIEW_JOB, "Clone omnimarket")["run"])
    bin_dir = tmp_path / "bin"
    work_dir = tmp_path / "workspace"
    bin_dir.mkdir()
    work_dir.mkdir()
    for name, body in (("git", _GIT_STUB), ("sleep", "#!/usr/bin/env bash\nexit 0\n")):
        stub = bin_dir / name
        stub.write_text(body, encoding="utf-8")
        stub.chmod(0o755)
    log = tmp_path / "git.log"
    log.touch()
    script = tmp_path / "step.sh"
    script.write_text(run, encoding="utf-8")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GIT_STUB_LOG": str(log),
        "STUB_LS_REMOTE": ls_remote,
        "STUB_REV_PARSE": rev_parse,
        "STUB_ANCESTOR_RC": str(ancestor_rc),
        "STUB_FETCH_RC": str(fetch_rc),
    }
    result = subprocess.run(
        ["bash", "-e", str(script)],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return result, log.read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize(
    ("ls_remote", "rev_parse", "ancestor_rc", "fetch_rc", "message"),
    [
        pytest.param("", "", 0, 0, "could be resolved", id="no-tag-on-the-remote"),
        pytest.param(
            f"{'1' * 40}\trefs/tags/dev-latest\n",
            "",
            0,
            0,
            "could be resolved",
            id="no-tag-matches-the-dev-utc-sha12-shape",
        ),
        pytest.param(
            _TAG_REF,
            "",
            0,
            1,
            "could be resolved",
            id="the-remote-cannot-be-fetched",
        ),
        pytest.param(
            _TAG_REF,
            f"{'f' * 40}",
            0,
            0,
            "is anchored to its commit and reachable from dev",
            id="tag-commit-differs-from-the-sha12-its-name-records",
        ),
        pytest.param(
            _TAG_REF,
            f"{_TAG_SHA12}{'0' * 28}",
            1,
            0,
            "is anchored to its commit and reachable from dev",
            id="tag-commit-is-not-an-ancestor-of-dev",
        ),
    ],
)
def test_the_clone_step_checks_out_nothing_it_cannot_anchor_and_never_fails(
    tmp_path: Path,
    ls_remote: str,
    rev_parse: str,
    ancestor_rc: int,
    fetch_rc: int,
    message: str,
) -> None:
    result, git_calls = _clone(
        tmp_path,
        ls_remote=ls_remote,
        rev_parse=rev_parse,
        ancestor_rc=ancestor_rc,
        fetch_rc=fetch_rc,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert message in output, output
    assert "::error::" not in output, output
    assert not any(" checkout" in f" {call}" for call in git_calls), git_calls


def test_the_clone_step_reads_the_newest_anchored_dev_tag(tmp_path: Path) -> None:
    """Positive control for the cases above: an anchored tag is checked out."""
    result, git_calls = _clone(
        tmp_path,
        ls_remote=_TAG_REF,
        rev_parse=f"{_TAG_SHA12}{'0' * 28}",
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert f"omnimarket read at tag {_TAG_NAME}" in output, output
    checkouts = [call for call in git_calls if " checkout" in f" {call}"]
    assert checkouts == [
        f"-C ../omnimarket checkout -q --detach {_TAG_SHA12}{'0' * 28}"
    ]
