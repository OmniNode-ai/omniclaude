# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for marketplace `onex` CLI version pin (OMN-8799, SD-12).

Verifies the plugin declares a pinned `onex` CLI version and that the pin is
consistent across the three manifest surfaces that must agree:

  1. plugins/onex/plugin-compat.yaml       → `min_runtime_version`
  2. plugins/onex/.claude-plugin/plugin.json → `requires.onex_cli.min_version`
  3. plugins/.claude-plugin/marketplace.json → `plugins[0].requires.onex_cli.min_version`

This prevents the "plugin says 0.39.0, marketplace says 0.38.0, runtime says 0.40.0"
drift class that the plan (§ 7) explicitly flags as a BF-5 risk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

PLUGIN_DIR = Path(__file__).parent.parent
REPO_PLUGINS_DIR = PLUGIN_DIR.parent

COMPAT_YAML = PLUGIN_DIR / "plugin-compat.yaml"
PLUGIN_JSON = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = REPO_PLUGINS_DIR / ".claude-plugin" / "marketplace.json"


@pytest.fixture(scope="module")
def compat() -> dict:
    assert COMPAT_YAML.exists(), f"plugin-compat.yaml missing at {COMPAT_YAML}"
    return yaml.safe_load(COMPAT_YAML.read_text())


@pytest.fixture(scope="module")
def plugin_manifest() -> dict:
    assert PLUGIN_JSON.exists(), f"plugin.json missing at {PLUGIN_JSON}"
    return json.loads(PLUGIN_JSON.read_text())


@pytest.fixture(scope="module")
def marketplace_manifest() -> dict:
    assert MARKETPLACE_JSON.exists(), f"marketplace.json missing at {MARKETPLACE_JSON}"
    return json.loads(MARKETPLACE_JSON.read_text())


class TestPluginRequiresOnexCli:
    def test_requires_block_present(self, plugin_manifest: dict) -> None:
        assert "requires" in plugin_manifest, (
            "plugin.json must declare a top-level `requires` block (OMN-8799 SD-12)"
        )

    def test_onex_cli_block_present(self, plugin_manifest: dict) -> None:
        assert "onex_cli" in plugin_manifest["requires"], (
            "plugin.json `requires` must include `onex_cli` (OMN-8799 SD-12)"
        )

    def test_onex_cli_has_package_pin(self, plugin_manifest: dict) -> None:
        onex_cli = plugin_manifest["requires"]["onex_cli"]
        assert onex_cli.get("package") == "omnibase-core", (
            "onex CLI ships with `omnibase-core` per plan § 4.4"
        )
        assert isinstance(onex_cli.get("min_version"), str)
        assert onex_cli["min_version"], "min_version must be non-empty"

    def test_onex_cli_has_install_hint(self, plugin_manifest: dict) -> None:
        hint = plugin_manifest["requires"]["onex_cli"].get("install_hint", "")
        assert "pipx" in hint, (
            "install_hint should point at `pipx install omnibase-core` "
            "(MVP path per plan § 4.4)"
        )
        assert "omnibase-core" in hint


class TestMarketplaceRequiresOnexCli:
    def test_plugins_entry_declares_requires(self, marketplace_manifest: dict) -> None:
        plugins = marketplace_manifest.get("plugins", [])
        assert plugins, "marketplace.json must declare at least one plugin"
        onex_entry = next((p for p in plugins if p.get("name") == "onex"), None)
        assert onex_entry is not None, (
            "marketplace.json must contain an `onex` plugin entry"
        )
        assert "requires" in onex_entry, (
            "marketplace `onex` plugin entry must declare `requires` (OMN-8799 SD-12)"
        )
        assert "onex_cli" in onex_entry["requires"]

    def test_install_hint_uses_pipx(self, marketplace_manifest: dict) -> None:
        onex_entry = next(
            p for p in marketplace_manifest["plugins"] if p["name"] == "onex"
        )
        hint = onex_entry["requires"]["onex_cli"].get("install_hint", "")
        assert "pipx" in hint and "omnibase-core" in hint


class TestCrossManifestConsistency:
    """The pin must be identical across all three manifest surfaces."""

    def test_compat_yaml_declares_onex_cli_block(self, compat: dict) -> None:
        assert "onex_cli" in compat, (
            "plugin-compat.yaml must declare an `onex_cli` block (OMN-8799 SD-12). "
            "It is the source of truth for the CLI pin consumed by plugin.json "
            "and marketplace.json."
        )
        onex_cli = compat["onex_cli"]
        assert onex_cli.get("package") == "omnibase-core"
        assert isinstance(onex_cli.get("min_version"), str)
        assert onex_cli["min_version"], "onex_cli.min_version must be non-empty"

    def test_plugin_pin_matches_compat_yaml(
        self, compat: dict, plugin_manifest: dict
    ) -> None:
        compat_min = compat["onex_cli"]["min_version"]
        plugin_min = plugin_manifest["requires"]["onex_cli"]["min_version"]
        assert plugin_min == compat_min, (
            f"plugin.json onex_cli.min_version ({plugin_min}) must match "
            f"plugin-compat.yaml onex_cli.min_version ({compat_min})"
        )

    def test_marketplace_pin_matches_compat_yaml(
        self, compat: dict, marketplace_manifest: dict
    ) -> None:
        compat_min = compat["onex_cli"]["min_version"]
        onex_entry = next(
            p for p in marketplace_manifest["plugins"] if p["name"] == "onex"
        )
        market_min = onex_entry["requires"]["onex_cli"]["min_version"]
        assert market_min == compat_min, (
            f"marketplace.json onex_cli.min_version ({market_min}) must match "
            f"plugin-compat.yaml onex_cli.min_version ({compat_min})"
        )

    def test_packages_match_across_surfaces(
        self,
        compat: dict,
        plugin_manifest: dict,
        marketplace_manifest: dict,
    ) -> None:
        compat_pkg = compat["onex_cli"]["package"]
        plugin_pkg = plugin_manifest["requires"]["onex_cli"]["package"]
        onex_entry = next(
            p for p in marketplace_manifest["plugins"] if p["name"] == "onex"
        )
        market_pkg = onex_entry["requires"]["onex_cli"]["package"]
        assert compat_pkg == plugin_pkg == market_pkg, (
            f"onex_cli.package must be identical across surfaces: "
            f"compat={compat_pkg}, plugin={plugin_pkg}, marketplace={market_pkg}"
        )

    def test_marketplace_source_of_truth_points_at_compat_yaml(
        self, marketplace_manifest: dict
    ) -> None:
        onex_entry = next(
            p for p in marketplace_manifest["plugins"] if p["name"] == "onex"
        )
        sot = onex_entry["requires"]["onex_cli"].get("source_of_truth", "")
        assert "plugin-compat.yaml" in sot, (
            "marketplace `requires.onex_cli.source_of_truth` must point at "
            "plugin-compat.yaml so future editors know where to update the pin"
        )
