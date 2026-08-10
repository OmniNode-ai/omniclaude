# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for the delegate-only consumer plugin surface (OMN-14688, epic OMN-14686).

Operator directive (2026-08-09): "only expose one plug-in and that is delegate."
The marketplace/plugin.json manifest schema has no per-skill allowlist, so
scoping the CONSUMER-facing plugin to delegate-only required a second,
physically-slim plugin source (`plugins/onex-delegate/`) rather than an
in-place filter on `plugins/onex/`. This test proves:

  1. Both consumer marketplace.json copies source ONLY the slim plugin, with
     matching (reconciled) versions -- closing the OMN-15496-class drift
     (root 1.0.0 vs plugins/ 1.1.0) that existed before this ticket.
  2. `plugins/onex-delegate/` ships exactly one skill (delegate), zero hooks,
     zero agents -- the Phase 1 exit gate from OMN-14688's original scope.
  3. The internal/dev skill tree (`plugins/onex/`, 100+ skills) is preserved
     on disk and reachable via a SEPARATE, non-consumer marketplace file
     (`plugins/onex-dev-marketplace/`) so local dev sessions do not lose
     access to onex:merge_sweep / onex:dod_sweep / etc. -- only the
     consumer-facing `onex@omninode-tools` install is scoped down.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

ROOT_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SCOPED_MARKETPLACE = PLUGINS_DIR / ".claude-plugin" / "marketplace.json"
DEV_MARKETPLACE = (
    PLUGINS_DIR / "onex-dev-marketplace" / ".claude-plugin" / "marketplace.json"
)

DELEGATE_PLUGIN_DIR = PLUGINS_DIR / "onex-delegate"
DEV_PLUGIN_DIR = PLUGINS_DIR / "onex"


def _load(path: Path) -> dict:
    assert path.exists(), f"expected manifest at {path}"
    return json.loads(path.read_text())


class TestConsumerMarketplaceIsDelegateOnly:
    def test_root_marketplace_has_exactly_one_plugin(self) -> None:
        manifest = _load(ROOT_MARKETPLACE)
        assert len(manifest["plugins"]) == 1, (
            "consumer marketplace must expose exactly one plugin (delegate-only "
            "directive, OMN-14688)"
        )

    def test_root_marketplace_sources_slim_plugin(self) -> None:
        manifest = _load(ROOT_MARKETPLACE)
        assert manifest["plugins"][0]["source"] == "./plugins/onex-delegate", (
            "root marketplace.json must source the slim onex-delegate plugin, "
            "not the full plugins/onex dev tree"
        )

    def test_scoped_marketplace_has_exactly_one_plugin(self) -> None:
        manifest = _load(SCOPED_MARKETPLACE)
        assert len(manifest["plugins"]) == 1

    def test_scoped_marketplace_sources_slim_plugin(self) -> None:
        manifest = _load(SCOPED_MARKETPLACE)
        assert manifest["plugins"][0]["source"] == "./onex-delegate"

    def test_both_marketplace_copies_have_matching_versions(self) -> None:
        """Closes the drifted-duplicate gap (root 1.0.0 vs plugins/ 1.1.0)."""
        root = _load(ROOT_MARKETPLACE)
        scoped = _load(SCOPED_MARKETPLACE)
        assert root["version"] == scoped["version"], (
            f"marketplace.json copies must not drift: root={root['version']!r} "
            f"scoped={scoped['version']!r}"
        )

    def test_both_marketplace_plugin_entries_have_matching_versions(self) -> None:
        root = _load(ROOT_MARKETPLACE)
        scoped = _load(SCOPED_MARKETPLACE)
        assert root["plugins"][0]["version"] == scoped["plugins"][0]["version"]

    def test_root_marketplace_also_declares_requires_onex_cli(self) -> None:
        """CodeRabbit (PR #1979): root marketplace.json previously omitted
        `requires.onex_cli`, so a root-sourced install could drift from the
        declared omnibase-core CLI pin unnoticed -- only the scoped copy had
        it. Both copies must declare and agree on the pin.
        """
        root = _load(ROOT_MARKETPLACE)
        scoped = _load(SCOPED_MARKETPLACE)
        root_cli = root["plugins"][0]["requires"]["onex_cli"]
        scoped_cli = scoped["plugins"][0]["requires"]["onex_cli"]
        assert root_cli["min_version"] == scoped_cli["min_version"]
        assert root_cli["package"] == scoped_cli["package"] == "omnibase-core"


