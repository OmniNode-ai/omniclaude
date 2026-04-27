# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for validate_skill_backing_node.py (OMN-10052).

Covers:
- Valid skill with a live backing node: passes.
- Missing node directory: fails with clear message.
- Missing contract.yaml: fails with clear message.
- Missing handlers/ directory: fails with clear message.
- Empty handlers/ (only stub content): fails with clear message.
- Allowlist with reason: exempts the skill.
- Allowlist entry with blank reason: raises ValueError.
- Allowlist entry with missing reason: raises ValueError.
- Skill with no backing-node declaration: not checked (no violation).
- skill_functional_audit inline format: extracts correctly.
- compliance_sweep inline format: extracts correctly.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from plugins.onex.skills._lib.validate_skill_backing_node import (
    NodeViolation,
    check_node_liveness,
    extract_backing_node,
    load_allowlist,
    scan,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_skill_md(tmp_path: Path, skill_name: str, backing_node: str | None) -> Path:
    """Create a minimal SKILL.md under tmp_path/plugins/onex/skills/<name>/."""
    skill_dir = tmp_path / "plugins" / "onex" / "skills" / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    if backing_node:
        skill_md.write_text(
            textwrap.dedent(f"""\
                ---
                description: Test skill
                version: 1.0.0
                ---

                # {skill_name}

                **Backing node**: `omnimarket/src/omnimarket/nodes/{backing_node}/`
            """),
            encoding="utf-8",
        )
    else:
        skill_md.write_text(
            textwrap.dedent(f"""\
                ---
                description: Test skill (no backing node)
                version: 1.0.0
                ---

                # {skill_name}

                This is a pure instruction skill.
            """),
            encoding="utf-8",
        )
    return skill_md


def _make_live_node(
    omnimarket_root: Path,
    node_name: str,
    *,
    handler_lines: int = 50,
) -> Path:
    """Create a minimal live node structure.

    Nodes are placed at ``omnimarket_root/src/omnimarket/nodes/<node_name>/``
    so that when ``OMNIMARKET_ROOT=omnimarket_root`` the validator resolves the
    path correctly (the resolver appends ``/src/omnimarket/nodes`` to the env
    var value).
    """
    node_dir = omnimarket_root / "src" / "omnimarket" / "nodes" / node_name
    node_dir.mkdir(parents=True, exist_ok=True)
    (node_dir / "contract.yaml").write_text("name: test_node\n", encoding="utf-8")
    handlers_dir = node_dir / "handlers"
    handlers_dir.mkdir()
    handler_file = handlers_dir / f"handler_{node_name}.py"
    body = "# handler\n" + "\n".join(f"line_{i} = {i}" for i in range(handler_lines))
    handler_file.write_text(body, encoding="utf-8")
    return node_dir


def _make_stub_handler(node_dir: Path, node_name: str) -> None:
    """Create a stub handler with fewer than _MIN_SUBSTANTIVE_LINES substantive lines.

    *node_dir* must already exist (created by the caller).
    """
    handlers_dir = node_dir / "handlers"
    handlers_dir.mkdir(exist_ok=True)
    (handlers_dir / f"handler_{node_name}.py").write_text(
        # No SPDX header — this is a test fixture stub, not a source file.
        textwrap.dedent("""\
            # stub — implementation pending

            def handle():
                pass
        """),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# extract_backing_node
# ---------------------------------------------------------------------------


class TestExtractBackingNode:
    def test_canonical_body_form(self, tmp_path: Path) -> None:
        """Standard **Backing node**: `omnimarket/.../<node>/` format."""
        skill_md = _make_skill_md(tmp_path, "my_skill", "node_my_impl")
        result = extract_backing_node(skill_md)
        assert result == "node_my_impl"

    def test_short_body_form(self, tmp_path: Path) -> None:
        """Short form: - **Backing node**: `node_foo`"""
        skill_dir = tmp_path / "plugins" / "onex" / "skills" / "short_skill"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(
            "# Short\n\n- **Backing node**: `node_short_impl`\n",
            encoding="utf-8",
        )
        assert extract_backing_node(md) == "node_short_impl"

    def test_inline_heading_form(self, tmp_path: Path) -> None:
        """Inline: **Skill ID**: ... · **Backing node**: `omnimarket/.../node_foo/` · ..."""
        skill_dir = tmp_path / "plugins" / "onex" / "skills" / "inline_skill"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(
            "**Skill ID**: `onex:inline_skill` · **Backing node**: "
            "`omnimarket/src/omnimarket/nodes/node_inline_impl/` · **Ticket**: OMN-1\n",
            encoding="utf-8",
        )
        assert extract_backing_node(md) == "node_inline_impl"

    def test_no_declaration_returns_none(self, tmp_path: Path) -> None:
        """Skills without a backing-node declaration return None."""
        skill_md = _make_skill_md(tmp_path, "pure_skill", None)
        assert extract_backing_node(skill_md) is None

    def test_frontmatter_form(self, tmp_path: Path) -> None:
        """YAML frontmatter: backing_node: node_foo"""
        skill_dir = tmp_path / "plugins" / "onex" / "skills" / "fm_skill"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        md.write_text(
            textwrap.dedent("""\
                ---
                description: test
                backing_node: "node_fm_impl"
                ---
                # FM Skill
            """),
            encoding="utf-8",
        )
        assert extract_backing_node(md) == "node_fm_impl"


# ---------------------------------------------------------------------------
# load_allowlist
# ---------------------------------------------------------------------------


class TestLoadAllowlist:
    def test_empty_allowlist_file(self, tmp_path: Path) -> None:
        """An allowlist with an empty list returns an empty dict."""
        al = tmp_path / "skill_backing_node_allowlist.yaml"
        al.write_text("allowlist: []\n", encoding="utf-8")
        # Patch path resolution by writing a minimal repo layout.
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "plugins" / "onex" / "skills" / "_lib").mkdir(parents=True)
        (
            repo
            / "plugins"
            / "onex"
            / "skills"
            / "_lib"
            / "skill_backing_node_allowlist.yaml"
        ).write_text("allowlist: []\n", encoding="utf-8")
        result = load_allowlist(repo)
        assert result == {}

    def test_valid_entry_returned(self, tmp_path: Path) -> None:
        """A valid allowlist entry is returned as {skill: reason}."""
        repo = tmp_path / "repo"
        (repo / "plugins" / "onex" / "skills" / "_lib").mkdir(parents=True)
        al = (
            repo
            / "plugins"
            / "onex"
            / "skills"
            / "_lib"
            / "skill_backing_node_allowlist.yaml"
        )
        al.write_text(
            textwrap.dedent("""\
                allowlist:
                  - skill: my_skill
                    reason: "Pre-existing — pending OMN-99999"
            """),
            encoding="utf-8",
        )
        result = load_allowlist(repo)
        assert result == {"my_skill": "Pre-existing — pending OMN-99999"}

    def test_blank_reason_raises(self, tmp_path: Path) -> None:
        """An allowlist entry with a blank reason raises ValueError."""
        repo = tmp_path / "repo"
        (repo / "plugins" / "onex" / "skills" / "_lib").mkdir(parents=True)
        al = (
            repo
            / "plugins"
            / "onex"
            / "skills"
            / "_lib"
            / "skill_backing_node_allowlist.yaml"
        )
        al.write_text(
            textwrap.dedent("""\
                allowlist:
                  - skill: bad_skill
                    reason: "   "
            """),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=r"non-empty.*reason"):
            load_allowlist(repo)

    def test_missing_reason_raises(self, tmp_path: Path) -> None:
        """An allowlist entry with no reason key raises ValueError."""
        repo = tmp_path / "repo"
        (repo / "plugins" / "onex" / "skills" / "_lib").mkdir(parents=True)
        al = (
            repo
            / "plugins"
            / "onex"
            / "skills"
            / "_lib"
            / "skill_backing_node_allowlist.yaml"
        )
        al.write_text(
            textwrap.dedent("""\
                allowlist:
                  - skill: no_reason_skill
            """),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=r"non-empty.*reason"):
            load_allowlist(repo)

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """When the allowlist file does not exist, an empty dict is returned."""
        assert load_allowlist(tmp_path) == {}


# ---------------------------------------------------------------------------
# check_node_liveness
# ---------------------------------------------------------------------------


class TestCheckNodeLiveness:
    """Tests for check_node_liveness.

    Convention: ``OMNIMARKET_ROOT`` is set to ``tmp_path`` so the resolver
    looks under ``tmp_path/src/omnimarket/nodes/<node_name>``.  Helper
    ``_make_live_node(tmp_path, name)`` already places nodes at that path.
    """

    def test_live_node_passes(self, tmp_path: Path) -> None:
        """A node with contract.yaml and a live handler passes."""
        _make_live_node(tmp_path, "node_live_impl")
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path)
        try:
            result = check_node_liveness(
                "my_skill", "node_live_impl", tmp_path / "repo"
            )
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert result is None

    def test_missing_directory_fails(self, tmp_path: Path) -> None:
        """Missing node directory produces a NodeViolation."""
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path / "nonexistent")
        try:
            result = check_node_liveness("my_skill", "node_missing", tmp_path / "repo")
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert isinstance(result, NodeViolation)
        assert "not found" in result.detail

    def test_missing_contract_yaml_fails(self, tmp_path: Path) -> None:
        """Node directory exists but contract.yaml is absent."""
        # Create node dir at the expected path (no contract.yaml)
        node_dir = tmp_path / "src" / "omnimarket" / "nodes" / "node_no_contract"
        node_dir.mkdir(parents=True)
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path)
        try:
            result = check_node_liveness(
                "my_skill", "node_no_contract", tmp_path / "repo"
            )
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert isinstance(result, NodeViolation)
        assert "contract.yaml" in result.detail

    def test_missing_handlers_dir_fails(self, tmp_path: Path) -> None:
        """Node directory + contract.yaml but no handlers/ directory."""
        node_dir = tmp_path / "src" / "omnimarket" / "nodes" / "node_no_handlers"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text("name: test\n", encoding="utf-8")
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path)
        try:
            result = check_node_liveness(
                "my_skill", "node_no_handlers", tmp_path / "repo"
            )
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert isinstance(result, NodeViolation)
        assert "handlers/" in result.detail

    def test_empty_handlers_dir_fails(self, tmp_path: Path) -> None:
        """handlers/ exists but contains no handler_*.py files."""
        node_dir = tmp_path / "src" / "omnimarket" / "nodes" / "node_empty_handlers"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text("name: test\n", encoding="utf-8")
        (node_dir / "handlers").mkdir()
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path)
        try:
            result = check_node_liveness(
                "my_skill", "node_empty_handlers", tmp_path / "repo"
            )
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert isinstance(result, NodeViolation)
        assert "no handler_*.py" in result.detail

    def test_stub_handler_fails(self, tmp_path: Path) -> None:
        """handler_*.py exists but is a stub (too few substantive lines)."""
        node_dir = tmp_path / "src" / "omnimarket" / "nodes" / "node_stub_handler"
        node_dir.mkdir(parents=True)
        (node_dir / "contract.yaml").write_text("name: test\n", encoding="utf-8")
        _make_stub_handler(node_dir, "node_stub_handler")
        import os

        os.environ["OMNIMARKET_ROOT"] = str(tmp_path)
        try:
            result = check_node_liveness(
                "my_skill", "node_stub_handler", tmp_path / "repo"
            )
        finally:
            del os.environ["OMNIMARKET_ROOT"]
        assert isinstance(result, NodeViolation)
        assert "stub" in result.detail


