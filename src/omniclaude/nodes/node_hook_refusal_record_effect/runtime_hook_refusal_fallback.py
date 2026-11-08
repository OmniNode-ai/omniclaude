# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Process entry for the fallback row of a refusal no interpreter could record (OMN-23017).

``hook_refusal.sh`` runs this file BY PATH under an interpreter that may have no
packages installed: it imports nothing from ``omniclaude`` and loads the
standard-library handler file beside it, so any interpreter that starts can
write the row.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

_HANDLER = (
    Path(__file__).resolve().parent / "handlers" / "handler_hook_refusal_fallback.py"
)


@dataclass(frozen=True)
class _Facts:
    """The attributes ``ProtocolFallbackFacts`` names, from the command line."""

    guard: str
    reason: str
    detail: str
    hooks_lib: str
    import_error: str
    interpreters: tuple[str, ...]


def main(argv: list[str] | None = None) -> int:
    """Parse the seam's operands and write the fallback row."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hooks-lib", required=True)
    parser.add_argument("--guard", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--detail", default="")
    parser.add_argument("--import-error", default="")
    parser.add_argument("--interpreters", nargs="*", default=[])
    args = parser.parse_args(argv)
    spec = importlib.util.spec_from_file_location(
        "handler_hook_refusal_fallback", _HANDLER
    )
    if spec is None or spec.loader is None:
        sys.stderr.write("hook refusal fallback: handler file is not loadable\n")
        return 1
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return int(
        module.write_fallback_row(
            _Facts(
                guard=args.guard,
                reason=args.reason,
                detail=args.detail,
                hooks_lib=args.hooks_lib,
                import_error=args.import_error,
                interpreters=tuple(args.interpreters),
            )
        )
    )


if __name__ == "__main__":
    sys.exit(main())
