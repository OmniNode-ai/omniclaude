# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject the retired tick-box/comment closeout instruction (OMN-20368 AC6).

Pass the source skill and workflow roots explicitly when auditing another
release. Missing roots are errors, so an absent checkout cannot look clean.
The process entry is ``runtime_done_closeout_instructions`` (OMN-21536).
"""

from __future__ import annotations

import re

from omniclaude.nodes.node_linear_effect.models import (
    ModelCloseoutInstructionAuditRequest,
    ModelCloseoutInstructionAuditResult,
)

_RETIRED = re.compile(r"dod_evidence\s+comment", re.IGNORECASE)
_SUFFIXES = {".md", ".txt", ".yaml", ".yml", ".json", ".py"}
_EXCLUDED = {".git", ".venv", "__pycache__", "node_modules", "tests", "fixtures"}


class HandlerDoneCloseoutInstructions:
    """Audits instruction roots for the retired ``dod_evidence comment`` closeout path."""

    def handle(
        self, request: ModelCloseoutInstructionAuditRequest
    ) -> ModelCloseoutInstructionAuditResult:
        out: list[str] = []
        for root in request.roots:
            if not root.is_dir():
                out.append(f"{root}: instruction root is missing or not a directory")
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix not in _SUFFIXES or any(
                    part in _EXCLUDED for part in path.relative_to(root).parts
                ):
                    continue
                if not path.is_file() or path.name.startswith("test_"):
                    continue
                for number, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1
                ):
                    if _RETIRED.search(line):
                        out.append(
                            f"{path}:{number}: retired closeout instruction; require a fresh bound PASS receipt"
                        )
        return ModelCloseoutInstructionAuditResult(findings=tuple(out))
