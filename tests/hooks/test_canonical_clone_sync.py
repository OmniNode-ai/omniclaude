# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the merge-driven canonical-clone sync (OMN-19607).

Named groups so the tickets' falsifiers can select them:

* ``matcher`` -- which tool calls are merges, and of which repository.
* ``engine`` -- the fetch and fast-forward of one clone, and every refusal.
  Each refusal test also proves nothing moved.
* ``hook`` -- the PostToolUse script: exit 0, silent, fast, on every path, and
  a real merge payload advances a real (hermetic) clone through the detached
  child.
* ``lan_source`` / ``identity`` -- lab-state-sync step 4: identity independent
  of the fetch URL, LAN remote-tracking refs, and receipt-able sync output.

Everything runs against hermetic repositories under ``tmp_path``. The "remote"
is a local bare repository whose path contains ``github.com/<owner>/<name>.git``
so the engine resolves an ``owner/name`` slug exactly as it does for a real
GitHub remote. Nothing reaches the network.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENGINE_PATH = (
    _REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "canonical_clone_sync.py"
)
_HOOK = (
    _REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "post_tool_use_merge_clone_sync.sh"
)


def _load_engine() -> ModuleType:
    spec = importlib.util.spec_from_file_location("canonical_clone_sync", _ENGINE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["canonical_clone_sync"] = module
    spec.loader.exec_module(module)
    return module


ccs = _load_engine()

_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables before shelling out to git (OMN-14891).

    Git exports these into every hook environment and they override both
    ``cwd=`` and ``git -C``, so a fixture run under a pre-push hook would
    otherwise operate on the real invoking worktree (OMN-18434).
    """
    scrubbed = {k: v for k, v in env.items() if k not in _GIT_LOCATION_ENV}
    scrubbed["GIT_CONFIG_NOSYSTEM"] = "1"
    return scrubbed


def _clean_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    env = scrub_git_location_env(os.environ)
    if extra:
        env.update(extra)
    return env


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


# --------------------------------------------------------------------------- #
# Hermetic registry
# --------------------------------------------------------------------------- #
class Registry:
    """An OMNI_HOME with canonical clones whose remotes look like GitHub."""

    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "registry"
        self.home.mkdir()
        self.state = tmp / "state"
        self.remotes = tmp / "remotes" / "github.com"
        self.seeds = tmp / "seeds"

    def env(self, **extra: str) -> dict[str, str]:
        return _clean_env(
            {
                "OMNI_HOME": str(self.home),
                "ONEX_STATE_DIR": str(self.state),
                "ONEX_REGISTRY_ROOTS": "",
                # Force full mode so the hook's behaviour does not depend on
                # the invoking process's cwd or an inherited OMNICLAUDE_MODE
                # (mode.sh auto-detects from $PWD and falls back to "lite"
                # off a bare CI checkout, whose cwd sits outside every
                # canonical-registry directory; these tests assert on the
                # hook actually running, so mode must be pinned, not
                # inherited).
                "OMNICLAUDE_MODE": "full",
                **extra,
            }
        )

    def make(
        self,
        name: str,
        *,
        branch: str = "dev",
        owner: str = "Acme",
        root: Path | None = None,
    ) -> Path:
        seed = self.seeds / owner / name
        seed.mkdir(parents=True)
        _git("init", "--quiet", "-b", branch, cwd=seed)
        _git("config", "user.email", "t@example.com", cwd=seed)
        _git("config", "user.name", "T", cwd=seed)
        (seed / "a.txt").write_text("one\n")
        (seed / "b.txt").write_text("one\n")
        _git("add", ".", cwd=seed)
        _git("commit", "--quiet", "-m", "one", cwd=seed)
        remote = self.remotes / owner / f"{name}.git"
        remote.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "--quiet", "--bare", str(seed), str(remote), cwd=self.tmp)
        _git("remote", "add", "origin", str(remote), cwd=seed)
        _git("fetch", "--quiet", "origin", cwd=seed)
        clone = (root or self.home) / name
        _git("clone", "--quiet", "-b", branch, str(remote), str(clone), cwd=self.tmp)
        _git("config", "user.email", "t@example.com", cwd=clone)
        _git("config", "user.name", "T", cwd=clone)
        return clone

    def advance(
        self,
        name: str,
        *,
        owner: str = "Acme",
        path: str = "a.txt",
        text: str = "two\n",
        branch: str = "dev",
    ) -> str:
        seed = self.seeds / owner / name
        (seed / path).write_text(text)
        _git("add", path, cwd=seed)
        _git("commit", "--quiet", "-m", f"change {path}", cwd=seed)
        _git("push", "--quiet", "origin", f"HEAD:{branch}", cwd=seed)
        return _git("rev-parse", "HEAD", cwd=seed)

    def log(self) -> list[dict[str, object]]:
        path = self.state / "logs" / ccs.LOG_NAME
        if not path.exists():
            return []
        return [
            json.loads(line) for line in path.read_text().splitlines() if line.strip()
        ]


@pytest.fixture
def reg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Registry:
    registry = Registry(tmp_path)
    for key in _GIT_LOCATION_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return registry


def _head(clone: Path) -> str:
    return _git("rev-parse", "HEAD", cwd=clone)


# --------------------------------------------------------------------------- #
# lab-state-sync step 4: identity and LAN source (implementation pending)
# --------------------------------------------------------------------------- #
def _lan_source_clones(reg: Registry) -> tuple[Path, Path]:
    """GitHub bare -> Mac source -> lab; only the lab is in the registry."""
    source_root = reg.tmp / "mac"
    source_root.mkdir()
    source = reg.make(
        "omnimarket", branch="main", owner="OmniNode-ai", root=source_root
    )
    lab = reg.home / "omnimarket"
    _git("clone", "--quiet", "-b", "main", str(source), str(lab), cwd=reg.tmp)
    _git("config", "onex.repo", "OmniNode-ai/omnimarket", cwd=lab)
    _git("config", "onex.fetchSourcePrefix", "refs/remotes/origin/", cwd=lab)
    assert _git("remote", cwd=lab) == "origin"
    assert _git("remote", "get-url", "origin", cwd=lab) == str(source)
    assert "github.com" not in str(source)
    assert _git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=lab) == "origin/main"
    return source, lab


def test_identity_config_overrides_a_plain_path_and_absent_config_stays_unknown(
    reg: Registry,
) -> None:
    clone = reg.make("omnimarket", branch="main", owner="OmniNode-ai")
    remote = reg.remotes / "OmniNode-ai" / "omnimarket.git"
    plain_remote = reg.tmp / "plain-remote.git"
    remote.rename(plain_remote)
    _git("remote", "set-url", "origin", str(plain_remote), cwd=clone)
    # Backwards-compatible control: a plain path alone carries no identity.
    assert ccs.clone_slug(clone) is None
    _git("config", "onex.repo", "OmniNode-ai/omnimarket", cwd=clone)
    assert ccs.clone_slug(clone) == "OmniNode-ai/omnimarket"


def test_identity_config_takes_precedence_over_a_github_url(reg: Registry) -> None:
    clone = reg.make("transport-name", branch="main", owner="Acme")
    _git("config", "onex.repo", "OmniNode-ai/omnimarket", cwd=clone)
    assert ccs.clone_slug(clone) == "OmniNode-ai/omnimarket"


def test_identity_sync_result_uses_config_with_a_plain_fetch_url(reg: Registry) -> None:
    _, lab = _lan_source_clones(reg)
    res = ccs.sync_clone(lab)
    assert res.result == ccs.UP_TO_DATE, res
    assert res.repo == "OmniNode-ai/omnimarket"


def test_identity_run_sync_finds_and_advances_a_clone_with_a_plain_fetch_url(
    reg: Registry,
) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    assert ccs.sync_clone(source).result == ccs.ADVANCED

    results = ccs.run_sync(reg.env(), ["OmniNode-ai/omnimarket"], "manual")

    assert [(r.clone, r.repo, r.result) for r in results] == [
        (str(lab), "OmniNode-ai/omnimarket", ccs.ADVANCED)
    ]
    (res,) = results
    assert (res.before, res.after, res.target) == (before, target, target)
    assert _head(lab) == target
    assert not any(row["result"] == ccs.NO_CLONE for row in reg.log())


def test_lan_source_fetch_branch_uses_source_tracking_ref_not_source_head(
    reg: Registry,
) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    # A fetch advances the source's origin/main without moving its local main.
    # Those distinct SHAs discriminate the two possible fetch refspecs.
    _git("fetch", "--quiet", "origin", cwd=source)
    assert _head(source) == before
    assert _git("rev-parse", "origin/main", cwd=source) == target

    fetch = ccs._fetch_branch(lab, "origin", "main")

    assert fetch.code == 0, fetch
    assert _git("rev-parse", "origin/main", cwd=lab) == target
    assert _head(lab) == before


def test_lan_source_g1_advances_without_access_to_github(reg: Registry) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    source_res = ccs.sync_clone(source)
    assert source_res.result == ccs.ADVANCED, source_res
    assert _git("rev-parse", "origin/main", cwd=source) == target
    github = reg.remotes / "OmniNode-ai" / "omnimarket.git"
    github.rename(reg.tmp / "github-unavailable.git")
    assert not github.exists()
    assert _git("remote", "get-url", "origin", cwd=source) == str(github)

    res = ccs.sync_clone(lab)

    assert res.result == ccs.ADVANCED, res
    assert (res.before, res.after, res.target) == (before, target, target)
    assert _head(lab) == target
    assert res.branch == "main"
    assert _git("remote", cwd=lab) == "origin"
    assert _git("remote", "get-url", "origin", cwd=lab) == str(source)
    assert res.repo == "OmniNode-ai/omnimarket"


def test_lan_source_e1_stays_at_old_sha_until_source_advances(reg: Registry) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    assert target != before
    assert _git("rev-parse", "origin/main", cwd=source) == before

    res = ccs.sync_clone(lab)

    assert res.result == ccs.UP_TO_DATE, res
    assert (res.before, res.after, res.target) == (before, before, before)
    assert _head(lab) == before
    assert _head(lab) != target
    assert _git("rev-parse", "origin/main", cwd=source) == before
    assert res.repo == "OmniNode-ai/omnimarket"


def test_lan_source_e3_unreachable_source_fails_without_github_fallback(
    reg: Registry,
) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    github = reg.remotes / "OmniNode-ai" / "omnimarket.git"
    assert github.is_dir()
    assert _git("rev-parse", "refs/heads/main", cwd=github) == target
    # The available GitHub remote is not configured on the lab at all.
    assert _git("remote", cwd=lab) == "origin"
    assert _git("remote", "get-url", "origin", cwd=lab) == str(source)
    source.rename(reg.tmp / "mac-unavailable")
    assert not source.exists()

    res = ccs.sync_clone(lab)

    assert res.result == ccs.FAILED, res
    assert "fetch origin main failed" in (res.reason or "")
    assert res.before == before
    assert _head(lab) == before
    assert _git("rev-parse", "origin/main", cwd=lab) == before
    assert _git("remote", cwd=lab) == "origin"
    assert _git("remote", "get-url", "origin", cwd=lab) == str(source)
    assert github.is_dir()
    assert res.repo == "OmniNode-ai/omnimarket"


def test_lan_source_e2_dirty_lab_behind_target_is_refused_without_changes(
    reg: Registry,
) -> None:
    source, lab = _lan_source_clones(reg)
    before = _head(lab)
    target = reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    _git("fetch", "--quiet", "origin", cwd=source)
    assert _git("rev-parse", "origin/main", cwd=source) == target
    dirty = lab / "b.txt"
    dirty.write_text("uncommitted lab work\n")
    status_before = _git("status", "--porcelain", cwd=lab)

    res = ccs.sync_clone(lab)

    assert res.result == ccs.REFUSED, res
    assert "uncommitted" in (res.reason or "")
    assert res.before == before
    assert res.target == target
    assert _head(lab) == before
    assert dirty.read_text() == "uncommitted lab work\n"
    assert _git("status", "--porcelain", cwd=lab) == status_before
    assert res.repo == "OmniNode-ai/omnimarket"


def test_lan_source_e2_dirty_lab_already_at_target_is_up_to_date(reg: Registry) -> None:
    _, lab = _lan_source_clones(reg)
    before = _head(lab)
    dirty = lab / "b.txt"
    dirty.write_text("uncommitted lab work\n")
    status_before = _git("status", "--porcelain", cwd=lab)

    res = ccs.sync_clone(lab)

    assert res.result == ccs.UP_TO_DATE, res
    assert (res.before, res.after, res.target) == (before, before, before)
    assert _head(lab) == before
    assert dirty.read_text() == "uncommitted lab work\n"
    assert _git("status", "--porcelain", cwd=lab) == status_before
    assert res.repo == "OmniNode-ai/omnimarket"


@pytest.mark.parametrize(
    ("advance", "missing_remote_head"),
    [(False, False), (True, False), (True, True)],
    ids=["up_to_date", "advanced", "advanced_with_reason"],
)
def test_lan_source_sync_cli_prints_full_shas_and_keeps_branch_column(
    reg: Registry,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    advance: bool,
    missing_remote_head: bool,
) -> None:
    # Use the existing GitHub-shaped local URL to isolate CLI formatting from
    # the independent identity-discovery and LAN-fetch contract failures.
    clone = reg.make("omnimarket", branch="main", owner="OmniNode-ai")
    before = _head(clone)
    after = (
        reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
        if advance
        else before
    )
    if missing_remote_head:
        github = reg.remotes / "OmniNode-ai" / "omnimarket.git"
        _git("symbolic-ref", "HEAD", "refs/heads/absent", cwd=github)
    for key, value in reg.env().items():
        monkeypatch.setenv(key, value)

    assert ccs.main(["sync", "--repo", "OmniNode-ai/omnimarket"]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    (line,) = captured.out.splitlines()
    result = ccs.ADVANCED if advance else ccs.UP_TO_DATE
    assert line.split()[:3] == [result, str(clone), "main"]
    (record,) = [row for row in reg.log() if row.get("clone") == str(clone)]
    reason = record["reason"] or ""
    if missing_remote_head:
        assert "remote set-head origin --auto failed" in reason
        assert line.split(maxsplit=4)[4] == reason
    assert line == f"{result:10} {clone} main {before}->{after} {reason}".rstrip()


@pytest.mark.parametrize(
    "result", [ccs.ADVANCED, ccs.UP_TO_DATE, ccs.REFUSED, ccs.FAILED]
)
def test_lan_source_json_log_has_receipt_ref_and_path_for_every_clone_result(
    reg: Registry, result: str
) -> None:
    # All four clone outcomes must carry receipt coordinates. Keep discovery
    # independent of onex.repo so a missing identity cannot mask missing keys.
    clone = reg.make("omnimarket", branch="main", owner="OmniNode-ai")
    if result in (ccs.ADVANCED, ccs.REFUSED):
        reg.advance("omnimarket", branch="main", owner="OmniNode-ai")
    if result == ccs.REFUSED:
        (clone / "b.txt").write_text("uncommitted\n")
    if result == ccs.FAILED:
        github = reg.remotes / "OmniNode-ai" / "omnimarket.git"
        github.rename(reg.tmp / "github-unavailable.git")

    (res,) = ccs.run_sync(reg.env(), None, "manual")

    assert res.result == result, res
    rows = [row for row in reg.log() if row.get("result") == result]
    assert len(rows) == 1
    (record,) = rows
    assert {"ref", "path"} <= record.keys(), record
    assert record["ref"] == "main"
    assert record["path"] == str(clone)


# --------------------------------------------------------------------------- #
# matcher
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "gh pr merge 123 --squash --repo OmniNode-ai/omniclaude",
            [("gh-pr-merge", "OmniNode-ai/omniclaude", False)],
        ),
        (
            "gh pr merge 12 -R OmniNode-ai/omnimarket --squash --auto",
            [("gh-pr-merge", "OmniNode-ai/omnimarket", True)],
        ),
        (
            "gh pr merge https://github.com/OmniNode-ai/omnimarket/pull/12 --squash",
            [("gh-pr-merge", "OmniNode-ai/omnimarket", False)],
        ),
        ("gh pr merge 12 --squash", [("gh-pr-merge", None, False)]),
        (
            "gh pr merge my-branch --squash --delete-branch",
            [("gh-pr-merge", None, False)],
        ),
        (
            "cd /x && gh pr merge 5 --repo=Acme/r --squash",
            [("gh-pr-merge", "Acme/r", False)],
        ),
        ("GH_REPO=Acme/r gh pr merge 5 --squash", [("gh-pr-merge", "Acme/r", False)]),
        (
            "timeout 60 gh pr merge 5 --repo Acme/r --squash",
            [("gh-pr-merge", "Acme/r", False)],
        ),
        (
            "/opt/homebrew/bin/gh pr merge 5 -R Acme/r -s",
            [("gh-pr-merge", "Acme/r", False)],
        ),
        (
            'gh pr merge 5 --repo Acme/r --squash --subject "fix: a merge" --body "x"',
            [("gh-pr-merge", "Acme/r", False)],
        ),
        (
            "gh api -X PUT repos/Acme/r/pulls/5/merge -f merge_method=squash",
            [("gh-api-merge", "Acme/r", False)],
        ),
        (
            "gh api --method PUT /repos/Acme/r/pulls/5/merge -f sha=abc",
            [("gh-api-merge", "Acme/r", False)],
        ),
        (
            "gh api --method=put repos/Acme/r/pulls/5/merge",
            [("gh-api-merge", "Acme/r", False)],
        ),
        (
            "gh api -XPUT repos/Acme/r/pulls/5/merge",
            [("gh-api-merge", "Acme/r", False)],
        ),
        (
            "gh api -X PUT 'repos/{owner}/{repo}/pulls/5/merge'",
            [("gh-api-merge", None, False)],
        ),
        (
            "uv run python scripts/ci/bulk_pr_throttle.py --owner Acme --repo r --prs 1,2 --operation arm-automerge",
            [("bulk-throttle-arm", "Acme/r", True)],
        ),
        (
            "gh pr merge 1 --repo Acme/a --squash; gh pr merge 2 --repo Acme/b --squash",
            [("gh-pr-merge", "Acme/a", False), ("gh-pr-merge", "Acme/b", False)],
        ),
    ],
)
def test_matcher_recognises_merge_verbs(
    command: str, expected: list[tuple[str, str | None, bool]]
) -> None:
    triggers = ccs.match_bash_command(command)
    assert [(t.verb, t.repo, t.armed) for t in triggers] == expected


@pytest.mark.parametrize(
    "command",
    [
        "gh api repos/Acme/r/pulls/5/merge",
        "gh api -X GET repos/Acme/r/pulls/5/merge",
        "gh api -X PUT repos/Acme/r/pulls/5/update-branch",
        "gh pr view 5 --repo Acme/r",
        "gh pr checks 5 --repo Acme/r",
        "gh pr merge 5 --repo Acme/r --disable-auto",
        "git merge --ff-only origin/dev",
        "echo 'gh pr merge 5 --repo Acme/r'",
        "grep -n 'gh pr merge' docs/x.md",
        "python3 scripts/ci/bulk_pr_throttle.py --owner Acme --repo r --prs 1 --operation update-branch",
        "python3 scripts/ci/bulk_pr_throttle.py --owner Acme --repo r --prs 1 --operation arm-automerge --dry-run",
        "gh pr merge 'unterminated",
    ],
)
def test_matcher_ignores_non_merges(command: str) -> None:
    assert ccs.match_bash_command(command) == []


def test_matcher_reads_the_mcp_merge_tool() -> None:
    payload = {
        "tool_name": "mcp__github__merge_pull_request",
        "tool_input": {"owner": "OmniNode-ai", "repo": "omnimarket", "pullNumber": 5},
        "tool_response": {"merged": True},
    }
    triggers = ccs.triggers_from_payload(payload)
    assert [(t.verb, t.repo) for t in triggers] == [
        ("mcp-merge", "OmniNode-ai/omnimarket")
    ]


@pytest.mark.parametrize(
    "response",
    [
        {"exit_code": 1, "stdout": "", "stderr": "not mergeable"},
        {"exitCode": 1},
        {"interrupted": True},
        {"is_error": True},
    ],
)
def test_matcher_ignores_a_failed_tool_call(response: dict[str, object]) -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr merge 5 --repo Acme/r --squash"},
        "tool_response": response,
    }
    assert ccs.triggers_from_payload(payload) == []


def test_matcher_ignores_other_tools() -> None:
    payload = {"tool_name": "Read", "tool_input": {"file_path": "/x/gh pr merge"}}
    assert ccs.triggers_from_payload(payload) == []


def test_matcher_treats_a_successful_bash_merge_as_a_trigger() -> None:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "gh pr merge 5 --repo Acme/r --squash"},
        "tool_response": {"stdout": "Merged", "stderr": "", "interrupted": False},
    }
    assert [(t.verb, t.repo) for t in ccs.triggers_from_payload(payload)] == [
        ("gh-pr-merge", "Acme/r")
    ]


# --------------------------------------------------------------------------- #
# engine
# --------------------------------------------------------------------------- #
def test_engine_advances_a_clean_clone_behind_its_upstream(reg: Registry) -> None:
    clone = reg.make("svc")
    before = _head(clone)
    target = reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED, res
    assert (res.before, res.after, res.target) == (before, target, target)
    assert _head(clone) == target
    assert res.repo == "Acme/svc"
    assert res.branch == "dev"


def test_engine_reports_up_to_date(reg: Registry) -> None:
    clone = reg.make("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.UP_TO_DATE
    assert res.before == res.after == res.target == _head(clone)


def test_engine_advances_despite_untracked_files(reg: Registry) -> None:
    clone = reg.make("svc")
    (clone / "scratch.txt").write_text("lane artifact\n")
    target = reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED
    assert _head(clone) == target
    assert (clone / "scratch.txt").read_text() == "lane artifact\n"


def test_engine_refuses_a_dirty_clone_and_moves_nothing(reg: Registry) -> None:
    clone = reg.make("svc")
    before = _head(clone)
    (clone / "b.txt").write_text("uncommitted\n")
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "uncommitted" in (res.reason or "")
    assert _head(clone) == before
    assert (clone / "b.txt").read_text() == "uncommitted\n"


def test_engine_refuses_staged_changes(reg: Registry) -> None:
    clone = reg.make("svc")
    before = _head(clone)
    (clone / "b.txt").write_text("staged\n")
    _git("add", "b.txt", cwd=clone)
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "staged" in (res.reason or "")
    assert _head(clone) == before


def test_engine_refuses_a_diverged_clone(reg: Registry) -> None:
    clone = reg.make("svc")
    (clone / "b.txt").write_text("local commit\n")
    _git("commit", "--quiet", "-am", "local", cwd=clone)
    before = _head(clone)
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "diverged" in (res.reason or "")
    assert _head(clone) == before


def test_engine_refuses_a_clone_ahead_of_its_upstream(reg: Registry) -> None:
    clone = reg.make("svc")
    (clone / "b.txt").write_text("unpushed\n")
    _git("commit", "--quiet", "-am", "unpushed", cwd=clone)
    before = _head(clone)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "ahead" in (res.reason or "")
    assert _head(clone) == before


def test_engine_refuses_a_detached_clone(reg: Registry) -> None:
    clone = reg.make("svc")
    _git("checkout", "--quiet", "--detach", cwd=clone)
    before = _head(clone)
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "detached" in (res.reason or "")
    assert _head(clone) == before


def test_engine_refuses_a_clone_on_a_lane_branch(reg: Registry) -> None:
    clone = reg.make("svc")
    _git("checkout", "--quiet", "-b", "lane/omn-1-work", cwd=clone)
    before = _head(clone)
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "not a tracking branch" in (res.reason or "")
    assert _git("branch", "--show-current", cwd=clone) == "lane/omn-1-work"
    assert _head(clone) == before


def test_engine_refuses_a_bare_clone(reg: Registry) -> None:
    clone = reg.make("svc")
    _git("config", "core.bare", "true", cwd=clone)
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "core.bare" in (res.reason or "")


def test_engine_refuses_a_clone_mid_merge(reg: Registry) -> None:
    clone = reg.make("svc")
    before = _head(clone)
    (clone / ".git" / "MERGE_HEAD").write_text(before + "\n")
    reg.advance("svc")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "MERGE_HEAD" in (res.reason or "")
    assert _head(clone) == before


def test_engine_follows_main_on_a_main_only_clone(reg: Registry) -> None:
    clone = reg.make("docs", branch="main")
    target = reg.advance("docs", branch="main")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED
    assert res.upstream == "origin/main"
    assert _head(clone) == target


# --- the remote default branch (RULING 2026-10-04T10:11:35Z) --------------- #
def _set_origin_head(
    reg: Registry, name: str, branch: str, owner: str = "Acme"
) -> None:
    """Point the bare origin's HEAD (its real default branch) at ``branch``."""
    remote = reg.remotes / owner / f"{name}.git"
    _git("symbolic-ref", "HEAD", f"refs/heads/{branch}", cwd=remote)


def _parked_on_main(
    reg: Registry,
    name: str = "svc",
    *,
    local_dev: bool = True,
    set_head: bool = True,
    origin_head: str = "dev",
) -> Path:
    """A clone parked on ``main`` whose remote default branch is ``origin_head``.

    The remote carries both branches; ``dev`` is then advanced on the remote so
    there is something to fast-forward. ``set_head=False`` leaves the clone
    with no ``refs/remotes/origin/HEAD`` symref.
    """
    clone = reg.make(name, branch="main")
    seed = reg.seeds / "Acme" / name
    _git("checkout", "--quiet", "-b", "dev", cwd=seed)
    _git("push", "--quiet", "origin", "dev", cwd=seed)
    _set_origin_head(reg, name, origin_head)
    _git("fetch", "--quiet", "origin", cwd=clone)
    if local_dev:
        _git("branch", "--track", "dev", "origin/dev", cwd=clone)
    if set_head:
        _git("remote", "set-head", "origin", "dev", cwd=clone)
    else:
        _git("remote", "set-head", "origin", "-d", cwd=clone)
    reg.advance(name, branch="dev")
    return clone


def _head_branch(clone: Path) -> str:
    return _git("symbolic-ref", "--short", "HEAD", cwd=clone)


def _local_refs(clone: Path) -> str:
    return _git("for-each-ref", "refs/heads", cwd=clone)


def test_engine_returns_a_clean_clone_on_main_to_the_remote_default(
    reg: Registry,
) -> None:
    clone = _parked_on_main(reg)
    main_sha = _head(clone)
    res = ccs.sync_clone(clone)
    target = _git("rev-parse", "origin/dev", cwd=clone)
    assert res.result == ccs.ADVANCED, res
    assert (res.branch, res.switched_from) == ("dev", "main")
    assert res.upstream == "origin/dev"
    assert (res.before, res.after, res.target) == (main_sha, target, target)
    assert _head_branch(clone) == "dev"
    assert _head(clone) == target


def test_engine_creates_the_default_branch_when_no_local_copy_exists(
    reg: Registry,
) -> None:
    clone = _parked_on_main(reg, local_dev=False)
    assert "dev" not in _local_refs(clone)
    res = ccs.sync_clone(clone)
    target = _git("rev-parse", "origin/dev", cwd=clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from == "main"
    assert _head_branch(clone) == "dev"
    assert _head(clone) == target
    assert _git("config", "branch.dev.remote", cwd=clone) == "origin"
    assert _git("config", "branch.dev.merge", cwd=clone) == "refs/heads/dev"


def test_engine_refuses_the_switch_when_local_default_carries_commits(
    reg: Registry,
) -> None:
    clone = _parked_on_main(reg)
    _git("switch", "--quiet", "dev", cwd=clone)
    (clone / "b.txt").write_text("unpushed\n")
    _git("commit", "--quiet", "-am", "unpushed", cwd=clone)
    _git("switch", "--quiet", "main", cwd=clone)
    refs_before = _local_refs(clone)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    reason = res.reason or ""
    assert "main" in reason and "dev" in reason
    assert "1 commit(s) origin/dev does not" in reason
    assert res.switched_from is None
    assert _head_branch(clone) == "main"
    assert _local_refs(clone) == refs_before


def test_engine_refuses_the_switch_over_tracked_changes(reg: Registry) -> None:
    clone = _parked_on_main(reg)
    (clone / "a.txt").write_text("dirt\n")
    refs_before = _local_refs(clone)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    assert "main" in (res.reason or "") and "dev" in (res.reason or "")
    assert _head_branch(clone) == "main"
    assert (clone / "a.txt").read_text() == "dirt\n"
    assert _local_refs(clone) == refs_before


def test_engine_never_switches_a_shared_commit_lock_tree(reg: Registry) -> None:
    clone = _parked_on_main(reg)
    lock = clone / ccs.SHARED_TREE_COMMIT_LOCK
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.touch()
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    assert "commit_lock" in (res.reason or "")
    assert _head_branch(clone) == "main"


def test_engine_refuses_the_switch_with_an_index_lock(reg: Registry) -> None:
    clone = _parked_on_main(reg)
    (clone / ".git" / "index.lock").touch()
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    assert "index.lock" in (res.reason or "")
    assert _head_branch(clone) == "main"


def test_engine_refuses_when_git_refuses_the_switch_over_an_untracked_file(
    reg: Registry,
) -> None:
    clone = _parked_on_main(reg)
    reg.advance("svc", path="new.txt", text="remote\n", branch="dev")
    _git("fetch", "--quiet", "origin", cwd=clone)
    _git("branch", "--force", "dev", "origin/dev", cwd=clone)
    (clone / "new.txt").write_text("local untracked\n")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    assert "new.txt" in (res.reason or "")
    assert res.switched_from is None
    assert _head_branch(clone) == "main"
    assert (clone / "new.txt").read_text() == "local untracked\n"


def test_engine_reports_a_fast_forward_git_refuses_after_the_switch(
    reg: Registry,
) -> None:
    clone = _parked_on_main(reg)
    reg.advance("svc", path="new.txt", text="remote\n", branch="dev")
    (clone / "new.txt").write_text("local untracked\n")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED, res
    assert "new.txt" in (res.reason or "")
    assert (res.branch, res.switched_from) == ("dev", "main")
    assert _head_branch(clone) == "dev"
    assert (clone / "new.txt").read_text() == "local untracked\n"


def _install_switch_guard(
    tmp: Path, monkeypatch: pytest.MonkeyPatch, *, half_apply: bool = False
) -> None:
    """A stand-in for the canonical-clone ``reference-transaction`` guard.

    The real guard denies a ``HEAD`` symref move (a branch switch) unless the
    sanctioned ``ONEX_CANONICAL_CONVERGE=1`` door is open. Git before 2.45 does
    not run ``reference-transaction`` for a symref move at all, so a fixture
    hook cannot refuse anything on such a host. This ``git`` shim on ``PATH``
    refuses at the same seam instead -- ``git switch`` -- for every caller, the
    engine and the test alike, which makes the plain ``git switch`` in the tests
    a positive control.

    ``half_apply`` reproduces OMN-18358: the guard checks the target tree out,
    then refuses even through the door, leaving HEAD on the old branch.
    """
    real = shutil.which("git")
    assert real
    shim_dir = tmp / "switch-guard-bin"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    lines = [
        "#!/bin/sh",
        'sub=$1; [ "$1" = -C ] && sub=$3',
        'if [ "$sub" = switch ]; then',
    ]
    if half_apply:
        lines += [
            '  last=; for a in "$@"; do last=$a; done',
            f'  "{real}" -C "$2" checkout --quiet "$last" -- . 2>/dev/null',
            '  echo "DENIED HEAD move" >&2; exit 1',
        ]
    else:
        lines += [
            '  [ "$ONEX_CANONICAL_CONVERGE" = 1 ] || { echo "DENIED HEAD move" >&2; exit 1; }'
        ]
    lines += ["fi", f'exec "{real}" "$@"', ""]
    shim.write_text("\n".join(lines))
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")


def test_engine_opens_the_converge_door_for_the_switch_alone(
    reg: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _parked_on_main(reg)
    _install_switch_guard(tmp_path, monkeypatch)
    # Positive control: the guard really does refuse a plain switch.
    with pytest.raises(subprocess.CalledProcessError) as denied:
        _git("switch", "--quiet", "dev", cwd=clone)
    assert "DENIED HEAD move" in denied.value.stderr
    assert _head_branch(clone) == "main"

    res = ccs.sync_clone(clone)
    target = _git("rev-parse", "origin/dev", cwd=clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from == "main"
    assert _head_branch(clone) == "dev"
    assert _head(clone) == target
    # The door was open for that one call only.
    assert "ONEX_CANONICAL_CONVERGE" not in os.environ
    with pytest.raises(subprocess.CalledProcessError):
        _git("switch", "--quiet", "main", cwd=clone)


def test_engine_reports_a_guard_refusal_that_left_the_tree_half_applied(
    reg: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _parked_on_main(reg, local_dev=False)
    _install_switch_guard(tmp_path, monkeypatch, half_apply=True)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.FAILED, res
    assert res.switched_from is None
    assert "half-applied" in (res.reason or "")
    assert _head_branch(clone) == "main"


def test_engine_keeps_its_old_behaviour_without_a_remote_head_symref(
    reg: Registry,
) -> None:
    # The origin's own default really is main, so a refreshed symref names the
    # checked-out branch and there is nothing to switch to.
    clone = _parked_on_main(reg, set_head=False, origin_head="main")
    assert not _git("for-each-ref", "refs/remotes/origin/HEAD", cwd=clone)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.UP_TO_DATE, res
    assert res.switched_from is None
    assert _head_branch(clone) == "main"


def test_engine_carries_unrelated_dirt_in_a_shared_commit_lock_tree(
    reg: Registry,
) -> None:
    clone = reg.make("home", branch="main")
    (clone / ".onex_state").mkdir()
    (clone / ".onex_state" / "commit.lock").write_text("")
    (clone / "b.txt").write_text("ledger append in flight\n")
    target = reg.advance("home", branch="main", path="a.txt")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED, res
    assert res.carried_dirty_paths == 1
    assert _head(clone) == target
    assert (clone / "b.txt").read_text() == "ledger append in flight\n"


def test_engine_refuses_overlapping_dirt_in_a_shared_tree(reg: Registry) -> None:
    clone = reg.make("home", branch="main")
    (clone / ".onex_state").mkdir()
    (clone / ".onex_state" / "commit.lock").write_text("")
    before = _head(clone)
    (clone / "a.txt").write_text("local edit\n")
    reg.advance("home", branch="main", path="a.txt")
    res = ccs.sync_clone(clone)
    assert res.result == ccs.REFUSED
    assert "also changed upstream" in (res.reason or "")
    assert _head(clone) == before
    assert (clone / "a.txt").read_text() == "local edit\n"


def test_engine_run_logs_every_clone_and_filters_by_repo(reg: Registry) -> None:
    svc = reg.make("svc")
    other = reg.make("other")
    other_before = _head(other)
    target = reg.advance("svc")
    reg.advance("other")
    results = ccs.run_sync(reg.env(), ["acme/SVC"], "manual")
    assert [(r.clone, r.result) for r in results] == [(str(svc), ccs.ADVANCED)]
    assert _head(other) == other_before
    log = reg.log()
    rows = [r for r in log if r.get("clone") == str(svc)]
    assert rows and rows[0]["before"] and rows[0]["after"] == target
    assert log[-1]["result"] == "RUN_COMPLETE"


def test_engine_run_logs_no_clone_for_an_unknown_repo(reg: Registry) -> None:
    reg.make("svc")
    ccs.run_sync(reg.env(), ["Acme/absent"], "manual")
    assert any(
        r.get("result") == ccs.NO_CLONE and r.get("repo") == "acme/absent"
        for r in reg.log()
    )


def test_engine_covers_every_registry_root_and_the_roots_file(reg: Registry) -> None:
    second = reg.tmp / "second_root"
    second.mkdir()
    third = reg.tmp / "third_root"
    third.mkdir()
    a = reg.make("svc")
    b = reg.make("svc2", root=second)
    c = reg.make("svc3", root=third)
    roots_file = reg.home / "scripts" / "git-hooks" / "registry-roots"
    roots_file.parent.mkdir(parents=True)
    roots_file.write_text(f"# header\nroot={reg.home}\nroot={third}\n")
    for name in ("svc", "svc2", "svc3"):
        reg.advance(name)
    results = ccs.run_sync(reg.env(ONEX_REGISTRY_ROOTS=str(second)), None, "timer")
    assert {(r.clone, r.result) for r in results} == {
        (str(a), ccs.ADVANCED),
        (str(b), ccs.ADVANCED),
        (str(c), ccs.ADVANCED),
    }


def test_engine_skips_linked_worktrees(reg: Registry) -> None:
    clone = reg.make("svc")
    _git("worktree", "add", "--quiet", str(reg.home / "wt"), "-b", "lane", cwd=clone)
    clones = ccs.discover_clones([reg.home])
    assert clones == [clone]


# --------------------------------------------------------------------------- #
# hook
# --------------------------------------------------------------------------- #
def _run_hook(
    payload: str, env: Mapping[str, str]
) -> tuple[subprocess.CompletedProcess[str], float]:
    started = time.monotonic()
    proc = subprocess.run(
        ["bash", str(_HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=dict(env),
        timeout=30,
        check=False,
    )
    return proc, time.monotonic() - started


def _merge_payload(command: str, cwd: str = "/tmp") -> str:
    return json.dumps(
        {
            "session_id": "s",
            "cwd": cwd,
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
        }
    )


def test_hook_is_silent_and_fast_on_a_non_merge(reg: Registry) -> None:
    proc, elapsed = _run_hook(_merge_payload("ls -la").replace("merge", "x"), reg.env())
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert elapsed < 1.0
    assert reg.log() == []


@pytest.mark.parametrize(
    "payload",
    ["merge {not json", "", "merge", '{"tool_name": "Bash", "tool_input": "merge"}'],
)
def test_hook_exits_zero_on_a_malformed_payload(reg: Registry, payload: str) -> None:
    proc, elapsed = _run_hook(payload, reg.env())
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert elapsed < 1.0


def test_hook_does_nothing_without_omni_home(reg: Registry) -> None:
    env = reg.env()
    env.pop("OMNI_HOME")
    proc, _ = _run_hook(_merge_payload("gh pr merge 5 --repo Acme/svc --squash"), env)
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert reg.log() == []


def test_hook_records_the_trigger_and_returns_fast(reg: Registry) -> None:
    reg.make("svc")
    env = reg.env(ONEX_CLONE_SYNC_HOOK_DRY_RUN="1")
    proc, elapsed = _run_hook(
        _merge_payload("gh pr merge 5 --repo Acme/svc --squash"), env
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert elapsed < 1.0
    (row,) = reg.log()
    assert row["result"] == "TRIGGERED"
    assert row["repos"] == ["Acme/svc"]


def test_hook_resolves_the_repo_from_the_session_cwd(reg: Registry) -> None:
    clone = reg.make("svc")
    env = reg.env(ONEX_CLONE_SYNC_HOOK_DRY_RUN="1")
    proc, _ = _run_hook(_merge_payload("gh pr merge 5 --squash", cwd=str(clone)), env)
    assert proc.returncode == 0
    (row,) = reg.log()
    assert row["repos"] == ["Acme/svc"]


def test_hook_advances_the_clone_through_the_detached_child(reg: Registry) -> None:
    clone = reg.make("svc")
    target = reg.advance("svc")
    proc, elapsed = _run_hook(
        _merge_payload("gh pr merge 5 --repo Acme/svc --squash"), reg.env()
    )
    assert proc.returncode == 0
    assert elapsed < 1.0
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if any(r.get("result") == "RUN_COMPLETE" for r in reg.log()):
            break
        time.sleep(0.2)
    assert _head(clone) == target
    rows = [r for r in reg.log() if r.get("clone") == str(clone)]
    assert rows and rows[0]["result"] == ccs.ADVANCED and rows[0]["trigger"] == "hook"


# --- the default is refreshed from the remote before it is acted on ------- #
def _origin_head_ref(clone: Path) -> str:
    return _git("symbolic-ref", "--short", "refs/remotes/origin/HEAD", cwd=clone)


def test_engine_refreshes_a_stale_symref_and_stays_on_dev(reg: Registry) -> None:
    clone = reg.make("svc", branch="dev")
    _git("push", "--quiet", "origin", "dev:main", cwd=reg.seeds / "Acme" / "svc")
    _git("fetch", "--quiet", "origin", cwd=clone)
    _git("remote", "set-head", "origin", "main", cwd=clone)
    assert _origin_head_ref(clone) == "origin/main"
    reg.advance("svc", branch="dev")
    res = ccs.sync_clone(clone)
    target = _git("rev-parse", "origin/dev", cwd=clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from is None
    assert _head_branch(clone) == "dev"
    assert _head(clone) == target
    assert _origin_head_ref(clone) == "origin/dev"


def test_engine_reaches_the_default_from_a_stale_symref(reg: Registry) -> None:
    clone = _parked_on_main(reg)
    _git("remote", "set-head", "origin", "main", cwd=clone)
    assert _origin_head_ref(clone) == "origin/main"
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from == "main"
    assert _head_branch(clone) == "dev"
    assert _origin_head_ref(clone) == "origin/dev"


def test_engine_never_switches_when_the_refresh_cannot_reach_the_remote(
    reg: Registry,
) -> None:
    clone = reg.make("svc", branch="dev")
    _git("push", "--quiet", "origin", "dev:main", cwd=reg.seeds / "Acme" / "svc")
    _git("fetch", "--quiet", "origin", cwd=clone)
    _git("remote", "set-head", "origin", "main", cwd=clone)
    _git("remote", "set-url", "origin", str(reg.tmp / "no-such-remote.git"), cwd=clone)
    before = _head(clone)
    res = ccs.sync_clone(clone)
    assert res.result in (ccs.FAILED, ccs.REFUSED), res
    assert res.switched_from is None
    assert "set-head" in (res.reason or ""), res
    assert _head_branch(clone) == "dev"
    assert _head(clone) == before


def test_engine_still_returns_to_main_when_main_is_the_origin_default(
    reg: Registry,
) -> None:
    clone = reg.make("svc", branch="main")
    _git("checkout", "--quiet", "-b", "dev", cwd=clone)
    _git("push", "--quiet", "-u", "origin", "dev", cwd=clone)
    assert _origin_head_ref(clone) == "origin/main"
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from == "dev"
    assert _head_branch(clone) == "main"
    assert _origin_head_ref(clone) == "origin/main"


def test_engine_corrects_a_stale_dev_symref_when_main_is_the_origin_default(
    reg: Registry,
) -> None:
    clone = reg.make("svc", branch="main")
    _git("checkout", "--quiet", "-b", "dev", cwd=clone)
    _git("push", "--quiet", "-u", "origin", "dev", cwd=clone)
    _git("remote", "set-head", "origin", "dev", cwd=clone)
    res = ccs.sync_clone(clone)
    assert res.result == ccs.ADVANCED, res
    assert res.switched_from == "dev"
    assert _head_branch(clone) == "main"
    assert _origin_head_ref(clone) == "origin/main"


def test_engine_opens_the_converge_door_for_set_head(
    reg: Registry, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard that refuses a plain ``remote set-head`` still lets the engine through."""
    clone = reg.make("svc", branch="dev")
    _git("push", "--quiet", "origin", "dev:main", cwd=reg.seeds / "Acme" / "svc")
    _git("fetch", "--quiet", "origin", cwd=clone)
    _git("remote", "set-head", "origin", "main", cwd=clone)
    real = shutil.which("git")
    assert real
    shim_dir = tmp_path / "set-head-guard-bin"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        "#!/bin/sh\n"
        'sub=$1; [ "$1" = -C ] && sub=$3\n'
        'if [ "$sub" = remote ]; then\n'
        '  [ "$ONEX_CANONICAL_CONVERGE" = 1 ] || { echo "DENIED HEAD move" >&2; exit 1; }\n'
        "fi\n"
        f'exec "{real}" "$@"\n'
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")
    with pytest.raises(subprocess.CalledProcessError) as denied:
        _git("remote", "set-head", "origin", "--auto", cwd=clone)
    assert "DENIED HEAD move" in denied.value.stderr
    res = ccs.sync_clone(clone)
    assert res.result in (ccs.UP_TO_DATE, ccs.ADVANCED), res
    assert _origin_head_ref(clone) == "origin/dev"
    assert "ONEX_CANONICAL_CONVERGE" not in os.environ
