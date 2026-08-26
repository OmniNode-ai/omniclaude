# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the org-wide KB doc gate (OMN-16589).

Exercises the module functions directly (fast, no subprocess) plus a set of
end-to-end tests against real tmp git repos (proves the git plumbing — status
detection, rename handling, staged vs ref-diff modes — actually works, not
just the pure evaluation logic).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "kb_doc_gate.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("kb_doc_gate", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the module's `from __future__ import annotations`
    # dataclasses resolve their string annotations via sys.modules[__module__]
    # at decoration time, so an unregistered module fails with a cryptic
    # AttributeError deep in dataclasses' internals.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mod():
    return _load_module()


# ---------------------------------------------------------------------------
# Unit-level: evaluate() against synthetic ChangedFile rows
# ---------------------------------------------------------------------------


def test_new_markdown_blocked_in_transition_mode(mod, tmp_path):
    changed = [mod.ChangedFile(status="A", path="docs/new-thing.md")]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new-thing.md").write_text("hello\n")

    violations = mod.evaluate(
        changed, mode="transition", extra_exemptions=(), repo_root=tmp_path
    )

    assert len(violations) == 1
    assert violations[0].path == "docs/new-thing.md"
    assert "new" in violations[0].reason.lower()


def test_new_markdown_blocked_in_strict_mode_too(mod, tmp_path):
    changed = [mod.ChangedFile(status="A", path="docs/new-thing.md")]
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "new-thing.md").write_text("hello\n")

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert len(violations) == 1


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "CLAUDE.md",
        "src/CLAUDE.md",
        ".claude/agents/foo.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "plugins/onex/skills/foo/SKILL.md",
        "agents/reviewer.md",
        "commands/deploy.md",
        "rules/no-foo.md",
        "hooks/pre-commit.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "tests/fixtures/sample.md",
    ],
)
def test_exempt_new_markdown_allowed(mod, tmp_path, path):
    changed = [mod.ChangedFile(status="A", path=path)]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_nested_readme_is_not_exempt(mod, tmp_path):
    # Only the repo-root README.md is exempt; nested READMEs are ordinary docs.
    changed = [mod.ChangedFile(status="A", path="src/README.md")]

    violations = mod.evaluate(
        changed, mode="transition", extra_exemptions=(), repo_root=tmp_path
    )

    assert len(violations) == 1
    assert violations[0].path == "src/README.md"


def test_stub_edit_within_cap_allowed_in_strict_mode(mod, tmp_path):
    target = tmp_path / "docs" / "pointer.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "\n".join(f"line {i}" for i in range(5)) + "\n"
    )  # 5 lines, well under cap
    changed = [mod.ChangedFile(status="M", path="docs/pointer.md")]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_stub_inflated_past_cap_blocked_in_strict_mode(mod, tmp_path):
    target = tmp_path / "docs" / "pointer.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "\n".join(f"line {i}" for i in range(mod.STUB_LINE_CAP + 5)) + "\n"
    )
    changed = [mod.ChangedFile(status="M", path="docs/pointer.md")]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert len(violations) == 1
    assert "stub cap" in violations[0].reason


