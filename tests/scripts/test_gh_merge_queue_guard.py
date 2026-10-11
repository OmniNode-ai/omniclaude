# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: the gh shim refuses a merge that bypasses a live merge-queue rule.

omnibase_infra#4197 was pulled from the dev merge queue for failed checks at 14:15:03Z on
2026-09-28 and then landed anyway by a raw REST PUT merge at 14:27:17Z -- the merge-drain
workflow's own prompt told the land lane to do exactly that. A prompt-text fix cannot be a
control by itself (a land lane is an LLM reading a prompt); this is the mechanical stop that
holds no matter what any prompt says. It sits in `scripts/user-bin/gh` (ahead of the real `gh`
on PATH via `install-gh-shim.sh`, OMN-19479) and needs no session restart: any process that
resolves `gh` from PATH picks it up the moment the file changes.

Each test puts a scripted fake `gh` behind the shim (never the network) and asserts:

* AC1 (`-k queue_put_blocked`): a raw REST PUT merge on a queue-protected branch is refused,
  and the fake `gh` never receives the merge call itself (only the two live-check reads).
* AC2 (`-k queue_admin_blocked`): `gh pr merge --admin` is refused on a queue-protected branch
  even when `--match-head-commit` is also present.
* AC3 (`-k queue_bare_merge_blocked`): `gh pr merge <n> --squash` with neither
  `--match-head-commit` nor `--auto` is refused on a queue-protected branch.
* AC4 (`-k queue_enqueue_form_allowed`): the sanctioned enqueue form (`--squash
  --match-head-commit <head>`) reaches the real `gh` unchanged on a queue-protected branch.
* AC5 (`-k no_queue_put_allowed`): the same raw REST PUT reaches the real `gh` unchanged when
  the live rules read shows no `merge_queue` rule -- the guard is not a blanket merge ban.
* AC6 (`-k unresolvable_fails_closed`): when the live rules read cannot be resolved (the fake
  `gh` answers empty), the call is refused rather than assumed safe (CLAUDE.md rule 16).
* AC7 (`-k unrelated_reads_never_reach_guard`): an ordinary read (`gh pr view ... --json url`)
  never triggers the two guard probe calls at all.

No test touches the network or a real repository.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

from tests.scripts.conftest import install_ancestry_ps

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "scripts" / "user-bin" / "gh"

# A scripted fake gh: logs every call's argv as one JSON line, then answers by shape.
#   pr view <n> --repo <repo> --json baseRefName --jq .baseRefName   -> $FAKE_BASE (or nothing)
#   api repos/<repo>/rules/branches/<branch>                         -> $FAKE_RULES (or nothing)
#   anything else                                                    -> logs and exits 0
FAKE_GH = r"""#!/bin/bash
python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@" >> "$FAKE_GH_LOG"
if [ "$1" = "pr" ] && [ "$2" = "view" ]; then
  printf '%s' "${FAKE_BASE:-}"
  exit 0
fi
if [ "$1" = "api" ] && [ "$2" = "repos/${FAKE_REPO:-o/r}/rules/branches/${FAKE_BASE:-base}" ]; then
  printf '%s' "${FAKE_RULES:-[]}"
  exit 0
fi
exit "${FAKE_GH_RC:-0}"
"""


