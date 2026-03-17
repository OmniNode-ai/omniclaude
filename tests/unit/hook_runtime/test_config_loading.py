"""Unit tests for HookRuntimeConfig.from_yaml. [OMN-5310]"""
from pathlib import Path

import pytest

from omniclaude.hook_runtime.server import HookRuntimeConfig


@pytest.mark.unit
def test_config_from_yaml(tmp_path: Path) -> None:
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """
delegation_enforcement:
  write_warn_threshold: 5
  read_block_threshold: 20
  bash_readonly_patterns:
    - '^git status'
""",
        encoding="utf-8",
    )
    config = HookRuntimeConfig.from_yaml(str(config_yaml))
    assert config.delegation.write_warn_threshold == 5
    assert config.delegation.read_block_threshold == 20
    assert "^git status" in config.delegation.bash_readonly_patterns


@pytest.mark.unit
def test_config_from_yaml_uses_defaults_for_missing_keys(tmp_path: Path) -> None:
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """
delegation_enforcement:
  write_warn_threshold: 99
""",
        encoding="utf-8",
    )
    config = HookRuntimeConfig.from_yaml(str(config_yaml))
    assert config.delegation.write_warn_threshold == 99
    # All other fields use dataclass defaults
    from omniclaude.hook_runtime.delegation_state import DelegationConfig

    defaults = DelegationConfig()
    assert config.delegation.write_block_threshold == defaults.write_block_threshold
    assert config.delegation.read_warn_threshold == defaults.read_warn_threshold


@pytest.mark.unit
def test_config_from_yaml_empty_file(tmp_path: Path) -> None:
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text("", encoding="utf-8")
    config = HookRuntimeConfig.from_yaml(str(config_yaml))
    # All fields use defaults
    from omniclaude.hook_runtime.delegation_state import DelegationConfig

    defaults = DelegationConfig()
    assert config.delegation.write_warn_threshold == defaults.write_warn_threshold
