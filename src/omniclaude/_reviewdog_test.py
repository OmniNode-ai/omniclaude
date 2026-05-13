# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Reviewdog proof-of-life module — OMN-10938.

This file exists solely to trigger reviewdog check runs on the PR.
The check runs appearing (ruff, mypy, trivy-security, bandit-security)
proves the reviewdog plumbing is wired correctly, independent of findings.
"""


def reviewdog_test() -> str:
    """Return a sentinel string for the proof-of-life PR."""
    return "reviewdog-proof-of-life-omn-10938"
