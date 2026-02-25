# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for SymbolIndexBuilder.

Verifies that the builder correctly handles:
    - Basic top-level definitions (functions, classes, constants)
    - ``__all__`` exports
    - ``from x import y`` re-exports
    - Skipping private names
    - Graceful handling of syntax errors

Related:
    - OMN-2548: Tier 1 AST-based detectors
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from omniclaude.quirks.tools.build_symbol_index import SymbolIndexBuilder


def _write_module(tmp_path: Path, rel_path: str, source: str) -> Path:
    """Write *source* to *tmp_path/rel_path*, creating parent dirs as needed."""
    file = tmp_path / rel_path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(textwrap.dedent(source), encoding="utf-8")
    return file


# ---------------------------------------------------------------------------
# Basic symbol extraction
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_basic_function_and_class(tmp_path: Path) -> None:
    """Top-level functions and classes should appear in the index."""
    _write_module(
        tmp_path,
        "mypkg/__init__.py",
        """\
        def public_fn(): pass
        class PublicClass: pass
        def _private(): pass
        """,
    )
    index = SymbolIndexBuilder.build(tmp_path)

    assert "mypkg" in index
    assert "public_fn" in index["mypkg"]
    assert "PublicClass" in index["mypkg"]
    assert "_private" not in index["mypkg"]


@pytest.mark.unit
def test_top_level_constants(tmp_path: Path) -> None:
    """Top-level assignments should be included."""
    _write_module(
        tmp_path,
        "pkg/__init__.py",
        """\
        VERSION = "1.0"
        _INTERNAL = 42
        """,
    )
    index = SymbolIndexBuilder.build(tmp_path)

    assert "pkg" in index
    assert "VERSION" in index["pkg"]
    assert "_INTERNAL" not in index["pkg"]


@pytest.mark.unit
def test_dunder_all_restricts_exports(tmp_path: Path) -> None:
    """When ``__all__`` is defined, only listed names are exported."""
    _write_module(
        tmp_path,
        "pkg/__init__.py",
        """\
        __all__ = ["exported_fn", "ExportedClass"]

        def exported_fn(): pass
        class ExportedClass: pass
        def not_exported(): pass
        """,
    )
    index = SymbolIndexBuilder.build(tmp_path)

    assert "exported_fn" in index["pkg"]
    assert "ExportedClass" in index["pkg"]
    assert "not_exported" not in index["pkg"]


@pytest.mark.unit
def test_from_import_reexport(tmp_path: Path) -> None:
    """``from x import y`` at module level should include ``y`` in exports."""
    _write_module(
        tmp_path,
        "pkg/__init__.py",
        """\
        from other_module import SomeClass, helper_fn
        """,
    )
    index = SymbolIndexBuilder.build(tmp_path)

    assert "SomeClass" in index["pkg"]
    assert "helper_fn" in index["pkg"]


@pytest.mark.unit
def test_submodule_indexed_separately(tmp_path: Path) -> None:
    """Sub-modules should appear as separate dotted paths."""
    _write_module(tmp_path, "pkg/__init__.py", "A = 1\n")
    _write_module(tmp_path, "pkg/utils.py", "def util_fn(): pass\n")

    index = SymbolIndexBuilder.build(tmp_path)

    assert "pkg" in index
    assert "pkg.utils" in index
    assert "util_fn" in index["pkg.utils"]


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skips_syntax_error_file(tmp_path: Path) -> None:
    """A file with a syntax error should be skipped without raising."""
    _write_module(tmp_path, "pkg/__init__.py", "def ok(): pass\n")
    bad = tmp_path / "pkg" / "broken.py"
    bad.write_text("def broken(\n    # unclosed paren\n", encoding="utf-8")

    index = SymbolIndexBuilder.build(tmp_path)

    # The valid module should still be indexed.
    assert "pkg" in index
    assert "ok" in index["pkg"]
    # The broken module should simply be absent (no exception).
    assert "pkg.broken" not in index


@pytest.mark.unit
def test_empty_package_returns_empty_index(tmp_path: Path) -> None:
    """A package directory with no ``.py`` files should yield an empty index."""
    (tmp_path / "empty_pkg").mkdir()
    index = SymbolIndexBuilder.build(tmp_path)
    assert index == {}


@pytest.mark.unit
def test_annotated_assignment_included(tmp_path: Path) -> None:
    """Annotated top-level assignments (``x: int = 1``) should be included."""
    _write_module(
        tmp_path,
        "pkg/__init__.py",
        """\
        MY_VALUE: int = 10
        _hidden: str = "no"
        """,
    )
    index = SymbolIndexBuilder.build(tmp_path)

    assert "MY_VALUE" in index["pkg"]
    assert "_hidden" not in index["pkg"]
