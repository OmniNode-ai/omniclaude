# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Timeout contracts reject ambiguous YAML without importing the runtime."""

from pathlib import Path

import pytest
import yaml

from omniclaude.nodes.node_git_effect.models.model_git_timeout_policy import (
    ModelGitTimeoutPolicy,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "content",
    [
        "error_handling: {}\nerror_handling: {}\n",
        "error_handling:\n  timeouts:\n    binary_probe_timeout_seconds: 5\n"
        "    binary_probe_timeout_seconds: 9\n",
        "defaults: &defaults {push: 60}\nerror_handling:\n  timeouts:\n"
        "    operation_timeout_seconds:\n      <<: *defaults\n      push: 7\n",
    ],
)
def test_duplicate_contract_keys_are_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "contract.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate YAML mapping key"):
        ModelGitTimeoutPolicy.from_contract(path, env={})


def test_loader_does_not_change_pyyaml_global_constructors(tmp_path: Path) -> None:
    before = dict(yaml.SafeLoader.yaml_constructors)
    ModelGitTimeoutPolicy.from_contract(env={})
    assert yaml.SafeLoader.yaml_constructors == before
    assert yaml.safe_load("key: first\nkey: second\n") == {"key": "second"}


@pytest.mark.parametrize("content", ["[]", "!!python/object/apply:os.system ['false']"])
def test_non_mapping_and_unsafe_yaml_are_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "contract.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises((ValueError, yaml.YAMLError)):
        ModelGitTimeoutPolicy.from_contract(path, env={})
