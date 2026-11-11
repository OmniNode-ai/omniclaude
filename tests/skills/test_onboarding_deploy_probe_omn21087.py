# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21087's deploy probe reads its digest from the entrypoint, so it follows the handler."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACT = REPO / "contracts/OMN-21087.yaml"
HANDLER = (
    REPO
    / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    / "handler_onboarding_preflight.sh"
)
STALE = "dod-omn21087-deploy-bootstrap"
FRESH_DOWNLOAD = "dod-omn21087-ac4-fresh-download-handler"
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"

pytestmark = pytest.mark.unit


def _superseding_probe() -> dict[str, object]:
    items = yaml.safe_load(CONTRACT.read_text())["dod_evidence"]
    ids = [item["id"] for item in items]
    found = [
        item
        for item in items
        if item.get("evidence_artifact") == f"supersedes_dod_evidence:{STALE}"
    ]
    assert len(found) == 1, f"one item must supersede {STALE}"
    assert ids.index(found[0]["id"]) > ids.index(STALE), "a superseder comes later"
    return found[0]


def test_deploy_probe_names_no_digest_of_its_own() -> None:
    (check,) = _superseding_probe()["checks"]
    command = check["check_value"]
    assert check["check_type"] == "command"
    assert not re.search(r"[0-9a-f]{64}", command), "a literal digest goes stale"
    assert "plugins/onex/skills/_bin/lab-onboarding.sh" in command
    assert "$(git rev-parse HEAD)" in command


def _fresh_download_probe() -> str:
    items = yaml.safe_load(CONTRACT.read_text())["dod_evidence"]
    (item,) = [item for item in items if item["id"] == FRESH_DOWNLOAD]
    assert item["binds_ac"] == ["AC4"]
    (command,) = [
        c["check_value"] for c in item["checks"] if c["check_type"] == "command"
    ]
    assert not re.search(r"[0-9a-f]{40}", command), (
        "a literal commit or digest goes stale"
    )
    return command
