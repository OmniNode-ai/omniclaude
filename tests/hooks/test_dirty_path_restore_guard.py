# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the dirty-path restore arm of the shared-tree git guard (OMN-18874).

Written red first. Before this ticket the guard carried no restore arm:
`shared_tree_git_guard.py` on `origin/dev` admitted both path-scoped restore
shapes explicitly (its `_checkout_is_path_scoped` returned "allowed" for
`git checkout -- <path>` and `git checkout <ref> -- <path>`), never looked at
whether the named path had uncommitted changes, and never evaluated
`git restore` at all. Every refusal below therefore failed on the base.

The hazard, in one sentence: a path-scoped checkout or restore returns the
file to the REFERENCE, not to what is in the working tree, so over a path
with uncommitted work it discards that work silently -- exit 0, no output,
and no reflog, because a working tree that was never committed has none.
Four lanes lost work this way, every one of them after reading Operating
Rule 17, which names the trap:

* OMN-18566 (2026-09-17) -- proving a RED test with HEAD still at the base
  branch, about 25 minutes of uncommitted edits;
* the OMN-18863 lane (2026-09-20) -- `git checkout HEAD -- <path>` on a
  branch freshly cut from its base, about 10 minutes, one source edit;
* OMN-18992 (2026-09-21) -- red-probing a guard before committing it, the
  whole implementation;
* OMN-19237 (2026-09-23) -- a negative probe on an uncommitted 49 KB rewrite
  of CLAUDE.md, restored from HEAD, which put back the 136 KB base file.

Each is replayed below against real git repositories: a command the guard
admits is then actually executed, a command it refuses is not, and the test
asserts on the bytes left on disk. The same sequences with the work
committed first are replayed too, and must pass end to end -- the guard
refuses the loss, never the recipe.

Positive and negative controls are carried throughout (Operating Rule 16):
every refused shape is paired with the same command over a clean path, and
`test_no_op_policy_admits_every_dirty_restore` re-runs the refusal set with
the restore vocabulary emptied and asserts every one is then admitted, so a
guard that refused everything could not pass this file.
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

sys.path.insert(0, str(LIB_DIR))

import shared_tree_git_guard  # noqa: E402
from shared_tree_git_guard import (  # noqa: E402
    Decision,
    Policy,
    evaluate_bash_command,
    load_policy,
    resolve_worktree_roots,
)

pytestmark = pytest.mark.unit

RESTORE_TICKET = "OMN-18874"

BASE_TEXT = "def guard():\n    return 'base'\n"
IMPL_TEXT = "def guard():\n    return 'implementation'\n"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        cwd=cwd,
        env=scrub_git_location_env(os.environ),
    )
    return result.stdout


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", str(repo))
    _git("-C", str(repo), "config", "user.email", "t@example.com")
    _git("-C", str(repo), "config", "user.name", "t")


def _commit_all(repo: Path, message: str) -> None:
    _git("-C", str(repo), "add", "-A")
    _git("-C", str(repo), "commit", "-q", "-m", message)


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


@pytest.fixture
def fleet_root(tmp_path: Path, policy: Policy) -> Path:
    """A stand-in for the registry clone at `$OMNI_HOME`, markers committed."""
    root = tmp_path / "fleet_root"
    _init(root)
    for marker in policy.registry_root_markers:
        target = root / marker
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture\n")
    (root / "docs" / "notes.md").parent.mkdir(parents=True, exist_ok=True)
    (root / "docs" / "notes.md").write_text("notes\n")
    _commit_all(root, "markers")
    return root


@pytest.fixture
def canonical(fleet_root: Path) -> Path:
    """A code-repo canonical clone directly under `$OMNI_HOME`.

    It carries a `dev` base and a remote-tracking `origin/dev` pointing at
    it, which is the shape every lane's worktree is cut from.
    """
    clone = fleet_root / "omnibase_infra"
    _init(clone)
    (clone / "src").mkdir()
    (clone / "src" / "guard.py").write_text(BASE_TEXT)
    (clone / "src" / "other.py").write_text("other\n")
    (clone / "CLAUDE.md").write_text("# base\n" + "rule\n" * 200)
    _commit_all(clone, "base")
    _git("-C", str(clone), "branch", "dev")
    _git("-C", str(clone), "update-ref", "refs/remotes/origin/dev", "dev")
    return clone


