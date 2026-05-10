# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for delegation_rule_loader."""

from __future__ import annotations

import importlib
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest


def _import_loader() -> Any:
    lib_dir = str(
        Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
    )
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)
    if "delegation_rule_loader" in sys.modules:
        del sys.modules["delegation_rule_loader"]
    return importlib.import_module("delegation_rule_loader")


VALID_YAML = textwrap.dedent("""\
    schema_version: "1.0"
    default_behavior: suggest
    rules:
      - task_class: test
        behavior: auto
        recipient: auto
      - task_class: document
        behavior: auto
        recipient: local-qwen-coder-30b
      - task_class: research
        behavior: suggest
        recipient: local-deepseek-r1-14b
      - task_class: implement
        behavior: "off"
    min_confidence: 0.85
    min_savings_usd: 0.001
""")


@pytest.mark.unit
class TestDelegationRuleLoaderMissingFile:
    def test_returns_none_when_file_missing(self, tmp_path: Path) -> None:
        mod = _import_loader()
        missing = tmp_path / "no-file.yaml"
        loader = mod.DelegationRuleLoader(config_path=missing)
        result = loader.get_rule("test")
        assert result is None


@pytest.mark.unit
class TestDelegationRuleLoaderOffRule:
    def test_off_rule_returns_decision_with_off_behavior(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("implement")
        assert result is not None
        assert result.behavior == "off"

    def test_off_rule_has_no_recipient(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("implement")
        assert result is not None
        assert result.recipient == ""


@pytest.mark.unit
class TestDelegationRuleLoaderAutoRule:
    def test_auto_rule_returns_auto_behavior(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test")
        assert result is not None
        assert result.behavior == "auto"
        assert result.recipient == "auto"

    def test_document_auto_rule_has_named_recipient(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("document")
        assert result is not None
        assert result.behavior == "auto"
        assert result.recipient == "local-qwen-coder-30b"


@pytest.mark.unit
class TestDelegationRuleLoaderSuggestRule:
    def test_suggest_rule_returns_suggest_behavior(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("research")
        assert result is not None
        assert result.behavior == "suggest"

    def test_unknown_class_falls_back_to_default(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("unknown_task_class")
        assert result is not None
        assert result.behavior == "suggest"


@pytest.mark.unit
class TestDelegationRuleLoaderConfidenceGate:
    def test_below_min_confidence_returns_none(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.5)
        assert result is None

    def test_at_min_confidence_returns_decision(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.85)
        assert result is not None

    def test_above_min_confidence_returns_decision(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.99)
        assert result is not None


@pytest.mark.unit
class TestDelegationRuleLoaderSavingsGate:
    def test_below_min_savings_returns_none(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.99, estimated_savings_usd=0.0005)
        assert result is None

    def test_at_min_savings_returns_decision(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.99, estimated_savings_usd=0.001)
        assert result is not None

    def test_no_savings_arg_passes_gate(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)
        result = loader.get_rule("test", confidence=0.99)
        assert result is not None


@pytest.mark.unit
class TestDelegationRuleLoaderMtimeCache:
    def test_file_reloaded_on_mtime_change(self, tmp_path: Path) -> None:
        mod = _import_loader()
        cfg = tmp_path / "delegation-rules.yaml"
        cfg.write_text(VALID_YAML)
        loader = mod.DelegationRuleLoader(config_path=cfg)

        r1 = loader.get_rule("test", confidence=0.99)
        assert r1 is not None

        updated_yaml = VALID_YAML.replace(
            "behavior: auto\n    recipient: auto",
            "behavior: suggest\n    recipient: auto",
        )
        cfg.write_text(updated_yaml)
        import os  # noqa: E401

        new_mtime = cfg.stat().st_mtime + 1
        os.utime(cfg, (new_mtime, new_mtime))

        r2 = loader.get_rule("test", confidence=0.99)
        assert r2 is not None
        assert r2.behavior == "suggest"
