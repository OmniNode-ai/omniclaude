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
     `delegate` (customer-local) only, plus zero hooks and zero agents
     (OMN-19965: `cloud_delegate` lives in the internal dev tree, not here).
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


class TestSlimPluginShipsDelegateOnly:
    def test_plugin_json_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / ".claude-plugin" / "plugin.json").exists()

    def test_exactly_one_skill_directory(self) -> None:
        skills_dir = DELEGATE_PLUGIN_DIR / "skills"
        assert skills_dir.exists(), f"missing {skills_dir}"
        skill_dirs = sorted(p.name for p in skills_dir.iterdir() if p.is_dir())
        assert skill_dirs == ["delegate"], (
            "the published plugin ships exactly one skill, `delegate` "
            f"(OMN-19965); found: {skill_dirs}"
        )

    def test_a_planted_second_skill_folder_is_detected(self, tmp_path: Path) -> None:
        """Positive control: the listing used above sees a planted folder."""
        (tmp_path / "delegate").mkdir()
        (tmp_path / "planted").mkdir()
        assert sorted(p.name for p in tmp_path.iterdir() if p.is_dir()) != ["delegate"]

    def test_delegate_skill_md_exists(self) -> None:
        assert (DELEGATE_PLUGIN_DIR / "skills" / "delegate" / "SKILL.md").exists()

    def test_skill_md_documents_the_one_time_permission_rule(self) -> None:
        text = (DELEGATE_PLUGIN_DIR / "skills" / "delegate" / "SKILL.md").read_text()
        assert "Bash(onex delegate:*)" in text, (
            "SKILL.md must tell the developer which permission rule stops the "
            "prompt on every call"
        )

    def test_manifests_do_not_advertise_a_second_skill(self) -> None:
        for path in (
            ROOT_MARKETPLACE,
            SCOPED_MARKETPLACE,
            DELEGATE_PLUGIN_DIR / ".claude-plugin" / "plugin.json",
        ):
            text = path.read_text()
            assert "cloud_delegate" not in text, f"{path} names cloud_delegate"
            assert "exactly two" not in text, f"{path} says two skills"

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


# --- OMN-22272: the default install is locked to delegate alone ----------------
#
# `plugins/distribution_manifest.yaml` carries a top-level `plugins:` list, one
# row per marketplace entry with name, marketplace, source and default_install.
# These checks make "the default install holds one skill" a tested rule, so a
# skill moved between packages later cannot join it unnoticed.

MANIFEST = PLUGINS_DIR / "distribution_manifest.yaml"
CONSUMER_MARKETPLACE = "omninode-tools"
DEV_MARKETPLACE_NAME = "omninode-tools-dev"
DELEGATE_SOURCE = "plugins/onex-delegate"
DEV_SOURCE = "plugins/onex"
FORBIDDEN_SURFACE_DIRS = ("hooks", "agents", "commands")


def _manifest() -> dict:
    import yaml

    assert MANIFEST.exists(), f"expected manifest at {MANIFEST}"
    return yaml.safe_load(MANIFEST.read_text())


def _plugin_rows() -> list[dict]:
    rows = _manifest().get("plugins")
    assert rows, f"{MANIFEST} has no top-level `plugins:` list (OMN-22272)"
    return rows


def _marketplace_source_dir(marketplace_file: Path, source: str) -> Path:
    """A marketplace source is relative to the directory holding .claude-plugin/."""
    return (marketplace_file.parent.parent / source).resolve()


def _assert_one_skill_and_no_extra_surface(plugin_dir: Path) -> None:
    skills = sorted(plugin_dir.rglob("SKILL.md"))
    assert len(skills) == 1, (
        f"the default install holds exactly one SKILL.md under {plugin_dir}; "
        f"found {len(skills)}: {[str(s.relative_to(plugin_dir)) for s in skills]}"
    )
    for name in FORBIDDEN_SURFACE_DIRS:
        assert not (plugin_dir / name).exists(), (
            f"the default install ships no {name} directory: {plugin_dir / name}"
        )


def _assert_single_default_install(rows: list[dict]) -> None:
    default_rows = [r for r in rows if r.get("default_install") is True]
    assert len(default_rows) == 1, (
        f"exactly one plugins: row has default_install true; found "
        f"{[(r.get('name'), r.get('marketplace')) for r in default_rows]}"
    )
    row = default_rows[0]
    assert (row["name"], row["marketplace"], row["source"]) == (
        "onex",
        CONSUMER_MARKETPLACE,
        DELEGATE_SOURCE,
    ), f"the one default_install row must be onex in omninode-tools; got {row}"


