#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI failure classification heuristics for ci_recovery skill."""

from __future__ import annotations

import re

INFRA_PATTERNS: list[str] = [
    r"runner",
    r"timeout",
    r"network",
    r"connection refused",
    r"503",
    r"lost connection",
]

CONFIG_PATTERNS: list[str] = [
    r"lock file",
    r"uv\.lock",
    r"version mismatch",
    r"missing dependency",
]


def classify_ci_failure(log: str, known_flaky: list[str] | None = None) -> str:
    """Classify a CI failure log into one of 4 categories.

    Args:
        log: The CI failure log text.
        known_flaky: List of test name substrings known to be flaky.

    Returns:
        One of: "flaky_test", "infra_issue", "config_error", "real_failure"
    """
    if known_flaky:
        for flaky_name in known_flaky:
            if flaky_name in log:
                return "flaky_test"

    log_lower = log.lower()
    for pattern in INFRA_PATTERNS:
        if re.search(pattern, log_lower):
            return "infra_issue"

    for pattern in CONFIG_PATTERNS:
        if re.search(pattern, log_lower):
            return "config_error"

    return "real_failure"