def test_stub_inflated_past_cap_allowed_in_transition_mode(mod, tmp_path):
    target = tmp_path / "docs" / "pointer.md"
    target.parent.mkdir(parents=True)
    target.write_text(
        "\n".join(f"line {i}" for i in range(mod.STUB_LINE_CAP + 50)) + "\n"
    )
    changed = [mod.ChangedFile(status="M", path="docs/pointer.md")]

    violations = mod.evaluate(
        changed, mode="transition", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_root_readme_exempt_from_cap_in_strict_mode(mod, tmp_path):
    target = tmp_path / "README.md"
    target.write_text("\n".join(f"line {i}" for i in range(500)) + "\n")
    changed = [mod.ChangedFile(status="M", path="README.md")]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_per_repo_exemption_override_honored(mod, tmp_path):
    changed = [mod.ChangedFile(status="A", path="docs/adr/0001-decision.md")]

    blocked = mod.evaluate(
        changed, mode="transition", extra_exemptions=(), repo_root=tmp_path
    )
    assert len(blocked) == 1

    allowed = mod.evaluate(
        changed,
        mode="transition",
        extra_exemptions=("docs/adr/**",),
        repo_root=tmp_path,
    )
    assert allowed == []


def test_renames_allowed_regardless_of_content(mod, tmp_path):
    target = tmp_path / "docs" / "moved.md"
    target.parent.mkdir(parents=True)
    target.write_text("\n".join(f"line {i}" for i in range(500)) + "\n")
    changed = [
        mod.ChangedFile(status="R", path="docs/moved.md", old_path="docs/old-name.md")
    ]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_deletions_allowed(mod, tmp_path):
    changed = [mod.ChangedFile(status="D", path="docs/removed.md")]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


def test_non_markdown_files_ignored(mod, tmp_path):
    changed = [mod.ChangedFile(status="A", path="src/new_module.py")]

    violations = mod.evaluate(
        changed, mode="strict", extra_exemptions=(), repo_root=tmp_path
    )

    assert violations == []


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_config_missing_file_returns_defaults(mod, tmp_path):
    mode, exemptions = mod.load_config(tmp_path / ".kb-doc-gate.yaml")
    assert mode is None
    assert exemptions == ()


def test_load_config_parses_mode_and_exemptions(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text(
        "\n".join(
            [
                "# a comment",
                "mode: strict",
                "exemptions:",
                '  - "docs/adr/**"',
                "  - docs/decisions/*.md",
                "",
            ]
        )
    )

    mode, exemptions = mod.load_config(config)

    assert mode == "strict"
    assert exemptions == ("docs/adr/**", "docs/decisions/*.md")


def test_load_config_rejects_bad_mode(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text("mode: yolo\n")

    with pytest.raises(ValueError, match="mode must be"):
        mod.load_config(config)


def test_load_config_rejects_unknown_key(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text("unknown_key: 1\n")

    with pytest.raises(ValueError, match="unknown key"):
        mod.load_config(config)


# ---------------------------------------------------------------------------
# Glob matcher
# ---------------------------------------------------------------------------


def test_glob_double_star_matches_any_depth(mod):
    assert mod.is_exempt("skills/foo/SKILL.md", ("**/skills/**",))
    assert mod.is_exempt("plugins/onex/skills/foo/SKILL.md", ("**/skills/**",))
    assert not mod.is_exempt("skillsxyz/foo.md", ("**/skills/**",))


def test_glob_exact_match_is_anchored(mod):
    assert mod.is_exempt("README.md", ("README.md",))
    assert not mod.is_exempt("docs/README.md", ("README.md",))


# ---------------------------------------------------------------------------
# End-to-end: real git repos, both --staged and --base-ref/--head-ref modes
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture
def git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("# Repo\n\nPointer to knowledge-base.\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "existing-stub.md").write_text("stub\npoints to KB\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(_SCRIPT), *argv],
        capture_output=True,
        text=True,
        check=False,
    )


def test_e2e_staged_mode_blocks_new_file(git_repo):
    (git_repo / "docs" / "sneaky-new-doc.md").write_text(
        "this should not exist locally\n"
    )
    _git(git_repo, "add", "docs/sneaky-new-doc.md")

    result = _run_cli(
        ["--staged", "--repo-root", str(git_repo), "docs/sneaky-new-doc.md"]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/sneaky-new-doc.md" in result.stderr


def test_e2e_staged_mode_allows_exempt_new_file(git_repo):
    (git_repo / ".claude").mkdir()
    (git_repo / ".claude" / "note.md").write_text("agent note\n")
    _git(git_repo, "add", ".claude/note.md")

    result = _run_cli(["--staged", "--repo-root", str(git_repo), ".claude/note.md"])

    assert result.returncode == 0, result.stderr


def test_e2e_base_ref_mode_blocks_new_file_on_branch(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    (git_repo / "docs" / "another-sneaky-doc.md").write_text("nope\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "add doc")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/another-sneaky-doc.md" in result.stderr


def test_e2e_rename_allowed_end_to_end(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    big_content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    (git_repo / "docs" / "existing-stub.md").write_text(big_content)
    _git(git_repo, "mv", "docs/existing-stub.md", "docs/renamed-stub.md")
    _git(git_repo, "commit", "-q", "-m", "rename doc")

    result = _run_cli(
        [
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--mode",
            "strict",
            "--repo-root",
            str(git_repo),
        ]
    )

    assert result.returncode == 0, result.stderr


def test_e2e_strict_mode_blocks_inflated_stub_on_branch(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    big_content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    (git_repo / "docs" / "existing-stub.md").write_text(big_content)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "inflate stub")

    result = _run_cli(
        [
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--mode",
            "strict",
            "--repo-root",
            str(git_repo),
        ]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/existing-stub.md" in result.stderr


def test_e2e_transition_mode_allows_inflated_stub_on_branch(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    big_content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    (git_repo / "docs" / "existing-stub.md").write_text(big_content)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "inflate stub")

    result = _run_cli(
        [
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--mode",
            "transition",
            "--repo-root",
            str(git_repo),
        ]
    )

    assert result.returncode == 0, result.stderr


def test_e2e_config_file_mode_takes_precedence_over_cli_flag(git_repo):
    (git_repo / ".kb-doc-gate.yaml").write_text("mode: strict\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "add strict config")
    _git(git_repo, "checkout", "-q", "-b", "feature")
    big_content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    (git_repo / "docs" / "existing-stub.md").write_text(big_content)
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "inflate stub")

    # CLI says transition, but the repo's own config says strict -- config wins.
    result = _run_cli(
        [
            "--base-ref",
            "main",
            "--head-ref",
            "feature",
            "--mode",
            "transition",
            "--repo-root",
            str(git_repo),
        ]
    )

    assert result.returncode == 1, result.stderr


def test_e2e_deletion_allowed(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "rm", "-q", "docs/existing-stub.md")
    _git(git_repo, "commit", "-q", "-m", "remove doc")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 0, result.stderr


def test_e2e_no_changes_is_ok(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "commit", "-q", "--allow-empty", "-m", "empty")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 0, result.stdout + result.stderr
