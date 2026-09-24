# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the ``git worktree add`` canonical-root guard (OMN-19229, OMN-19123).

``pre_tool_use_worktree_guard.sh`` took the first non-dash word after ``add``
as the destination and resolved it against the hook's cwd. Every real
occurrence below was a wrong verdict from that loop, and each is replayed
through the registered shell hook, so this module fails against the old
script and passes against the new decision core:

* ledger:5591 -- ``"$WT"`` judged as the literal ``$WT`` and refused;
* ledger:5848 -- the value of ``-b`` judged as the destination and refused;
* ledger:4007 (the OMN-19123 incident) and ledger:5841 -- ``git -C <clone>
  worktree add <relative>`` never matched the guard's pattern, so a worktree
  that git resolved inside a canonical clone was admitted;
* 2026-09-23 -- ``git worktree add -h 2>&1`` refused with ``2>&1`` as the path.

The positive and negative controls pin the verdicts the old loop already got
right, so the new parser is shown to keep them.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
HOOK = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_worktree_guard.sh"
)

sys.path.insert(0, str(LIB_DIR))

import shell_words  # noqa: E402
import worktree_add_guard  # noqa: E402
from worktree_add_guard import evaluate  # noqa: E402


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A registry root with a worktrees root and two canonical clones."""
    home = tmp_path / "registry"
    for name in ("omni_worktrees", "omnibase_infra", "second-clone"):
        (home / name).mkdir(parents=True)
    return home


@pytest.fixture
def sandbox_home(tmp_path: Path) -> Path:
    """A ``$HOME`` with no ``~/.omnibase/.env``, so no developer env leaks in."""
    home = tmp_path / "fake_home"
    home.mkdir()
    return home


def _run_hook(
    command: str,
    *,
    workspace: Path,
    sandbox_home: Path,
    cwd: Path,
    env_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT / "plugins" / "onex")
    # The repo guard passes the hook through outside an OmniNode repo.
    env["CLAUDE_PROJECT_DIR"] = str(REPO_ROOT)
    env["HOME"] = str(sandbox_home)
    env["ONEX_STATE_DIR"] = str(sandbox_home / ".onex_state")
    env["OMNI_HOME"] = str(workspace)
    for key in ("ONEX_WORKTREES_ROOT", "OMNI_WORKTREES_DIR", "ONEX_HOOKS_MASK", "WT"):
        env.pop(key, None)
    for key, value in (env_overrides or {}).items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}
    return subprocess.run(  # noqa: S603
        ["bash", str(HOOK)],  # noqa: S607
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        env=env,
        cwd=cwd,
    )


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    return str(json.loads(result.stdout)["reason"])


def _assert_allowed(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, (
        f"expected admission, got exit {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def _assert_refused(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 2, (
        f"expected refusal, got exit {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return _reason(result)


@pytest.mark.unit
class TestReplayedOccurrences:
    """Each real occurrence, verbatim apart from the workspace path and branch names."""

    def test_ledger_5591_quoted_variable_destination_is_expanded(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        wt = workspace / "omni_worktrees" / "OMN-17573" / "omnibase_infra"
        result = _run_hook(
            f'WT="{wt}"; git worktree add "$WT" -b feat/omn-17573 origin/dev',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace / "omnibase_infra",
        )
        _assert_allowed(result)

    def test_ledger_5848_branch_value_is_not_the_destination(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            "git worktree add --no-track -b ledger-publish-omn19212 "
            '"$OMNI_HOME/omni_worktrees/OMN-19212/registry-ledger-publish" origin/main',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)

    def test_ledger_4007_relative_path_under_git_c_lands_in_the_clone(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        """The OMN-19123 incident command, verbatim (AC5)."""
        result = _run_hook(
            "git -C omnibase_infra worktree add omni_worktrees/OMN-19113/omnibase_infra "
            "-b feat/omn-19113 origin/dev",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        landed = (
            workspace
            / "omnibase_infra"
            / "omni_worktrees"
            / "OMN-19113"
            / "omnibase_infra"
        )
        assert str(landed.resolve()) in reason

    def test_ledger_5841_absolute_git_c_relative_path_lands_in_the_clone(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            "git -C $OMNI_HOME/second-clone worktree add "
            "omni_worktrees/OMN-19236/second-clone -b feat/omn-19236 origin/dev",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        landed = workspace / "second-clone" / "omni_worktrees" / "OMN-19236"
        assert str(landed.resolve()) in reason

    def test_help_with_a_redirection_creates_nothing(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            "git worktree add -h 2>&1 | head -30",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)


@pytest.mark.unit
class TestControls:
    def test_path_first_absolute_under_root_is_admitted(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        dest = workspace / "omni_worktrees" / "OMN-1" / "repo"
        result = _run_hook(
            f"git worktree add {dest} -b feat/x origin/dev",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)

    def test_flags_first_absolute_under_root_is_admitted(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        dest = workspace / "omni_worktrees" / "OMN-1" / "repo"
        result = _run_hook(
            f"git worktree add -b feat/x {dest} origin/dev",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)

    def test_relative_path_resolved_against_git_c_under_root_is_admitted(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            f"git -C {workspace / 'omnibase_infra'} worktree add "
            "../omni_worktrees/OMN-1/omnibase_infra -b feat/x origin/dev",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=sandbox_home,
        )
        _assert_allowed(result)

    def test_absolute_path_outside_root_is_refused(
        self, workspace: Path, sandbox_home: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere" / "repo"
        result = _run_hook(
            f"git worktree add {outside} -b feat/x",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        assert str(outside.resolve()) in reason
        assert "onex hooks disable WORKTREE_GUARD" in reason

    def test_segment_match_alone_no_longer_admits(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        """OMN-19123 AC2: a path containing `omni_worktrees` inside a clone is refused."""
        dest = workspace / "omnibase_infra" / "omni_worktrees" / "OMN-1" / "repo"
        result = _run_hook(
            f"git worktree add {dest} -b feat/x",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        assert str(dest.resolve()) in _assert_refused(result)

    def test_backslash_continuation_between_worktree_and_add_is_judged(
        self, workspace: Path, sandbox_home: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "elsewhere"
        result = _run_hook(
            f"git worktree \\\n  add {outside} -b feat/x",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        assert str(outside.resolve()) in _assert_refused(result)

    def test_mention_in_a_commit_message_is_not_judged(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            "git commit -m 'fix: git worktree add /tmp/x was misread'",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)


@pytest.mark.unit
class TestExpansion:
    """OMN-19229 AC1-AC3."""

    def test_worktree_guard_expands_env_variable(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        wt = workspace / "omni_worktrees" / "OMN-1" / "repo"
        result = _run_hook(
            'git worktree add "$WT" -b x',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
            env_overrides={"WT": str(wt)},
        )
        _assert_allowed(result)

    def test_worktree_guard_expands_braced_variable_and_home(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            'git worktree add "${OMNI_HOME}/omni_worktrees/OMN-1/repo" -b x',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        _assert_allowed(result)

    def test_unset_variable_is_refused_naming_it(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        result = _run_hook(
            'git worktree add "$WT" -b x',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        assert "`$WT` is unset" in reason

    def test_variable_outside_root_is_refused_naming_the_expanded_value(
        self, workspace: Path, sandbox_home: Path, tmp_path: Path
    ) -> None:
        outside = tmp_path / "x"
        result = _run_hook(
            'git worktree add "$WT" -b x',
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
            env_overrides={"WT": str(outside)},
        )
        reason = _assert_refused(result)
        assert f"expands to `{outside}`" in reason

    @pytest.mark.parametrize(
        "destination",
        ['"$(touch {marker})"', "`touch {marker}`/x", '"$(touch {marker})/x"'],
    )
    def test_command_substitution_is_refused_and_never_run(
        self, workspace: Path, sandbox_home: Path, tmp_path: Path, destination: str
    ) -> None:
        marker = tmp_path / "substitution-ran"
        result = _run_hook(
            f"git worktree add {destination.format(marker=marker)} -b x",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        assert "never executed" in _assert_refused(result)
        assert not marker.exists(), "the guard executed a command substitution"

    def test_evaluate_spawns_no_process(
        self, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _forbidden(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("the guard spawned a process")

        monkeypatch.setattr(subprocess, "Popen", _forbidden)
        monkeypatch.setattr(os, "system", _forbidden)
        monkeypatch.setattr(os, "popen", _forbidden)
        decision = evaluate(
            'git worktree add "$(mktemp -d)"',
            cwd=workspace,
            root=workspace / "omni_worktrees",
            env={},
        )
        assert decision.blocked
        assert "never executed" in decision.reason

    def test_expand_helper_shared(self) -> None:
        """OMN-19229 AC4: every guard that judges a path uses ONE helper."""
        import pr_body_stamp_guard
        import shared_tree_git_guard

        assert worktree_add_guard.tokenize is shell_words.tokenize
        for guard in (worktree_add_guard, shared_tree_git_guard, pr_body_stamp_guard):
            assert guard.expand_word is shell_words.expand_word, guard.__name__


def _judge(command: str, workspace: Path, cwd: Path | None = None) -> str | None:
    """None when admitted, else the refusal reason."""
    decision = evaluate(
        command,
        cwd=cwd or workspace,
        root=workspace / "omni_worktrees",
        env={
            "OMNI_HOME": str(workspace),
            "HOME": str(workspace / "home"),
            "WT_ENV": str(workspace / "omni_worktrees" / "T" / "r"),
            "PWD": str(workspace / "omni_worktrees" / "T"),
        },
    )
    return decision.reason if decision.blocked else None


@pytest.mark.unit
class TestArgumentParsing:
    @pytest.mark.parametrize(
        "command",
        [
            "git worktree add --lock --reason 'long reason' {dest}",
            "git worktree add --reason=why --lock {dest}",
            "git worktree add -bfeat/x {dest}",
            "git worktree add -fb feat/x {dest}",
            "git worktree add -B feat/x --orphan {dest}",
            "git worktree add --det -- {dest}",
            "git worktree add -- {dest} origin/dev",
            "git --no-pager -c core.x=y worktree add {dest}",
            "cd {workspace}/omnibase_infra && git worktree add ../omni_worktrees/T/r",
            "(cd /tmp) && git worktree add omni_worktrees/T/r",
            "env FOO=1 nohup git worktree add {dest}",
            'export WT={dest}; git worktree add "$WT"',
            "cat > f <<EOF\ngit worktree add /tmp/x\nEOF\ngit worktree add {dest}",
            "git status # git worktree add /tmp/x\ngit worktree add {dest}",
            'BR=feat/x; git worktree add -b"$BR" {dest}',
            'git worktree add --lock --reason="$HOME" {dest}',
            "eval git worktree add {dest}",
            "bash <<EOF\ngit worktree add {dest}\nEOF",
            'S="git worktree add {dest}"; bash -c "$S"',
            "env -C {workspace}/omnibase_infra git worktree add ../omni_worktrees/T/r",
            "git worktree add {dest} && bash scripts/check.sh",
            "timeout 60 git worktree add {dest}",
            "bash -o pipefail -c 'git worktree add {dest}'",
            "git commit -m \"$(cat <<'EOF'\nfix: it doesn't misread git worktree add\nEOF\n)\"",
        ],
    )
    def test_admitted(self, workspace: Path, command: str) -> None:
        dest = workspace / "omni_worktrees" / "T" / "r"
        assert _judge(command.format(dest=dest, workspace=workspace), workspace) is None

    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("git worktree add --bogus {dest}", "`--bogus` is not"),
            ("git worktree add -x {dest}", "`-x`"),
            ("git worktree add --lock=yes {dest}", "takes no value"),
            ("git worktree add '$WT'", "Got: "),
            ("git worktree add ~/x", "expands to"),
            ("git worktree add {workspace}/omni_worktrees", "Got: "),
            (
                "git worktree add {workspace}/omni_worktrees/../omnibase_infra/x",
                "Got: ",
            ),
            ("git worktree add {workspace}/omni_worktrees/*/x", "glob"),
            ("git worktree add '{dest}", "cannot be split"),
            ('cd "$NOPE" && git worktree add omni_worktrees/T/r', "`$NOPE` is unset"),
            ('git -C "$NOPE" worktree add omni_worktrees/T/r', "`$NOPE` is unset"),
            ("bash -c 'git worktree add /tmp/x'", "Got: "),
            ('git worktree add "${{WT:-/tmp}}"', "not resolved"),
            ("git status # comment\ngit worktree add /tmp/y", "Got: "),
            # The review findings on the first revision of this change.
            ("eval git worktree add /tmp/x", "Got: "),
            ("bash <<EOF\ngit worktree add /tmp/x\nEOF", "Got: "),
            ("sh <<'EOF'\ngit worktree add /tmp/x\nEOF", "Got: "),
            ('S="git worktree add /tmp/x"; bash -c "$S"', "Got: "),
            (
                'bash -c "$UNSET_SCRIPT"  # runs git worktree add',
                "`$UNSET_SCRIPT` is unset",
            ),
            (
                "env -C {workspace}/omnibase_infra git worktree add omni_worktrees/T/r",
                "resolves against",
            ),
            ("env -S 'git worktree add /tmp/x'", "Got: "),
            ("sudo git worktree add /tmp/x", "Got: "),
            ("echo 'git worktree add /tmp/x' | bash", "standard input"),
            # A variable the command changes, or the shell manages.
            ('read WT_ENV; git worktree add "$WT_ENV"', "cannot resolve"),
            (
                'for WT_ENV in a b; do git worktree add "$WT_ENV"; done',
                "cannot resolve",
            ),
            ('cd /tmp && git worktree add "$PWD/x"', "set by the shell"),
            # The second review pass.
            ("timeout 60 bash -c 'git worktree add /tmp/x'", "Got: "),
            ("sudo bash -c 'git worktree add /tmp/x'", "Got: "),
            ("nice -n 5 sh -c 'git worktree add /tmp/x'", "Got: "),
            ("if true; then bash -c 'git worktree add /tmp/x'; fi", "Got: "),
            ("{{ bash -c 'git worktree add /tmp/x'; }}", "Got: "),
            ("! bash -c 'git worktree add /tmp/x'", "Got: "),
            (
                "if true; then cd {workspace}/omnibase_infra; fi; git worktree add wt2",
                "resolves against",
            ),
            (
                "{{ cd {workspace}/omnibase_infra; }}; git worktree add wt2",
                "resolves against",
            ),
            ("X='br /tmp/x'; git worktree add -b $X", "split"),
            ("echo /tmp/x | xargs git worktree add", "not on the command line"),
            ("bash -c -- 'git worktree add /tmp/x'", "Got: "),
            ("bash -c -e 'git worktree add /tmp/x'", "Got: "),
            ("bash -s arg <<EOF\ngit worktree add /tmp/x\nEOF", "Got: "),
        ],
    )
    def test_refused(self, workspace: Path, command: str, expected: str) -> None:
        dest = workspace / "omni_worktrees" / "T" / "r"
        reason = _judge(command.format(dest=dest, workspace=workspace), workspace)
        assert reason is not None
        assert expected in reason

    def test_git_c_relative_path_is_absolute_in_the_refusal(
        self, workspace: Path
    ) -> None:
        reason = _judge(
            "git -C omnibase_infra worktree add omni_worktrees/X/omnibase_infra",
            workspace,
        )
        assert reason is not None
        expected = (workspace / "omnibase_infra" / "omni_worktrees" / "X").resolve()
        assert str(expected) in reason
        assert "resolves against" in reason

    def test_prefix_assignment_reaches_the_child_shell(self, workspace: Path) -> None:
        decision = evaluate(
            "WT=/tmp/x bash -c 'git worktree add \"$WT\"'",
            cwd=workspace,
            root=workspace / "omni_worktrees",
            env={"WT": str(workspace / "omni_worktrees" / "T" / "r")},
        )
        assert decision.blocked
        assert "/tmp/x" in decision.reason

    def test_unresolvable_root_refuses_only_a_real_add(self, workspace: Path) -> None:
        mention = evaluate(
            "git commit -m 'git worktree add /x'", cwd=workspace, root=None, env={}
        )
        assert not mention.blocked
        real = evaluate(
            f"git worktree add {workspace}/omni_worktrees/T/r",
            cwd=workspace,
            root=None,
            env={},
        )
        assert real.blocked
        assert "OMNI_HOME" in real.reason


@pytest.mark.unit
class TestShellWords:
    def test_quote_kinds_are_kept(self) -> None:
        tokens = shell_words.tokenize("""a"$B"'$C'\\$D""")
        assert len(tokens) == 1
        word = tokens[0]
        assert isinstance(word, shell_words.Word)
        assert shell_words.expand_word(word, {"B": "b"}) == "ab$C$D"

    def test_redirections_and_their_targets_are_dropped(self) -> None:
        words = shell_words.split_commands(
            shell_words.tokenize("cmd a 2>&1 >/dev/null b <in 3>&- c")
        )
        assert [[w.text for w in c] for c in words] == [["cmd", "a", "b", "c"]]

    def test_newlines_and_operators_split_commands(self) -> None:
        commands = shell_words.split_commands(
            shell_words.tokenize("a 1 && b 2\nc 3 | d; (e)")
        )
        assert [[w.text for w in c] for c in commands] == [
            ["a", "1"],
            ["b", "2"],
            ["c", "3"],
            ["d"],
            ["e"],
        ]

    def test_empty_variable_is_unresolvable(self) -> None:
        (word,) = shell_words.tokenize('"$E/x"')
        assert isinstance(word, shell_words.Word)
        with pytest.raises(shell_words.UnresolvableWord, match="empty"):
            shell_words.expand_word(word, {"E": ""})

    def test_assignment_split(self) -> None:
        (word,) = shell_words.tokenize('WT="$H/x"')
        assert isinstance(word, shell_words.Word)
        pair = word.assignment()
        assert pair is not None
        name, value = pair
        assert name == "WT"
        assert shell_words.expand_word(value, {"H": "/h"}) == "/h/x"


@pytest.mark.unit
class TestStrayWorktreeRoot:
    """The sibling ``omni_worktrees`` beside the registry root is a stray root.

    Operator ruling 2026-09-24: it is never used. It was populated twice by
    commands the guard never judged -- ``mkdir -p`` and ``git clone`` into it,
    after a lane redefined OMNI_HOME as the registry's parent -- and a second
    sanctioned root, ``omnibase_internal/omni_worktrees`` beside the registry,
    now exists. Each replay below is the historical command with only the
    workspace path substituted.
    """

    @staticmethod
    def _stray(workspace: Path) -> Path:
        return workspace.parent / "omni_worktrees"

    def test_redefined_registry_env_mkdir_into_the_stray_root_is_refused(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        parent = workspace.parent
        result = _run_hook(
            f"set -e; OMNI_HOME={parent}; WT=$OMNI_HOME/omni_worktrees/OMN-18479; "
            "mkdir -p $WT",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        assert str(self._stray(workspace).resolve()) in reason
        assert "stray worktree root" in reason

    def test_mkdir_of_a_literal_stray_path_is_refused(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        stray = self._stray(workspace) / "OMN-19042"
        result = _run_hook(
            f"mkdir -p {stray}",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        assert "stray worktree root" in _assert_refused(result)

    def test_clone_after_cd_into_the_stray_root_is_refused(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        stray = self._stray(workspace) / "OMN-18479"
        result = _run_hook(
            f"cd {stray} && git clone git@github.com:OmniNode-ai/RSD.git RSD",
            workspace=workspace,
            sandbox_home=sandbox_home,
            cwd=workspace,
        )
        reason = _assert_refused(result)
        assert str((stray / "RSD").resolve()) in reason

    def test_clone_without_a_directory_derives_it_from_the_url(
        self, workspace: Path
    ) -> None:
        stray = self._stray(workspace) / "T"
        reason = _judge(
            f"cd {stray} && git clone --depth 1 https://github.com/o/RSD.git",
            workspace,
        )
        assert reason is not None
        assert str((stray / "RSD").resolve()) in reason

    def test_worktree_add_into_the_stray_root_names_it(self, workspace: Path) -> None:
        stray = self._stray(workspace) / "OMN-18479" / "omnibase_infra"
        reason = _judge(
            f"git -C {workspace}/omnibase_infra worktree add {stray} -b x origin/dev",
            workspace,
        )
        assert reason is not None
        assert "stray worktree root" in reason

    def test_nested_stray_root_inside_a_clone_is_refused(self, workspace: Path) -> None:
        reason = _judge(
            f"mkdir -p {workspace}/omnibase_infra/omni_worktrees/OMN-1", workspace
        )
        assert reason is not None
        assert "stray worktree root" in reason

    @pytest.mark.parametrize(
        "command",
        [
            "mkdir -p $OMNI_HOME/omni_worktrees/OMN-1",
            "mkdir -p {workspace}/omni_worktrees/OMN-1/repo",
            "mkdir {workspace}/omni_worktrees",
            "cd {workspace}/omni_worktrees/OMN-1 && git clone git@github.com:o/RSD.git",
            "git clone https://github.com/o/r.git {workspace}/omni_worktrees/T/r",
            "git clone https://github.com/o/r.git /tmp/scratch-clone",
            "mkdir -p /tmp/lane-scratch && ls $OMNI_HOME/omni_worktrees",
            'mkdir -p "$UNSET_SCRATCH/notes"',
            "ls {stray}",
            "git -C {workspace}/omnibase_infra worktree list | grep omni_worktrees",
        ],
    )
    def test_positive_controls_are_admitted(
        self, workspace: Path, command: str
    ) -> None:
        text = command.format(workspace=workspace, stray=self._stray(workspace))
        assert _judge(text, workspace) is None

    def test_unresolvable_destination_naming_a_worktrees_dir_is_refused(
        self, workspace: Path
    ) -> None:
        reason = _judge('mkdir -p "$UNSET_BASE/omni_worktrees/OMN-1"', workspace)
        assert reason is not None
        assert "cannot be resolved" in reason

    def test_second_sanctioned_root_admits_once_it_exists(
        self, workspace: Path, sandbox_home: Path
    ) -> None:
        internal = workspace.parent / "omnibase_internal" / "omni_worktrees"
        dest = internal / "OMN-1" / "omnibase_infra"
        command = f"git -C {workspace}/omnibase_infra worktree add {dest} -b x"
        # Control: before the root exists, it is not sanctioned.
        reason = _assert_refused(
            _run_hook(
                command, workspace=workspace, sandbox_home=sandbox_home, cwd=workspace
            )
        )
        assert str(workspace / "omni_worktrees") in reason
        internal.mkdir(parents=True)
        _assert_allowed(
            _run_hook(
                command, workspace=workspace, sandbox_home=sandbox_home, cwd=workspace
            )
        )

    def test_second_root_is_listed_in_the_refusal(self, workspace: Path) -> None:
        internal = workspace.parent / "omnibase_internal" / "omni_worktrees"
        internal.mkdir(parents=True)
        decision = evaluate(
            "git worktree add /tmp/elsewhere/x",
            cwd=workspace,
            root=workspace / "omni_worktrees",
            env={},
            extra_roots=[internal],
        )
        assert decision.blocked
        assert str(internal.resolve()) in decision.reason
