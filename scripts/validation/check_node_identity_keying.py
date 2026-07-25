#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""ONEX Node-Identity Bare-Name-Keying Checker.

Flags dict constructions that key a cross-package node collection on a bare
``name`` attribute/key, with no package/repo qualifier — the exact anti-
pattern behind three independent, separately-discovered-and-fixed incidents:

  - OMN-10865: omnibase_infra runtime wiring aliased nodes by bare contract
    ``name:``, crashing omninode-runtime boot (``ValueError: Duplicate local
    ingress route alias``) the moment two packages declared a node with the
    same name.
  - OMN-14571: the Memgraph architecture-graph populate handler keyed
    ``ONEXNode.node_id`` on the bare contract name, silently MERGE-collapsing
    same-named nodes from different repos into one node.
  - OMN-14575: the contract-topic census's ``find_defects()`` keyed
    ``by_name = {n.name: n for n in graph.nodes}`` on bare name, silently
    letting the alphabetically-last package's copy overwrite every other.

Each of the three was found and fixed independently, with no shared
mechanism to catch a fourth recurrence. This is that mechanism: a fast,
AST-based, author-time check — not a data-flow-complete analysis. It flags
the two shapes each incident actually had:

  1. A dict/set comprehension whose key is a bare ``<var>.name`` attribute
     access: ``{n.name: n for n in nodes}``.
  2. A ``for`` loop that assigns into a dict subscripted by a bare
     ``<var>.name`` attribute access: ``for n in nodes: by_name[n.name] = n``.

A qualified key — anything built with an f-string, ``.join()``, string
concatenation, or a tuple like ``(package, name)`` — does not match either
shape and is not flagged.

**Scoped to node/contract collections only.** Keying a dict by bare
``.name`` is an extremely common, entirely benign pattern for objects that
have nothing to do with ONEX node identity (LLM model scores, agent
registries, personality profiles, ...) — an early unscoped version of this
check found 6 hits in this repo alone, all false positives on exactly that
shape. To stay precise, both shapes above only fire when the iterated
collection's source text contains ``node`` or ``contract`` (case-
insensitive) — e.g. ``graph.nodes``, ``self.nodes``, ``contracts``,
``node_specs``. A dict keyed by ``.name`` over ``self.models`` or
``request.agent_registry`` is not flagged; suppress a genuine false
positive that does match with ``# node-identity-keying-ok: <reason>`` on
the flagged line.

Exit codes:
    0 - No violations
    1 - Violations found

Usage:
    python scripts/validation/check_node_identity_keying.py [files...]
    python scripts/validation/check_node_identity_keying.py --report src/

Linear tickets: OMN-14584 (this check), OMN-10865/OMN-14571/OMN-14575 (the
three incidents it generalizes), OMN-14599 (the deeper canonical-identity-
type refactor this check is a fast-follow for, not a replacement of).
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path

_SUPPRESSION_MARKER = "node-identity-keying-ok:"


class ModelNodeIdentityKeyingViolation:
    """One flagged bare-name-keying site."""

    __slots__ = ("file_path", "line", "snippet")

    def __init__(self, file_path: Path, line: int, snippet: str) -> None:
        self.file_path = file_path
        self.line = line
        self.snippet = snippet


_NODE_COLLECTION_MARKERS = ("node", "contract")


def _is_bare_name_attr(expr: ast.expr) -> bool:
    """True for a bare ``<var>.name`` attribute access — not an f-string,
    concatenation, tuple, or any other qualified expression."""
    return isinstance(expr, ast.Attribute) and expr.attr == "name"


def _looks_like_node_collection(iterable: ast.expr) -> bool:
    """True if the iterated collection's source text plausibly refers to
    ONEX nodes/contracts (e.g. ``graph.nodes``, ``self.nodes``,
    ``contracts``, ``node_specs``) rather than some unrelated ``.name``-
    having object (LLM models, agents, personality profiles, ...)."""
    try:
        text = ast.unparse(iterable).lower()
    except (ValueError, TypeError):
        return False
    return any(marker in text for marker in _NODE_COLLECTION_MARKERS)


def _line_is_suppressed(source_lines: list[str], lineno: int) -> bool:
    if 1 <= lineno <= len(source_lines):
        return _SUPPRESSION_MARKER in source_lines[lineno - 1]
    return False


def _check_file(file_path: Path) -> list[ModelNodeIdentityKeyingViolation]:
    try:
        source = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []

    source_lines = source.splitlines()
    violations: list[ModelNodeIdentityKeyingViolation] = []

    for node in ast.walk(tree):
        # Shape 1: {n.name: n for n in nodes} / {n.name: n for n in nodes if ...}
        if isinstance(node, ast.DictComp) and _is_bare_name_attr(node.key):
            iterable = node.generators[0].iter if node.generators else None
            if iterable is not None and _looks_like_node_collection(iterable):
                if not _line_is_suppressed(source_lines, node.lineno):
                    violations.append(
                        ModelNodeIdentityKeyingViolation(
                            file_path,
                            node.lineno,
                            "dict comprehension keyed on bare `<var>.name`",
                        )
                    )

        # Shape 2: for n in nodes: by_name[n.name] = n
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            if not _looks_like_node_collection(node.iter):
                continue
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if isinstance(target, ast.Subscript) and _is_bare_name_attr(
                        target.slice
                    ):
                        if not _line_is_suppressed(source_lines, stmt.lineno):
                            violations.append(
                                ModelNodeIdentityKeyingViolation(
                                    file_path,
                                    stmt.lineno,
                                    "dict assignment keyed on bare `<var>.name`",
                                )
                            )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", default=["src"])
    parser.add_argument(
        "--report",
        action="store_true",
        help="Report all violations without failing (informational mode).",
    )
    args = parser.parse_args(argv)

    files: list[Path] = []
    for raw_path in args.paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        elif path.suffix == ".py":
            files.append(path)

    all_violations: list[ModelNodeIdentityKeyingViolation] = []
    for file_path in files:
        all_violations.extend(_check_file(file_path))

    if not all_violations:
        print("OK: no bare-name node-identity keying found.")
        return 0

    for violation in all_violations:
        print(f"{violation.file_path}:{violation.line}: {violation.snippet}")

    print(
        f"\n{len(all_violations)} violation(s): keying a cross-package node "
        "collection on a bare `.name` attribute silently collapses same-"
        "named nodes from different packages (OMN-10865/14571/14575). "
        "Qualify the key with a package/repo identifier, e.g. "
        '`f"{package}::{n.name}"` or `(package, n.name)`.\n'
        f"Suppress a genuine false positive with `# {_SUPPRESSION_MARKER} <reason>` "
        "on the flagged line."
    )

    return 0 if args.report else 1


if __name__ == "__main__":
    raise SystemExit(main())
