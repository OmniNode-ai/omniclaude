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
import shutil
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).parent.parent.parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

ROOT_MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
SCOPED_MARKETPLACE = PLUGINS_DIR / ".claude-plugin" / "marketplace.json"
DEV_MARKETPLACE = (
    PLUGINS_DIR / "onex-dev-marketplace" / ".claude-plugin" / "marketplace.json"
)

DISTRIBUTION_MANIFEST = PLUGINS_DIR / "distribution_manifest.yaml"

DELEGATE_PLUGIN_DIR = PLUGINS_DIR / "onex-delegate"
DEV_PLUGIN_DIR = PLUGINS_DIR / "onex"

CONSUMER_MARKETPLACE_NAME = "omninode-tools"
DEV_MARKETPLACE_NAME = "omninode-tools-dev"


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


# ---------------------------------------------------------------------------
# OMN-22272 (T1 of the plugin-surface retirement plan): the default plugin
# surface is a tested rule. `plugins:` in distribution_manifest.yaml lists one
# row per marketplace entry; exactly one is the default install, and the tree
# behind it holds exactly one SKILL.md and no hooks, agents or commands.
# ---------------------------------------------------------------------------

# (marketplace file, directory its relative `source` values resolve against)
_CONSUMER_MARKETPLACES = (
    (ROOT_MARKETPLACE, REPO_ROOT),
    (SCOPED_MARKETPLACE, PLUGINS_DIR),
)
_FORBIDDEN_COMPONENT_DIRS = ("hooks", "agents", "commands")


def _plugin_rows() -> list[dict]:
    manifest = yaml.safe_load(DISTRIBUTION_MANIFEST.read_text())
    assert "plugins" in manifest, (
        "plugins/distribution_manifest.yaml must carry a top-level `plugins:` "
        "list, one row per marketplace entry (OMN-22272)"
    )
    return manifest["plugins"]


def _default_install_rows(rows: list[dict]) -> list[dict]:
    return [row for row in rows if row.get("default_install") is True]


def _entry_tree_problems(tree: Path) -> list[str]:
    """Reasons `tree` is not a delegate-alone plugin tree (empty when it is)."""
    problems: list[str] = []
    skill_files = sorted(
        str(p.relative_to(tree)) for p in tree.rglob("SKILL.md") if p.is_file()
    )
    if len(skill_files) != 1:
        problems.append(f"expected exactly one SKILL.md, found {skill_files}")
    for name in _FORBIDDEN_COMPONENT_DIRS:
        if (tree / name).exists():
            problems.append(f"{name}/ must not exist in the default install tree")
    return problems


class TestDefaultPluginSurfaceLocked:
    def test_plugins_list_exists(self) -> None:
        rows = _plugin_rows()
        assert rows, "plugins: list must not be empty"
        for row in rows:
            assert {"name", "marketplace", "source", "default_install"} <= set(row), (
                f"plugins row missing a required key: {row}"
            )
            assert isinstance(row["default_install"], bool), row

    def test_exactly_one_default_install_row_and_it_is_the_consumer_entry(
        self,
    ) -> None:
        defaults = _default_install_rows(_plugin_rows())
        assert len(defaults) == 1, (
            f"exactly one plugins row may have default_install true, found {defaults}"
        )
        row = defaults[0]
        assert row["name"] == "onex"
        assert row["marketplace"] == CONSUMER_MARKETPLACE_NAME
        assert row["source"] == "plugins/onex-delegate"

    def test_dev_marketplace_onex_row_is_not_default_install(self) -> None:
        dev_rows = [
            row
            for row in _plugin_rows()
            if row["marketplace"] == DEV_MARKETPLACE_NAME and row["name"] == "onex"
        ]
        assert len(dev_rows) == 1, f"expected one dev onex row, found {dev_rows}"
        assert dev_rows[0]["default_install"] is False

    def test_second_default_install_row_is_detected(self) -> None:
        """Positive control for the default_install count: a planted second
        true row makes the one-row predicate false."""
        rows = [dict(row) for row in _plugin_rows()]
        for row in rows:
            if row["marketplace"] == DEV_MARKETPLACE_NAME:
                row["default_install"] = True
        assert len(_default_install_rows(rows)) != 1

    def test_plugins_rows_match_marketplace_entries(self) -> None:
        """Every plugins row is a real marketplace entry and vice versa."""
        listed = {(r["marketplace"], r["name"]) for r in _plugin_rows()}
        actual = {
            (m["name"], p["name"])
            for m in (
                _load(SCOPED_MARKETPLACE),
                _load(DEV_MARKETPLACE),
            )
            for p in m["plugins"]
        }
        assert listed == actual

    def test_consumer_marketplace_files_agree(self) -> None:
        """The two omninode-tools marketplace files list the same plugin names,
        with sources that resolve to the same directory."""
        resolved: list[dict[str, Path]] = []
        for path, base in _CONSUMER_MARKETPLACES:
            manifest = _load(path)
            assert manifest["name"] == CONSUMER_MARKETPLACE_NAME
            resolved.append(
                {p["name"]: (base / p["source"]).resolve() for p in manifest["plugins"]}
            )
        assert resolved[0] == resolved[1], (
            f"consumer marketplace files disagree: {resolved[0]} vs {resolved[1]}"
        )

    def test_default_install_row_source_matches_the_marketplace_entry(self) -> None:
        (row,) = _default_install_rows(_plugin_rows())
        for path, base in _CONSUMER_MARKETPLACES:
            entry = {p["name"]: p for p in _load(path)["plugins"]}[row["name"]]
            assert (base / entry["source"]).resolve() == (
                REPO_ROOT / row["source"]
            ).resolve()

    def test_default_install_tree_holds_exactly_one_skill_and_no_components(
        self,
    ) -> None:
        (row,) = _default_install_rows(_plugin_rows())
        assert _entry_tree_problems(REPO_ROOT / row["source"]) == []

    def test_a_second_skill_in_a_copy_of_onex_delegate_is_red(
        self, tmp_path: Path
    ) -> None:
        """Fixture case: copy onex-delegate, add a second SKILL.md, and the
        one-SKILL.md assertion must refuse the copy (the clean copy passes)."""
        copy = tmp_path / "onex-delegate"
        shutil.copytree(
            DELEGATE_PLUGIN_DIR, copy, ignore=shutil.ignore_patterns("tests")
        )
        assert _entry_tree_problems(copy) == [], "positive control: clean copy passes"
        (copy / "skills" / "second").mkdir()
        (copy / "skills" / "second" / "SKILL.md").write_text("---\nname: second\n---\n")
        problems = _entry_tree_problems(copy)
        assert any("exactly one SKILL.md" in p for p in problems), problems

    @pytest.mark.parametrize("directory", _FORBIDDEN_COMPONENT_DIRS)
    def test_a_forbidden_component_directory_in_a_copy_is_red(
        self, tmp_path: Path, directory: str
    ) -> None:
        copy = tmp_path / "onex-delegate"
        shutil.copytree(
            DELEGATE_PLUGIN_DIR, copy, ignore=shutil.ignore_patterns("tests")
        )
        (copy / directory).mkdir()
        assert any(directory in p for p in _entry_tree_problems(copy))

    def test_no_omni_component_is_stable(self) -> None:
        manifest = yaml.safe_load(DISTRIBUTION_MANIFEST.read_text())
        offenders = [
            c["id"]
            for c in manifest["components"]
            if c.get("owning_package") == "omni" and c.get("exposure") == "stable"
        ]
        assert offenders == [], f"owning_package omni must never be stable: {offenders}"