def _write_exec(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    fake_dir = tmp_path / "realbin"
    fake_dir.mkdir()
    _write_exec(fake_dir / "gh", FAKE_GH)
    # Not a lane by ancestry, wherever the suite runs (OMN-20911).
    install_ancestry_ps(fake_dir)
    return {
        "PATH": f"{SHIM.parent}:{fake_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path / "home"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "FAKE_GH_LOG": str(tmp_path / "calls.jsonl"),
        "FAKE_REPO": "o/r",
        "FAKE_BASE": "dev",
        "GIT_CONFIG_NOSYSTEM": "1",
        "ONEX_GH_READ_ROUTING": "0",
    }


def _run(
    env: dict[str, str], *args: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    e = dict(env)
    e.update(extra or {})
    return subprocess.run(
        ["gh", *args], env=e, capture_output=True, text=True, timeout=30, check=False
    )


def _calls(env: dict[str, str]) -> list[list[str]]:
    log = Path(env["FAKE_GH_LOG"])
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


QUEUE_RULES = json.dumps([{"type": "merge_queue", "parameters": {}}])
NO_QUEUE_RULES = json.dumps([{"type": "required_status_checks", "parameters": {}}])


@pytest.mark.unit
def test_queue_put_blocked(env: dict[str, str]) -> None:
    r = _run(
        env,
        "api",
        "-X",
        "PUT",
        "repos/o/r/pulls/4197/merge",
        "-f",
        "merge_method=squash",
        "-f",
        "sha=deadbeef",
        extra={"FAKE_RULES": QUEUE_RULES},
    )
    assert r.returncode != 0
    assert "OMN-17427" in r.stderr
    assert "merge_queue" in r.stderr
    calls = _calls(env)
    # The real shim flow reaches precisely the two live-check reads -- never the
    # raw REST merge itself. This guards against detection that only works in a
    # helper/unit scope rather than from the shim's actual argv classification.
    assert calls == [
        [
            "pr",
            "view",
            "4197",
            "--repo",
            "o/r",
            "--json",
            "baseRefName",
            "--jq",
            ".baseRefName",
        ],
        ["api", "repos/o/r/rules/branches/dev"],
    ]


@pytest.mark.unit
def test_queue_admin_blocked(env: dict[str, str]) -> None:
    r = _run(
        env,
        "pr",
        "merge",
        "4197",
        "--repo",
        "o/r",
        "--squash",
        "--match-head-commit",
        "deadbeef",
        "--admin",
        extra={"FAKE_RULES": QUEUE_RULES},
    )
    assert r.returncode != 0
    assert "--admin" in r.stderr
    calls = _calls(env)
    assert all(c[:2] != ["pr", "merge"] for c in calls), calls


@pytest.mark.unit
def test_queue_bare_merge_blocked(env: dict[str, str]) -> None:
    r = _run(
        env,
        "pr",
        "merge",
        "4197",
        "--repo",
        "o/r",
        "--squash",
        extra={"FAKE_RULES": QUEUE_RULES},
    )
    assert r.returncode != 0
    assert "match-head-commit" in r.stderr
    calls = _calls(env)
    assert all(c[:2] != ["pr", "merge"] for c in calls), calls


@pytest.mark.unit
def test_queue_enqueue_form_allowed(env: dict[str, str]) -> None:
    r = _run(
        env,
        "pr",
        "merge",
        "4197",
        "--repo",
        "o/r",
        "--squash",
        "--match-head-commit",
        "deadbeef",
        extra={"FAKE_RULES": QUEUE_RULES},
    )
    assert r.returncode == 0, r.stderr
    calls = _calls(env)
    assert any(c[:2] == ["pr", "merge"] for c in calls), calls


@pytest.mark.unit
def test_no_queue_put_allowed(env: dict[str, str]) -> None:
    r = _run(
        env,
        "api",
        "-X",
        "PUT",
        "repos/o/r/pulls/9/merge",
        "-f",
        "merge_method=squash",
        "-f",
        "sha=deadbeef",
        extra={"FAKE_RULES": NO_QUEUE_RULES},
    )
    assert r.returncode == 0, r.stderr
    calls = _calls(env)
    assert any("pulls/9/merge" in " ".join(c) for c in calls), calls


@pytest.mark.unit
def test_unresolvable_fails_closed(env: dict[str, str]) -> None:
    # FAKE_BASE unset -> the "pr view" probe answers empty -> the branch, and so the rules
    # read, can never be resolved.
    r = _run(
        env,
        "api",
        "-X",
        "PUT",
        "repos/o/r/pulls/4197/merge",
        "-f",
        "merge_method=squash",
        "-f",
        "sha=deadbeef",
        extra={"FAKE_BASE": ""},
    )
    assert r.returncode != 0
    assert "could not be confirmed safe" in r.stderr
    calls = _calls(env)
    assert all(c[0] != "api" or "pulls/4197/merge" not in " ".join(c) for c in calls), (
        calls
    )


@pytest.mark.unit
def test_unrelated_reads_never_reach_guard(env: dict[str, str]) -> None:
    r = _run(env, "api", "repos/o/r/issues/9")
    assert r.returncode == 0, r.stderr
    calls = _calls(env)
    # exactly the one read call -- no rules/branches probe was ever made for an unrelated read
    assert len(calls) == 1, calls
    assert not any("rules/branches" in " ".join(c) for c in calls), calls
