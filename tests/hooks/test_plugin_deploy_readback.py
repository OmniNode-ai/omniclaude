# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the truthful plugin-deploy readback [OMN-15274].

RED-first against exists-but-wrong. The surface that existed before this ticket
is not missing -- it is present, plausible, and wrong: reading
``installed_plugins.json`` returns a real directory containing a real
``hooks.json``, so "is this hook deployed?" gets a confident answer from a tree
Claude Code has not opened in weeks.

The fixture registry in ``fixtures/plugin_registry_dead_cache/`` reproduces that
exactly, in the real ``installed_plugins.json`` shape:

* the recorded ``installPath`` points at a **dead cache** carrying
  ``hooks.json`` v1.3.0 that registers ``subagent_stop_report_contract_guard.sh``;
* the **resolved** load path (directory-source marketplace -> the clone) carries
  ``hooks.json`` v1.6.0 that does **not** register that guard;
* a second registry entry records a Linux ``installPath`` that exists nowhere on
  this machine.

RED anchor: :func:`test_red_old_read_reports_the_guard_deployed_from_a_dead_tree`
drives ``naive_registry_load_path`` -- the pre-OMN-15274 read -- and asserts it
reports the guard as deployed. That assertion passes, and that is the defect.
GREEN anchor: :func:`test_truthful_readback_reports_the_guard_absent_for_every_agent_class`
drives the same fixture through ``build_readback`` and gets the opposite,
correct answer plus a loud ``LOAD_PATH_MISMATCH``.

Everything is hermetic: a throwaway ``CLAUDE_HOME``, a throwaway git clone with
its own bare origin. No network, no ``~/.claude`` read, no lane touched.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from plugin_deploy_readback import (  # noqa: E402
    DEFAULT_PLUGIN_ID,
    EnumReadbackTripwire,
    EnumSeverity,
    build_readback,
    main,
    naive_registry_load_path,
    read_hooks_config,
    read_registry_entries,
    render_text,
    resolve_load_path,
)

pytestmark = pytest.mark.unit

_FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "plugin_registry_dead_cache"

_REPORT_CONTRACT_GUARD = "subagent_stop_report_contract_guard.sh"
_SECRET_LEAK_GUARD = "subagent_stop_secret_leak_guard.sh"


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------


def _git(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "readback-test",
            "GIT_AUTHOR_EMAIL": "readback@test.invalid",
            "GIT_COMMITTER_NAME": "readback-test",
            "GIT_COMMITTER_EMAIL": "readback@test.invalid",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
        },
    )


def _write_hook_scripts(plugin_root: pathlib.Path, hooks_json: dict) -> None:
    """Materialize an executable stub for every command registered in hooks.json."""
    scripts_dir = plugin_root / "hooks" / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    for blocks in hooks_json["hooks"].values():
        for block in blocks:
            for hook in block["hooks"]:
                name = os.path.basename(hook["command"])
                target = scripts_dir / name
                target.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
                target.chmod(0o755)


def _build_plugin_tree(root: pathlib.Path, hooks_fixture: str) -> dict:
    """Create ``<root>/hooks/hooks.json`` + executable stubs from a fixture file."""
    hooks_json = json.loads((_FIXTURES / hooks_fixture).read_text(encoding="utf-8"))
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "hooks" / "hooks.json").write_text(
        json.dumps(hooks_json, indent=2), encoding="utf-8"
    )
    _write_hook_scripts(root, hooks_json)
    return hooks_json


