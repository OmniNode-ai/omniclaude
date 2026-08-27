# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behavioural tests for the gate-escape deny list in
``scripts/user-hooks/canonical-clone-guard.py``.

OMN-16725. The system under test is the repo copy of the user-level Claude Code
PreToolUse hook — the declared source of truth that
``scripts/install-canonical-clone-guard.sh`` installs to ``~/.claude/hooks/``.
Sibling file ``test_canonical_clone_guard.py`` (OMN-16496) covers the
canonical-clone scan; this file covers only the gate-escape deny list.

It is driven exactly the way Claude Code drives it — as a
subprocess with the hook JSON on stdin — with ``OMNI_HOME`` / ``HOME`` pointed
at a scratch registry so the guard's own log lands under the scratch
``$OMNI_HOME/.onex_state/hooks/`` and nothing touches the real machine.

Three things are covered, and the third matters as much as the first:

  DENIED      every pattern in the OMN-16725 deny list actually refuses.
  ALLOWED     every NEAR MISS still passes. A guard that denies
              ``git push -n`` (which is ``--dry-run``, not ``--no-verify``),
              ``grep --no-verify``, ``git commit -m"no-op"``, or a heredoc that
              DOCUMENTS a forbidden flag would be worse than no guard at all:
              it would train agents to route around it.
  MESSAGES    every deny reason names the failure mode AND the mechanical
              alternative (memory feedback_workers_disregard_negative_directives
              — a bare prohibition gets worked around).

Plus a no-weakening regression block: the pre-existing canonical-clone denials
must still fire unchanged.

Run:
    uv run pytest tests/scripts/test_canonical_clone_guard_bypass.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "user-hooks" / "canonical-clone-guard.py"

CANONICAL_REPOS = ("omnimarket", "omnibase_infra", "omniclaude")
WORKTREE = "OMN-16725/omniclaude"


@dataclass(frozen=True)
class Registry:
    home: Path
    omni_home: Path

    def clone(self, name: str) -> Path:
        return self.omni_home / name

    @property
    def worktree(self) -> Path:
        return self.omni_home / "omni_worktrees" / WORKTREE


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    home = tmp_path / "home"
    omni_home = home / "omni_home"
    for repo in CANONICAL_REPOS:
        (omni_home / repo / ".git").mkdir(parents=True)
    (omni_home / "omni_worktrees" / WORKTREE).mkdir(parents=True)
    (home / ".claude" / "hooks").mkdir(parents=True)
    return Registry(home=home, omni_home=omni_home)


def run_guard(
    registry: Registry, tool_name: str, tool_input: dict[str, object], cwd: Path
) -> Verdict:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(registry.home)}
    env["OMNI_HOME"] = str(registry.omni_home)
    payload = json.dumps(
        {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd)}
    )
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, (
        f"guard must always exit 0 (got {proc.returncode})\n{proc.stderr}"
    )
    if not proc.stdout.strip():
        return Verdict(decision="allow", reason="")
    hso = json.loads(proc.stdout)["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    return Verdict(
        decision=hso["permissionDecision"], reason=hso["permissionDecisionReason"]
    )


def bash(registry: Registry, command: str, cwd: Path | None = None) -> Verdict:
    return run_guard(registry, "Bash", {"command": command}, cwd or registry.worktree)


# --- DENIED: every pattern in the deny list --------------------------------

DENIED = [
    # core.hooksPath override — the live 2026-08-25/27 incident.
    ("hookspath -c", 'git -c core.hooksPath=/dev/null commit -m "x"'),
    ("hookspath -c lowercase key", "git -c core.hookspath=/tmp/h commit"),
    (
        "hookspath -c mixed with other config",
        'git -c user.name=x -c core.hooksPath=/dev/null commit -m "y"',
    ),
    ("hookspath --config-env", "git --config-env=core.hooksPath=HP commit -m x"),
    ("hookspath persisted via git config", "git config core.hooksPath /dev/null"),
    ("hookspath persisted --local", "git config --local core.hooksPath /tmp/nohooks"),
    # --no-verify on any subcommand.
    ("commit --no-verify", 'git commit --no-verify -m "x"'),
    ("push --no-verify", "git push --no-verify"),
    ("push --no-verify with remote", "git push --no-verify origin HEAD"),
    ("merge --no-verify", "git merge --no-verify feature"),
    ("--no-verify after git -C", 'git -C /tmp/repo commit --no-verify -m "x"'),
    # -n where it MEANS --no-verify (commit only).
    ("commit -n", 'git commit -n -m "x"'),
    ("commit -n clustered with -a", 'git commit -an -m "x"'),
    ("commit -nm cluster", 'git commit -nm "x"'),
    # pre-push escape variables.
    ("PREPUSH_FULL_SUITE prefix", "PREPUSH_FULL_SUITE=1 git push"),
    ("PREPUSH_FULL_SUITE exported", "export PREPUSH_FULL_SUITE=1"),
    ("PREPUSH_ALLOW_* prefix", "PREPUSH_ALLOW_LOCAL_FULL_SUITE=1 git push"),
    ("PREPUSH_ALLOW_* exported", "export PREPUSH_ALLOW_SOMETHING_ELSE=1"),
    ("PREPUSH_LOAD_THRESHOLD", "PREPUSH_LOAD_THRESHOLD=99 git push"),
    ("ENABLE_SMART_TESTS=off", "ENABLE_SMART_TESTS=off git push"),
    ("ENABLE_SMART_TESTS=0", "ENABLE_SMART_TESTS=0 git push"),
    ("ENABLE_SMART_TESTS=false", "ENABLE_SMART_TESTS=false uv run pytest"),
    # skip tokens in the commit message.
    (
        "skip-deploy-gate token",
        'git commit -m "feat(OMN-1): x [skip-deploy-gate: n/a]"',
    ),
    (
        "skip-receipt-gate token",
        'git commit -am "chore(OMN-1): y [skip-receipt-gate: docs]"',
    ),
    ("skip token via --message=", "git commit --message=fix-[skip-deploy-gate:x]"),
    # laundering attempts that the structural matcher still sees.
    ("compound after cd", "cd /tmp && git commit --no-verify"),
    ("behind an env wrapper", "env git commit --no-verify"),
    ("second segment of a chain", "uv run pytest && git push --no-verify"),
]


