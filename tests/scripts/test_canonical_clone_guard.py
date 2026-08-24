# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behavioural tests for ``scripts/user-hooks/canonical-clone-guard.py`` (OMN-16496).

The system under test is the user-level Claude Code PreToolUse hook that keeps
agents out of the canonical clones under ``$OMNI_HOME/<repo>`` (omni_home
CLAUDE.md rule 9). It is driven exactly the way Claude Code drives it: as a
subprocess with the hook JSON on stdin, ``OMNI_HOME`` in the environment, and
``HOME`` pointed at a scratch directory so the guard's own log lands there.

Gap coverage from the 2026-08-24 omnimarket forensics (ledger row
2026-08-24T18:29:29Z):

  G2  plumbing verbs (``update-ref`` was used live at 2026-08-23T21:06:54Z to
      move ``refs/heads/dev`` in the canonical clone) are denied on a canonical
      path, while their read-only forms stay allowed.
  G4  the sanctioned convergence script is recognised, the deny message points
      at it, raw ``reset --hard`` stays denied, ``stash list|show`` are allowed.
  G5  ``$OMNI_HOME`` / ``${OMNI_HOME}`` / ``~`` / in-command assignments are
      expanded in ``cd`` and ``git -C`` arguments, so the three logged
      false-positive shapes (guard log lines 155, 181, 206) are allowed.
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
WORKTREES = (
    "OMN-16130/onex_change_control",
    "OMN-16375/omnimarket-0389",
    "OMN-1/omnimarket",
)


@dataclass(frozen=True)
class Registry:
    """A scratch ``$OMNI_HOME`` with fake canonical clones and worktrees."""

    home: Path
    omni_home: Path

    def clone(self, name: str) -> Path:
        return self.omni_home / name

    def worktree(self, rel: str) -> Path:
        return self.omni_home / "omni_worktrees" / rel

    @property
    def log(self) -> str:
        path = self.home / ".claude" / "hooks" / "logs" / "canonical-clone-guard.log"
        return path.read_text(encoding="utf-8") if path.is_file() else ""


@dataclass(frozen=True)
class Verdict:
    decision: str
    reason: str
    log: str

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


@pytest.fixture
def registry(tmp_path: Path) -> Registry:
    home = tmp_path / "home"
    omni_home = home / "omni_home"
    for repo in CANONICAL_REPOS:
        (omni_home / repo / ".git").mkdir(parents=True)
        (omni_home / repo / "src").mkdir()
        (omni_home / repo / ".claude" / "worktrees" / "wf_8eb1198b-fb8-1").mkdir(
            parents=True
        )
    for rel in WORKTREES:
        (omni_home / "omni_worktrees" / rel).mkdir(parents=True)
    (omni_home / "docs" / "tracking").mkdir(parents=True)
    (omni_home / "omniclaude" / "scripts").mkdir()
    (home / ".claude" / "hooks").mkdir(parents=True)
    return Registry(home=home, omni_home=omni_home)


