# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Hostile Reviewer pin carries chunk-scaled review deadlines (OMN-17427).

The workflow clones the omniintelligence revision recorded by uv.lock.
The pin carries omniintelligence#1107 (chunk-scaled review deadline) and
#1108 (last endpoint keeps its own timeout), on top of #1099's Claude API
voters. Both the source pin and lock must carry those changes.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# omniintelligence#1107 scales review deadlines; #1108 preserves endpoint timeouts.
CHUNK_DEADLINE_PIN = "921b322b8e43f695961a06a04759dc88bb3e88ff"
# The previous pin carries #1099's Claude API voters but rejects review_deadline_seconds.
PRE_CHUNK_DEADLINE_PIN = "7f686d4bbca251dd3db49c1222ff8d6f738abd6c"
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


def test_pyproject_pins_chunk_deadline_and_last_endpoint_timeout_revision() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert pyproject_rev(text) == CHUNK_DEADLINE_PIN


def test_lock_records_only_chunk_deadline_and_last_endpoint_timeout_revision() -> None:
    text = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert lock_revs(text) == {CHUNK_DEADLINE_PIN}


def test_the_workflow_clones_the_rev_the_lock_records() -> None:
    text = (ROOT / ".github" / "workflows" / "hostile-reviewer.yml").read_text(
        encoding="utf-8"
    )
    assert "omniintelligence\\.git\\?rev=[0-9a-f]{40}" in text


def test_the_pin_before_chunk_deadline_and_last_endpoint_timeout_is_caught() -> None:
    """Positive control: #1099's pin and lock before #1107 and #1108."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    before_pyproject = pyproject.replace(CHUNK_DEADLINE_PIN, PRE_CHUNK_DEADLINE_PIN)
    before_lock = lock.replace(CHUNK_DEADLINE_PIN, PRE_CHUNK_DEADLINE_PIN)
    assert pyproject_rev(before_pyproject) == PRE_CHUNK_DEADLINE_PIN
    assert lock_revs(before_lock) == {PRE_CHUNK_DEADLINE_PIN}
