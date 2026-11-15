# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""``sibling-lock-refresh.yml`` is dispatch-only (OMN-24189).

RULING 2026-11-09T21:54:25Z lane=orchestrator-31d9: a downstream repository
moves its pin on a sibling only when it needs something new from it, so the
nightly schedule is removed and the sibling lock refresh runs only by
workflow_dispatch, when a change needs a newer sibling. These tests pin that
shape: manual dispatch is kept, no automatic trigger remains, and the cron
literal is gone from the workflow file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "sibling-lock-refresh.yml"
)


def _triggers() -> dict[object, object]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 reads the bare key ``on`` as the boolean True.
    return loaded.get("on", loaded.get(True))


@pytest.mark.unit
def test_manual_dispatch_is_kept() -> None:
    assert "workflow_dispatch" in _triggers()


@pytest.mark.unit
def test_workflow_is_dispatch_only() -> None:
    assert set(_triggers()) == {"workflow_dispatch"}, (
        "RULING 2026-11-09T21:54:25Z lane=orchestrator-31d9 (OMN-24189): the "
        "sibling lock refresh must have no automatic trigger — the nightly "
        "schedule is removed and the train runs only by workflow_dispatch, "
        "when a change needs a newer sibling."
    )


@pytest.mark.unit
def test_the_cron_literal_is_gone() -> None:
    assert "cron:" not in WORKFLOW.read_text(encoding="utf-8")
