# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""validate_skill_backing_node -- pre-commit invocation shim (OMN-10171, SEAM-2).

Canonical implementation moved to omnibase_core per ADR:
  omnibase_core/docs/decisions/adr-2026-04-28-skill-liveness-validator-home.md

This file is the omniclaude pre-commit entry point. It delegates all logic to
``omnibase_core.validation.validator_skill_backing_node`` and re-exports the
public API so that co-located callers (e.g. ``validate_skill_aspiration.py``)
continue to import from this path without modification.

Usage (via pre-commit hook, unchanged)::

    python plugins/onex/skills/_lib/validate_skill_backing_node.py [ROOT]

ROOT is passed to the canonical implementation as ``omniclaude_root``.

Bootstrap note: imports from omnibase_core are deferred to function call time
so this shim is importable before omnibase_core is updated to the version that
ships validator_skill_backing_node (OMN-10171 transitional window).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omnibase_core.validation.validator_skill_backing_node import (
        SkillLivenessViolation,
    )


def _core() -> object:
    """Return the canonical omnibase_core validator module (lazy import)."""
    from omnibase_core.validation import validator_skill_backing_node  # noqa: PLC0415

    return validator_skill_backing_node


def load_allowlist(omniclaude_root: Path) -> dict[str, str]:
    return _core().load_allowlist(omniclaude_root)  # type: ignore[attr-defined]


def extract_backing_node(skill_md_path: Path) -> str | None:
    return _core().extract_backing_node(skill_md_path)  # type: ignore[attr-defined]


def check_node_liveness(
    skill_name: str,
    node_name: str,
    omniclaude_root: Path,
) -> SkillLivenessViolation | None:
    return _core().check_node_liveness(skill_name, node_name, omniclaude_root)  # type: ignore[attr-defined]


def scan(omniclaude_root: Path) -> list[str]:
    return _core().scan(omniclaude_root)  # type: ignore[attr-defined]


def _omnimarket_available(omniclaude_root: Path) -> bool:
    return _core()._omnimarket_available(omniclaude_root)  # type: ignore[attr-defined]


def _resolve_omnimarket_nodes_root(omniclaude_root: Path) -> list[Path]:
    return _core()._resolve_omnimarket_nodes_root(omniclaude_root)  # type: ignore[attr-defined]


def _get_violation_class() -> type:
    return _core().SkillLivenessViolation  # type: ignore[attr-defined]


# NodeViolation / SkillLivenessViolation: lazy proxies for callers that do isinstance checks.
# Callers that import these names and use them in isinstance() must call _get_violation_class()
# or import directly from omnibase_core after the version bump lands.
# These aliases are provided for validate_skill_aspiration.py backward compat.
try:
    from omnibase_core.validation.validator_skill_backing_node import (  # noqa: E402
        SkillLivenessViolation,
    )

    NodeViolation = SkillLivenessViolation
except ImportError:
    SkillLivenessViolation = None  # type: ignore[assignment,misc]
    NodeViolation = None  # type: ignore[assignment]

__all__ = [
    "NodeViolation",
    "SkillLivenessViolation",
    "_omnimarket_available",
    "_resolve_omnimarket_nodes_root",
    "check_node_liveness",
    "extract_backing_node",
    "load_allowlist",
    "scan",
]


def main(argv: list[str] | None = None) -> int:
    """Delegate to the canonical omnibase_core implementation."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        # Default: omniclaude root is four levels above this shim file
        # (plugins/onex/skills/_lib/validate_skill_backing_node.py)
        args = [str(Path(__file__).resolve().parents[4])]
    core = _core()
    return core.main(args)  # type: ignore[attr-defined]


if __name__ == "__main__":
    sys.exit(main())
