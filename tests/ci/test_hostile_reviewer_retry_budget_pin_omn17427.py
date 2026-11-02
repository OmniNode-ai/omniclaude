# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The Hostile Reviewer pin carries chunk-scaled review deadlines (OMN-17427).

The workflow clones the omniintelligence revision recorded by uv.lock.
The pin carries omniintelligence#1107 (chunk-scaled review deadline) and
#1108 (last endpoint keeps its own timeout), on top of #1099's Claude API
voters. Both the source pin and lock must carry those changes. The source
names a dev-merge tag (OMN-21900), so the floor is the dev-merge tag of the
commit that carries them: a tag sorts by its merge timestamp.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
# omniintelligence#1107 scales review deadlines; #1108 preserves endpoint timeouts.
# This is the dev-merge tag of the commit that carries both; a pin must not sort below it.
CHUNK_DEADLINE_TAG_FLOOR = "dev-20261019012929-921b322b8e43"
# A dev-merge tag older than the floor: #1099's Claude API voters, before #1107 and #1108.
PRE_CHUNK_DEADLINE_TAG = "dev-20261018000000-7f686d4bbca2"
_DEV_TAG = re.compile(r"^dev-[0-9]{14}-[0-9a-f]{12}$")
_LOCK_TAGS = re.compile(r"omniintelligence\.git\?tag=(dev-[0-9]{14}-[0-9a-f]{12})")


def pyproject_tag(pyproject_text: str) -> str:
    """The dev-merge tag ``[tool.uv.sources]`` pins omninode-intelligence at."""
    source = tomllib.loads(pyproject_text)["tool"]["uv"]["sources"][
        "omninode-intelligence"
    ]
    assert "rev" not in source
    return str(source["tag"])


def lock_tags(lock_text: str) -> set[str]:
    """Every omniintelligence dev-merge tag ``uv.lock`` records."""
    return set(_LOCK_TAGS.findall(lock_text))


def test_pyproject_pins_chunk_deadline_and_last_endpoint_timeout_revision() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    tag = pyproject_tag(text)
    assert _DEV_TAG.fullmatch(tag)
    assert tag >= CHUNK_DEADLINE_TAG_FLOOR


def test_lock_records_only_the_pyproject_tag() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert lock_tags(lock) == {pyproject_tag(pyproject)}


def test_the_workflow_clones_omniintelligence_at_its_newest_dev_tag() -> None:
    """OMN-20910: the review tooling is read at a dev-* tag, not the lock's rev."""
    text = (ROOT / ".github" / "workflows" / "hostile-reviewer.yml").read_text(
        encoding="utf-8"
    )
    assert "'refs/tags/dev-*'" in text
    assert "omniintelligence\\.git\\?rev=[0-9a-f]{40}" not in text


def test_the_pin_before_chunk_deadline_and_last_endpoint_timeout_is_caught() -> None:
    """Positive control: #1099's pin before #1107 and #1108 sorts below the floor."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    current = pyproject_tag(pyproject)
    before_pyproject = pyproject.replace(current, PRE_CHUNK_DEADLINE_TAG)
    before_lock = lock.replace(current, PRE_CHUNK_DEADLINE_TAG)
    assert pyproject_tag(before_pyproject) < CHUNK_DEADLINE_TAG_FLOOR
    assert lock_tags(before_lock) == {PRE_CHUNK_DEADLINE_TAG}
