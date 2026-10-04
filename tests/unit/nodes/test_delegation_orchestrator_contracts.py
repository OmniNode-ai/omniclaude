# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Contract and discovery smoke tests for the delegation orchestrator shells."""

from __future__ import annotations

import importlib
import tomllib
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
import yaml
from omnibase_core.nodes.node_orchestrator import NodeOrchestrator


@pytest.mark.unit
@pytest.mark.parametrize(
    ("node_name", "class_name", "capability", "input_module", "input_name"),
    [
        (
            "node_skill_delegate_orchestrator",
            "NodeSkillDelegateOrchestrator",
            "skill.delegate",
            "omniclaude.shared.models",
            "ModelSkillRequest",
        ),
        (
            "node_local_coding_orchestrator",
            "NodeLocalCodingOrchestrator",
            "local_coding.orchestration",
            "omnibase_core.models.events.model_event_envelope",
            "ModelEventEnvelope",
        ),
    ],
    ids=["skill-delegate", "local-coding"],
)
def test_orchestrator_contract_and_entry_point(
    node_name: str,
    class_name: str,
    capability: str,
    input_module: str,
    input_name: str,
) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    with (repo_root / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)

    module_name = f"omniclaude.nodes.{node_name}"
    entry_value = project["project"]["entry-points"]["onex.nodes"][node_name]
    assert entry_value == module_name
    package = EntryPoint(name=node_name, value=entry_value, group="onex.nodes").load()
    node_module = importlib.import_module(f"{module_name}.node")
    node_class = getattr(package, class_name)
    assert node_class is getattr(node_module, class_name)
    assert class_name in package.__all__
    assert issubclass(node_class, NodeOrchestrator)

    contract_path = Path(package.__file__).with_name("contract.yaml")
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    assert (
        contract_path
        == repo_root / "src" / "omniclaude" / "nodes" / node_name / "contract.yaml"
    )
    assert contract["name"] == node_name
    assert contract["contract_name"] == node_name
    assert contract["node_name"] == node_name
    assert contract["node_type"] == "ORCHESTRATOR_GENERIC"
    assert [item["name"] for item in contract["capabilities"]] == [capability]
    assert contract["input_model"]["module"] == input_module
    assert contract["input_model"]["name"] == input_name
    assert getattr(importlib.import_module(input_module), input_name) is not None
