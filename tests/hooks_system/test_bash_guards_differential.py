# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""One entrypoint, one interpreter, the same decisions (OMN-20118).

The seven Bash PreToolUse guards were seven registered hooks, each starting its
own Python interpreter for its decision core. They are now one registered
entrypoint, ``pre_tool_use_bash_guards.sh``, that sources each guard and runs
every decision core the call needs in one interpreter. This suite is the proof
that no decision moved:

* ``test_entrypoint_decides_what_the_seven_hooks_decided``: for every command in
  the corpus, from a lane worktree and from the canonical clone, the entrypoint's
  exit status and refusal equal what the seven separate scripts at origin/dev
  ``b5f04266b`` decided (``fixtures/bash_guard_golden.json``), composed the way
  Claude Code composes seven hooks: any refusal refuses, and every refusing
  guard's reason is shown.
* ``test_each_guard_run_alone_still_decides_as_before``: every guard script run
  on its own (its own interpreter again) decides as the golden record says, so
  the scripts the entrypoint sources are the scripts that were recorded.
* ``test_at_most_one_interpreter_per_call``: a call that trips every guard's
  pre-filter starts ONE interpreter for all of them, and a call that trips none
  starts none.
* ``test_a_dead_shared_interpreter_fails_every_guard_closed``: when the one
  interpreter cannot run, every guard that needed it refuses with its own
  evaluation-failed message; none is silently allowed.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from tests.hooks_system import bash_guard_corpus as corpus

PLUGIN_ROOT = corpus.REPO_ROOT / "plugins" / "onex"
PYTHON = sys.executable


def _golden() -> dict[str, Any]:
    return dict(corpus.load_golden())


