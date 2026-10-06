# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Cross-guard regressions for top-20 item 3 (OMN-17427)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib"))
import pr_body_stamp_guard as body
import shared_tree_git_guard as shared
import worktree_add_guard as worktree

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
