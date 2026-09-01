# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the org-wide KB doc gate (OMN-16589 pilot, OMN-17172 fleet shape).

Exercises the module functions directly (fast, no subprocess) plus a set of
end-to-end tests against real tmp git repos (proves the git plumbing — status
detection, rename handling, staged vs ref-diff vs tree scan — actually works,
not just the pure evaluation logic).

The behavioral contract under test is the operator ruling of 2026-09-01: an
allowed set of markdown that may remain in a product repo, with everything
else being documentation that must LEAVE (be deleted, not stubbed). Two modes:
``diff`` blocks add-or-modify outside that set, ``strict`` blocks the mere
existence of anything outside it.
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


def _allowed(mod, *extra: str) -> tuple[str, ...]:
    return mod.DEFAULT_ALLOWED + extra


# ---------------------------------------------------------------------------
# diff mode: add / modify / rename / delete
# ---------------------------------------------------------------------------


def test_diff_mode_blocks_new_markdown(mod):
    changed = [mod.ChangedFile(status="A", path="docs/new-thing.md")]

    violations = mod.evaluate_diff(changed, allowed=_allowed(mod))

    assert len(violations) == 1
    assert violations[0].path == "docs/new-thing.md"
    assert "new" in violations[0].reason


def test_diff_mode_blocks_modification_of_existing_markdown(mod):
    """The OMN-17172 widening: the pilot let any in-place edit through."""
    changed = [mod.ChangedFile(status="M", path="docs/existing.md")]

    violations = mod.evaluate_diff(changed, allowed=_allowed(mod))

    assert len(violations) == 1
    assert "modified" in violations[0].reason


def test_diff_mode_blocks_shrinking_a_doc_to_a_pointer_stub(mod):
    """A stub is not a removal — the ruling is explicit, and the pilot's
    30-line stub cap would have waved this through as 'small enough'."""
    changed = [mod.ChangedFile(status="M", path="docs/design/big-design.md")]

    assert mod.evaluate_diff(changed, allowed=_allowed(mod)) != []


def test_diff_mode_allows_deletion(mod):
    changed = [mod.ChangedFile(status="D", path="docs/going-away.md")]

    assert mod.evaluate_diff(changed, allowed=_allowed(mod)) == []


def test_diff_mode_blocks_rename_to_another_disallowed_path(mod):
    """`git mv docs/a.md docs/b.md` must not launder a doc past the gate."""
    changed = [
        mod.ChangedFile(status="R", path="docs/b.md", old_path="docs/a.md"),
    ]

    violations = mod.evaluate_diff(changed, allowed=_allowed(mod))

    assert len(violations) == 1
    assert violations[0].path == "docs/b.md"
    assert "docs/a.md" in violations[0].reason


def test_diff_mode_allows_rename_into_the_allowed_set(mod):
    changed = [
        mod.ChangedFile(
            status="R", path=".github/CONTRIBUTING.md", old_path="docs/contributing.md"
        ),
    ]

    assert mod.evaluate_diff(changed, allowed=_allowed(mod)) == []


def test_diff_mode_ignores_non_markdown(mod):
    changed = [
        mod.ChangedFile(status="A", path="docs/diagram.png"),
        mod.ChangedFile(status="M", path="src/thing.py"),
    ]

    assert mod.evaluate_diff(changed, allowed=_allowed(mod)) == []


def test_diff_mode_honors_repo_extra_allowed(mod):
    changed = [mod.ChangedFile(status="A", path="plugins/onex/README.md")]

    assert mod.evaluate_diff(changed, allowed=_allowed(mod)) != []
    assert mod.evaluate_diff(changed, allowed=_allowed(mod, "plugins/**")) == []


# ---------------------------------------------------------------------------
# The allowed set itself — the ruling, expressed as a table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "CLAUDE.md",
        ".claude/agents/foo.md",
        ".claude/CLAUDE.md",
        "CHANGELOG.md",
        "CHANGELOG-2025.md",
        "LICENSE.md",
        "SECURITY.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug.md",
        "skills/deploy/SKILL.md",
        "plugins/onex/skills/foo/SKILL.md",
        "commands/deploy.md",
        "agents/reviewer.md",
        "tests/fixtures/sample.md",
        "tests/unit/data/payload.md",
        "tests/golden/chain.md",
        "src/pkg/tests/e2e/fixtures/case.md",
    ],
)
def test_allowed_paths(mod, path):
    assert mod.is_allowed(path, mod.DEFAULT_ALLOWED), path