@pytest.fixture
def worktree(fleet_root: Path, canonical: Path) -> Path:
    """A lane worktree, freshly cut from `origin/dev`: HEAD IS the base."""
    wt = fleet_root / "omni_worktrees" / "OMN-1" / "omnibase_infra"
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(
        "-C",
        str(canonical),
        "worktree",
        "add",
        "-q",
        str(wt),
        "-b",
        "lane/omn-1",
        "origin/dev",
    )
    return wt


def _evaluate(command: str, policy: Policy, cwd: Path, fleet_root: Path) -> Decision:
    return evaluate_bash_command(
        command, policy, cwd=cwd, registry_root=fleet_root, worktree_roots=()
    )


def _replay(
    commands: list[str], policy: Policy, cwd: Path, fleet_root: Path
) -> list[Decision]:
    """Drive each command through the guard, EXECUTING the ones it admits.

    This is the tool seam in miniature: a refused command never reaches the
    shell, an admitted one does, and the next command is judged against the
    tree the previous ones actually left.
    """
    decisions: list[Decision] = []
    for command in commands:
        decision = _evaluate(command, policy, cwd, fleet_root)
        decisions.append(decision)
        if not decision.blocked:
            subprocess.run(
                command,
                shell=True,
                check=True,
                capture_output=True,
                cwd=cwd,
                env=scrub_git_location_env(os.environ),
            )
    return decisions


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------


def test_policy_declares_the_restore_vocabulary(policy: Policy) -> None:
    assert policy.restore_ticket == RESTORE_TICKET
    assert policy.restore_subcommands == frozenset({"checkout", "restore"})
    # A restore verb nobody puts through the vocabulary loop is a verb the
    # guard never evaluates, so both must also be in the refused set.
    assert policy.restore_subcommands <= policy.refused_subcommands
    # The pre-image refs a restored file's content is compared against, so
    # the Rule 17 committed-first sequence passes: its third command
    # restores a path whose content is origin/dev's.
    assert "HEAD" in policy.restore_reachable_refs
    assert "origin/dev" in policy.restore_reachable_refs
    assert policy.git_probe_timeout_seconds > 0
    assert "ONEX_WORKTREES_ROOT" in policy.worktree_root_envs


# ---------------------------------------------------------------------------
# AC1: a restore over a dirty path is refused; over a clean path it is not
# ---------------------------------------------------------------------------


DIRTY_RESTORE_SHAPES = [
    "git checkout HEAD -- src/guard.py",
    "git checkout origin/dev -- src/guard.py",
    "git checkout -- src/guard.py",
    "git checkout HEAD src/guard.py",
    "git checkout src/guard.py",
    "git restore src/guard.py",
    "git restore -- src/guard.py",
    "git restore --source=HEAD src/guard.py",
    "git restore -s origin/dev src/guard.py",
    "git restore --staged --worktree src/guard.py",
    "git restore -SW src/guard.py",
    # Whole-directory and whole-tree pathspecs cover the dirty file too.
    "git checkout HEAD -- src",
    "git checkout HEAD -- src/",
    "git checkout HEAD -- .",
    "git restore .",
    # The -C form, and a wrapper.
    "git -C {wt} checkout HEAD -- src/guard.py",
    "env GIT_TRACE=0 git checkout HEAD -- src/guard.py",
]


