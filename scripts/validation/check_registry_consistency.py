#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Fast cross-registry consistency gate for hook event types.

This mirrors ``tests/hooks/test_registry_consistency.py`` without importing the
pytest suite or ``omniclaude.hooks`` package. The CI gate only needs registry
shape, so it parses the committed Python/YAML sources directly and avoids
conftest/plugin startup hangs.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EMIT_CLIENT = REPO_ROOT / "plugins/onex/hooks/lib/emit_client_wrapper.py"
EVENT_REGISTRY = REPO_ROOT / "src/omniclaude/hooks/event_registry.py"
TOPICS = REPO_ROOT / "src/omniclaude/hooks/topics.py"

CAPTURE_EVENT_TYPES = ("artifact.captured", "tool.output.captured")


def _literal_strings(node: ast.AST) -> set[str]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values: set[str] = set()
        for item in node.elts:
            if not isinstance(item, ast.Constant) or not isinstance(item.value, str):
                raise ValueError("expected a literal string collection")
            values.add(item.value)
        return values
    raise ValueError("expected a literal string collection")


def _supported_event_types(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "SUPPORTED_EVENT_TYPES"
            for t in node.targets
        ):
            continue
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name):
            if node.value.func.id == "frozenset" and node.value.args:
                return _literal_strings(node.value.args[0])
        return _literal_strings(node.value)
    raise ValueError(f"SUPPORTED_EVENT_TYPES not found in {path}")


def _topic_base_values(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "TopicBase":
            continue
        values: dict[str, str] = {}
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign):
                continue
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                continue
            if isinstance(stmt.value, ast.Constant) and isinstance(
                stmt.value.value, str
            ):
                values[stmt.targets[0].id] = stmt.value.value
        return values
    raise ValueError(f"TopicBase not found in {path}")


def _event_registry_topics(
    path: Path, topic_values: dict[str, str]
) -> dict[str, set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "EVENT_REGISTRY":
            continue
        if not isinstance(node.value, ast.Dict):
            raise ValueError("EVENT_REGISTRY must be a literal dict")
        registry: dict[str, set[str]] = {}
        for key, value in zip(node.value.keys, node.value.values, strict=True):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise ValueError("EVENT_REGISTRY keys must be literal strings")
            event_type = key.value
            registry[event_type] = _fanout_topics(value, topic_values)
        return registry
    raise ValueError(f"EVENT_REGISTRY not found in {path}")


def _fanout_topics(node: ast.AST, topic_values: dict[str, str]) -> set[str]:
    if not isinstance(node, ast.Call):
        return set()
    topics: set[str] = set()
    for keyword in node.keywords:
        if keyword.arg != "fan_out" or not isinstance(keyword.value, ast.List):
            continue
        for item in keyword.value.elts:
            if not isinstance(item, ast.Call):
                continue
            for fanout_kw in item.keywords:
                if fanout_kw.arg != "topic_base":
                    continue
                topic_node = fanout_kw.value
                if not (
                    isinstance(topic_node, ast.Attribute)
                    and isinstance(topic_node.value, ast.Name)
                    and topic_node.value.id == "TopicBase"
                ):
                    raise ValueError("FanOutRule topic_base must use TopicBase.<NAME>")
                topics.add(topic_values[topic_node.attr])
    return topics


def _daemon_events(path: Path) -> dict[str, object]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("events"), dict):
        raise ValueError(f"{path} must contain an events mapping")
    return raw["events"]


def check_registry_consistency(daemon_registry_path: Path) -> list[str]:
    supported = _supported_event_types(EMIT_CLIENT)
    event_registry = _event_registry_topics(EVENT_REGISTRY, _topic_base_values(TOPICS))
    daemon_events = _daemon_events(daemon_registry_path)

    violations: list[str] = []
    missing_registry = sorted(supported - set(event_registry))
    if missing_registry:
        violations.append(
            "SUPPORTED_EVENT_TYPES entries missing from omniclaude EVENT_REGISTRY: "
            f"{missing_registry}"
        )

    missing_daemon = sorted(supported - set(daemon_events))
    if missing_daemon:
        violations.append(
            "SUPPORTED_EVENT_TYPES entries missing from omnimarket daemon registry: "
            f"{missing_daemon}"
        )

    for event_type in CAPTURE_EVENT_TYPES:
        event_def = daemon_events.get(event_type)
        if not isinstance(event_def, dict):
            violations.append(f"{event_type} not registered in daemon registry")
            continue
        fan_out = event_def.get("fan_out")
        if not isinstance(fan_out, list):
            violations.append(f"{event_type} has no fan_out list")
            continue
        rules = [rule for rule in fan_out if isinstance(rule, dict)]
        if len(rules) != 1 or rules[0].get("tier") != "duty_critical":
            violations.append(
                f"{event_type} must have exactly one duty_critical fan_out rule, "
                f"got: {rules}"
            )

    mismatches: dict[str, set[str]] = {}
    for event_type in sorted(supported):
        source_topics = event_registry.get(event_type, set())
        event_def = daemon_events.get(event_type)
        daemon_topics = {
            str(rule["topic"])
            for rule in event_def.get("fan_out", [])
            if isinstance(event_def, dict) and isinstance(rule, dict)
        }
        missing = source_topics - daemon_topics
        if missing:
            mismatches[event_type] = missing
    if mismatches:
        violations.append(
            "omniclaude EVENT_REGISTRY fan-out topics missing from daemon registry: "
            f"{mismatches}"
        )

    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daemon-registry", required=True, type=Path)
    args = parser.parse_args(argv)

    violations = check_registry_consistency(args.daemon_registry)
    if violations:
        print(f"Registry consistency gate failed: {len(violations)} violation(s)")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("Registry consistency gate passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