@pytest.mark.parametrize(("label", "command"), DENIED, ids=[d[0] for d in DENIED])
def test_gate_escape_is_denied(registry: Registry, label: str, command: str) -> None:
    verdict = bash(registry, command)
    assert verdict.denied, f"{label!r} must be denied: {command}"


# --- ALLOWED: near misses that must never be denied -------------------------

ALLOWED = [
    # `-n` on push is --dry-run, NOT --no-verify. The single most important
    # near miss in this file: denying it would be a factual error about git.
    ("push -n is dry-run", "git push -n"),
    ("push -n with remote", "git push -n origin HEAD"),
    ("push --dry-run", "git push --dry-run"),
    ("commit --dry-run", "git commit --dry-run"),
    # plain, correct usage.
    ("plain commit", 'git commit -m "feat(OMN-16725): extend the guard"'),
    ("plain push", "git push"),
    ("plain push with upstream", "git push -u origin HEAD"),
    ("status", "git status --short"),
    ("log -n", "git log -n 5 --oneline"),
    ("clean -n", "git clean -n"),
    # a flag cluster whose value merely CONTAINS n.
    ("attached -m value containing n", 'git commit -m"no-op formatting pass"'),
    ("message mentioning -n", 'git commit -m "fix: correct -n handling on push"'),
    (
        "message mentioning --no-verify",
        'git commit -m "docs: explain why --no-verify is banned"',
    ),
    (
        "message mentioning a skip token in prose",
        'git commit -m "docs: the skip-deploy-gate escape hatch"',
    ),
    # `-c` AFTER the subcommand is commit-reuse, not global config.
    ("commit -c HEAD is message reuse", "git commit -c HEAD --amend"),
    ("commit -C HEAD is message reuse", "git commit -C HEAD"),
    # config READS and the restore-default form.
    ("config --get hooksPath", "git config --get core.hooksPath"),
    ("config --unset hooksPath", "git config --unset core.hooksPath"),
    ("config --list", "git config --list"),
    # searching or emitting documentation that QUOTES a forbidden flag.
    ("grep --no-verify as its own flag", "grep --no-verify /tmp/file"),
    ("grep for the pattern", 'grep -rn "git commit --no-verify" /tmp'),
    ("rg for the pattern", 'rg "core.hooksPath" /tmp'),
    ("echo quoted", 'echo "never run git commit --no-verify"'),
    ("echo unquoted", "echo git commit --no-verify"),
    ("printf documentation", "printf '%s\\n' git commit --no-verify"),
    ("cat a doc that mentions it", "cat /tmp/why-no-verify-is-banned.md"),
    ("grep for the env var", "grep PREPUSH_ALLOW_ /tmp/hook.sh"),
    ("read the env var", "echo $PREPUSH_FULL_SUITE"),
    # enabling / clearing directions are the SAFE direction.
    ("ENABLE_SMART_TESTS=on", "ENABLE_SMART_TESTS=on git push"),
    ("ENABLE_SMART_TESTS=1", "ENABLE_SMART_TESTS=1 git push"),
    ("PREPUSH_FULL_SUITE cleared", "PREPUSH_FULL_SUITE= git push"),
    # an unrelated variable that merely shares a prefix word.
    ("unrelated PREPUSH var", "PREPUSH_201_GATE_RUNNER_HOSTNAME=omninode-pc git push"),
    # ordinary non-git work.
    ("pytest", "uv run pytest -m unit"),
    ("ruff", "uv run ruff check --fix src/ tests/"),
]


@pytest.mark.parametrize(("label", "command"), ALLOWED, ids=[a[0] for a in ALLOWED])
def test_near_miss_is_allowed(registry: Registry, label: str, command: str) -> None:
    verdict = bash(registry, command)
    assert not verdict.denied, (
        f"{label!r} is legitimate and must NOT be denied: {command}\n{verdict.reason}"
    )


