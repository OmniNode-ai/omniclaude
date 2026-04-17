# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""``ModelSubagentStopReport`` — SubagentStop verifier verdict wrapper [OMN-9086].

The verdict model is defined alongside the verifier logic in
``plugins/onex/hooks/lib/subagent_claim_verifier.py`` so they evolve together.
This module re-exports it (per the Task 2 file list in
``docs/plans/2026-04-17-unused-hooks-applications.md``) so downstream callers
outside the hooks package can import from a stable ``models/`` path.
"""

from __future__ import annotations

import pathlib
import sys

_LIB_DIR = pathlib.Path(__file__).resolve().parent.parent / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from subagent_claim_verifier import (  # type: ignore[import-not-found]  # noqa: E402
    EnumVerdict,
    EnumWorkerReportKind,
    ModelExtractionResult,
    ModelSubagentStopReport,
    ModelWorkerReport,
    ModelWorkerReportPR,
)

__all__ = [
    "EnumVerdict",
    "EnumWorkerReportKind",
    "ModelExtractionResult",
    "ModelSubagentStopReport",
    "ModelWorkerReport",
    "ModelWorkerReportPR",
]
