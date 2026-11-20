# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The awaiting_reply skill is a dispatch shim to the omnimarket nodes [OMN-26222]."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_PATH = REPO_ROOT / "plugins" / "onex" / "skills" / "awaiting_reply" / "SKILL.md"
MANIFEST_PATH = REPO_ROOT / "plugins" / "distribution_manifest.yaml"
BACKING_NODES = ["node_awaiting_reply_compute", "node_awaiting_reply_effect"]


def _frontmatter() -> dict[str, object]:
    text = SKILL_PATH.read_text(encoding="utf-8")
    _, block, _ = text.split("---", 2)
    data = yaml.safe_load(block)
    assert isinstance(data, dict)
    return data


@pytest.mark.unit
def test_skill_is_bootstrap_dispatch_shim() -> None:
    meta = _frontmatter()
    assert meta["skill_kind"] == "dispatch"
    assert meta["bootstrap"] is True
    assert str(meta["description"]).startswith("Bootstrap skill")


@pytest.mark.unit
def test_skill_declares_one_onex_skill_command() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    assert "uv run onex skill awaiting_reply" in text
    assert "--bundle" in text


@pytest.mark.unit
def test_manifest_entry_names_backing_nodes() -> None:
    manifest = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = (
        [e for e in manifest if isinstance(e, dict)]
        if isinstance(manifest, list)
        else [
            e
            for v in manifest.values()
            if isinstance(v, list)
            for e in v
            if isinstance(e, dict)
        ]
    )
    entry = next(e for e in entries if e.get("id") == "awaiting_reply")
    assert entry["kind"] == "skill"
    assert entry["backing_nodes"] == BACKING_NODES
