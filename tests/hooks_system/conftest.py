# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Fixtures for the hook system suite (OMN-20109)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.hooks_system._harness import Rig, kill_tagged, make_rig


@pytest.fixture
def rig(tmp_path: Path) -> Iterator[Rig]:
    """An isolated rig. Teardown kills every process still carrying its token,
    so a red test cannot leave the leak it found running on the host."""
    the_rig = make_rig(tmp_path)
    try:
        yield the_rig
    finally:
        kill_tagged(the_rig.token)
