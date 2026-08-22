# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Load and validate the static module adjacency map."""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelAdjacencyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    reverse_deps: list[str] = Field(default_factory=list)


class ModelThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    modules_changed_for_full_suite: int = Field(..., ge=1)


class ModelPathTrigger(BaseModel):
    """Map a changed-path prefix outside ``src/`` to test paths to select.

    The adjacency map only understands ``src/omniclaude/<module>``; every other
    path (workflows, CI scripts) resolved to nothing and fell through to the
    ``tests/unit/`` fallback. That made guards living outside ``tests/unit/``
    unreachable on the everyday dev path (OMN-15393).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    path_prefix: str = Field(..., min_length=1)
    test_paths: list[str] = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_test_paths_are_directories(self) -> ModelPathTrigger:
        for test_path in self.test_paths:
            if not test_path.endswith("/"):
                raise ValueError(
                    f"path_trigger test_path '{test_path}' must end with '/' "
                    f"(pytest is invoked with these as directory arguments)"
                )
        return self


class ModelAdjacencyMap(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(..., ge=1)
    shared_modules: list[str]
    thresholds: ModelThresholds
    test_infrastructure_paths: list[str]
    adjacency: dict[str, ModelAdjacencyEntry]
    path_triggers: list[ModelPathTrigger] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shared_modules_in_adjacency(self) -> ModelAdjacencyMap:
        for shared in self.shared_modules:
            if shared not in self.adjacency:
                raise ValueError(f"shared_module '{shared}' has no adjacency entry")
        for module, entry in self.adjacency.items():
            for dep in entry.reverse_deps:
                if dep not in self.adjacency:
                    raise ValueError(
                        f"adjacency['{module}'].reverse_deps references unknown module '{dep}'"
                    )
        return self


def load_adjacency_map(path: Path) -> ModelAdjacencyMap:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return ModelAdjacencyMap.model_validate(raw)
