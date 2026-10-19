# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21087's deploy probe reads its digest from the entrypoint, so it follows the handler."""

from __future__ import annotations

import hashlib
import re
import subprocess
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


def test_deploy_probe_reads_the_digest_the_checked_out_handler_has() -> None:
    (check,) = _superseding_probe()["checks"]
    extract = check["check_value"].split(" && ", 1)[0]
    assert extract.startswith("d=$(")
    read = subprocess.run(
        ["/bin/bash", "-c", f'{extract} && printf %s "$d"'],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    )
    assert read.stdout == hashlib.sha256(HANDLER.read_bytes()).hexdigest()
