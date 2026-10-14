# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Hostile Reviewer clones omniintelligence at the larger retry budget (OMN-17427).

The review voter asks for 4096 tokens. When a reply does not parse as review
JSON it retries once, and before omniintelligence#1072 that retry got the same
4096-token cap, so a reply cut off at the cap failed the vote again and the
verdict degraded to ``degraded_quorum``. omniintelligence#1072 gives the retry
8192 tokens. The workflow clones omniintelligence at the rev ``uv.lock``
records for it, so the fix reaches this repository's Hostile Review Gate only
when the pin in ``pyproject.toml`` and the rev in ``uv.lock`` name a revision
that carries it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# The merge commit of omniintelligence#1072 on its dev branch.
RETRY_BUDGET_PIN = "3fcbf795087a79081c0ceeb676216bf64c5d49ae"
# The pin before this change, which retries at the same 4096-token cap.
PRE_RETRY_BUDGET_PIN = "f4bf0a1989fc37bd7ad9b4a7ad591f801d2a1070"
_LOCK_REVS = re.compile(r"omniintelligence\.git\?rev=([0-9a-f]{40})")


def pyproject_rev(pyproject_text: str) -> str:
    """The rev ``[tool.uv.sources]`` pins omninode-intelligence at."""
    source = tomllib.loads(pyproject_text)["tool"]["uv"]["sources"][
        "omninode-intelligence"
    ]
    return str(source["rev"])


def lock_revs(lock_text: str) -> set[str]:
    """Every omniintelligence rev ``uv.lock`` records."""
    return set(_LOCK_REVS.findall(lock_text))


def test_pyproject_pins_omniintelligence_at_the_retry_budget_revision() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject_rev(text) == RETRY_BUDGET_PIN


def test_the_lock_records_only_the_retry_budget_revision() -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert lock_revs(text) == {RETRY_BUDGET_PIN}


def test_the_workflow_clones_the_rev_the_lock_records() -> None:
    text = (ROOT / ".github" / "workflows" / "hostile-reviewer.yml").read_text(
        encoding="utf-8"
    )
    assert "omniintelligence\\.git\\?rev=[0-9a-f]{40}" in text


def test_the_pin_before_the_retry_budget_is_caught() -> None:
    """Positive control: the pin and lock as they were before this change."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    before_pyproject = pyproject.replace(RETRY_BUDGET_PIN, PRE_RETRY_BUDGET_PIN)
    before_lock = lock.replace(RETRY_BUDGET_PIN, PRE_RETRY_BUDGET_PIN)
    assert pyproject_rev(before_pyproject) == PRE_RETRY_BUDGET_PIN
    assert lock_revs(before_lock) == {PRE_RETRY_BUDGET_PIN}