class TestDefaultInstallLockedToDelegate:
    def test_manifest_has_plugins_list(self) -> None:
        rows = _plugin_rows()
        for row in rows:
            assert {"name", "marketplace", "source", "default_install"} <= set(row), (
                f"plugins: row missing a field: {row}"
            )
            assert isinstance(row["default_install"], bool), row

    def test_consumer_marketplace_files_agree_on_plugin_names_and_directory(
        self,
    ) -> None:
        root = _load(ROOT_MARKETPLACE)
        scoped = _load(SCOPED_MARKETPLACE)
        assert sorted(p["name"] for p in root["plugins"]) == sorted(
            p["name"] for p in scoped["plugins"]
        )
        root_dirs = {
            p["name"]: _marketplace_source_dir(ROOT_MARKETPLACE, p["source"])
            for p in root["plugins"]
        }
        scoped_dirs = {
            p["name"]: _marketplace_source_dir(SCOPED_MARKETPLACE, p["source"])
            for p in scoped["plugins"]
        }
        assert root_dirs == scoped_dirs, (
            "the two omninode-tools marketplace files must resolve each plugin "
            f"to the same directory: root={root_dirs} scoped={scoped_dirs}"
        )

    def test_manifest_rows_match_the_consumer_marketplace_entries(self) -> None:
        consumer_rows = {
            (r["name"], r["source"])
            for r in _plugin_rows()
            if r["marketplace"] == CONSUMER_MARKETPLACE
        }
        root = _load(ROOT_MARKETPLACE)
        assert consumer_rows == {
            (
                p["name"],
                _marketplace_source_dir(ROOT_MARKETPLACE, p["source"])
                .relative_to(REPO_ROOT)
                .as_posix(),
            )
            for p in root["plugins"]
        }

    def test_tree_behind_consumer_entry_holds_one_skill_and_no_extra_surface(
        self,
    ) -> None:
        root = _load(ROOT_MARKETPLACE)
        for entry in root["plugins"]:
            _assert_one_skill_and_no_extra_surface(
                _marketplace_source_dir(ROOT_MARKETPLACE, entry["source"])
            )

    def test_second_skill_in_a_copy_of_onex_delegate_is_refused(
        self, tmp_path: Path
    ) -> None:
        """Fixture case: the one-SKILL.md assertion is red on a planted second skill."""
        import shutil

        copy = tmp_path / "onex-delegate"
        shutil.copytree(
            DELEGATE_PLUGIN_DIR, copy, ignore=shutil.ignore_patterns("tests")
        )
        _assert_one_skill_and_no_extra_surface(
            copy
        )  # positive control: clean copy passes
        (copy / "skills" / "second").mkdir()
        (copy / "skills" / "second" / "SKILL.md").write_text("---\nname: second\n---\n")
        with pytest.raises(AssertionError, match=r"exactly one SKILL\.md"):
            _assert_one_skill_and_no_extra_surface(copy)

    def test_planted_hooks_directory_is_refused(self, tmp_path: Path) -> None:
        import shutil

        copy = tmp_path / "onex-delegate"
        shutil.copytree(
            DELEGATE_PLUGIN_DIR, copy, ignore=shutil.ignore_patterns("tests")
        )
        (copy / "hooks").mkdir()
        with pytest.raises(AssertionError, match="no hooks directory"):
            _assert_one_skill_and_no_extra_surface(copy)

    def test_default_install_is_exactly_the_delegate_row(self) -> None:
        _assert_single_default_install(_plugin_rows())

    def test_default_install_dev_onex_row_is_false(self) -> None:
        dev_rows = [
            r
            for r in _plugin_rows()
            if r["marketplace"] == DEV_MARKETPLACE_NAME and r["name"] == "onex"
        ]
        assert len(dev_rows) == 1
        assert dev_rows[0]["source"] == DEV_SOURCE
        assert dev_rows[0]["default_install"] is False

    def test_default_install_second_true_row_is_refused(self) -> None:
        rows = [dict(r) for r in _plugin_rows()]
        _assert_single_default_install(rows)  # positive control
        for row in rows:
            if row["marketplace"] == DEV_MARKETPLACE_NAME:
                row["default_install"] = True
        with pytest.raises(AssertionError, match="exactly one"):
            _assert_single_default_install(rows)

    def test_default_install_zero_true_rows_is_refused(self) -> None:
        rows = [{**r, "default_install": False} for r in _plugin_rows()]
        with pytest.raises(AssertionError, match="exactly one"):
            _assert_single_default_install(rows)

    def test_no_omni_component_is_stable(self) -> None:
        components = _manifest()["components"]
        omni_owned = [c for c in components if c.get("owning_package") == "omni"]
        stable_omni = [c["id"] for c in omni_owned if c.get("exposure") == "stable"]
        assert stable_omni == [], (
            f"no component owned by package omni may be stable: {stable_omni}"
        )
        planted = [
            *components,
            {"id": "x", "owning_package": "omni", "exposure": "stable"},
        ]
        assert [
            c["id"]
            for c in planted
            if c.get("owning_package") == "omni" and c.get("exposure") == "stable"
        ] == ["x"], "positive control: the filter sees a planted stable omni component"
