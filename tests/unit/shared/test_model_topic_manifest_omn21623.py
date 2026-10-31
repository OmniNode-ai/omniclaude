# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""ModelTopicManifest and ModelTopicRegistry resolve topics or fail to load (OMN-21623)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.models.model_topic_manifest import ModelTopicManifest
from omniclaude.models.model_topic_registry import ModelTopicRegistry


@pytest.mark.unit
def test_manifest_resolves_a_declared_topic(tmp_path: Path) -> None:
    path = tmp_path / "topics.yaml"
    path.write_text("publish:\n  one: t.one\n", encoding="utf-8")
    manifest = ModelTopicManifest.from_path(path)
    assert manifest.get("publish", "one") == "t.one"


@pytest.mark.unit
def test_manifest_beside_reads_the_topics_yaml_next_to_a_module(
    tmp_path: Path,
) -> None:
    (tmp_path / "topics.yaml").write_text("s:\n  n: t.n\n", encoding="utf-8")
    manifest = ModelTopicManifest.beside(str(tmp_path / "module.py"))
    assert manifest.get("s", "n") == "t.n"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("section", "name"), [("publish", "missing"), ("missing", "one")]
)
def test_manifest_undeclared_topic_fails_to_resolve(
    tmp_path: Path, section: str, name: str
) -> None:
    path = tmp_path / "topics.yaml"
    path.write_text("publish:\n  one: t.one\n", encoding="utf-8")
    with pytest.raises(ValueError, match=name):
        ModelTopicManifest.from_path(path).get(section, name)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text", ["- a\n- b\n", "publish: [a, b]\n", "publish:\n  one: 1\n"]
)
def test_manifest_malformed_file_fails_to_load(tmp_path: Path, text: str) -> None:
    path = tmp_path / "topics.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="topics"):
        ModelTopicManifest.from_path(path)


@pytest.mark.unit
def test_registry_resolves_event_types_in_the_order_given(tmp_path: Path) -> None:
    path = tmp_path / "topic_registry.yaml"
    path.write_text(
        "topics:\n"
        "  - event_type: a.b\n    topic: t.ab\n"
        "  - event_type: c.d\n    topic: t.cd\n",
        encoding="utf-8",
    )
    registry = ModelTopicRegistry.from_path(path)
    assert registry.topics("c.d", "a.b") == ["t.cd", "t.ab"]


@pytest.mark.unit
def test_registry_undeclared_event_type_fails_to_resolve(tmp_path: Path) -> None:
    path = tmp_path / "topic_registry.yaml"
    path.write_text("topics:\n  - event_type: a.b\n    topic: t.ab\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"x\.y"):
        ModelTopicRegistry.from_path(path).topics("a.b", "x.y")


@pytest.mark.unit
def test_registry_without_a_topics_list_fails_to_load(tmp_path: Path) -> None:
    path = tmp_path / "topic_registry.yaml"
    path.write_text("other: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="topics"):
        ModelTopicRegistry.from_path(path)


@pytest.mark.unit
def test_default_registry_declares_the_demo_event_types() -> None:
    topics = ModelTopicRegistry.default().topics("session.started", "tool.content")
    assert topics == [
        "onex.evt.omniclaude.session-started.v1",
        "onex.cmd.omniintelligence.tool-content.v1",
    ]