@pytest.fixture
def dead_cache_workstation(tmp_path: pathlib.Path) -> dict[str, pathlib.Path]:
    """A workstation whose plugin registry points at a dead cache.

    Returns the CLAUDE_HOME, the resolved load path (inside a real git clone
    with a real upstream), and the cache tree the registry names.
    """
    claude_home = tmp_path / "claude_home"
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"

    # --- upstream + clone: the directory-source marketplace root ---------
    origin.mkdir(parents=True)
    _git(origin, "init", "--bare", "--initial-branch=dev", ".")
    clone.mkdir(parents=True)
    _git(clone, "init", "--initial-branch=dev", ".")
    _git(clone, "remote", "add", "origin", str(origin))

    (clone / ".claude-plugin").mkdir(parents=True)
    (clone / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "omninode-tools",
                "plugins": [{"name": "onex", "source": "./plugins/onex"}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    live_root = clone / "plugins" / "onex"
    live_root.mkdir(parents=True)
    _build_plugin_tree(live_root, "live_hooks.json")

    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "live plugin tree")
    _git(clone, "push", "-q", "origin", "dev")
    _git(clone, "branch", "--set-upstream-to=origin/dev", "dev")

    # --- the dead cache the registry records -----------------------------
    cache_root = claude_home / "plugins" / "cache" / "omninode-tools" / "onex" / "2.3.1"
    cache_root.mkdir(parents=True)
    _build_plugin_tree(cache_root, "cache_hooks.json")

    # --- registry files, real shape, placeholders substituted ------------
    plugins_dir = claude_home / "plugins"
    for name, subs in (
        ("known_marketplaces.json", {"__CLONE_ROOT__": str(clone)}),
        ("installed_plugins.json", {"__CACHE_INSTALL_PATH__": str(cache_root)}),
    ):
        text = (_FIXTURES / name).read_text(encoding="utf-8")
        for token, value in subs.items():
            text = text.replace(token, value)
        (plugins_dir / name).write_text(text, encoding="utf-8")

    return {
        "claude_home": claude_home,
        "clone": clone,
        "origin": origin,
        "live_root": live_root,
        "cache_root": cache_root,
    }


def _registered_script_names(config) -> set[str]:
    return {os.path.basename(r.command) for r in config.registrations}


# ---------------------------------------------------------------------------
# RED anchor -- the pre-OMN-15274 read, and why it is wrong
# ---------------------------------------------------------------------------


def test_red_old_read_reports_the_guard_deployed_from_a_dead_tree(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """RED: the registry read returns a real tree, a real version, a wrong answer.

    This is the exists-but-wrong surface. It resolves, it parses, it reports
    ``subagent_stop_report_contract_guard.sh`` as registered and EXEC-OK, and
    every one of those facts is about a directory that does not execute.
    """
    home = dead_cache_workstation["claude_home"]

    recorded = naive_registry_load_path(home, DEFAULT_PLUGIN_ID)
    assert recorded == str(dead_cache_workstation["cache_root"])
    assert recorded != str(dead_cache_workstation["live_root"])

    old_verdict = read_hooks_config(pathlib.Path(recorded))
    assert old_verdict.exists, (
        "the dead cache is readable -- that is what makes it a trap"
    )
    assert old_verdict.version == "1.3.0"

    guard = [
        r
        for r in old_verdict.registrations
        if os.path.basename(r.command) == _REPORT_CONTRACT_GUARD
    ]
    assert guard, "old read finds the guard registered..."
    assert guard[0].exec_ok, "...and executable, so the old verdict is 'deployed'"

    # The same read is blind to what actually runs.
    assert _SECRET_LEAK_GUARD not in _registered_script_names(old_verdict)


# ---------------------------------------------------------------------------
# GREEN -- the truthful readback
# ---------------------------------------------------------------------------


def test_truthful_readback_resolves_the_clone_not_the_recorded_cache(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    resolution = resolve_load_path(
        dead_cache_workstation["claude_home"], DEFAULT_PLUGIN_ID
    )
    assert resolution.ok
    assert resolution.resolved_root == str(dead_cache_workstation["live_root"])
    assert resolution.source_type == "directory"
    assert resolution.install_location == str(dead_cache_workstation["clone"])
    assert resolution.plugin_source == "./plugins/onex"


def test_truthful_readback_reports_the_guard_absent_for_every_agent_class(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """GREEN: same fixture, opposite (correct) answer, for all three classes."""
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)

    assert rb.live_hooks is not None
    assert rb.live_hooks.version == "1.6.0"
    assert _REPORT_CONTRACT_GUARD not in _registered_script_names(rb.live_hooks)
    assert _SECRET_LEAK_GUARD in _registered_script_names(rb.live_hooks)

    assert {c.agent_class for c in rb.per_agent_class} == {
        "main_session",
        "task_subagent",
        "workflow_subagent",
    }
    for cls in rb.per_agent_class:
        names = {os.path.basename(r.command) for r in cls.active}
        assert _REPORT_CONTRACT_GUARD not in names, cls.agent_class
        assert cls.load_path == str(dead_cache_workstation["live_root"])
        assert cls.hooks_json_version == "1.6.0"


def test_per_agent_class_event_applicability(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """Classes share one config; they differ in which events can fire."""
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    by_class = {c.agent_class: c for c in rb.per_agent_class}

    main_events = {r.event for r in by_class["main_session"].active}
    assert "Stop" in main_events
    assert "SubagentStop" not in main_events

    for key in ("task_subagent", "workflow_subagent"):
        events = {r.event for r in by_class[key].active}
        assert "SubagentStop" in events, key
        assert "Stop" not in events, key
        names = {os.path.basename(r.command) for r in by_class[key].active}
        assert _SECRET_LEAK_GUARD in names, key


def test_every_registered_hook_carries_an_exec_ok_check(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    assert rb.live_hooks is not None
    assert rb.live_hooks.registrations
    for reg in rb.live_hooks.registrations:
        assert reg.exec_ok is True
        assert reg.script_path is not None
        assert reg.script_path.startswith(str(dead_cache_workstation["live_root"]))


# ---------------------------------------------------------------------------
# Tripwires
# ---------------------------------------------------------------------------


def _tripwires(rb, kind: EnumReadbackTripwire) -> list:
    return [t for t in rb.tripwires if t.tripwire is kind]


def test_load_path_mismatch_tripwire_fires_loudly(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    fired = _tripwires(rb, EnumReadbackTripwire.LOAD_PATH_MISMATCH)
    assert len(fired) == 1
    assert str(dead_cache_workstation["cache_root"]) in fired[0].detail
    assert str(dead_cache_workstation["live_root"]) in fired[0].detail
    assert "does not execute" in fired[0].detail


def test_nonexistent_recorded_install_path_is_surfaced_not_ignored(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """The Linux ``/home/jonah`` code-review entry -- the second instance."""
    entries = read_registry_entries(dead_cache_workstation["claude_home"])
    code_review = [e for e in entries if e.plugin_id.startswith("code-review@")]
    assert code_review and code_review[0].exists is False

    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    fired = _tripwires(rb, EnumReadbackTripwire.REGISTRY_PATH_MISSING)
    assert any("code-review@claude-plugins-official" in t.detail for t in fired)


def test_cache_drift_is_reported_as_inert_information(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    fired = _tripwires(rb, EnumReadbackTripwire.CACHE_DRIFT)
    assert len(fired) == 1
    assert fired[0].severity is EnumSeverity.INFO
    assert "1.3.0" in fired[0].detail and "1.6.0" in fired[0].detail


def test_resolution_rule_changed_when_resolved_root_moves_into_the_cache(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """If Claude Code ever honors the documented copy semantics, say so loudly."""
    home = dead_cache_workstation["claude_home"]
    cache_root = dead_cache_workstation["cache_root"]
    marketplace_root = cache_root.parent  # .../cache/omninode-tools/onex
    (marketplace_root / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (marketplace_root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "onex", "source": "./2.3.1"}]}),
        encoding="utf-8",
    )
    known = home / "plugins" / "known_marketplaces.json"
    data = json.loads(known.read_text(encoding="utf-8"))
    data["omninode-tools"]["installLocation"] = str(marketplace_root)
    known.write_text(json.dumps(data), encoding="utf-8")

    rb = build_readback(home, fetch=False)
    assert rb.resolution.resolved_root == str(cache_root)
    fired = _tripwires(rb, EnumReadbackTripwire.RESOLUTION_RULE_CHANGED)
    assert fired and all(t.severity is EnumSeverity.ALARM for t in fired)
    assert any("inside the plugin cache" in t.detail for t in fired)
    assert rb.alarms


def test_resolution_rule_changed_when_recorded_and_resolved_agree_with_live_cache(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """Agreement is not reassurance while a divergent cache tree still exists."""
    home = dead_cache_workstation["claude_home"]
    registry = home / "plugins" / "installed_plugins.json"
    data = json.loads(registry.read_text(encoding="utf-8"))
    data["plugins"]["onex@omninode-tools"][0]["installPath"] = str(
        dead_cache_workstation["live_root"]
    )
    registry.write_text(json.dumps(data), encoding="utf-8")

    rb = build_readback(home, fetch=False)
    assert not _tripwires(rb, EnumReadbackTripwire.LOAD_PATH_MISMATCH)
    fired = _tripwires(rb, EnumReadbackTripwire.RESOLUTION_RULE_CHANGED)
    assert fired and fired[0].severity is EnumSeverity.ALARM
    assert "AGREE" in fired[0].detail


def test_missing_hook_script_at_the_load_path_is_an_alarm(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """Registered but not executable = cannot fire, however green CI was."""
    (
        dead_cache_workstation["live_root"] / "hooks" / "scripts" / _SECRET_LEAK_GUARD
    ).unlink()
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)

    fired = _tripwires(rb, EnumReadbackTripwire.HOOK_SCRIPT_MISSING)
    assert fired and fired[0].severity is EnumSeverity.ALARM
    assert _SECRET_LEAK_GUARD in fired[0].detail
    assert rb.live_hooks is not None
    assert any(
        os.path.basename(r.command) == _SECRET_LEAK_GUARD and not r.exec_ok
        for r in rb.live_hooks.registrations
    )


# ---------------------------------------------------------------------------
# Merged-not-deployed / dirty -- the OMN-15244 signal
# ---------------------------------------------------------------------------


def test_merged_not_deployed_signal_when_load_path_tree_is_behind(
    dead_cache_workstation: dict[str, pathlib.Path],
    tmp_path: pathlib.Path,
) -> None:
    """A hook merged upstream is not a live hook: there is no install step."""
    clone = dead_cache_workstation["clone"]
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(dead_cache_workstation["origin"]), str(other))
    (
        other / "plugins" / "onex" / "hooks" / "scripts" / _REPORT_CONTRACT_GUARD
    ).write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "merge the report-contract guard upstream")
    _git(other, "push", "-q", "origin", "dev")
    _git(clone, "fetch", "-q", "origin")

    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)

    assert rb.git is not None and rb.git.behind == 1
    fired = _tripwires(rb, EnumReadbackTripwire.MERGED_NOT_DEPLOYED)
    assert fired and fired[0].severity is EnumSeverity.ALARM
    assert "1 commit(s) behind" in fired[0].detail
    assert "pull --ff-only" in fired[0].detail
    assert rb.alarms


def test_clean_up_to_date_load_path_raises_no_deploy_alarm(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    assert rb.git is not None
    assert rb.git.behind == 0
    assert rb.git.dirty_files == 0
    assert not _tripwires(rb, EnumReadbackTripwire.MERGED_NOT_DEPLOYED)
    assert not _tripwires(rb, EnumReadbackTripwire.DIRTY_LOAD_PATH)


def test_dirty_load_path_tripwire(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """OMN-15273: an uncommitted edit changes enforcement with no commit behind it."""
    hooks_json = dead_cache_workstation["live_root"] / "hooks" / "hooks.json"
    hooks_json.write_text(
        hooks_json.read_text(encoding="utf-8").replace("1.6.0", "1.6.1"),
        encoding="utf-8",
    )
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    assert rb.git is not None and rb.git.dirty_files == 1
    fired = _tripwires(rb, EnumReadbackTripwire.DIRTY_LOAD_PATH)
    assert fired and "corresponds to no commit" in fired[0].detail


def test_no_fetch_marks_the_behind_count_unverified(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    assert rb.git is not None and rb.git.fetched is False
    assert _tripwires(rb, EnumReadbackTripwire.UPSTREAM_UNVERIFIED)


def test_fetch_refreshes_the_behind_count(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """With a local file:// origin the fetch is offline but real."""
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=True)
    assert rb.git is not None and rb.git.fetched is True
    assert not _tripwires(rb, EnumReadbackTripwire.UPSTREAM_UNVERIFIED)


# ---------------------------------------------------------------------------
# Degraded inputs and CLI contract
# ---------------------------------------------------------------------------


def test_unresolvable_marketplace_alarms_rather_than_falling_back_to_the_registry(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """No silent fallback: an unresolvable load path is the loudest answer."""
    home = dead_cache_workstation["claude_home"]
    (home / "plugins" / "known_marketplaces.json").unlink()

    rb = build_readback(home, fetch=False)
    assert rb.resolution.resolved_root is None
    assert rb.live_hooks is None
    assert _tripwires(rb, EnumReadbackTripwire.RESOLUTION_RULE_CHANGED)
    # The registry is still reported, but never promoted to truth.
    assert rb.naive_registry_path == str(dead_cache_workstation["cache_root"])


def test_absent_registry_does_not_break_resolution(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    home = dead_cache_workstation["claude_home"]
    (home / "plugins" / "installed_plugins.json").unlink()
    rb = build_readback(home, fetch=False)
    assert rb.resolution.resolved_root == str(dead_cache_workstation["live_root"])
    assert rb.naive_registry_path is None
    assert not _tripwires(rb, EnumReadbackTripwire.LOAD_PATH_MISMATCH)


def test_cli_json_output_and_exit_codes(
    dead_cache_workstation: dict[str, pathlib.Path],
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = str(dead_cache_workstation["claude_home"])

    rc = main(["--claude-home", home, "--no-fetch", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, "mismatch alone is WARN-level: reported loudly, not fatal"
    assert payload["resolved_load_path"] == str(dead_cache_workstation["live_root"])
    assert payload["naive_registry_install_path"] == str(
        dead_cache_workstation["cache_root"]
    )
    assert payload["live_hooks"]["version"] == "1.6.0"
    assert len(payload["per_agent_class"]) == 3
    assert any(
        t["tripwire"] == EnumReadbackTripwire.LOAD_PATH_MISMATCH.value
        for t in payload["tripwires"]
    )

    rc_strict = main(["--claude-home", home, "--no-fetch", "--strict", "--json"])
    capsys.readouterr()
    assert rc_strict == 3

    rc_missing = main(
        ["--claude-home", str(pathlib.Path(home) / "nope"), "--no-fetch", "--json"]
    )
    capsys.readouterr()
    assert rc_missing == 1


def test_cli_text_render_names_both_paths_and_the_verdict(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    text = render_text(rb)
    assert "RESOLVED LOAD PATH" in text
    assert "NOT the load path" in text
    assert str(dead_cache_workstation["live_root"]) in text
    assert str(dead_cache_workstation["cache_root"]) in text
    assert "VERDICT: OK" in text
    for label in ("main session", "Task()", "Workflow-tool"):
        assert label in text


def test_load_path_outside_a_git_repo_reports_no_deploy_state(
    dead_cache_workstation: dict[str, pathlib.Path],
) -> None:
    """A non-git load path is legal; it just has no behind/dirty signal to give."""
    shutil.rmtree(dead_cache_workstation["clone"] / ".git")
    rb = build_readback(dead_cache_workstation["claude_home"], fetch=False)
    assert rb.git is not None and rb.git.is_repo is False
    assert not _tripwires(rb, EnumReadbackTripwire.MERGED_NOT_DEPLOYED)
    assert rb.live_hooks is not None and rb.live_hooks.version == "1.6.0"
