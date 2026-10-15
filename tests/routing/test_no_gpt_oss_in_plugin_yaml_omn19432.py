# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19432: no plugin YAML names the retired gpt-oss model.

gpt-oss-120b left the lab on 2026-10-08. A plugin agent or hook config that still
lists it as a serving tier describes a model nothing serves. The check reads
parsed YAML keys and values, so a dated comment recording what once served a tier
is history and does not count.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_PLUGINS = Path(__file__).resolve().parents[2] / "plugins"
_GPT_OSS = re.compile(r"gpt[-_ ]?oss", re.IGNORECASE)


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    return []


def _gpt_oss_values(text: str) -> list[str]:
    return [
        s
        for doc in yaml.safe_load_all(text)
        for s in _strings(doc)
        if _GPT_OSS.search(s)
    ]


@pytest.mark.unit
def test_detector_finds_a_spelling_in_a_value_but_not_in_a_comment() -> None:
    assert _gpt_oss_values("tier: 'GPT-OSS 120B for design'\n") == [
        "GPT-OSS 120B for design"
    ]
    assert _gpt_oss_values("# gpt-oss was here\ntier: local\n") == []


@pytest.mark.unit
def test_plugins_have_yaml_to_scan() -> None:
    assert len(list(_PLUGINS.rglob("*.yaml"))) > 100


@pytest.mark.unit
def test_no_plugin_yaml_names_gpt_oss() -> None:
    offenders = {
        str(path.relative_to(_PLUGINS)): found
        for path in sorted(_PLUGINS.rglob("*.yaml"))
        if (found := _gpt_oss_values(path.read_text(encoding="utf-8")))
    }
    assert offenders == {}


@pytest.mark.unit
def test_retired_smart_responder_baseline_entries_are_removed() -> None:
    baseline = yaml.safe_load(
        (_PLUGINS.parent / "config/hardcoded_model_config_baseline.yaml").read_text(
            encoding="utf-8"
        )
    )
    retired_hashes = {
        "199be5452e8aeac55ca0916cf142ee1e2d829974",
        "5648f4815171ab5174067eb79f228464a25b96f5",
        "b9f8e6a110cb996d2416e09c4dd59920e8c86f97",
        "e525c4b269ec45b64ffff94b7eaafd04501552b7",
    }
    retained = [
        entry
        for entry in baseline["entries"]
        if entry["path"] == "plugins/onex/agents/configs/omniagent-smart-responder.yaml"
        and entry["family"] == "M"
        and entry["content_sha1"] in retired_hashes
    ]
    assert retained == [], f"Retired smart-responder exemptions remain: {retained}"
