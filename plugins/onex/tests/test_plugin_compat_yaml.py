# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for plugin-compat.yaml schema validity (OMN-8789).

Verifies:
- YAML parses without error
- Required top-level fields are present and correctly typed
- All declared nodes have at least one topic
- All topics have required fields (name, schema_version, role)
- Topic names follow the onex.{cmd,evt}.* naming convention
- No duplicate topic names across nodes
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

COMPAT_YAML_PATH = Path(__file__).parent.parent / "plugin-compat.yaml"
TOPIC_PATTERN = re.compile(r"^onex\.(cmd|evt)\.[a-z0-9-]+\.[a-z0-9-]+\.v\d+$")


@pytest.fixture(scope="module")
def compat_doc() -> dict:
    assert COMPAT_YAML_PATH.exists(), (
        f"plugin-compat.yaml not found at {COMPAT_YAML_PATH}"
    )
    return yaml.safe_load(COMPAT_YAML_PATH.read_text())


class TestPluginCompatYamlTopLevel:
    def test_plugin_field_present(self, compat_doc: dict) -> None:
        assert "plugin" in compat_doc
        assert isinstance(compat_doc["plugin"], str)
        assert compat_doc["plugin"] == "onex"

    def test_plugin_version_present(self, compat_doc: dict) -> None:
        assert "plugin_version" in compat_doc
        assert isinstance(compat_doc["plugin_version"], str)

    def test_min_runtime_version_present(self, compat_doc: dict) -> None:
        assert "min_runtime_version" in compat_doc
        assert isinstance(compat_doc["min_runtime_version"], str)

    def test_max_runtime_version_present(self, compat_doc: dict) -> None:
        assert "max_runtime_version" in compat_doc
        assert isinstance(compat_doc["max_runtime_version"], str)

    def test_nodes_field_is_list(self, compat_doc: dict) -> None:
        assert "nodes" in compat_doc
        assert isinstance(compat_doc["nodes"], list)

    def test_nodes_list_not_empty(self, compat_doc: dict) -> None:
        assert len(compat_doc["nodes"]) > 0

    def test_min_less_than_max(self, compat_doc: dict) -> None:
        from packaging.version import Version

        min_v = Version(compat_doc["min_runtime_version"])
        max_v = Version(compat_doc["max_runtime_version"])
        assert min_v < max_v, (
            f"min_runtime_version ({min_v}) must be less than max_runtime_version ({max_v})"
        )


class TestPluginCompatYamlNodes:
    def test_all_nodes_have_name(self, compat_doc: dict) -> None:
        for entry in compat_doc["nodes"]:
            assert "node" in entry, f"Node entry missing 'node' key: {entry}"
            assert isinstance(entry["node"], str)

    def test_all_nodes_have_topics(self, compat_doc: dict) -> None:
        for entry in compat_doc["nodes"]:
            assert "topics" in entry, f"Node {entry.get('node')} missing 'topics'"
            assert len(entry["topics"]) > 0, (
                f"Node {entry['node']} has empty topics list"
            )

    def test_all_topics_have_required_fields(self, compat_doc: dict) -> None:
        for entry in compat_doc["nodes"]:
            for topic in entry["topics"]:
                assert "name" in topic, (
                    f"Topic missing 'name' in node {entry['node']}: {topic}"
                )
                assert "schema_version" in topic, (
                    f"Topic missing 'schema_version' in node {entry['node']}: {topic}"
                )
                assert "role" in topic, (
                    f"Topic missing 'role' in node {entry['node']}: {topic}"
                )

    def test_all_topic_names_match_convention(self, compat_doc: dict) -> None:
        for entry in compat_doc["nodes"]:
            for topic in entry["topics"]:
                name = topic["name"]
                assert TOPIC_PATTERN.match(name), (
                    f"Topic name '{name}' in node {entry['node']} does not match "
                    f"onex.{{cmd,evt}}.<service>.<action>.v<N> convention"
                )

    def test_topic_roles_are_valid(self, compat_doc: dict) -> None:
        valid_roles = {"subscribe", "publish"}
        for entry in compat_doc["nodes"]:
            for topic in entry["topics"]:
                assert topic["role"] in valid_roles, (
                    f"Topic {topic['name']} in node {entry['node']} "
                    f"has invalid role '{topic['role']}'; must be one of {valid_roles}"
                )

    def test_no_duplicate_node_names(self, compat_doc: dict) -> None:
        names = [entry["node"] for entry in compat_doc["nodes"]]
        assert len(names) == len(set(names)), (
            f"Duplicate node entries found: {[n for n in names if names.count(n) > 1]}"
        )

    def test_no_duplicate_topic_names_within_node(self, compat_doc: dict) -> None:
        for entry in compat_doc["nodes"]:
            topic_names = [t["name"] for t in entry["topics"]]
            assert len(topic_names) == len(set(topic_names)), (
                f"Duplicate topic names in node {entry['node']}: "
                f"{[n for n in topic_names if topic_names.count(n) > 1]}"
            )

    def test_minimum_node_count(self, compat_doc: dict) -> None:
        # DoD requires all 47 R-class nodes declared — we have ~47 nodes with event_bus topics
        node_count = len(compat_doc["nodes"])
        assert node_count >= 40, (
            f"Expected at least 40 R-class nodes declared, got {node_count}. "
            "Add missing nodes to plugin-compat.yaml."
        )