def test_heredoc_documenting_forbidden_flags_is_allowed(registry: Registry) -> None:
    """Authoring a runbook that quotes the bans is not running them."""
    command = (
        "cat > /tmp/runbook.md <<'EOF'\n"
        "Never run: git commit --no-verify\n"
        "Never run: git -c core.hooksPath=/dev/null commit\n"
        "Never set: PREPUSH_FULL_SUITE=1\n"
        "Never set: ENABLE_SMART_TESTS=off\n"
        "EOF\n"
    )
    assert not bash(registry, command).denied


def test_heredoc_close_reopens_scanning(registry: Registry) -> None:
    """A real bypass AFTER the heredoc terminator is still caught."""
    command = (
        "cat > /tmp/doc.md <<'EOF'\ngit commit --no-verify\nEOF\ngit push --no-verify\n"
    )
    assert bash(registry, command).denied


# --- MESSAGES: prohibition + failure mode + alternative ---------------------

MESSAGE_CASES = [
    (
        "git -c core.hooksPath=/dev/null commit",
        ["FAILURE MODE", "is a FILE", "ZERO hooks", "rev-parse --git-path hooks"],
    ),
    (
        "git config core.hooksPath /dev/null",
        ["FAILURE MODE", "PERSISTS", "--unset core.hooksPath"],
    ),
    ("git commit --no-verify", ["FAILURE MODE", "DO THIS INSTEAD"]),
    ("git commit -n", ["--no-verify", "git push -n", "--dry-run", "DO THIS INSTEAD"]),
    (
        'git commit -m "x [skip-deploy-gate: y]"',
        ["FAILURE MODE", "skip-token-allowed", "DO THIS INSTEAD"],
    ),
    (
        "PREPUSH_FULL_SUITE=1 git push",
        ["FAILURE MODE", "FAIL-CLOSED", "DO THIS INSTEAD"],
    ),
    ("PREPUSH_ALLOW_X=1 git push", ["FAILURE MODE", "REJECTS", "DO THIS INSTEAD"]),
    ("PREPUSH_LOAD_THRESHOLD=99 git push", ["FAILURE MODE", "DO THIS INSTEAD"]),
    ("ENABLE_SMART_TESTS=off git push", ["FAILURE MODE", "DO THIS INSTEAD"]),
]


@pytest.mark.parametrize(
    ("command", "fragments"), MESSAGE_CASES, ids=[c[0][:40] for c in MESSAGE_CASES]
)
def test_deny_message_names_failure_mode_and_alternative(
    registry: Registry, command: str, fragments: list[str]
) -> None:
    verdict = bash(registry, command)
    assert verdict.denied, command
    assert verdict.reason.startswith("BLOCKED:"), verdict.reason
    for fragment in fragments:
        assert fragment in verdict.reason, (
            f"deny message for {command!r} is missing {fragment!r}:\n{verdict.reason}"
        )


@pytest.mark.parametrize(("label", "command"), DENIED, ids=[d[0] for d in DENIED])
def test_every_deny_message_offers_an_alternative(
    registry: Registry, label: str, command: str
) -> None:
    """No bare prohibitions: every refusal must tell the caller what to do."""
    reason = bash(registry, command).reason
    assert "FAILURE MODE" in reason, reason
    assert "DO THIS INSTEAD" in reason, reason


# --- NO WEAKENING: pre-existing canonical-clone behaviour is unchanged ------


def test_canonical_clone_commit_still_denied(registry: Registry) -> None:
    verdict = bash(registry, 'git commit -m "x"', cwd=registry.clone("omnimarket"))
    assert verdict.denied
    assert "canonical clone" in verdict.reason


def test_canonical_clone_update_ref_still_denied(registry: Registry) -> None:
    verdict = bash(
        registry,
        "git update-ref refs/heads/dev origin/dev",
        cwd=registry.clone("omnimarket"),
    )
    assert verdict.denied


def test_canonical_clone_edit_still_denied(registry: Registry) -> None:
    target = registry.clone("omniclaude") / "src" / "x.py"
    verdict = run_guard(
        registry, "Edit", {"file_path": str(target)}, registry.clone("omniclaude")
    )
    assert verdict.denied


def test_canonical_clone_pull_still_allowed(registry: Registry) -> None:
    verdict = bash(registry, "git pull --ff-only", cwd=registry.clone("omnimarket"))
    assert not verdict.denied


def test_worktree_commit_still_allowed(registry: Registry) -> None:
    verdict = bash(registry, 'git commit -m "feat(OMN-16725): x"')
    assert not verdict.denied


def test_guard_fails_open_on_garbage_stdin(registry: Registry) -> None:
    proc = subprocess.run(
        [sys.executable, str(GUARD)],
        input="not json at all",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(registry.home),
            "OMNI_HOME": str(registry.omni_home),
        },
        check=False,
    )
    assert proc.returncode == 0
    assert not proc.stdout.strip()