@pytest.mark.parametrize(
    "path",
    [
        "docs/architecture.md",
        "src/README.md",  # only the ROOT README is load-bearing
        "docs/README.md",
        "src/CLAUDE.md",  # ruling: root CLAUDE.md or under .claude/ only
        "CONTRIBUTING.md",  # allowed under .github/, not at the root
        "CODE_OF_CONDUCT.md",
        "rules/no-foo.md",  # pilot default; not in the ruling
        "hooks/pre-commit.md",
        "tests/test_plan.md",  # tests/** is narrowed to the fixture subtrees
        "tests/unit/notes.md",
        "design-tasks/task-1.md",
        "evidence/2026-01-01-run.md",
    ],
)
def test_disallowed_paths(mod, path):
    assert not mod.is_allowed(path, mod.DEFAULT_ALLOWED), path


def test_glob_double_star_matches_any_depth(mod):
    assert mod.is_allowed("skills/foo/SKILL.md", ("**/skills/**",))
    assert mod.is_allowed("plugins/onex/skills/foo/SKILL.md", ("**/skills/**",))
    assert not mod.is_allowed("skillsxyz/foo.md", ("**/skills/**",))


def test_glob_exact_match_is_anchored(mod):
    assert mod.is_allowed("README.md", ("README.md",))
    assert not mod.is_allowed("docs/README.md", ("README.md",))


# ---------------------------------------------------------------------------
# strict mode: whole-tree scan
# ---------------------------------------------------------------------------


def test_strict_mode_flags_untouched_markdown(mod):
    paths = ["README.md", "docs/legacy.md", "docs/sub/other.md"]

    violations = mod.evaluate_tree(paths, allowed=_allowed(mod))

    assert [v.path for v in violations] == ["docs/legacy.md", "docs/sub/other.md"]


def test_strict_mode_clean_tree_passes(mod):
    paths = ["README.md", "CLAUDE.md", ".github/PULL_REQUEST_TEMPLATE.md"]

    assert mod.evaluate_tree(paths, allowed=_allowed(mod)) == []


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------


def test_missing_config_returns_no_mode_and_no_extras(mod, tmp_path):
    assert mod.load_config(tmp_path / ".kb-doc-gate.yaml") == (None, ())