class TestSlimPluginShipsDelegateOnly:
    def test_plugin_json_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / ".claude-plugin" / "plugin.json").exists()

    def test_exactly_one_skill_directory(self) -> None:
        skills_dir = DELEGATE_PLUGIN_DIR / "skills"
        assert skills_dir.exists(), f"missing {skills_dir}"
        skill_dirs = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
        assert skill_dirs == ["delegate"], (
            f"onex-delegate must ship exactly one skill (delegate), found: {skill_dirs}"
        )

    def test_delegate_skill_md_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / "skills" / "delegate" / "SKILL.md").exists()

    def test_zero_hooks(self) -> None:
        assert not (DELEGATE_PLUGIN_DIR / "hooks").exists(), (
            "onex-delegate must ship zero hooks (Phase 1 exit gate, OMN-14688)"
        )
        assert not (DELEGATE_PLUGIN_DIR / "hooks.json").exists()

    def test_zero_agents(self) -> None:
        assert not (DELEGATE_PLUGIN_DIR / "agents").exists(), (
            "onex-delegate must ship zero agents (Phase 1 exit gate, OMN-14688)"
        )

    def test_plugin_compat_yaml_present(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / "plugin-compat.yaml").exists()


class TestInternalDevSurfacePreserved:
    """Verify the delegate-only directive scoped the CONSUMER plugin, not dev
    tooling: the full skill tree stays on disk and reachable via a distinct,
    non-consumer marketplace name so local sessions do not lose skills.
    """

    def test_full_dev_skill_tree_still_on_disk(self) -> None:
        skills_dir = DEV_PLUGIN_DIR / "skills"
        assert skills_dir.exists()
        skill_dirs = [p for p in skills_dir.iterdir() if p.is_dir()]
        assert len(skill_dirs) > 50, (
            "plugins/onex (internal dev tree) must retain its full skill set "
            "-- the delegate-only directive scopes the consumer marketplace "
            "only, per operator note in OMN-14688"
        )

    def test_dev_marketplace_exists_and_is_distinct_from_consumer(self) -> None:
        dev = _load(DEV_MARKETPLACE)
        consumer = _load(SCOPED_MARKETPLACE)
        assert dev["name"] != consumer["name"], (
            "dev marketplace must use a distinct marketplace name so "
            "`claude plugin marketplace update omninode-tools` (the consumer "
            "path) never touches or advertises the full dev tree"
        )

    def test_dev_marketplace_sources_full_onex_tree(self) -> None:
        dev = _load(DEV_MARKETPLACE)
        # "../onex" (parent-directory escape) is rejected by `claude plugin
        # marketplace add` as invalid input -- source must be a forward-relative
        # path within the marketplace's own directory. "./onex" is a tracked
        # symlink (plugins/onex-dev-marketplace/onex -> ../onex) that resolves
        # to the same physical files without a literal ".." in the manifest.
        assert dev["plugins"][0]["source"] == "./onex"

    def test_dev_marketplace_onex_symlink_resolves_to_full_tree(self) -> None:
        symlink_path = PLUGINS_DIR / "onex-dev-marketplace" / "onex"
        assert symlink_path.is_symlink(), f"expected a symlink at {symlink_path}"
        resolved = symlink_path.resolve()
        assert resolved == DEV_PLUGIN_DIR.resolve(), (
            f"onex-dev-marketplace/onex must resolve to plugins/onex, got {resolved}"
        )
