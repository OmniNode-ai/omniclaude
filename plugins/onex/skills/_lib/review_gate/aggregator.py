#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verdict aggregation for the review gate skill."""

from __future__ import annotations

from typing import Any

BLOCKING_SEVERITIES_DEFAULT = {"CRITICAL", "MAJOR"}
BLOCKING_SEVERITIES_STRICT = {"CRITICAL", "MAJOR", "MINOR"}


def aggregate_verdicts(
    verdicts: list[dict[str, Any]], *, strict: bool = False
) -> dict[str, Any]:
    """Aggregate review agent verdicts into a gate pass/fail decision.

    Args:
        verdicts: List of agent verdict dicts, each with "agent", "verdict", "findings".
        strict: If True, MINOR findings also block. Default blocks on MAJOR+.

    Returns:
        Dict with gate_verdict ("pass"|"fail"), total_findings, blocking_count,
        strict, agent_count, findings.
    """
    blocking_set = BLOCKING_SEVERITIES_STRICT if strict else BLOCKING_SEVERITIES_DEFAULT
    all_findings: list[dict[str, Any]] = []
    blocking_count = 0

    for v in verdicts:
        for f in v.get("findings", []):
            all_findings.append(f)
            if f.get("severity", "").upper() in blocking_set:
                blocking_count += 1

    return {
        "gate_verdict": "fail" if blocking_count > 0 else "pass",
        "total_findings": len(all_findings),
        "blocking_count": blocking_count,
        "strict": strict,
        "agent_count": len(verdicts),
        "findings": all_findings,
    }