def test_config_parses_mode_and_allowed(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text(
        "# repo config\nmode: strict\nallowed:\n  - \"plugins/**\"\n  - 'docs/adr/**'\n"
    )

    assert mod.load_config(config) == ("strict", ("plugins/**", "docs/adr/**"))


def test_config_rejects_unknown_mode(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text("mode: transition\n")

    with pytest.raises(ValueError, match="mode must be one of"):
        mod.load_config(config)


def test_config_rejects_unknown_key(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text("exemptions:\n  - 'docs/**'\n")

    with pytest.raises(ValueError, match="unknown key"):
        mod.load_config(config)


def test_config_rejects_list_item_outside_allowed_section(mod, tmp_path):
    config = tmp_path / ".kb-doc-gate.yaml"
    config.write_text("mode: strict\n  - 'docs/**'\n")

    with pytest.raises(ValueError, match="outside an 'allowed:' section"):
        mod.load_config(config)


# ---------------------------------------------------------------------------
# End-to-end: real git repos
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
    (repo / "README.md").write_text("# Repo\n\nDocs live in the knowledge-base.\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "legacy.md").write_text("a doc that should have moved\n")
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
    (git_repo / "docs" / "sneaky-new-doc.md").write_text("should not exist locally\n")
    _git(git_repo, "add", "docs/sneaky-new-doc.md")

    result = _run_cli(
        ["--staged", "--repo-root", str(git_repo), "docs/sneaky-new-doc.md"]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/sneaky-new-doc.md" in result.stderr


def test_e2e_staged_mode_allows_allowed_new_file(git_repo):
    (git_repo / ".claude").mkdir()
    (git_repo / ".claude" / "note.md").write_text("agent note\n")
    _git(git_repo, "add", ".claude/note.md")

    result = _run_cli(["--staged", "--repo-root", str(git_repo), ".claude/note.md"])

    assert result.returncode == 0, result.stderr


def test_e2e_diff_mode_blocks_edit_of_existing_doc(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    (git_repo / "docs" / "legacy.md").write_text("edited in place\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "edit doc")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/legacy.md" in result.stderr


def test_e2e_diff_mode_allows_deletion(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "rm", "-q", "docs/legacy.md")
    _git(git_repo, "commit", "-q", "-m", "remove doc")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 0, result.stderr


def test_e2e_diff_mode_blocks_rename_within_docs(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "mv", "docs/legacy.md", "docs/renamed.md")
    _git(git_repo, "commit", "-q", "-m", "rename doc")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 1, result.stderr
    assert "docs/renamed.md" in result.stderr


def test_e2e_diff_mode_ignores_untouched_violations(git_repo):
    """docs/legacy.md is already on the branch and stays disallowed — but a PR
    that does not touch it is not this gate's problem in diff mode."""
    _git(git_repo, "checkout", "-q", "-b", "feature")
    (git_repo / "src.py").write_text("x = 1\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "unrelated change")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 0, result.stderr


def test_e2e_strict_mode_flags_the_same_untouched_file(git_repo):
    """Same tree, same PR, strict mode: existence alone is the violation."""
    _git(git_repo, "checkout", "-q", "-b", "feature")
    (git_repo / "src.py").write_text("x = 1\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "unrelated change")

    result = _run_cli(["--mode", "strict", "--repo-root", str(git_repo)])

    assert result.returncode == 1, result.stderr
    assert "docs/legacy.md" in result.stderr


def test_e2e_strict_mode_passes_on_a_scrubbed_tree(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "rm", "-q", "docs/legacy.md")
    _git(git_repo, "commit", "-q", "-m", "scrub docs")

    result = _run_cli(["--mode", "strict", "--repo-root", str(git_repo)])

    assert result.returncode == 0, result.stderr


def test_e2e_config_file_mode_takes_precedence_over_cli_flag(git_repo):
    (git_repo / ".kb-doc-gate.yaml").write_text("mode: strict\n")
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "add strict config")

    # CLI says diff (which would pass — nothing changed), config says strict.
    result = _run_cli(
        [
            "--base-ref",
            "main",
            "--head-ref",
            "main",
            "--mode",
            "diff",
            "--repo-root",
            str(git_repo),
        ]
    )

    assert result.returncode == 1, result.stderr
    assert "strict mode" in result.stderr


def test_e2e_repo_config_allowed_list_is_honored(git_repo):
    (git_repo / ".kb-doc-gate.yaml").write_text('allowed:\n  - "docs/**"\n')
    _git(git_repo, "add", "-A")
    _git(git_repo, "commit", "-q", "-m", "allow docs")

    result = _run_cli(["--mode", "strict", "--repo-root", str(git_repo)])

    assert result.returncode == 0, result.stderr


def test_e2e_diff_mode_without_a_source_is_a_usage_error(git_repo):
    result = _run_cli(["--repo-root", str(git_repo)])

    assert result.returncode == 2
    assert "--staged or --base-ref" in result.stderr


def test_e2e_bad_config_is_exit_2_not_a_pass(git_repo):
    (git_repo / ".kb-doc-gate.yaml").write_text("mode: nonsense\n")

    result = _run_cli(["--mode", "strict", "--repo-root", str(git_repo)])

    assert result.returncode == 2
    assert "config error" in result.stderr


def test_e2e_no_changes_is_ok(git_repo):
    _git(git_repo, "checkout", "-q", "-b", "feature")
    _git(git_repo, "commit", "-q", "--allow-empty", "-m", "empty")

    result = _run_cli(
        ["--base-ref", "main", "--head-ref", "feature", "--repo-root", str(git_repo)]
    )

    assert result.returncode == 0, result.stdout + result.stderr
