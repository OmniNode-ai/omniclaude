# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the shared-tree git admission gate (OMN-18798).

Written red first against an absent decision core: neither
`shared_tree_git_guard.py` nor `pre_tool_use_shared_tree_git_guard.sh`
existed before this ticket, so every test below fails at import on
`origin/dev` (`git show origin/dev:plugins/onex/hooks/lib/shared_tree_git_guard.py`
returns `fatal: path ... does not exist`).

Every blocking case reproduces a mechanism measured in the shared registry
clone at `$OMNI_HOME` and recorded on the ticket:

* `git reset` -- 20 `reset: moving to origin/main` reflog entries on
  2026-09-18 alone, twice re-orphaning a staged 1,258-row ledger-roll
  archive and twice dropping a peer lane's unpushed commit;
* `git clean` -- the verb that would have destroyed that archive outright
  during the 2h22m it existed only as an untracked file;
* `git checkout -b` / `git switch` -- the STRANDING half: a feature branch
  in the shared clone makes `commit_lock.py` refuse every other lane's
  ledger commit with exit 78 for as long as it is checked out.

There is deliberately no case admitting a refused verb in the registry clone
via some spelling of consent: each one has a sanctioned alternative that
reaches the same outcome without touching state a peer lane owns.

Positive controls are carried throughout (Operating Rule 16). A refusal test
proves nothing on its own if the guard refuses everything, so each refused
shape is paired with an allowed one, and `test_no_op_policy_admits_every_
refused_shape` re-runs the whole refusal set against a policy declaring a
verb nobody types -- the pre-change behaviour -- and asserts every one is
then admitted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_DIR = REPO_ROOT / "plugins" / "onex" / "hooks"
LIB_DIR = HOOKS_DIR / "lib"
HOOK_SCRIPT = HOOKS_DIR / "scripts" / "pre_tool_use_shared_tree_git_guard.sh"
POLICY_PATH = HOOKS_DIR / "config" / "shared_tree_git_guard_policy.json"
NAMESAKE_SCRIPT = "pre_tool_use_scope_gate.sh"

sys.path.insert(0, str(LIB_DIR))

from shared_tree_git_guard import (  # noqa: E402
    GATE_BIT_NAME,
    TICKET,
    Policy,
    PolicyError,
    evaluate_bash_command,
    load_policy,
    resolve_registry_root,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(*args: str) -> None:
    subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        env=scrub_git_location_env(os.environ),
    )


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", str(repo))
    _git("-C", str(repo), "config", "user.email", "t@example.com")
    _git("-C", str(repo), "config", "user.name", "t")
    _git("-C", str(repo), "commit", "-q", "--allow-empty", "-m", "init")


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


@pytest.fixture
def registry(tmp_path: Path, policy: Policy) -> Path:
    """A stand-in for the shared registry clone at `$OMNI_HOME`.

    Carries both declared markers so the marker fallback can be exercised
    without an env var, and is a real git clone so `.git` is a directory.

    The markers are COMMITTED, not just written: they are tracked files in
    the real registry clone, so a worktree of this fixture must carry them too --
    which is the whole point of `test_marker_fallback_does_not_gate_a_
    registry_worktree`, whose premise would be vacuous otherwise.
    """
    root = tmp_path / "registry_clone"
    _init(root)
    for marker in policy.registry_root_markers:
        target = root / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n")
    _git("-C", str(root), "add", "-A")
    _git("-C", str(root), "commit", "-q", "-m", "markers")
    return root


@pytest.fixture
def code_clone(registry: Path) -> Path:
    """A code-repo canonical clone under the registry root.

    Its git root is `$OMNI_HOME/<repo>`, not `$OMNI_HOME`, so it is out of
    scope -- it already has the OMN-7018/OMN-14330 worktree guard.
    """
    clone = registry / "omniclaude"
    _init(clone)
    return clone