@pytest.mark.parametrize("shape", DIRTY_RESTORE_SHAPES)
def test_a_restore_over_an_unstaged_edit_is_refused(
    shape: str, worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    command = shape.format(wt=worktree)
    decision = _evaluate(command, policy, worktree, fleet_root)
    assert decision.blocked, command
    assert RESTORE_TICKET in decision.reason
    assert "src/guard.py" in decision.reason


@pytest.mark.parametrize("shape", DIRTY_RESTORE_SHAPES)
def test_the_same_restore_over_a_clean_path_passes(
    shape: str, worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """The negative control for every refusal above: not a blanket block."""
    command = shape.format(wt=worktree)
    decision = _evaluate(command, policy, worktree, fleet_root)
    assert not decision.blocked, (command, decision.reason)


def test_a_restore_over_a_staged_change_is_refused(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Staged is not committed: the index blob is reachable from no ref."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    _git("-C", str(worktree), "add", "src/guard.py")
    for command in (
        "git checkout HEAD -- src/guard.py",
        "git restore --staged --worktree src/guard.py",
        "git restore --source=HEAD --staged --worktree src/guard.py",
    ):
        decision = _evaluate(command, policy, worktree, fleet_root)
        assert decision.blocked, command
        assert "staged" in decision.reason


def test_a_restore_that_keeps_the_content_is_not_refused(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Precision, not blanket: two restores over a staged edit lose nothing.

    `git checkout -- <path>` restores the WORKING TREE from the INDEX, and
    here the two already agree, so it is a no-op. `git restore --staged`
    resets only the index and leaves the edit in the working tree. Refusing
    either would be refusing work that cannot lose anything, which is how a
    lane learns to route around a guard.
    """
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    _git("-C", str(worktree), "add", "src/guard.py")
    for command in (
        "git checkout -- src/guard.py",
        "git restore src/guard.py",
        "git restore --staged src/guard.py",
    ):
        decision = _evaluate(command, policy, worktree, fleet_root)
        assert not decision.blocked, (command, decision.reason)


def test_restoring_an_untracked_file_the_source_carries_is_refused(
    worktree: Path, fleet_root: Path, canonical: Path, policy: Policy
) -> None:
    """An untracked file the source ref ALSO carries is overwritten by it."""
    (canonical / "src" / "later.py").write_text("upstream\n")
    _commit_all(canonical, "later")
    _git("-C", str(canonical), "update-ref", "refs/remotes/origin/dev", "main")
    (worktree / "src" / "later.py").write_text("my own untracked draft\n")
    decision = _evaluate(
        "git checkout origin/dev -- src/later.py", policy, worktree, fleet_root
    )
    assert decision.blocked
    assert "untracked" in decision.reason


def test_an_untracked_file_the_source_lacks_is_left_alone(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Overlay mode never deletes a path the source does not name."""
    (worktree / "src" / "draft.py").write_text("mine\n")
    decision = _evaluate("git checkout HEAD -- src", policy, worktree, fleet_root)
    assert not decision.blocked, decision.reason


def test_a_deleted_file_is_restored_without_refusal(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Bringing a deleted file back discards no content."""
    (worktree / "src" / "guard.py").unlink()
    decision = _evaluate(
        "git checkout HEAD -- src/guard.py", policy, worktree, fleet_root
    )
    assert not decision.blocked, decision.reason


def test_a_path_that_does_not_exist_yet_passes(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    decision = _evaluate(
        "git checkout HEAD -- src/nothing_here.py", policy, worktree, fleet_root
    )
    assert not decision.blocked, decision.reason


# ---------------------------------------------------------------------------
# OMN-19021's criteria, folded in: per-path judgement, named in the refusal
# ---------------------------------------------------------------------------


def test_a_mixed_invocation_is_judged_per_path(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """One clean path does not launder a dirty one, and only the dirty is named."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = _evaluate(
        "git checkout HEAD -- src/other.py src/guard.py",
        policy,
        worktree,
        fleet_root,
    )
    assert decision.blocked
    assert "src/guard.py" in decision.reason
    assert "src/other.py" not in decision.reason


# ---------------------------------------------------------------------------
# AC2: the refusal names both sanctioned alternatives
# ---------------------------------------------------------------------------


def test_the_refusal_names_the_object_store_read_and_commit_first(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = _evaluate(
        "git checkout HEAD -- src/guard.py", policy, worktree, fleet_root
    )
    assert decision.blocked
    assert "git show <rev>:<path> > <scratch file>" in decision.reason
    assert "commit" in decision.reason.lower()
    assert "git log -1" in decision.reason
    # It is a worktree, so the shared-clone wording must not leak in: that
    # message tells the reader to go to a worktree they are already in.
    assert "shared registry clone" not in decision.reason
    assert "onex hooks disable" in decision.reason


def test_the_object_store_read_is_never_refused(
    worktree: Path, fleet_root: Path, policy: Policy, tmp_path: Path
) -> None:
    """The alternative the refusal prescribes must itself pass over dirty work."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    scratch = tmp_path / "pre-image.py"
    for command in (
        f"git show origin/dev:src/guard.py > {scratch}",
        f"git show HEAD:src/guard.py > {scratch}",
        f"git -C {worktree} show origin/dev:src/guard.py > {scratch}",
    ):
        decision = _evaluate(command, policy, worktree, fleet_root)
        assert not decision.blocked, (command, decision.reason)


# ---------------------------------------------------------------------------
# AC3: replay the four real occurrences
# ---------------------------------------------------------------------------


RULE_17_SEQUENCE = [
    "git checkout origin/dev -- src/guard.py",
    "cat src/guard.py",
    "git checkout HEAD -- src/guard.py",
]


def test_replay_omn_18566_rule_17_sequence_with_the_edit_uncommitted(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """OMN-18566: the three-command Rule 17 sequence, HEAD still at the base.

    On a branch freshly cut from its base, HEAD IS the base, so the first
    command already destroys the edit. The guard refuses it, and the third,
    and the edit is still on disk afterwards.
    """
    target = worktree / "src" / "guard.py"
    target.write_text(IMPL_TEXT)
    decisions = _replay(RULE_17_SEQUENCE, policy, worktree, fleet_root)
    assert decisions[0].blocked
    assert not decisions[1].blocked
    assert decisions[2].blocked
    assert target.read_text() == IMPL_TEXT


def test_replay_omn_18566_rule_17_sequence_with_the_edit_committed_first(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """The same sequence, implementation committed first, passes end to end.

    The third command runs over a path that IS dirty against HEAD -- it
    holds origin/dev's version -- but that content is reachable from
    origin/dev, so restoring loses nothing and the guard must not refuse.
    """
    target = worktree / "src" / "guard.py"
    target.write_text(IMPL_TEXT)
    _commit_all(worktree, "implementation")
    decisions = _replay(RULE_17_SEQUENCE, policy, worktree, fleet_root)
    assert [d.blocked for d in decisions] == [False, False, False], [
        d.reason for d in decisions
    ]
    assert target.read_text() == IMPL_TEXT


def test_replay_omn_18863_checkout_of_head_when_head_is_the_base(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """The OMN-18863 lane: one re-authored source edit, HEAD at the base."""
    target = worktree / "src" / "other.py"
    target.write_text("other\n# the re-authored edit\n")
    decisions = _replay(
        ["git checkout HEAD -- src/other.py"], policy, worktree, fleet_root
    )
    assert decisions[0].blocked
    assert target.read_text() == "other\n# the re-authored edit\n"


def test_replay_omn_18992_red_probe_of_an_uncommitted_guard(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """OMN-18992: red-probing a guard before committing it.

    The lane had the whole implementation uncommitted in the guard module
    and a new test beside it, and reverted the module to the base to watch
    the test fail. The implementation was rewritten from scratch.
    """
    guard = worktree / "src" / "guard.py"
    guard.write_text(IMPL_TEXT)
    new_test = worktree / "src" / "test_guard.py"
    new_test.write_text("def test_guard():\n    assert True\n")
    decisions = _replay(
        [
            "git checkout origin/dev -- src/guard.py",
            "git restore --source=origin/dev src/guard.py",
        ],
        policy,
        worktree,
        fleet_root,
    )
    assert all(d.blocked for d in decisions)
    assert guard.read_text() == IMPL_TEXT
    assert new_test.exists()


def test_replay_omn_19237_negative_probe_on_an_uncommitted_rewrite(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """OMN-19237: an uncommitted CLAUDE.md rewrite, probed, then restored.

    The lane mutated the rewritten file to prove a pointer test could fail,
    then restored it from HEAD, which put back the base file over the
    uncommitted rewrite.
    """
    claude = worktree / "CLAUDE.md"
    rewrite = "# slim\n" + "pointer\n" * 20
    claude.write_text(rewrite + "PROBE MUTATION\n")
    decisions = _replay(
        ["git checkout HEAD -- CLAUDE.md"], policy, worktree, fleet_root
    )
    assert decisions[0].blocked
    assert claude.read_text() == rewrite + "PROBE MUTATION\n"


def test_replay_omn_19237_committed_first_on_a_scratch_copy_passes(
    worktree: Path, fleet_root: Path, policy: Policy, tmp_path: Path
) -> None:
    """The committed-first variant, in the shape the lane itself recorded.

    The lane's own FRICTION row names the correct move: commit the rewrite,
    then probe a scratch copy. Every command in that sequence must pass,
    and the committed rewrite must survive it. Restoring from HEAD over a
    path that holds only committed content passes too.
    """
    claude = worktree / "CLAUDE.md"
    rewrite = "# slim\n" + "pointer\n" * 20
    claude.write_text(rewrite)
    _commit_all(worktree, "rewrite")
    scratch = tmp_path / "probe-CLAUDE.md"
    decisions = _replay(
        [
            f"git show HEAD:CLAUDE.md > {scratch}",
            f"echo 'PROBE MUTATION' >> {scratch}",
            "git checkout HEAD -- CLAUDE.md",
        ],
        policy,
        worktree,
        fleet_root,
    )
    assert [d.blocked for d in decisions] == [False, False, False], [
        d.reason for d in decisions
    ]
    assert claude.read_text() == rewrite
    assert scratch.read_text() == rewrite + "PROBE MUTATION\n"


def test_a_probe_mutation_over_committed_work_is_still_refused(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Stated rather than implied: the guard cannot tell a probe from work.

    A probe mutation typed into the tracked file is uncommitted content
    that exists nowhere else, exactly like the edits the four occurrences
    lost. Nothing but the lane knows it is disposable, so it is refused,
    and the refusal points at the scratch-copy read that never needs one.
    """
    claude = worktree / "CLAUDE.md"
    rewrite = "# slim\n" + "pointer\n" * 20
    claude.write_text(rewrite)
    _commit_all(worktree, "rewrite")
    claude.write_text(rewrite + "PROBE MUTATION\n")
    decision = _evaluate("git checkout HEAD -- CLAUDE.md", policy, worktree, fleet_root)
    assert decision.blocked
    assert "git show <rev>:<path> > <scratch file>" in decision.reason


def test_the_replay_is_refused_when_reached_through_a_cd_prefix(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Lanes reach their worktree with `cd <wt> &&`, the payload cwd elsewhere."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = evaluate_bash_command(
        f"cd {worktree} && git checkout HEAD -- src/guard.py",
        policy,
        cwd=fleet_root,
        registry_root=fleet_root,
        worktree_roots=(),
    )
    assert decision.blocked
    assert RESTORE_TICKET in decision.reason


# ---------------------------------------------------------------------------
# AC4: scope -- worktrees and canonical clones under $OMNI_HOME, not elsewhere
# ---------------------------------------------------------------------------


def test_refused_in_a_canonical_clone_under_fleet_root(
    canonical: Path, fleet_root: Path, policy: Policy
) -> None:
    (canonical / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = _evaluate(
        "git checkout HEAD -- src/guard.py", policy, canonical, fleet_root
    )
    assert decision.blocked
    assert RESTORE_TICKET in decision.reason


def test_refused_in_the_registry_clone_itself(fleet_root: Path, policy: Policy) -> None:
    """The registry clone: a clean path is allowed, a dirty one is not."""
    clean = _evaluate(
        "git checkout HEAD -- docs/notes.md", policy, fleet_root, fleet_root
    )
    assert not clean.blocked, clean.reason
    (fleet_root / "docs" / "notes.md").write_text("an uncommitted note\n")
    dirty = _evaluate(
        "git checkout HEAD -- docs/notes.md", policy, fleet_root, fleet_root
    )
    assert dirty.blocked
    assert RESTORE_TICKET in dirty.reason


def test_not_refused_in_a_scratch_repository_elsewhere(
    tmp_path: Path, fleet_root: Path, worktree: Path, policy: Policy
) -> None:
    """AC4: the same dirty-path command outside the root is left alone.

    Paired with a positive control inside the root in the same test, so a
    guard that stopped firing everywhere could not pass it.
    """
    scratch = tmp_path / "elsewhere" / "scratch"
    _init(scratch)
    (scratch / "src").mkdir()
    (scratch / "src" / "guard.py").write_text(BASE_TEXT)
    _commit_all(scratch, "base")
    (scratch / "src" / "guard.py").write_text(IMPL_TEXT)
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    command = "git checkout HEAD -- src/guard.py"
    outside = _evaluate(command, policy, scratch, fleet_root)
    assert not outside.blocked, outside.reason
    inside = _evaluate(command, policy, worktree, fleet_root)
    assert inside.blocked


def test_a_declared_worktrees_root_outside_fleet_root_is_in_scope(
    tmp_path: Path, fleet_root: Path, canonical: Path, policy: Policy
) -> None:
    """ONEX_WORKTREES_ROOT can point off-tree; a clone under it is in scope."""
    off_root = tmp_path / "wt_root"
    clone = off_root / "OMN-2" / "repo"
    _init(clone)
    (clone / "f.txt").write_text("base\n")
    _commit_all(clone, "base")
    (clone / "f.txt").write_text("edit\n")
    roots = resolve_worktree_roots(policy, {"ONEX_WORKTREES_ROOT": str(off_root)})
    assert roots == (off_root.resolve(),)
    decision = evaluate_bash_command(
        "git checkout HEAD -- f.txt",
        policy,
        cwd=clone,
        registry_root=fleet_root,
        worktree_roots=roots,
    )
    assert decision.blocked
    unscoped = evaluate_bash_command(
        "git checkout HEAD -- f.txt",
        policy,
        cwd=clone,
        registry_root=fleet_root,
        worktree_roots=(),
    )
    assert not unscoped.blocked, unscoped.reason


def test_a_worktree_is_in_scope_even_when_fleet_root_is_unset(
    worktree: Path, policy: Policy
) -> None:
    """A thin hook environment must not turn the guard off in a worktree."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = evaluate_bash_command(
        "git checkout HEAD -- src/guard.py",
        policy,
        cwd=worktree,
        registry_root=None,
        worktree_roots=(),
    )
    assert decision.blocked


# ---------------------------------------------------------------------------
# Shapes that are not path restores stay untouched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "git checkout dev",
        "git checkout -b lane/omn-2-next",
        "git status --porcelain",
        "git diff -- src/guard.py",
        "git log -1 --oneline",
        "grep -n 'git checkout HEAD -- src/guard.py' notes.md",
        "echo git restore src/guard.py",
    ],
)
def test_non_restore_shapes_pass_over_dirty_work(
    command: str, worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    decision = _evaluate(command, policy, worktree, fleet_root)
    assert not decision.blocked, (command, decision.reason)


# ---------------------------------------------------------------------------
# Fail closed when dirtiness cannot be determined
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        # An unresolvable cd: which tree the restore runs in is unknown.
        'cd "$WT" && git checkout HEAD -- src/guard.py',
        # A path the guard cannot read without the shell.
        'git checkout HEAD -- "$TARGET"',
        # Paths from a file the guard does not read.
        "git checkout HEAD --pathspec-from-file=paths.txt",
        "git restore --pathspec-from-file paths.txt",
        # A different repository or work tree than the one resolved.
        "git --work-tree=/elsewhere checkout HEAD -- src/guard.py",
        "git --git-dir=/elsewhere/.git restore src/guard.py",
        # The same relocation spelled as environment, which _strip_wrappers
        # drops and the probes scrub (review finding, OMN-18874).
        "GIT_DIR=/elsewhere/.git git checkout HEAD -- src/guard.py",
        "env GIT_WORK_TREE=/elsewhere git restore src/guard.py",
        "export GIT_WORK_TREE=/elsewhere; git checkout HEAD -- src/guard.py",
        # Brace expansion: git would be asked about a literal `{a,b}` that
        # matches nothing while the shell hands the command both files.
        "git checkout HEAD -- src/{guard,other}.py",
    ],
)
def test_an_indeterminate_restore_is_refused(
    command: str, worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    decision = _evaluate(command, policy, worktree, fleet_root)
    assert decision.blocked, command
    assert RESTORE_TICKET in decision.reason
    assert "could not" in decision.reason or "cannot" in decision.reason


def test_brace_expansion_cannot_launder_a_dirty_path(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Review finding: `{a,b}` read as clean while the shell expands it.

    Replayed for real, so the assertion is on the bytes left on disk.
    """
    target = worktree / "src" / "guard.py"
    target.write_text(IMPL_TEXT)
    decisions = _replay(
        ["git checkout HEAD -- src/{guard,other}.py"], policy, worktree, fleet_root
    )
    assert decisions[0].blocked
    assert target.read_text() == IMPL_TEXT


def test_an_env_relocated_restore_from_a_clean_tree_is_refused(
    worktree: Path, canonical: Path, fleet_root: Path, policy: Policy
) -> None:
    """Review finding: the probe read the clean cwd, git wrote the dirty tree."""
    (canonical / "src" / "guard.py").write_text(IMPL_TEXT)
    command = (
        f"GIT_DIR={canonical}/.git GIT_WORK_TREE={canonical} "
        "git checkout HEAD -- src/guard.py"
    )
    decision = _evaluate(command, policy, worktree, fleet_root)
    assert decision.blocked
    assert (canonical / "src" / "guard.py").read_text() == IMPL_TEXT


def _make_conflict(worktree: Path) -> Path:
    """A real both-modified conflict on src/guard.py, hand-resolved."""
    target = worktree / "src" / "guard.py"
    _git("-C", str(worktree), "checkout", "-q", "-b", "side")
    target.write_text("def guard():\n    return 'side'\n")
    _commit_all(worktree, "side")
    _git("-C", str(worktree), "checkout", "-q", "lane/omn-1")
    target.write_text("def guard():\n    return 'lane'\n")
    _commit_all(worktree, "lane")
    subprocess.run(
        ["git", "-C", str(worktree), "merge", "-q", "side"],
        capture_output=True,
        check=False,
        env=scrub_git_location_env(os.environ),
    )
    status = _git("-C", str(worktree), "status", "--porcelain", "--", "src/guard.py")
    assert status.startswith("UU"), status
    target.write_text("def guard():\n    return 'hand resolution'\n")
    return target


@pytest.mark.parametrize(
    "command",
    [
        "git checkout --theirs -- src/guard.py",
        "git checkout --ours -- src/guard.py",
        "git checkout -m -- src/guard.py",
        "git restore --theirs src/guard.py",
    ],
)
def test_a_hand_resolved_conflict_is_not_overwritten(
    command: str, worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Review finding: an index-sourced checkout skipped conflicted paths.

    A conflicted path has no stage-0 entry, so it was never "in the source"
    and overlay mode passed it -- while `--ours`, `--theirs` and `-m` each
    rewrite the working-tree file and discard the resolution.
    """
    target = _make_conflict(worktree)
    decisions = _replay([command], policy, worktree, fleet_root)
    assert decisions[0].blocked, command
    assert "hand resolution" in target.read_text()


def test_an_unresolved_branch_checkout_names_git_switch(
    worktree: Path, fleet_root: Path, policy: Policy
) -> None:
    """Fail closed, stated: with the directory unknown, a bare `git checkout X`
    may be a branch switch or a path restore, and the refusal says so and
    names the unambiguous verb instead of calling it a restore outright.
    """
    decision = _evaluate('cd "$REPO" && git checkout dev', policy, worktree, fleet_root)
    assert decision.blocked
    assert "switches branches or restores" in decision.reason
    assert "git switch" in decision.reason
    literal = _evaluate(
        f"cd {worktree} && git checkout dev", policy, worktree, fleet_root
    )
    assert not literal.blocked, literal.reason


def test_a_failing_git_probe_is_refused(
    worktree: Path,
    fleet_root: Path,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If git itself cannot answer, the restore is refused, not admitted."""

    def _broken(*_args: object, **_kwargs: object) -> str:
        raise shared_tree_git_guard.GitProbeError("simulated: git timed out")

    monkeypatch.setattr(shared_tree_git_guard, "_run_git", _broken)
    decision = _evaluate(
        "git checkout HEAD -- src/guard.py", policy, worktree, fleet_root
    )
    assert decision.blocked
    assert "simulated: git timed out" in decision.reason


def test_a_real_git_timeout_is_refused(
    worktree: Path, fleet_root: Path, tmp_path: Path, policy: Policy
) -> None:
    """The timeout is enforced on the subprocess, not only declared."""
    raw = json.loads(POLICY_PATH.read_text())
    raw["git_probe_timeout_seconds"] = 0.000001
    tight = tmp_path / "tight.json"
    tight.write_text(json.dumps(raw))
    decision = _evaluate(
        "git checkout HEAD -- src/guard.py", load_policy(tight), worktree, fleet_root
    )
    assert decision.blocked
    assert RESTORE_TICKET in decision.reason


# ---------------------------------------------------------------------------
# The RED control: an emptied restore vocabulary admits every refused shape
# ---------------------------------------------------------------------------


def test_no_op_policy_admits_every_dirty_restore(
    tmp_path: Path, worktree: Path, fleet_root: Path
) -> None:
    raw = json.loads(POLICY_PATH.read_text())
    raw["restore_subcommands"] = ["a-verb-nobody-types"]
    noop_path = tmp_path / "noop.json"
    noop_path.write_text(json.dumps(raw))
    noop = load_policy(noop_path)
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    for shape in DIRTY_RESTORE_SHAPES:
        command = shape.format(wt=worktree)
        decision = _evaluate(command, noop, worktree, fleet_root)
        assert not decision.blocked, (command, decision.reason)


# ---------------------------------------------------------------------------
# End to end through the real shell wrapper
# ---------------------------------------------------------------------------


def _run_hook(
    tmp_path: Path,
    command: str,
    cwd: Path,
    fleet_root: Path,
    mask: str | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(HOOKS_DIR.parent),
        # The real omniclaude checkout, so is_omninode_repo() lets the call
        # through to the guard; the payload cwd is what the core resolves.
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hook.log"),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        "OMNICLAUDE_MODE": "full",
        "OMNI_HOME": str(fleet_root),
    }
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
    ["git checkout HEAD -- src/guard.py", "git restore src/guard.py"],
)
def test_shell_wrapper_refuses_a_dirty_restore_in_a_worktree(
    command: str, tmp_path: Path, worktree: Path, fleet_root: Path
) -> None:
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    result = _run_hook(tmp_path, command, cwd=worktree, fleet_root=fleet_root)
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert '"decision": "block"' in result.stdout
    assert RESTORE_TICKET in result.stdout


def test_shell_wrapper_allows_a_clean_restore_in_a_worktree(
    tmp_path: Path, worktree: Path, fleet_root: Path
) -> None:
    result = _run_hook(
        tmp_path,
        "git restore src/guard.py",
        cwd=worktree,
        fleet_root=fleet_root,
    )
    assert result.returncode == 0, (result.stdout, result.stderr)


def test_shell_wrapper_logs_a_deliberate_disable(
    tmp_path: Path, worktree: Path, fleet_root: Path
) -> None:
    """A disabled guard admits the command and says so in the hook log."""
    (worktree / "src" / "guard.py").write_text(IMPL_TEXT)
    result = _run_hook(
        tmp_path,
        "git checkout HEAD -- src/guard.py",
        cwd=worktree,
        fleet_root=fleet_root,
        mask="0x0",
    )
    assert result.returncode == 0, (result.stdout, result.stderr)
    log = (tmp_path / "hook.log").read_text()
    assert "DISABLED" in log
    assert "onex hooks enable SCOPE_GATE" in log
