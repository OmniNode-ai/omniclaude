# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The sharded test job keeps headroom over its slowest measured shard (OMN-19998).

The push run on dev head 9ee6e7f115a2 held ``Tests (Split 1/5)`` for 903 s. The
job's 15-minute ceiling cancelled it, ``Tests Gate`` failed on the cancelled
shard, and dev went red with no failing test. Green dev runs measured the same
shards at 459 s to 819 s, so the ceiling had under 10 percent headroom.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

CI_WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

SLOWEST_MEASURED_SHARD_SECONDS = 903
MIN_HEADROOM_RATIO = 1.5


def test_sharded_test_job_ceiling_has_headroom_over_slowest_shard() -> None:
    job = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))["jobs"]["test"]
    assert job["name"].startswith("Tests (Split")
    ceiling_seconds = job["timeout-minutes"] * 60
    assert ceiling_seconds >= SLOWEST_MEASURED_SHARD_SECONDS * MIN_HEADROOM_RATIO
