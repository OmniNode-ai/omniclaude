# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Cross-guard regressions for top-20 item 3 (OMN-17427)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib"))
import pr_body_stamp_guard as body
import worktree_add_guard as worktree

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as shared

pytestmark = pytest.mark.unit


def test_worktree_assignments_are_sequential(tmp_path: Path) -> None:
    root = tmp_path / "omni_worktrees"
    decision = worktree.evaluate(
        'A="$ROOT" B="$A/ticket/repo"; git worktree add "$B" origin/dev',
        cwd=tmp_path,
        root=root,
        env={"ROOT": str(root)},
    )
    assert not decision.blocked, decision.reason
    assert decision.judged == (str(root / "ticket/repo"),)


def test_body_file_uses_hook_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file = tmp_path / "body.md"
    file.write_text("Evidence-Source: OCC#9999\n")
    monkeypatch.setenv("RESOLVER_BODY", str(file))
    (edit,) = body.parse_pr_body_edits(
        'gh pr edit 1 --body-file "$RESOLVER_BODY"',
        body.load_policy(),
        cwd=str(tmp_path),
    )
    assert edit.new_body == file.read_text(), edit.unreadable_reason


def test_body_export_then_write_follows_cd_double_dash(tmp_path: Path) -> None:
    dest = tmp_path / "dest"
    dest.mkdir()
    command = f"""export B=body.md; cd -- '{dest}'
cat > "$B" <<'EOF'
Evidence-Source: OCC#9999
It's a body with an unmatched " quote.
EOF
gh pr edit 1 --body-file "$B"
"""
    (edit,) = body.parse_pr_body_edits(command, body.load_policy(), cwd=str(tmp_path))
    assert edit.new_body is not None, edit.unreadable_reason
    assert "It's a body" in edit.new_body
    assert not (dest / "body.md").exists(), "the resolver must never execute the write"


def test_shared_target_keeps_single_quotes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = tmp_path / "registry"
    literal = tmp_path / "$RESOLVER_TREE"
    for directory in (registry, literal):
        (directory / ".git").mkdir(parents=True)
    monkeypatch.setenv("RESOLVER_TREE", str(registry))
    decision = shared.evaluate_bash_command(
        "git -C '$RESOLVER_TREE' reset --hard", shared.load_policy(), tmp_path, registry
    )
    assert not decision.blocked, decision.reason
    decision = shared.evaluate_bash_command(
        'git -C "$RESOLVER_TREE" reset --hard', shared.load_policy(), tmp_path, registry
    )
    assert decision.blocked


def test_shared_composes_every_git_c(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    (registry / ".git").mkdir(parents=True)
    decision = shared.evaluate_bash_command(
        f"git -C '{tmp_path}' -C registry reset --hard",
        shared.load_policy(),
        tmp_path / "other",
        registry,
    )
    assert decision.blocked, "the final relative -C resolves against the preceding -C"


def test_same_command_unknown_write_does_not_read_stale_body(tmp_path: Path) -> None:
    file = tmp_path / "body.md"
    file.write_text("Evidence-Source: OCC#9999\n")
    (edit,) = body.parse_pr_body_edits(
        'python -c "unknown_writer()"; gh pr edit 1 --body-file body.md',
        body.load_policy(),
        cwd=str(tmp_path),
    )
    assert edit.new_body is None
    assert edit.unreadable_reason is not None


def test_unknown_shared_directory_refuses_mutation(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    clone = tmp_path / "clone"
    for directory in (registry, clone):
        (directory / ".git").mkdir(parents=True)
    decision = shared.evaluate_bash_command(
        'cd "$(choose_tree)"; git reset --hard', shared.load_policy(), clone, registry
    )
    assert decision.blocked


def test_body_subshell_directory_does_not_leak(tmp_path: Path) -> None:
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / "body.md").write_text("Evidence-Source: OCC#9999\n")
    (child / "body.md").write_text("dropped the stamp\n")
    command = f"(cd '{child}'; cat body.md); gh pr edit 1 --body-file body.md"
    (edit,) = body.parse_pr_body_edits(command, body.load_policy(), cwd=str(tmp_path))
    assert edit.new_body == (tmp_path / "body.md").read_text(), edit.unreadable_reason


def test_unknown_first_git_c_is_not_hidden_by_second(tmp_path: Path) -> None:
    registry = tmp_path / "registry"
    (registry / ".git").mkdir(parents=True)
    decision = shared.evaluate_bash_command(
        'git -C "$(choose_tree)" -C registry reset --hard',
        shared.load_policy(),
        tmp_path,
        registry,
    )
    assert decision.blocked


@pytest.mark.parametrize("quoted", [False, True])
def test_shared_cd_preserves_shell_word_splitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, quoted: bool
) -> None:
    registry = tmp_path / "registry"
    clone = tmp_path / "clone with spaces"
    for directory in (registry, clone):
        (directory / ".git").mkdir(parents=True)
    monkeypatch.setenv("RESOLVER_TREE", str(clone))
    operand = '"$RESOLVER_TREE"' if quoted else "$RESOLVER_TREE"
    decision = shared.evaluate_bash_command(
        f"cd {operand}; git reset --hard", shared.load_policy(), registry, registry
    )
    # Unquoted cd fails with multiple operands, leaving the shell in registry.
    assert decision.blocked is not quoted, decision.reason


@pytest.mark.parametrize("format_string", ["%s", "%b", "-%s"])
@pytest.mark.parametrize("retains_stamp", [False, True])
def test_body_printf_option_terminator_is_resolved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    format_string: str,
    retains_stamp: bool,
) -> None:
    destination = tmp_path / "destination"
    destination.mkdir()
    stamp = "Evidence-" + "Source: OCC#9999"
    replacement = (
        f"It's a readable body with an unmatched \" quote.\n{stamp}\n"
        if retains_stamp
        else "It's a body without the line.\n"
    )
    command = (
        f"B=body.md; cd -- '{destination}'; "
        f'printf -- \'{format_string}\' "$RESOLVER_TEXT" > "$B"; '
        'gh pr edit 1 --body-file "$B"'
    )
    monkeypatch.setenv("RESOLVER_TEXT", replacement)
    # Check the shell builtin's output without executing the edit or file write.
    actual = subprocess.run(
        [
            "bash",
            "-c",
            'printf -- "$1" "$2"',
            "printf-fixture",
            format_string,
            replacement,
        ],
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    (edit,) = body.parse_pr_body_edits(command, body.load_policy(), cwd=str(tmp_path))
    assert edit.new_body == actual, edit.unreadable_reason
    findings = body.check_bash_command(
        command, body.load_policy(), lambda _: f"{stamp}\n", cwd=str(tmp_path)
    )
    assert [finding.kind for finding in findings] == (
        [] if retains_stamp else ["dropped_stamp"]
    )
    assert not (destination / "body.md").exists(), (
        "projection must never run the writer"
    )


def test_body_printf_variable_option_still_requires_workaround(tmp_path: Path) -> None:
    (edit,) = body.parse_pr_body_edits(
        "printf -v TEXT '%s' unreadable; printf '%s' \"$TEXT\" > body.md; "
        "gh pr edit 1 --body-file body.md",
        body.load_policy(),
        cwd=str(tmp_path),
    )
    assert edit.new_body is None
    assert edit.unreadable_reason is not None
    assert "its own Bash call" in edit.unreadable_reason