@pytest.fixture
def registry_worktree(registry: Path) -> Path:
    """A WORKTREE of the registry clone -- the sanctioned remedy.

    It carries the same two marker files, which is exactly why the marker
    fallback also requires a `.git` DIRECTORY. Refusing here would refuse
    the thing the refusal message recommends.
    """
    worktree = registry / "omni_worktrees" / "OMN-1" / "registry_clone"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git("-C", str(registry), "worktree", "add", str(worktree), "-b", "lane-branch")
    return worktree


# ---------------------------------------------------------------------------
# Policy loading
# ---------------------------------------------------------------------------


def test_policy_loads_and_declares_expected_vocabulary(policy: Policy) -> None:
    assert policy.ticket == "OMN-18798"
    assert policy.rule == "Operating Rule 19"
    for verb in (
        "reset",
        "checkout",
        "switch",
        "clean",
        "rebase",
        "branch",
        "merge",
    ):
        assert verb in policy.refused_subcommands
    assert "--ff-only" in policy.merge_allowed_flags
    # checkout and branch are the two with a sanctioned shape, so they are
    # the two that must NOT be unconditional.
    assert policy.unconditional_subcommands == frozenset(
        {"reset", "switch", "clean", "rebase"}
    )
    assert policy.unconditional_subcommands <= policy.refused_subcommands


def test_missing_policy_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PolicyError):
        load_policy(tmp_path / "does-not-exist.json")


def test_malformed_policy_json_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_unconditional_must_be_a_subset_of_refused(tmp_path: Path) -> None:
    raw = json.loads(POLICY_PATH.read_text())
    raw["unconditional_subcommands"] = ["reset", "not-a-refused-verb"]
    bad = tmp_path / "inconsistent.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(PolicyError):
        load_policy(bad)


# ---------------------------------------------------------------------------
# REFUSED in the registry clone
# ---------------------------------------------------------------------------


REFUSED_IN_REGISTRY = [
    "git reset",
    "git reset --hard origin/main",
    "git reset --soft HEAD~1",
    "git reset origin/main",
    "git checkout origin/main",
    "git checkout main",
    "git checkout -b lane/some-branch",
    "git checkout -B lane/some-branch",
    "git switch main",
    "git switch -c lane/some-branch",
    "git switch --detach HEAD",
    "git clean -fd",
    "git clean -n",
    "git clean -fdx docs/",
    "git rebase origin/main",
    "git rebase --continue",
    "git rebase -i HEAD~3",
    # A merge that is not --ff-only runs a content merge on the shared tree.
    "git merge origin/main",
    "git merge",
    "git merge --no-ff origin/main",
    "git merge -X theirs origin/main",
]

#: The four command shapes of the 2026-09-19 14:43-14:55Z incident, read
#: verbatim off the shared clone's own reflog, plus the merge that produced
#: the lossy resolution. Kept as a named list rather than folded into the
#: set above so a reader can see that the measured window is covered shape
#: by shape, and so removing the coverage removes a named test.
#:
#:   14:46:09Z  reset: moving to 637e93c5a8
#:   14:47:25Z  reset: moving to 637e93c5a8   (the same reset, again)
#:   14:52:55Z  checkout: moving from main to lane/ledger-rows-1435-fix
#:   14:52:55Z  merge origin/main: Merge made by the 'ort' strategy
#:   14:55:04Z  checkout: moving from lane/ledger-rows-1435-fix to main
#:
#: Measured effects: a peer lane's ledger commit was dropped from local
#: `main` by the reset and survived only because the rows were still in the
#: working tree; while the clone sat on the branch, commit_lock.py refused
#: every other lane with exit 78 (STRANDED-CLONE at 14:53:23Z); and rows
#: appended between 14:48Z and 14:53Z did not survive the round trip.
INCIDENT_2026_09_19_SHAPES = [
    "git reset --hard 637e93c5a87d3314d0784d4321a90dbcddc4efc3",
    "git reset 637e93c5a8",
    "git checkout -b lane/ledger-rows-1435-fix",
    "git merge origin/main",
    "git checkout main",
]


