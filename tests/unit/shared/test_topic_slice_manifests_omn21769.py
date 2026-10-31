# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Topics of the OMN-21769 slice come from manifests and contracts, not code literals."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.hooks.topics import TopicBase
from omniclaude.models.model_topic_manifest import ModelTopicManifest

_LEDGER_ROWS = (
    "ack",
    "claim",
    "correction",
    "friction",
    "hold",
    "msg",
    "operator_consent",
    "release",
    "ruling",
    "status",
    "terminal",
)


@pytest.mark.unit
@pytest.mark.parametrize("row", _LEDGER_ROWS)
def test_ledger_v2_member_is_the_manifest_topic(row: str) -> None:
    manifest = ModelTopicManifest.beside(
        str(Path(__file__).parents[3] / "src/omniclaude/hooks/topics.py")
    )
    member = TopicBase[f"WORK_LEDGER_{row.upper()}_V2"]
    assert member.value == manifest.get("work_ledger_v2", row)
    assert member.value == f"onex.evt.omnimarket.work-ledger-{row.replace('_', '-')}.v2"


@pytest.mark.unit
def test_intelligence_client_topics_come_from_its_manifest() -> None:
    pytest.importorskip("omnibase_infra.runtime.request_response_wiring")
    from omniclaude.lib.core.intelligence_event_client import IntelligenceEventClient

    manifest = ModelTopicManifest.beside(
        str(Path(__file__).parents[3] / "src/omniclaude/lib/core/topics.yaml")
    )
    assert (
        manifest.get("code_analysis", "requested")
        == IntelligenceEventClient.TOPICS["requested"]
    )
    assert (
        manifest.get("code_analysis", "completed")
        == IntelligenceEventClient.TOPICS["completed"]
    )
    assert (
        manifest.get("code_analysis", "failed")
        == IntelligenceEventClient.TOPICS["failed"]
    )


@pytest.mark.unit
def test_route_matcher_topic_is_read_from_the_status_orchestrator_contract() -> None:
    from omniclaude.runtime.__main__ import _check_route_matcher

    ok, message = _check_route_matcher()
    assert ok is True
    assert "onex.cmd.omniclaude.status.v1" in message


@pytest.mark.unit
def test_topic_of_reads_the_subscribe_topic_of_a_node_contract(tmp_path: Path) -> None:
    node = tmp_path / "nodes" / "node_x"
    node.mkdir(parents=True)
    (node / "contract.yaml").write_text(
        "event_bus:\n  subscribe:\n    topic: t.sub\n", encoding="utf-8"
    )
    module = tmp_path / "pkg" / "mod.py"
    assert ModelTopicManifest.topic_of(str(module), "node_x") == "t.sub"


@pytest.mark.unit
def test_manifest_undeclared_topic_fails_to_resolve(tmp_path: Path) -> None:
    path = tmp_path / "topics.yaml"
    path.write_text("publish:\n  one: t.one\n", encoding="utf-8")
    assert ModelTopicManifest.from_path(path).get("publish", "one") == "t.one"
    with pytest.raises(ValueError, match="missing"):
        ModelTopicManifest.from_path(path).get("publish", "missing")
