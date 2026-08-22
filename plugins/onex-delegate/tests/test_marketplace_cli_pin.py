# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for marketplace `onex` CLI version pin (OMN-8799, SD-12).

Verifies the plugin declares a pinned `onex` CLI version and that the pin is
consistent across the three manifest surfaces that must agree:

  1. plugins/onex-delegate/plugin-compat.yaml       → `min_runtime_version`
  2. plugins/onex-delegate/.claude-plugin/plugin.json → `requires.onex_cli.min_version`
  3. plugins/.claude-plugin/marketplace.json          → `plugins[0].requires.onex_cli.min_version`

This prevents the "plugin says 0.39.0, marketplace says 0.38.0, runtime says 0.40.0"
drift class that the plan (§ 7) explicitly flags as a BF-5 risk.

SCOPE WARNING (OMN-16041). These are MANIFEST-CONSISTENCY tests: they prove the
three surfaces agree with each other, and nothing more. They passed for months
against a pin that named the wrong package and could not install a runnable
`onex delegate` on any combination of published wheels. Consistency is not
installability -- test_install_works.py is the test that proves the declared
pins actually produce a working command, and it must never be deleted in favour
of these.

Relocated from plugins/onex/tests/ under OMN-14688: the consumer-facing
marketplace entry now sources plugins/onex-delegate (delegate-only), not
plugins/onex (the full internal dev tree), so the pin's source of truth moved
with it. plugins/onex/plugin-compat.yaml remains the compat surface for the
internal dev tree and is unaffected by this file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

PLUGIN_DIR = Path(__file__).parent.parent
REPO_PLUGINS_DIR = PLUGIN_DIR.parent

#: The package that registers the `delegate` subcommand into the `onex.cli`
#: entry-point group. NOT the package that ships the `onex` executable.
DELEGATE_PROVIDER = "omnibase-infra"
#: The package whose [project.scripts] ships the `onex` executable itself.
CONSOLE_SCRIPT_PROVIDER = "omnibase-core"

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
        assert onex_cli.get("package") == DELEGATE_PROVIDER, (
            "`package` must name the package that provides the `delegate` "
            "SUBCOMMAND. That is omnibase-infra "
            '([project.entry-points."onex.cli"] delegate = '
            "omnibase_infra.cli.cli_delegate:delegate_command), NOT omnibase-core "
            "-- omnibase-core alone yields `Error: No such command 'delegate'` "
            "(OMN-16041)."
        )
        assert isinstance(onex_cli.get("min_version"), str)
        assert onex_cli["min_version"], "min_version must be non-empty"

    def test_onex_cli_names_the_console_script_provider(
        self, plugin_manifest: dict
    ) -> None:
        """Both packages are required, and each must be named separately.

        omnibase-core ships the `onex` executable; omnibase-infra ships the
        subcommand. Declaring only one of them is the OMN-16041 defect.
        """
        onex_cli = plugin_manifest["requires"]["onex_cli"]
        assert onex_cli.get("console_script_package") == CONSOLE_SCRIPT_PROVIDER
        assert onex_cli.get("console_script_min_version")

    def test_install_hint_installs_both_packages(self, plugin_manifest: dict) -> None:
        """An install hint naming only one package cannot produce a working CLI.

        This is the assertion the pre-OMN-16041 suite lacked: it checked that
        three manifests agreed with each other, which they did -- on a hint that
        could never install a runnable `onex delegate`.
        """
        onex_cli = plugin_manifest["requires"]["onex_cli"]
        for key in ("install_hint", "install_hint_pipx"):
            hint = onex_cli.get(key, "")
            assert DELEGATE_PROVIDER in hint, (
                f"{key} must install {DELEGATE_PROVIDER} (provides `delegate`)"
            )
            assert CONSOLE_SCRIPT_PROVIDER in hint, (
                f"{key} must install {CONSOLE_SCRIPT_PROVIDER} (provides `onex`)"
            )
        assert "pipx" in onex_cli["install_hint_pipx"]

    def test_install_hint_is_not_cwd_dependent(self, plugin_manifest: dict) -> None:
        """`uv run onex` resolves the CURRENT directory's project venv.

        It therefore only works inside a repo that co-installs omnibase-infra and
        fails from anywhere else -- so it may never appear in an install hint
        (OMN-16041 F3).
        """
        onex_cli = plugin_manifest["requires"]["onex_cli"]
        for key in ("install_hint", "install_hint_pipx"):
            assert "uv run" not in onex_cli.get(key, ""), (
                f"{key} must not use `uv run` -- it is cwd-dependent"
            )
        assert onex_cli.get("cwd_independent") is True


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

    def test_install_hint_installs_both_packages(
        self, marketplace_manifest: dict
    ) -> None:
        onex_entry = next(
            p for p in marketplace_manifest["plugins"] if p["name"] == "onex"
        )
        onex_cli = onex_entry["requires"]["onex_cli"]
        for key in ("install_hint", "install_hint_pipx"):
            hint = onex_cli.get(key, "")
            assert DELEGATE_PROVIDER in hint and CONSOLE_SCRIPT_PROVIDER in hint
            assert "uv run" not in hint
        assert "pipx" in onex_cli["install_hint_pipx"]


class TestCrossManifestConsistency:
    """The pin must be identical across all three manifest surfaces."""

    def test_compat_yaml_declares_onex_cli_block(self, compat: dict) -> None:
        assert "onex_cli" in compat, (
            "plugin-compat.yaml must declare an `onex_cli` block (OMN-8799 SD-12). "
            "It is the source of truth for the CLI pin consumed by plugin.json "
            "and marketplace.json."
        )
        onex_cli = compat["onex_cli"]
        assert onex_cli.get("package") == DELEGATE_PROVIDER
        assert onex_cli.get("console_script_package") == CONSOLE_SCRIPT_PROVIDER
        assert isinstance(onex_cli.get("min_version"), str)
        assert onex_cli["min_version"], "onex_cli.min_version must be non-empty"

    def test_compat_yaml_keys_are_flat(self, compat: dict) -> None:
        """session_start_onex_cli_pin_check.sh parses this block with awk.

        A nested mapping under onex_cli would make that state machine read the
        wrong `min_version`, so every value here must be a scalar.
        """
        for key, value in compat["onex_cli"].items():
            assert not isinstance(value, (dict, list)), (
                f"onex_cli.{key} must be a scalar -- the SessionStart hook parses "
                f"this block with awk, not a YAML parser"
            )

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
