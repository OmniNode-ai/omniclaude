# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""SymbolIndexBuilder — utility to build a symbol index from a Python package.

The symbol index is a mapping of ``module_path -> set[exported_name]`` that
``HallucinatedApiDetector`` uses to cross-reference symbol references found in
generated code against the actual exported symbols in the target repo.

Usage::

    from omniclaude.quirks.tools.build_symbol_index import SymbolIndexBuilder

    index = SymbolIndexBuilder.build("/path/to/package")
    # index["mypackage.utils"] == {"helper_fn", "HelperClass", ...}

The builder is a **pure function** — no I/O side effects beyond reading source
files.  All file discovery uses ``pathlib``; no shell commands are invoked.

Exported symbol resolution:
    1. If a module defines ``__all__``, only those names are included.
    2. Otherwise, all top-level names that do not start with ``_`` are included.
    3. ``from x import y`` re-exports at the module level are followed one hop
       (no recursive resolution to avoid cycles).

Related:
    - OMN-2548: Tier 1 AST-based detectors
    - OMN-2360: Quirks Detector epic
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["SymbolIndex", "SymbolIndexBuilder"]

# Type alias for the symbol index produced by this builder.
SymbolIndex = dict[str, set[str]]


def _module_path_from_file(root: Path, file: Path) -> str:
    """Convert an absolute file path to a dotted module path.

    Args:
        root: Root directory of the package (parent of the top-level package).
        file: Absolute path to a ``.py`` file.

    Returns:
        Dotted module path, e.g. ``"mypackage.sub.module"``.
    """
    relative = file.relative_to(root)
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _extract_all_names(tree: ast.Module) -> set[str] | None:
    """Return the names listed in ``__all__``, or ``None`` if not defined.

    Only handles the common case of ``__all__ = [...]`` or ``__all__ = (...)``.
    More complex patterns (augmented assignment, conditional) are skipped and
    ``None`` is returned.
    """
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "__all__"
        ):
            val = node.value
            if isinstance(val, (ast.List, ast.Tuple)):
                names: set[str] = set()
                for elt in val.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        names.add(elt.value)
                return names
    return None


def _extract_top_level_names(tree: ast.Module) -> set[str]:
    """Return all top-level names defined or imported in *tree*.

    Includes:
    - Function definitions (``def``)
    - Async function definitions (``async def``)
    - Class definitions (``class``)
    - Top-level assignments (e.g. ``MY_CONST = 42``)
    - ``import x as y`` (imported name)
    - ``from x import y`` / ``from x import y as z``

    Excludes names starting with ``_``.
    """
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not node.name.startswith("_"):
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and not node.target.id.startswith("_"):
                names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                # For ``import x.y.z``, Python binds only ``x`` unless aliased.
                bound_name = alias.asname if alias.asname else alias.name.split(".")[0]
                if not bound_name.startswith("_"):
                    names.add(bound_name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_name = alias.asname if alias.asname else alias.name
                if bound_name != "*" and not bound_name.startswith("_"):
                    names.add(bound_name)
    return names


def _parse_module(file: Path) -> ast.Module | None:
    """Parse a Python file and return its AST, or ``None`` on error."""
    try:
        source = file.read_text(encoding="utf-8", errors="replace")
        return ast.parse(source, filename=str(file))
    except SyntaxError as exc:
        logger.debug("SymbolIndexBuilder: skip %s (syntax error: %s)", file, exc)
        return None
    except OSError as exc:
        logger.debug("SymbolIndexBuilder: skip %s (IO error: %s)", file, exc)
        return None


class SymbolIndexBuilder:
    """Build a symbol index from a Python package directory.

    The index maps dotted module paths to the set of names exported by each
    module.  It is used by ``HallucinatedApiDetector`` to validate symbol
    references in generated code.
    """

    @staticmethod
    def build(package_root: str | Path) -> SymbolIndex:
        """Walk *package_root* and return a symbol index.

        Args:
            package_root: Path to the root of a Python package (must contain
                an ``__init__.py`` file at the top level or any sub-directory).
                This is the **parent** of the first package directory when
                computing dotted module paths.

        Returns:
            A ``dict[str, set[str]]`` mapping dotted module paths to the set
            of exported names.  Modules that fail to parse are skipped with a
            debug-level log message.
        """
        root = Path(package_root).resolve()
        index: SymbolIndex = {}

        for file in sorted(root.rglob("*.py")):
            tree = _parse_module(file)
            if tree is None:
                continue

            module_path = _module_path_from_file(root, file)
            if not module_path:
                continue

            all_names = _extract_all_names(tree)
            if all_names is not None:
                exported = all_names
            else:
                exported = _extract_top_level_names(tree)

            if exported:
                index[module_path] = exported

        return index