@pytest.mark.parametrize("command", REFUSED_IN_REGISTRY)
def test_refuses_destructive_verb_in_registry_clone(
    command: str, registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked, command
    assert TICKET in decision.reason
    assert "Operating Rule 19" in decision.reason
    assert "omni_worktrees" in decision.reason
    assert "--ff-only" in decision.reason
    assert GATE_BIT_NAME in decision.reason


@pytest.mark.parametrize("command", INCIDENT_2026_09_19_SHAPES)
def test_refuses_every_shape_of_the_2026_09_19_incident(
    command: str, registry: Path, policy: Policy
) -> None:
    """Each command shape the shared clone's reflog recorded that window.

    This is the falsifier for the ticket's own motivating incident: if any
    of these five is admitted, the guard would not have stopped the loss it
    is being landed for.
    """
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked, command
    assert TICKET in decision.reason


def test_refuses_a_non_ff_merge_but_allows_the_ff_only_sync(
    registry: Path, policy: Policy
) -> None:
    """The merge arm's two sides, asserted together.

    The pair is the point: `--ff-only` is the sanctioned sync verb and must
    stay open, so a guard that refused both would be refusing the remedy its
    own message recommends.
    """
    blocked = evaluate_bash_command(
        "git merge origin/main", policy, cwd=registry, registry_root=registry
    )
    assert blocked.blocked
    assert "CONTENT merge" in blocked.reason
    allowed = evaluate_bash_command(
        "git merge --ff-only origin/main",
        policy,
        cwd=registry,
        registry_root=registry,
    )
    assert not allowed.blocked


@pytest.mark.parametrize(
    "command", ["git merge --abort", "git merge --quit", "git merge --continue"]
)
def test_allows_in_progress_merge_management(
    command: str, registry: Path, policy: Policy
) -> None:
    """Refusing these would strand the tree mid-conflict, not protect it."""
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert not decision.blocked, (command, decision.reason)


def test_refuses_blanket_path_scoped_checkout(registry: Path, policy: Policy) -> None:
    """`git checkout -- .` is path-scoped syntax doing a blanket revert."""
    decision = evaluate_bash_command(
        "git checkout -- .", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    assert "BLANKET" in decision.reason


def test_refuses_checkout_with_operand_and_no_double_dash(
    registry: Path, policy: Policy
) -> None:
    """git cannot tell a ref from a path without `--`, so neither can this."""
    decision = evaluate_bash_command(
        "git checkout docs/tracking/ROLLING_WORK_LEDGER.md",
        policy,
        cwd=registry,
        registry_root=registry,
    )
    assert decision.blocked
    assert "`--` separator" in decision.reason


def test_refuses_branch_delete_of_the_current_branch(
    registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git branch -D main", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    assert "'main'" in decision.reason


def test_refuses_branch_rename_with_one_operand(registry: Path, policy: Policy) -> None:
    """`git branch -m <new>` renames the CURRENT branch."""
    decision = evaluate_bash_command(
        "git branch -m renamed", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    assert "renames the" in decision.reason


def test_refuses_when_head_is_unreadable(registry: Path, policy: Policy) -> None:
    """A detached HEAD leaves the target branch unknowable -- fail closed."""
    _git("-C", str(registry), "checkout", "-q", "--detach")
    decision = evaluate_bash_command(
        "git branch -D some-branch", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    assert "could not be read" in decision.reason


def test_dash_c_target_is_checked_instead_of_cwd(
    registry: Path, code_clone: Path, policy: Policy
) -> None:
    """cwd is a harmless clone; `-C` points at the registry -- that wins."""
    decision = evaluate_bash_command(
        f"git -C {registry} reset --hard origin/main",
        policy,
        cwd=code_clone,
        registry_root=registry,
    )
    assert decision.blocked


def test_refused_verb_inside_a_compound_command_is_found(
    registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git fetch origin && git reset --hard origin/main",
        policy,
        cwd=registry,
        registry_root=registry,
    )
    assert decision.blocked


def test_wrapped_invocation_is_still_matched(registry: Path, policy: Policy) -> None:
    decision = evaluate_bash_command(
        "env FOO=1 git clean -fd", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked


# ---------------------------------------------------------------------------
# ALLOWED in the registry clone -- the positive controls
# ---------------------------------------------------------------------------


ALLOWED_IN_REGISTRY = [
    # The Operating Rule 17 path-scoped restore recipe, both spellings.
    "git checkout -- docs/tracking/ROLLING_WORK_LEDGER.md",
    "git checkout origin/main -- docs/tracking/ROLLING_WORK_LEDGER.md",
    "git checkout HEAD -- docs/a.md docs/b.md",
    # Bare checkout changes nothing.
    "git checkout",
    # Fast-forward-only sync.
    "git merge --ff-only origin/main",
    "git pull --ff-only origin main",
    "git fetch origin",
    "git fetch --all --prune",
    # Branch shapes that do not move the tree.
    "git branch lane/new-branch",
    "git branch -D some-other-branch",
    "git branch --list",
    # Every read.
    "git status --porcelain",
    "git log --oneline -5",
    "git diff origin/main",
    "git show HEAD:docs/a.md",
    "git rev-parse HEAD",
    "git reflog -5",
    "git worktree list",
    "git stash list",
    # Prose that merely names a refused verb is not an invocation.
    "echo 'never run git reset --hard in the shared tree'",
    "grep -rn 'git clean' docs/",
]


@pytest.mark.parametrize("command", ALLOWED_IN_REGISTRY)
def test_allows_sanctioned_command_in_registry_clone(
    command: str, registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        command, policy, cwd=registry, registry_root=registry
    )
    assert not decision.blocked, (command, decision.reason)


def test_non_git_command_never_matches(registry: Path, policy: Policy) -> None:
    decision = evaluate_bash_command(
        "rm -rf build/", policy, cwd=registry, registry_root=registry
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# SCOPE: only the registry clone itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", REFUSED_IN_REGISTRY)
def test_allows_every_refused_verb_in_a_registry_worktree(
    command: str, registry_worktree: Path, registry: Path, policy: Policy
) -> None:
    """The sanctioned remedy must not be refused by the refusal's own guard."""
    decision = evaluate_bash_command(
        command, policy, cwd=registry_worktree, registry_root=registry
    )
    assert not decision.blocked, (command, decision.reason)


def test_allows_reset_in_a_code_repo_canonical_clone(
    code_clone: Path, registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git reset --hard origin/dev", policy, cwd=code_clone, registry_root=registry
    )
    assert not decision.blocked


def test_allows_reset_in_an_unrelated_clone(
    tmp_path: Path, registry: Path, policy: Policy
) -> None:
    elsewhere = tmp_path / "elsewhere" / "some-repo"
    _init(elsewhere)
    decision = evaluate_bash_command(
        "git reset --hard origin/main", policy, cwd=elsewhere, registry_root=registry
    )
    assert not decision.blocked


def test_allows_reset_outside_any_git_repository(
    tmp_path: Path, registry: Path, policy: Policy
) -> None:
    loose = tmp_path / "loose"
    loose.mkdir()
    decision = evaluate_bash_command(
        "git reset --hard", policy, cwd=loose, registry_root=registry
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# Registry-root resolution
# ---------------------------------------------------------------------------


def test_registry_root_resolves_from_the_declared_env_vars(
    registry: Path, policy: Policy
) -> None:
    assert resolve_registry_root(policy, {"OMNI_HOME": str(registry)}) == registry
    assert (
        resolve_registry_root(policy, {"ONEX_REGISTRY_ROOT": str(registry)}) == registry
    )
    assert resolve_registry_root(policy, {}) is None


def test_a_stale_env_value_pointing_nowhere_is_ignored(
    tmp_path: Path, policy: Policy
) -> None:
    missing = tmp_path / "does-not-exist"
    assert resolve_registry_root(policy, {"OMNI_HOME": str(missing)}) is None


def test_marker_fallback_gates_the_registry_when_the_env_is_absent(
    registry: Path, policy: Policy
) -> None:
    """With no env var the guard must not go dark in the tree it protects."""
    decision = evaluate_bash_command(
        "git reset --hard origin/main", policy, cwd=registry, registry_root=None
    )
    assert decision.blocked


def test_marker_fallback_does_not_gate_a_registry_worktree(
    registry_worktree: Path, policy: Policy
) -> None:
    """The worktree carries the same markers; its `.git` is a FILE.

    Positive control for the test above: the two differ only in the `.git`
    entry's type, so a fallback that matched on markers alone would refuse
    the sanctioned remedy.
    """
    for marker in policy.registry_root_markers:
        assert (registry_worktree / marker).exists()
    assert (registry_worktree / ".git").is_file()
    decision = evaluate_bash_command(
        "git reset --hard origin/main",
        policy,
        cwd=registry_worktree,
        registry_root=None,
    )
    assert not decision.blocked


def test_env_root_is_authoritative_over_the_markers(
    registry: Path, tmp_path: Path, policy: Policy
) -> None:
    """A second checkout carrying the markers is not the shared clone."""
    other = tmp_path / "personal" / "registry_clone"
    _init(other)
    for marker in policy.registry_root_markers:
        target = other / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n")
    decision = evaluate_bash_command(
        "git reset --hard origin/main", policy, cwd=other, registry_root=registry
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# Untokenisable commands: narrow fail-closed
# ---------------------------------------------------------------------------


def test_untokenisable_command_naming_a_refused_verb_is_refused(
    registry: Path, policy: Policy
) -> None:
    decision = evaluate_bash_command(
        "git reset --hard 'unbalanced", policy, cwd=registry, registry_root=registry
    )
    assert decision.blocked
    assert "could not be tokenised" in decision.reason


def test_untokenisable_command_naming_no_refused_verb_passes(
    registry: Path, policy: Policy
) -> None:
    """An unbalanced quote in unrelated work is not this guard's business."""
    decision = evaluate_bash_command(
        "echo 'unbalanced", policy, cwd=registry, registry_root=registry
    )
    assert not decision.blocked


# ---------------------------------------------------------------------------
# The RED control: a policy refusing nothing admits every shape
# ---------------------------------------------------------------------------


def test_no_op_policy_admits_every_refused_shape(
    tmp_path: Path, registry: Path
) -> None:
    """Reproduces the pre-change state: no refused vocabulary, no refusals.

    Without this, every refusal test above would also pass against a guard
    that refuses unconditionally. Operating Rule 16: prove the zero.
    """
    raw = json.loads(POLICY_PATH.read_text())
    raw["refused_subcommands"] = ["a-verb-nobody-types"]
    raw["unconditional_subcommands"] = ["a-verb-nobody-types"]
    noop_path = tmp_path / "noop.json"
    noop_path.write_text(json.dumps(raw))
    noop = load_policy(noop_path)
    for command in REFUSED_IN_REGISTRY:
        decision = evaluate_bash_command(
            command, noop, cwd=registry, registry_root=registry
        )
        assert not decision.blocked, command


# ---------------------------------------------------------------------------
# The bit borrow is faithful: registering the namesake must turn this red.
# ---------------------------------------------------------------------------


def test_borrowed_bit_namesake_is_unregistered() -> None:
    """SCOPE_GATE is borrowed from pre_tool_use_scope_gate.sh.

    hook_bits.sh is GENERATED from omnibase_core's hook_activations.yaml, so
    minting a dedicated bit is a cross-repo change this guard does not need.
    The borrow is only safe while the namesake stays unregistered -- if it
    were registered, `onex hooks disable SCOPE_GATE` would silently disable
    two independent controls at once. This test is the pin: it must turn red
    the moment someone registers the namesake without giving this guard its
    own bit first.
    """
    assert GATE_BIT_NAME == "SCOPE_GATE"
    hooks_json = json.loads((HOOKS_DIR / "hooks.json").read_text())
    all_commands = json.dumps(hooks_json)
    assert NAMESAKE_SCRIPT not in all_commands, (
        f"{NAMESAKE_SCRIPT} is now registered in hooks.json, which means the "
        f"{GATE_BIT_NAME} bit this guard borrows is no longer an uncontested "
        "borrow. Give pre_tool_use_shared_tree_git_guard.sh its own bit, or "
        "pick a different unregistered namesake, before registering that "
        "script."
    )


def test_the_guard_is_registered_on_the_bash_matcher() -> None:
    hooks_json = json.loads((HOOKS_DIR / "hooks.json").read_text())
    groups = hooks_json["hooks"]["PreToolUse"]
    bash_groups = [g for g in groups if g.get("matcher") == "Bash"]
    assert bash_groups, "no PreToolUse group matches Bash"
    commands = [h["command"] for g in bash_groups for h in g["hooks"]]
    assert any(HOOK_SCRIPT.name in c for c in commands), commands


# ---------------------------------------------------------------------------
# End-to-end shell wrapper
# ---------------------------------------------------------------------------


def _run_hook(
    tmp_path: Path,
    command: str,
    cwd: Path,
    omni_home_dir: str | None = None,
    mask: str | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload: dict[str, object] = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        # Always the REAL omniclaude checkout, never the synthetic tmp repo
        # under test: is_omninode_repo() (repo_guard.sh) resolves its root
        # from CLAUDE_PROJECT_DIR and would otherwise pass this fixture
        # through untouched before the guard ever runs. The payload's own
        # `cwd` field -- not this env var -- is what the decision core
        # resolves its target directory from.
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
    }
    if omni_home_dir is not None:
        env["OMNI_HOME"] = omni_home_dir
    if mask is not None:
        env["ONEX_HOOKS_MASK"] = mask
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        "git reset --hard origin/main",
        "git checkout -b lane/some-branch",
        "git switch main",
        "git clean -fd",
        "git rebase origin/main",
        "git checkout origin/main",
    ],
)
def test_shell_wrapper_refuses_in_registry_clone(
    command: str, tmp_path: Path, registry: Path
) -> None:
    result = _run_hook(tmp_path, command, cwd=registry, omni_home_dir=str(registry))
    assert result.returncode == 2, (command, result.stdout, result.stderr)
    combined = result.stdout + result.stderr
    assert '"decision": "block"' in combined
    assert TICKET in combined
    assert "Operating Rule 19" in combined


@pytest.mark.parametrize(
    "command",
    [
        "git checkout origin/main -- docs/tracking/ROLLING_WORK_LEDGER.md",
        "git merge --ff-only origin/main",
        "git fetch origin",
        "git status --porcelain",
    ],
)
def test_shell_wrapper_allows_sanctioned_command(
    command: str, tmp_path: Path, registry: Path
) -> None:
    result = _run_hook(tmp_path, command, cwd=registry, omni_home_dir=str(registry))
    assert result.returncode == 0, (command, result.stdout, result.stderr)


def test_shell_wrapper_allows_refused_verb_in_a_worktree(
    tmp_path: Path, registry_worktree: Path, registry: Path
) -> None:
    result = _run_hook(
        tmp_path,
        "git reset --hard origin/main",
        cwd=registry_worktree,
        omni_home_dir=str(registry),
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_shell_wrapper_ignores_a_non_bash_tool(tmp_path: Path, registry: Path) -> None:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload = {
        "tool_name": "Edit",
        "tool_input": {"command": "git reset --hard origin/main"},
        "cwd": str(registry),
    }
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
            "HOME": str(home),
            "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "OMNICLAUDE_MODE": "full",
            "OMNI_HOME": str(registry),
        },
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_shell_wrapper_disabled_via_mask(tmp_path: Path, registry: Path) -> None:
    result = _run_hook(
        tmp_path,
        "git reset --hard origin/main",
        cwd=registry,
        omni_home_dir=str(registry),
        mask="0x0",
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
