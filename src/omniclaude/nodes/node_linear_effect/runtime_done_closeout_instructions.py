#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Process entry of the closeout instruction audit: ``python -m`` this module (OMN-20368 AC6, OMN-21536).

Reads the roots from the command line, runs ``HandlerDoneCloseoutInstructions`` and
prints the findings. Exit 0 when clean, 1 when any root is missing or stale.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from omniclaude.nodes.node_linear_effect.handlers.handler_done_closeout_instructions import (
    HandlerDoneCloseoutInstructions,
)
from omniclaude.nodes.node_linear_effect.models import (
    ModelCloseoutInstructionAuditRequest,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    args = parser.parse_args()
    roots = args.roots or [Path(__file__).resolve().parents[4] / "plugins/onex/skills"]
    result = HandlerDoneCloseoutInstructions().handle(
        ModelCloseoutInstructionAuditRequest(roots=tuple(roots))
    )
    if result.findings:
        sys.stdout.write("\n".join(result.findings) + "\n")
        return 1
    sys.stdout.write(
        f"PASS: no retired closeout instruction in {len(roots)} source root(s)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