def run_guard(
    registry: Registry,
    tool_name: str,
    tool_input: dict[str, object],
    cwd: Path,
    *,
    with_omni_home: bool = True,
    raw_stdin: str | None = None,
) -> Verdict:
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(registry.home)}
    if with_omni_home:
        env["OMNI_HOME"] = str(registry.omni_home)
    payload = (
        raw_stdin
        if raw_stdin is not None
        else json.dumps(
            {"tool_name": tool_name, "tool_input": tool_input, "cwd": str(cwd)}
        )
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
    decision, reason = "allow", ""
    if proc.stdout.strip():
        out = json.loads(proc.stdout)
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "PreToolUse"
        decision = hso["permissionDecision"]
        reason = hso["permissionDecisionReason"]
    return Verdict(decision=decision, reason=reason, log=registry.log)


def bash(registry: Registry, command: str, cwd: Path, **kw: object) -> Verdict:
    return run_guard(registry, "Bash", {"command": command}, cwd, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Pre-existing contract (must not regress)
# ---------------------------------------------------------------------------

_LEGACY_DENIED = [
    "git commit -m x",
    "git add -A",
    "git checkout dev",
    "git checkout -b scratch",
    "git switch -c scratch",
    "git merge origin/dev",
    "git rebase origin/dev",
    "git cherry-pick abc123",
    "git revert HEAD",
    "git reset --hard origin/dev",
    "git reset --soft HEAD~1",
    "git stash",
    "git stash push -m wip",
    "git stash pop",
    "git restore --staged .",
    "git restore .",
    "git rm -r src",
    "git mv a b",
    "git am fix.patch",
    "git apply fix.patch",
    "git push origin dev",
]


@pytest.mark.unit
@pytest.mark.parametrize("command", _LEGACY_DENIED)
def test_legacy_mutations_denied_in_canonical(registry: Registry, command: str) -> None:
    verdict = bash(registry, command, registry.clone("omnimarket"))
    assert verdict.denied, command
    assert "omnimarket" in verdict.reason
    assert "worktree add" in verdict.reason


@pytest.mark.unit
@pytest.mark.parametrize("command", _LEGACY_DENIED)
def test_legacy_mutations_allowed_in_worktree(registry: Registry, command: str) -> None:
    verdict = bash(registry, command, registry.worktree("OMN-1/omnimarket"))
    assert not verdict.denied, (command, verdict.reason)


@pytest.mark.unit
def test_edit_inside_canonical_denied(registry: Registry) -> None:
    target = registry.clone("omnimarket") / "src" / "x.py"
    verdict = run_guard(registry, "Edit", {"file_path": str(target)}, registry.home)
    assert verdict.denied
    assert "omnimarket" in verdict.reason
    assert "DENY Edit" in verdict.log


@pytest.mark.unit
def test_notebook_edit_inside_canonical_denied(registry: Registry) -> None:
    target = registry.clone("omnibase_infra") / "nb.ipynb"
    verdict = run_guard(
        registry, "NotebookEdit", {"notebook_path": str(target)}, registry.home
    )
    assert verdict.denied


@pytest.mark.unit
def test_edit_in_worktree_and_omni_home_top_level_allowed(registry: Registry) -> None:
    for target in (
        registry.worktree("OMN-1/omnimarket") / "src" / "x.py",
        registry.omni_home / "docs" / "tracking" / "LEDGER.md",
        registry.omni_home / "CLAUDE.md",
        registry.home / "elsewhere" / "x.py",
    ):
        verdict = run_guard(
            registry, "Write", {"file_path": str(target)}, registry.home
        )
        assert not verdict.denied, (target, verdict.reason)


@pytest.mark.unit
def test_out_of_scope_inputs_allowed(registry: Registry) -> None:
    canonical = registry.clone("omnimarket")
    assert not bash(registry, "git commit -m x", canonical, with_omni_home=False).denied
    assert not run_guard(
        registry, "Read", {"file_path": str(canonical / "x")}, canonical
    ).denied
    assert not bash(registry, "ls -la", canonical).denied
    assert not run_guard(registry, "Bash", {}, canonical, raw_stdin="not json").denied
    assert not run_guard(registry, "Bash", {}, canonical, raw_stdin="").denied


# ---------------------------------------------------------------------------
# G2 — plumbing verbs
# ---------------------------------------------------------------------------

_G2_DENIED = [
    pytest.param("git update-ref refs/heads/dev origin/dev", id="update-ref"),
    pytest.param("git update-ref -d refs/heads/scratch", id="update-ref-delete"),
    pytest.param(
        "git symbolic-ref HEAD refs/heads/jonah/scratch", id="symbolic-ref-write"
    ),
    pytest.param(
        "git symbolic-ref -d refs/remotes/origin/HEAD", id="symbolic-ref-delete"
    ),
    pytest.param("git read-tree -mu origin/dev", id="read-tree"),
    pytest.param("git read-tree HEAD", id="read-tree-plain"),
    pytest.param("git checkout-index -a -f", id="checkout-index"),
    pytest.param("git branch -f dev origin/dev", id="branch-force"),
    pytest.param("git branch --force dev origin/dev", id="branch-force-long"),
    pytest.param("git branch -D scratch", id="branch-D"),
    pytest.param("git branch -d scratch", id="branch-d"),
    pytest.param("git branch -m dev dev-old", id="branch-move"),
    pytest.param("git branch -M dev", id="branch-move-force"),
    pytest.param("git branch -c dev dev-copy", id="branch-copy"),
    pytest.param("git branch scratch", id="branch-create"),
    pytest.param("git branch scratch origin/dev", id="branch-create-from"),
    pytest.param("git branch -u origin/dev", id="branch-upstream"),
    pytest.param("git branch --set-upstream-to=origin/dev", id="branch-set-upstream"),
    pytest.param("git branch --unset-upstream", id="branch-unset-upstream"),
    pytest.param(
        "git worktree remove .claude/worktrees/wf_8eb1198b-fb8-1",
        id="worktree-remove-nested",
    ),
    pytest.param(
        "git worktree remove --force .claude/worktrees/wf_8eb1198b-fb8-1",
        id="worktree-remove-nested-force",
    ),
    pytest.param("git clean -fd", id="clean-fd"),
    pytest.param("git clean -fdx", id="clean-fdx"),
    pytest.param("git clean --force -d", id="clean-force-long"),
    pytest.param("git fetch origin dev:dev", id="fetch-refspec-local-branch"),
    pytest.param(
        "git fetch origin +refs/heads/dev:refs/heads/dev", id="fetch-refspec-refs-heads"
    ),
    pytest.param(
        "git fetch origin refs/pull/2125/head:pr-2125", id="fetch-pr-head-local-branch"
    ),
    pytest.param(
        "git fetch --update-head-ok origin dev:dev", id="fetch-update-head-ok"
    ),
    pytest.param("git pull origin dev:dev", id="pull-refspec-local-branch"),
    pytest.param(
        "git update-index --assume-unchanged pyproject.toml", id="update-index-assume"
    ),
    pytest.param("git update-index --add newfile", id="update-index-add"),
    pytest.param("git replace HEAD HEAD~1", id="replace"),
    pytest.param("git replace -d abc123", id="replace-delete"),
    pytest.param(
        "git filter-branch --tree-filter 'rm -f secret' HEAD", id="filter-branch"
    ),
]


@pytest.mark.unit
@pytest.mark.parametrize("command", _G2_DENIED)
def test_g2_plumbing_denied_in_canonical(registry: Registry, command: str) -> None:
    verdict = bash(registry, command, registry.clone("omnimarket"))
    assert verdict.denied, f"{command!r} must be denied in a canonical clone"
    assert "omnimarket" in verdict.reason
    assert "DENY Bash" in verdict.log


@pytest.mark.unit
@pytest.mark.parametrize("command", _G2_DENIED)
def test_g2_plumbing_allowed_in_worktree(registry: Registry, command: str) -> None:
    verdict = bash(registry, command, registry.worktree("OMN-1/omnimarket"))
    assert not verdict.denied, (command, verdict.reason)


@pytest.mark.unit
def test_g2_update_ref_live_incident_shape(registry: Registry) -> None:
    """Exact shape of the 2026-08-23T21:06:54Z incident, run from outside the clone.

    The literal ``$OMNI_HOME`` in the command is what the agent typed; the hook
    must expand it (G5) and then deny the plumbing ref move (G2).
    """
    command = "cd $OMNI_HOME/omnimarket && git update-ref refs/heads/dev origin/dev"
    verdict = bash(registry, command, registry.home)
    assert verdict.denied
    assert "git update-ref" in verdict.reason
    assert "omnimarket" in verdict.reason
    assert "DENY Bash 'git update-ref'" in verdict.log

    absolute = (
        f"cd {registry.clone('omnimarket')} && "
        "git update-ref refs/heads/dev origin/dev 2>&1 | tail -1"
    )
    assert bash(registry, absolute, registry.home).denied

    via_c = (
        f"git -C {registry.clone('omnimarket')} update-ref refs/heads/dev origin/dev"
    )
    assert bash(registry, via_c, registry.home).denied


@pytest.mark.unit
def test_g2_worktree_move_into_canonical_denied(registry: Registry) -> None:
    src = registry.worktree("OMN-1/omnimarket")
    nested = registry.clone("omnimarket") / ".claude" / "worktrees" / "moved"
    command = f"git -C {registry.clone('omnimarket')} worktree move {src} {nested}"
    assert bash(registry, command, registry.home).denied

    outside = registry.omni_home / "omni_worktrees" / "OMN-2" / "omnimarket"
    command = f"git -C {registry.clone('omnimarket')} worktree move {src} {outside}"
    assert not bash(registry, command, registry.home).denied


@pytest.mark.unit
def test_g2_worktree_remove_of_sanctioned_worktree_allowed(registry: Registry) -> None:
    """Closeout hygiene runs ``worktree remove`` from the canonical clone; it must pass."""
    wt = registry.worktree("OMN-16130/onex_change_control")
    for command in (
        f"git -C {registry.clone('omnimarket')} worktree remove {wt}",
        f"git -C {registry.clone('omnimarket')} worktree remove --force {wt}",
        'git -C "$OMNI_HOME/omnimarket" worktree remove "$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control"',
        f"cd {registry.clone('omnimarket')} && git worktree remove ../omni_worktrees/OMN-16130/onex_change_control && git worktree prune",
    ):
        verdict = bash(registry, command, registry.home)
        assert not verdict.denied, (command, verdict.reason)


_READ_ONLY_IN_CANONICAL = [
    "git status --porcelain",
    "git log --oneline -3",
    "git diff --stat",
    "git show HEAD --stat",
    "git rev-parse HEAD",
    "git remote -v",
    "git config --get remote.origin.url",
    "git fetch",
    "git fetch origin",
    "git fetch --all --prune",
    "git fetch origin dev",
    "git fetch origin dev:refs/remotes/origin/dev",
    "git fetch origin 'refs/heads/*:refs/remotes/origin/*'",
    "git fetch origin refs/tags/v1.0.0:refs/tags/v1.0.0",
    "git fetch https://github.com/OmniNode-ai/omnimarket.git dev",
    "git fetch git@github.com:OmniNode-ai/omnimarket.git dev",
    "git pull",
    "git pull --ff-only",
    "git pull --ff-only origin dev",
    "git branch",
    "git branch --show-current",
    "git branch -a",
    "git branch -r",
    "git branch -vv",
    "git branch -avv",
    "git branch --list 'jonah/*'",
    "git branch --contains 44ff5795",
    "git branch -r --contains HEAD",
    "git branch --merged",
    "git branch --no-merged origin/dev",
    "git branch --points-at HEAD",
    "git branch --format='%(refname:short)'",
    "git symbolic-ref HEAD",
    "git symbolic-ref --short HEAD",
    "git symbolic-ref -q --short HEAD",
    "git clean -n",
    "git clean -nd",
    "git clean --dry-run -d",
    "git stash list",
    "git stash show -p 'stash@{0}'",
    "git update-index --refresh",
    "git update-index -q --refresh",
    "git update-index -q --really-refresh --unmerged",
    "git replace",
    "git replace -l",
    "git replace --list",
    "git worktree list",
    "git worktree list --porcelain",
    "git worktree prune",
    "git diff-index --cached 44ff5795",
    "git ls-files --others --exclude-standard",
    "git stash list | head -5",
    "git branch --show-current 2>/dev/null",
]


@pytest.mark.unit
@pytest.mark.parametrize("command", _READ_ONLY_IN_CANONICAL)
def test_read_only_forms_allowed_in_canonical(registry: Registry, command: str) -> None:
    verdict = bash(registry, command, registry.clone("omnimarket"))
    assert not verdict.denied, (command, verdict.reason)


@pytest.mark.unit
def test_worktree_add_from_canonical_allowed(registry: Registry) -> None:
    command = (
        'git -C "$OMNI_HOME/omnimarket" worktree add '
        '"$OMNI_HOME/omni_worktrees/OMN-2/omnimarket" -b jonah/omn-2-x'
    )
    assert not bash(registry, command, registry.home).denied
    command = (
        f"cd {registry.clone('omnimarket')} && git pull --ff-only && "
        f"git worktree add {registry.omni_home}/omni_worktrees/OMN-2/omnimarket -b jonah/omn-2-x"
    )
    assert not bash(registry, command, registry.home).denied


# ---------------------------------------------------------------------------
# G4 — sanctioned convergence path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_g4_raw_reset_hard_denied_and_points_at_converge_script(
    registry: Registry,
) -> None:
    for command in (
        "git reset --hard origin/dev",
        'git -C "$OMNI_HOME/omnimarket" reset --hard origin/dev',
        "git checkout -- .",
        "git restore --staged . && git restore .",
        "git stash && git pull --ff-only",
    ):
        verdict = bash(registry, command, registry.clone("omnimarket"))
        assert verdict.denied, command
        assert "converge-canonical-clone.sh" in verdict.reason, command
        assert "--execute" in verdict.reason


@pytest.mark.unit
def test_g4_converge_script_invocation_allowed(registry: Registry) -> None:
    script = (
        registry.omni_home / "omniclaude" / "scripts" / "converge-canonical-clone.sh"
    )
    for command in (
        f"bash {script} omnimarket --execute",
        'bash "$OMNI_HOME/omniclaude/scripts/converge-canonical-clone.sh" omnimarket',
        f"cd {registry.clone('omnimarket')} && bash {script} . --execute && git status --porcelain",
        f"{script} omnimarket --execute --ticket OMN-16496 && git -C {registry.clone('omnimarket')} log -1",
    ):
        verdict = bash(registry, command, registry.home)
        assert not verdict.denied, (command, verdict.reason)
    assert "converge-canonical-clone.sh" in registry.log


@pytest.mark.unit
def test_g4_converge_script_does_not_launder_other_mutations(
    registry: Registry,
) -> None:
    """Mentioning the script does not allow a *separate* mutation in the same command."""
    script = (
        registry.omni_home / "omniclaude" / "scripts" / "converge-canonical-clone.sh"
    )
    command = f"bash {script} omnimarket --execute; git -C {registry.clone('omnimarket')} commit -m x"
    assert bash(registry, command, registry.home).denied


@pytest.mark.unit
def test_g4_stash_read_forms_allowed_write_forms_denied(registry: Registry) -> None:
    canonical = registry.clone("omnimarket")
    assert not bash(registry, "git stash list", canonical).denied
    assert not bash(registry, "git stash show", canonical).denied
    for command in (
        "git stash",
        "git stash push",
        "git stash pop",
        "git stash drop",
        "git stash apply",
    ):
        assert bash(registry, command, canonical).denied, command


# ---------------------------------------------------------------------------
# G5 — env-var / tilde / assignment expansion in cd and -C arguments
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_g5_log_line_155_shape_allowed(registry: Registry) -> None:
    """``cd "$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control" && git add`` from
    inside the omnimarket clone was denied as
    ``omnimarket/$OMNI_HOME/omni_worktrees/...`` (guard log line 155)."""
    command = (
        'cd "$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control" && git add -A'
    )
    verdict = bash(registry, command, registry.clone("omnimarket"))
    assert not verdict.denied, verdict.reason
    assert "$OMNI_HOME" not in verdict.log


@pytest.mark.unit
def test_g5_log_line_206_shape_allowed(registry: Registry) -> None:
    """Same false positive from inside the omnibase_infra clone (guard log line 206)."""
    command = (
        'cd "$OMNI_HOME/omni_worktrees/OMN-16375/omnimarket-0389" && '
        'git add -A && git commit -m "fix(OMN-16375): x"'
    )
    verdict = bash(registry, command, registry.clone("omnibase_infra"))
    assert not verdict.denied, verdict.reason


@pytest.mark.unit
def test_g5_log_line_181_shape_assignment_allowed(registry: Registry) -> None:
    """``cd "$WT" && git apply`` where ``WT`` was assigned earlier in the same
    command was denied as ``omnimarket/$WT`` (guard log line 181)."""
    for command in (
        'WT="$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control"; cd "$WT" && git apply fix.patch',
        'export WT="$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control"; cd "$WT" && git apply fix.patch',
        'WT=$OMNI_HOME/omni_worktrees/OMN-16130/onex_change_control\ncd "$WT"\ngit apply fix.patch',
    ):
        verdict = bash(registry, command, registry.clone("omnimarket"))
        assert not verdict.denied, (command, verdict.reason)


@pytest.mark.unit
def test_g5_unresolvable_variable_is_unknown_location_not_canonical(
    registry: Registry,
) -> None:
    """An unset variable cannot be resolved; the guard must not glue it onto cwd."""
    verdict = bash(
        registry, 'cd "$WT" && git apply fix.patch', registry.clone("omnimarket")
    )
    assert not verdict.denied, verdict.reason
    assert "UNRESOLVED" in verdict.log
    verdict = bash(
        registry,
        'cd "$(git rev-parse --show-toplevel)" && git apply fix.patch',
        registry.clone("omnimarket"),
    )
    assert not verdict.denied, verdict.reason


@pytest.mark.unit
def test_g5_assignment_pointing_at_canonical_still_denied(registry: Registry) -> None:
    for command in (
        'WT="$OMNI_HOME/omnimarket"; cd "$WT" && git commit -m x',
        'export WT="$OMNI_HOME/omnimarket"; cd $WT && git add -A',
        'REPO=omnimarket; cd "$OMNI_HOME/$REPO" && git checkout -b scratch',
    ):
        verdict = bash(registry, command, registry.home)
        assert verdict.denied, command


@pytest.mark.unit
def test_g5_brace_and_default_forms(registry: Registry) -> None:
    assert bash(
        registry, 'cd "${OMNI_HOME}/omnimarket" && git commit -m x', registry.home
    ).denied
    assert bash(
        registry,
        'cd "${OMNI_HOME:?set OMNI_HOME}/omnimarket" && git commit -m x',
        registry.home,
    ).denied
    assert not bash(
        registry,
        'cd "${OMNI_HOME:?set OMNI_HOME}/omni_worktrees/OMN-1/omnimarket" && git commit -m x',
        registry.clone("omnimarket"),
    ).denied
    assert bash(
        registry,
        'cd "${UNSET_X:-$OMNI_HOME/omnimarket}" && git commit -m x',
        registry.home,
    ).denied


@pytest.mark.unit
def test_g5_tilde_expansion(registry: Registry) -> None:
    assert bash(
        registry, "cd ~/omni_home/omnimarket && git commit -m x", registry.home
    ).denied
    assert not bash(
        registry,
        "cd ~/omni_home/omni_worktrees/OMN-1/omnimarket && git commit -m x",
        registry.clone("omnimarket"),
    ).denied


@pytest.mark.unit
def test_g5_dash_c_expansion(registry: Registry) -> None:
    assert not bash(
        registry,
        'git -C "$OMNI_HOME/omni_worktrees/OMN-1/omnimarket" add -A',
        registry.clone("omnimarket"),
    ).denied
    assert bash(
        registry, 'git -C "$OMNI_HOME/omnimarket" commit -m x', registry.home
    ).denied
    assert bash(
        registry, "git -C ${OMNI_HOME}/omnimarket push origin dev", registry.home
    ).denied


@pytest.mark.unit
def test_g5_pushd_popd_and_subshell_tracking(registry: Registry) -> None:
    canonical = registry.clone("omnimarket")
    command = 'pushd "$OMNI_HOME/omni_worktrees/OMN-1/omnimarket" && git add -A && popd && git commit -m x'
    verdict = bash(registry, command, canonical)
    assert verdict.denied, "commit after popd runs in the canonical clone"
    assert "DENY Bash 'git commit'" in verdict.log

    assert bash(
        registry, '(cd "$OMNI_HOME/omnimarket" && git commit -m x)', registry.home
    ).denied
    assert not bash(
        registry,
        '(cd "$OMNI_HOME/omni_worktrees/OMN-1/omnimarket" && git commit -m x)',
        canonical,
    ).denied


@pytest.mark.unit
def test_g5_edit_path_with_literal_env_var(registry: Registry) -> None:
    verdict = run_guard(
        registry, "Edit", {"file_path": "$OMNI_HOME/omnimarket/src/x.py"}, registry.home
    )
    assert verdict.denied
    verdict = run_guard(
        registry,
        "Edit",
        {"file_path": "$OMNI_HOME/omni_worktrees/OMN-1/omnimarket/src/x.py"},
        registry.clone("omnimarket"),
    )
    assert not verdict.denied