# ---------------------------------------------------------------------------
# scan (integration)
# ---------------------------------------------------------------------------


class TestScan:
    def test_no_skills_is_clean(self, tmp_path: Path) -> None:
        """A repo with no SKILL.md files is clean."""
        (tmp_path / "plugins" / "onex" / "skills").mkdir(parents=True)
        assert scan(tmp_path) == []

    def test_skill_without_backing_node_not_checked(self, tmp_path: Path) -> None:
        """Pure-instruction skills (no backing-node declaration) are not checked."""
        _make_skill_md(tmp_path, "pure_skill", None)
        assert scan(tmp_path) == []

    def test_skill_with_live_node_passes(self, tmp_path: Path) -> None:
        """A skill pointing at a live node produces no violations.

        Uses the sibling-repo layout: ``<tmp_path.parent>/omnimarket/src/omnimarket/nodes/``.
        ``_make_live_node`` accepts the omnimarket root (not the nodes dir) and
        appends ``src/omnimarket/nodes/<name>`` internally.
        """
        _make_skill_md(tmp_path, "good_skill", "node_good_impl")
        # Sibling layout probe: repo_root.parent / "omnimarket" / "src" / "omnimarket" / "nodes"
        omnimarket_root = tmp_path.parent / "omnimarket"
        _make_live_node(omnimarket_root, "node_good_impl")
        errors = scan(tmp_path)
        assert errors == []

    def test_skill_with_missing_node_fails(self, tmp_path: Path) -> None:
        """A skill whose backing node doesn't exist produces a violation."""
        _make_skill_md(tmp_path, "bad_skill", "node_missing_impl")
        errors = scan(tmp_path)
        assert len(errors) == 1
        assert "bad_skill" in errors[0]
        assert "node_missing_impl" in errors[0]

    def test_allowlisted_skill_is_skipped(self, tmp_path: Path) -> None:
        """An allowlisted skill is not checked even if its node is missing."""
        _make_skill_md(tmp_path, "exempt_skill", "node_missing_exempt")
        lib_dir = tmp_path / "plugins" / "onex" / "skills" / "_lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "skill_backing_node_allowlist.yaml").write_text(
            textwrap.dedent("""\
                allowlist:
                  - skill: exempt_skill
                    reason: "Pre-existing — pending OMN-99999"
            """),
            encoding="utf-8",
        )
        assert scan(tmp_path) == []

    def test_allowlist_blank_reason_raises_in_scan(self, tmp_path: Path) -> None:
        """scan() propagates ValueError from a malformed allowlist."""
        _make_skill_md(tmp_path, "bad_al_skill", "node_whatever")
        lib_dir = tmp_path / "plugins" / "onex" / "skills" / "_lib"
        lib_dir.mkdir(parents=True, exist_ok=True)
        (lib_dir / "skill_backing_node_allowlist.yaml").write_text(
            textwrap.dedent("""\
                allowlist:
                  - skill: bad_al_skill
                    reason: ""
            """),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=r"non-empty.*reason"):
            scan(tmp_path)
