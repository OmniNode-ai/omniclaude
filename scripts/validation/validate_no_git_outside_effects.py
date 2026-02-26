#!/usr/bin/env python3
"""
CI check: No git subprocess or gh CLI calls outside *effect* files.

Task 2 from OMN-2592:
  grep check — no git subprocess or `gh` CLI calls outside `*effect*` files
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

# Matches "git" or "gh" as a standalone word (not "github", "lightweight", etc.)
# at the start of a string (after optional whitespace), using a word boundary.
_GIT_COMMAND_RE = re.compile(r"^\s*(git|gh)\b", re.IGNORECASE)


def is_effect_file(path: Path) -> bool:
    """Return True if the given file is an *effect* file.

    A file is considered an effect file if:
    - Its filename contains "effect", OR
    - It resides inside a node directory whose name contains "effect"
      (e.g., handlers/ inside node_git_effect/)
    """
    name = path.name.lower()
    if "effect" in name:
        return True
    # Check if any ancestor directory is a node_*effect* directory
    for parent in path.parents:
        parent_name = parent.name.lower()
        if parent_name.startswith("node_") and "effect" in parent_name:
            return True
    return False


def is_node_module(path: Path) -> bool:
    """Return True if the file is inside a nodes/ directory (i.e., an ONEX node module).

    The git/gh check only applies to ONEX nodes. Infrastructure modules like
    src/omniclaude/trace/ are allowed to call git for their intrinsic purposes.
    """
    return "nodes" in path.parts


class GitCallVisitor(ast.NodeVisitor):
    """AST visitor that detects git/gh subprocess calls."""

    # Kept for reference; actual matching uses _GIT_COMMAND_RE word-boundary regex
    GIT_STRINGS: tuple[str, ...] = ("git ", "git\t", "gh ", "gh\t")
    SUBPROCESS_MODULES: tuple[str, ...] = ("subprocess",)
    SUBPROCESS_FUNCS: tuple[str, ...] = (
        "run",
        "call",
        "check_call",
        "check_output",
        "Popen",
        "getoutput",
        "getstatusoutput",
    )

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.violations: list[str] = []
        self._subprocess_names: set[str] = {"subprocess"}

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name in self.SUBPROCESS_MODULES:
                local = alias.asname or alias.name
                self._subprocess_names.add(local)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        if (node.module or "") in self.SUBPROCESS_MODULES:
            for alias in node.names:
                if alias.name in self.SUBPROCESS_FUNCS:
                    local = alias.asname or alias.name
                    self._subprocess_names.add(local)
        self.generic_visit(node)

    def _is_git_string(self, node: ast.expr) -> bool:
        """Return True if the node is a string constant that starts with a git/gh command.

        Uses a word-boundary regex so bare ``"git"`` and ``"gh"`` (common with
        ``shell=True``) are caught, while ``"github"`` or ``"lightweight"`` are not.
        """
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return bool(_GIT_COMMAND_RE.match(node.value))
        return False

    def _check_args_for_git(self, args: list[ast.expr], lineno: int) -> None:
        for arg in args:
            if self._is_git_string(arg):
                self.violations.append(
                    f"{self.filepath}:{lineno}: git/gh call via subprocess "
                    f"(string literal '{_truncate(arg)}')"
                )
            # Also detect list literals like ["git", "commit", ...]
            if isinstance(arg, ast.List):
                elements = arg.elts
                if elements and isinstance(elements[0], ast.Constant):
                    first = str(elements[0].value).strip().lower()
                    if first in ("git", "gh"):
                        self.violations.append(
                            f"{self.filepath}:{lineno}: git/gh call via subprocess list "
                            f"(first element '{elements[0].value}')"
                        )

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Pattern: subprocess.run(["git", ...]) or subprocess.check_output("git ...")
        if isinstance(node.func, ast.Attribute):
            if (
                isinstance(node.func.value, ast.Name)
                and node.func.value.id in self._subprocess_names
                and node.func.attr in self.SUBPROCESS_FUNCS
            ):
                self._check_args_for_git(node.args, node.lineno)
        # Pattern: run(["git", ...]) after from subprocess import run
        elif isinstance(node.func, ast.Name):
            if node.func.id in self._subprocess_names:
                self._check_args_for_git(node.args, node.lineno)
        # Pattern: os.system("git ...")
        if isinstance(node.func, ast.Attribute) and node.func.attr == "system":
            self._check_args_for_git(node.args, node.lineno)
        self.generic_visit(node)


def _truncate(node: ast.expr, max_len: int = 60) -> str:
    if isinstance(node, ast.Constant):
        s = repr(node.value)
        return s[:max_len] + "..." if len(s) > max_len else s
    return "<expr>"


def check_file(filepath: Path) -> list[str]:
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError as exc:
        return [f"{filepath}: SyntaxError: {exc}"]

    visitor = GitCallVisitor(filepath)
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    root = Path(__file__).resolve()
    for _ in range(10):
        if (root / "pyproject.toml").exists() or (root / "src").exists():
            break
        root = root.parent

    src_root = root / "src"
    if not src_root.exists():
        print(f"WARNING: src/ not found under {root}; skipping")
        return 0

    all_violations: list[str] = []

    for py_file in sorted(src_root.rglob("*.py")):
        # Only enforce inside ONEX node modules; infrastructure modules may call git legitimately
        if not is_node_module(py_file):
            continue
        if is_effect_file(py_file):
            continue
        violations = check_file(py_file)
        all_violations.extend(violations)

    if not all_violations:
        print(
            "OK: No git/gh subprocess calls found outside *effect* files (within node modules)"
        )
        return 0

    print(f"FAIL: Found {len(all_violations)} git/gh call violation(s):\n")
    for v in all_violations:
        print(f"  {v}")
    print(
        "\ngit and gh CLI calls must be confined to *effect* files."
        "\nMove subprocess calls to an effect node."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
