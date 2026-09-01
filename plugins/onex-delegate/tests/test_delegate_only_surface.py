# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""TDD tests for the slim consumer plugin surface (OMN-14688, OMN-17354).

The marketplace/plugin.json manifest schema has no per-skill allowlist, so
scoping the CONSUMER-facing plugin to a physically-slim source
(`plugins/onex-delegate/`) rather than an in-place filter on `plugins/onex/`
keeps internal tooling out of customer installs. This test proves:

  1. Both consumer marketplace.json copies source ONLY the slim plugin, with
     matching (reconciled) versions -- closing the OMN-15496-class drift
     (root 1.0.0 vs plugins/ 1.1.0) that existed before this ticket.
  2. `plugins/onex-delegate/` ships exactly the customer delegation siblings:
     `delegate` (customer-local) and `cloud_delegate` (dashboard-key gateway),
     plus zero hooks and zero agents. OMN-17354 adds the cloud sibling required
     for beta U4 without exposing the internal/dev skill tree.
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


class TestConsumerMarketplaceIsSlim:
    def test_root_marketplace_has_exactly_one_plugin(self) -> None:
        manifest = _load(ROOT_MARKETPLACE)
        assert len(manifest["plugins"]) == 1, (
            "consumer marketplace must expose exactly one slim plugin (OMN-14688)"
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
        declared CLI pin unnoticed -- only the scoped copy had it. Both copies
        must declare and agree on the pin.

        OMN-16041: the expected package is read from plugin-compat.yaml (the
        declared source of truth) instead of being hardcoded here. The old
        hardcoded "omnibase-core" was the defect -- it pinned this test to a
        package that does not provide the plugin's only command.
        """
        import yaml

        compat = yaml.safe_load(
            (DELEGATE_PLUGIN_DIR / "plugin-compat.yaml").read_text()
        )["onex_cli"]
        root = _load(ROOT_MARKETPLACE)
        scoped = _load(SCOPED_MARKETPLACE)
        root_cli = root["plugins"][0]["requires"]["onex_cli"]
        scoped_cli = scoped["plugins"][0]["requires"]["onex_cli"]
        assert root_cli["min_version"] == scoped_cli["min_version"]
        assert root_cli["package"] == scoped_cli["package"] == compat["package"]


class TestSlimPluginShipsCustomerDelegationSkills:
    def test_plugin_json_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / ".claude-plugin" / "plugin.json").exists()

    def test_exactly_the_customer_delegation_skill_directories(self) -> None:
        skills_dir = DELEGATE_PLUGIN_DIR / "skills"
        assert skills_dir.exists(), f"missing {skills_dir}"
        skill_dirs = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
        assert skill_dirs == ["cloud_delegate", "delegate"], (
            "onex-delegate must ship only the customer delegation siblings "
            f"(delegate, cloud_delegate), found: {skill_dirs}"
        )

    def test_delegate_skill_md_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / "skills" / "delegate" / "SKILL.md").exists()

    def test_cloud_delegate_skill_files_exist(self) -> None:
        cloud_skill_dir = DELEGATE_PLUGIN_DIR / "skills" / "cloud_delegate"
        assert (cloud_skill_dir / "SKILL.md").exists()
        assert (cloud_skill_dir / "prompt.md").exists()

    def test_cloud_delegate_is_the_canonical_thin_shim(self) -> None:
        """The published copy must not drift into its own transport implementation."""
        source = DEV_PLUGIN_DIR / "skills" / "cloud_delegate"
        shipped = DELEGATE_PLUGIN_DIR / "skills" / "cloud_delegate"
        for name in ("SKILL.md", "prompt.md"):
            assert (shipped / name).read_text() == (source / name).read_text(), (
                f"{name} must stay byte-identical to the canonical cloud_delegate "
                "skill; update both through the shared thin-shim contract"
            )

    def test_cloud_delegate_keeps_dashboard_key_and_gateway_boundaries(self) -> None:
        skill_text = (
            DELEGATE_PLUGIN_DIR / "skills" / "cloud_delegate" / "SKILL.md"
        ).read_text()
        prompt_text = (
            DELEGATE_PLUGIN_DIR / "skills" / "cloud_delegate" / "prompt.md"
        ).read_text()
        published_text = f"{skill_text}\n{prompt_text}"

        for required in (
            "onex cloud delegate",
            "onxk_",
            "--api-key-stdin",
            "result.txt",
            "receipt.json",
            "run.json",
        ):
            assert required in published_text
        for forbidden in ("ANTHROPIC_API_KEY", "api.anthropic.com", "curl "):
            assert forbidden not in published_text, (
                f"published cloud_delegate must not introduce {forbidden!r}"
            )

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
    """Verify slim consumer scoping does not expose or delete dev
    tooling: the full skill tree stays on disk and reachable via a distinct,
    non-consumer marketplace name so local sessions do not lose skills.
    """

    def test_full_dev_skill_tree_still_on_disk(self) -> None:
        skills_dir = DEV_PLUGIN_DIR / "skills"
        assert skills_dir.exists()
        skill_dirs = [p for p in skills_dir.iterdir() if p.is_dir()]
        assert len(skill_dirs) > 50, (
            "plugins/onex (internal dev tree) must retain its full skill set "
            "-- the slim consumer package scopes the marketplace only"
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
