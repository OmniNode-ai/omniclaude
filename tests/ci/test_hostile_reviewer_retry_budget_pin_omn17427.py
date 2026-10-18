# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Hostile Reviewer pin carries Claude API voters (OMN-20910).

The workflow clones the omniintelligence revision recorded by uv.lock.
The Claude API voter merge retains the larger retry budget and accepts
existing lab voters, so both the source pin and lock must carry that merge.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# The merge of omniintelligence#1099 also retains the larger retry budget.
CLAUDE_API_VOTER_PIN = "7f686d4bbca251dd3db49c1222ff8d6f738abd6c"
# The previous pin has the larger retry budget but no Claude API voter.
PRE_CLAUDE_API_VOTER_PIN = "3fcbf795087a79081c0ceeb676216bf64c5d49ae"
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


def test_pyproject_pins_omniintelligence_at_the_claude_api_voter_revision() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject_rev(text) == CLAUDE_API_VOTER_PIN


def test_the_lock_records_only_the_claude_api_voter_revision() -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert lock_revs(text) == {CLAUDE_API_VOTER_PIN}


def test_the_workflow_clones_the_rev_the_lock_records() -> None:
    text = (ROOT / ".github" / "workflows" / "hostile-reviewer.yml").read_text(
        encoding="utf-8"
    )
    assert "omniintelligence\\.git\\?rev=[0-9a-f]{40}" in text


def test_the_pin_before_claude_api_voters_is_caught() -> None:
    """Positive control: the pin and lock as they were before this change."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    before_pyproject = pyproject.replace(CLAUDE_API_VOTER_PIN, PRE_CLAUDE_API_VOTER_PIN)
    before_lock = lock.replace(CLAUDE_API_VOTER_PIN, PRE_CLAUDE_API_VOTER_PIN)
    assert pyproject_rev(before_pyproject) == PRE_CLAUDE_API_VOTER_PIN
    assert lock_revs(before_lock) == {PRE_CLAUDE_API_VOTER_PIN}