def _expected(per_guard: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Seven hook results composed the way the entrypoint states it composes them."""
    blocks = [per_guard[s] for s in corpus.GUARD_SCRIPTS if per_guard[s]["rc"] == 2]
    if len(blocks) == 1:
        return {"rc": 2, "out": blocks[0]["out"]}
    if blocks:
        reasons = [
            b["out"].get("reason", json.dumps(b["out"]))
            if isinstance(b["out"], dict)
            else b["out"]
            for b in blocks
        ]
        return {"rc": 2, "out": {"decision": "block", "reason": "\n\n".join(reasons)}}
    for script in corpus.GUARD_SCRIPTS:
        if per_guard[script]["rc"] != 0:
            return per_guard[script]
    return {"rc": 0}


def test_golden_covers_the_corpus() -> None:
    golden = _golden()
    expected_keys = {
        f"{kind}\t{command}" for kind, command in corpus.cases(corpus.load_commands())
    }
    assert set(golden) == expected_keys, (
        "the golden record and the corpus disagree; re-record the golden against "
        f"{corpus.GOLDEN_BASE} (see tests/hooks_system/bash_guard_corpus.py)"
    )
    refusals = sum(
        1 for per_guard in golden.values() for d in per_guard.values() if d["rc"] == 2
    )
    allows = sum(1 for per_guard in golden.values() if _expected(per_guard)["rc"] == 0)
    # Positive control: a corpus that no guard refuses (or that every guard
    # refuses) cannot tell a working entrypoint from a broken one.
    assert refusals >= 50 and allows >= 50, (refusals, allows)
    for script in corpus.GUARD_SCRIPTS:
        assert any(pg[script]["rc"] == 2 for pg in golden.values()), (
            f"{script} refuses nothing in the corpus, so its decisions are unproven"
        )


def _run_all(script: str) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    golden = _golden()
    with corpus.workspace() as ws:

        def one(key: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
            kind, template = key.split("\t", 1)
            rc, out = corpus.run_script(
                ws, PLUGIN_ROOT, script, ws.fill(template), kind, PYTHON
            )
            want = (
                _expected(golden[key])
                if script == corpus.ENTRYPOINT
                else golden[key][script]
            )
            return key, corpus.decision(ws, rc, out), want

        with ThreadPoolExecutor(max_workers=8) as pool:
            return list(pool.map(one, sorted(golden)))


def _mismatches(results: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> str:
    bad = [(k, got, want) for k, got, want in results if got != want]
    return "\n".join(
        f"  {k!r}\n    got:  {json.dumps(got)[:400]}\n    want: {json.dumps(want)[:400]}"
        for k, got, want in bad[:15]
    ) + (f"\n  ... {len(bad)} mismatches in all" if bad else "")


def test_entrypoint_decides_what_the_seven_hooks_decided() -> None:
    results = _run_all(corpus.ENTRYPOINT)
    report = _mismatches(results)
    assert not report, "the entrypoint changed a decision:\n" + report


@pytest.mark.parametrize("script", corpus.GUARD_SCRIPTS)
def test_each_guard_run_alone_still_decides_as_before(script: str) -> None:
    results = _run_all(script)
    report = _mismatches(results)
    assert not report, f"{script} run on its own changed a decision:\n" + report


def _count_pythons(tmp_path: Path, command: str) -> tuple[int, int, str]:
    log = tmp_path / "pythons.log"
    shim = tmp_path / "python-shim"
    shim.write_text(f'#!/bin/sh\necho "$$ $*" >> "{log}"\nexec "{PYTHON}" "$@"\n')
    shim.chmod(0o755)
    with corpus.workspace() as ws:
        rc, out = corpus.run_script(
            ws, PLUGIN_ROOT, corpus.ENTRYPOINT, command, "worktree", str(shim)
        )
    lines = log.read_text().splitlines() if log.exists() else []
    # A refusal also starts the refusal recorder, backgrounded and disowned so
    # it is off the call's wall time (error-guard.sh hook_record_refusal); it is
    # not a decision core and is not counted.
    starts = sum(1 for line in lines if "hook_refusal_recorder.py" not in line)
    return starts, rc, out


def test_at_most_one_interpreter_per_call(tmp_path: Path) -> None:
    # Trips all seven pre-filters, and every guard allows it.
    starts, rc, out = _count_pythons(
        tmp_path,
        "git log --oneline -1 | grep -c 'secret-branch-push'; "
        "echo 'the `git worktree add` note'; git stash list; "
        "gh api repos/o/r/pulls/1 --jq .title; printf '%s\\n' --body",
    )
    assert rc == 0, out
    assert starts == 1, f"{starts} interpreter starts for one call"

    (tmp_path / "pythons.log").unlink(missing_ok=True)
    starts, rc, out = _count_pythons(tmp_path, "ls -la")
    assert rc == 0, out
    assert starts == 0, f"{starts} interpreter starts for a call no guard needs"


def test_two_refusals_carry_both_reasons(tmp_path: Path) -> None:
    starts, rc, out = _count_pythons(
        tmp_path, "git worktree add /tmp/onex-x -b x; git stash pop"
    )
    assert rc == 2
    reason = json.loads(out)["reason"]
    assert "must be created under" in reason and "stash" in reason
    assert starts == 1


# Trips every guard's pre-filter so every guard needs its decision core.
_EVERY_GUARD_COMMAND = (
    "git worktree add /tmp/onex-x -b x; git stash list; "
    "gh api repos/o/r/pulls/1; echo 'a `b`'; printf %s --body; echo secret; "
    "git push origin lane/one"
)
# How each guard's own fail-closed refusal names itself.
_EVERY_GUARD_NAMES = (
    "worktree guard",  # worktree
    "OMN-16485",  # pr ownership
    "OMN-17957",  # credential rotation
    "OMN-17334",  # git stash
    "OMN-18798",  # shared tree
    "OMN-18335",  # pr body stamp
    "OMN-18750",  # prose substitution
)


def test_a_dead_shared_interpreter_fails_every_guard_closed(tmp_path: Path) -> None:
    dead = tmp_path / "dead-python"
    dead.write_text("#!/bin/sh\nexit 1\n")
    dead.chmod(0o755)
    command = _EVERY_GUARD_COMMAND
    with corpus.workspace() as ws:
        rc, out = corpus.run_script(
            ws, PLUGIN_ROOT, corpus.ENTRYPOINT, command, "worktree", str(dead)
        )
    assert rc == 2, out
    reason = json.loads(out)["reason"]
    for words in _EVERY_GUARD_NAMES:
        assert words in reason, f"no fail-closed refusal naming {words!r}:\n{reason}"


@pytest.mark.parametrize(
    "command",
    [
        "git stash pop",
        "gh pr edit 5 --body x",
        "aws iam create-access-key --user-name operator-k8s",
        "git worktree add /tmp/onex-x -b x",
        "ls -la",
    ],
)
def test_an_unwritable_request_dir_is_never_less_strict(
    tmp_path: Path, command: str
) -> None:
    # The request for the shared interpreter cannot be written. Every guard
    # that needed its core must then refuse through its own failed-core branch:
    # the entrypoint may refuse more than the seven separate hooks did (several
    # of them fail open on an unwritable TMPDIR through error-guard.sh), never
    # less. Before the fix, `git stash pop` was allowed here.
    # Under a regular file, so no `mkdir -p` along the way can create it (a
    # missing directory under a writable parent gets created by error-guard.sh
    # and would make this test pass without exercising anything).
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    env = {"TMPDIR": str(blocker / "tmp")}
    with corpus.workspace() as ws:
        separate = [
            corpus.run_script(
                ws, PLUGIN_ROOT, script, command, "worktree", PYTHON, extra_env=env
            )[0]
            for script in corpus.GUARD_SCRIPTS
        ]
        rc, out = corpus.run_script(
            ws,
            PLUGIN_ROOT,
            corpus.ENTRYPOINT,
            command,
            "worktree",
            PYTHON,
            extra_env=env,
        )
    if 2 in separate:
        assert rc == 2, (separate, out)
    else:
        assert rc in (0, 2), (separate, rc, out)
