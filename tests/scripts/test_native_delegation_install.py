# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Real installer, isolated from the operator's profile.

Catch classic/mod double registration, stale cache, destructive merges,
non-idempotent install, and native enablement surviving OFF.

The upgrade/repeat/OFF journey needs a real Claude Code CLI and real registry
and skips, saying so, on a host without one. The installer's registration
itself (the exact plugin install call and the marketplace and plugin it points
at) is checked with a stub CLI, so it runs everywhere.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = "onex-delegation@onex-delegation-local"


def test_contracted_prepare_retry_keeps_the_same_plugin_identity(
    tmp_path: Path,
) -> None:
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_native_delegation import (
        HandlerNativeDelegation,
    )
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_native_delegation import (
        ModelNativeDelegationRequest,
    )

    plugin = tmp_path / "plugin/plugins/onex"
    (plugin / "hooks/lib").mkdir(parents=True)
    request = ModelNativeDelegationRequest(
        operation="prepare",
        install_root=tmp_path,
        claude_settings=tmp_path / "profile/settings.json",
        python_bin=sys.executable,
    )
    handler = HandlerNativeDelegation()
    handler.handle(request)
    manifest = plugin / ".claude-plugin/plugin.json"
    first = manifest.read_bytes()
    handler.handle(request)
    assert manifest.read_bytes() == first


GUARD = {"hooks": [{"type": "command", "command": "/unrelated/guard.sh"}]}


def _stub_claude(
    bin_dir: Path, calls: Path, install_exit: int = 0, on_install: str = ""
) -> None:
    """A claude CLI stand-in: logs each call's arguments; plugin install exits as told.

    A failing install first writes to the profile, as a vendor writer that dies
    part way would, so a test can tell a restore from an untouched file.
    ``on_install`` is a bash snippet run in the plugin install branch before it exits.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    claude = bin_dir / "claude"
    claude.write_text(
        "#!/bin/bash\n"
        'case "$*" in *--version*) echo "claude 2.1.326-stub"; exit 0;; esac\n'
        f'for a in "$@"; do printf "[%s]" "$a"; done >> "{calls}"; echo >> "{calls}"\n'
        'if [[ "$*" == *"plugin install"* ]]; then\n'
        f"  if [ {install_exit} -ne 0 ]; then\n"
        '    echo "{\\"partial\\": true}" > "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"\n'
        '    echo "stub: plugin install failed" >&2\n'
        "  fi\n"
        f"  {on_install}\n"
        f"  exit {install_exit}\n"
        "fi\n"
        "exit 0\n"
    )
    claude.chmod(0o755)


def _run_stub_install(
    home: Path, bin_dir: Path, python: str = sys.executable, *extra: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            "--apply",
            "--skip-pip",
            "--skip-smoke",
            "--python",
            python,
            *extra,
        ],
        env={"HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.unit
@pytest.mark.parametrize("had_settings", [True, False])
def test_failed_plugin_install_leaves_settings_exactly_as_they_were(
    tmp_path: Path, had_settings: bool
) -> None:
    """A vendor install failure must not strand the user without delegation.

    The old owned rows are removed before Claude's installer runs; when that
    installer fails, settings.json is put back byte for byte (or removed again
    if it did not exist), the installer exits non-zero naming the failure, and
    no rollback manifest claims an install that did not happen.
    """
    home = tmp_path / "home"
    profile = home / ".claude"
    profile.mkdir(parents=True)
    install_root = home / ".omninode/delegation"
    settings = profile / "settings.json"
    if had_settings:
        legacy = f"{install_root}/plugin/plugins/onex/hooks/scripts/pre_tool_use_delegation.sh"
        # Compact on purpose: any rewrite by the installer changes these bytes.
        settings.write_text(
            json.dumps(
                {
                    "model": "keep",
                    "hooks": {
                        "UserPromptSubmit": [
                            GUARD,
                            {"hooks": [{"type": "command", "command": legacy}]},
                        ]
                    },
                },
                separators=(",", ":"),
            )
        )
    before = settings.read_bytes() if had_settings else None
    calls = tmp_path / "calls.log"
    _stub_claude(tmp_path / "bin", calls, install_exit=1)

    result = _run_stub_install(home, tmp_path / "bin")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "[plugin][install]" in calls.read_text(), "the vendor installer never ran"
    assert (settings.read_bytes() if settings.exists() else None) == before
    assert "Claude's plugin installer failed" in result.stderr, result.stderr
    assert "restored" in result.stderr, result.stderr
    assert not (install_root / "rollback-manifest.json").exists()


def _classic_install(home: Path, extra_hooks: dict | None = None) -> Path:
    """A command-hook install made before the native port, with its script on disk."""
    profile = home / ".claude"
    profile.mkdir(parents=True)
    root = home / ".omninode/delegation"
    script = root / "plugin/plugins/onex/hooks/scripts/pre_tool_use_delegation.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/bash\n# classic delegation hook\nexit 0\n")
    script.chmod(0o755)
    row = {
        "hooks": [
            {"type": "command", "command": f"ONEX_DELEGATION_HOOK=prompts {script}"}
        ]
    }
    (root / "hooks-delegation.json").write_text(
        json.dumps({"hooks": {"UserPromptSubmit": [row]}})
    )
    settings = profile / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "model": "keep",
                "hooks": {"UserPromptSubmit": [GUARD, row], **(extra_hooks or {})},
            }
        )
    )
    (root / "rollback-manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "install_root": str(root),
                "claude_settings": str(settings),
                "settings_backup": None,
                "installed_hook_config": str(root / "hooks-delegation.json"),
                "package": "omninode-claude",
            }
        )
    )
    return root


def _tree(root: Path) -> dict[str, bytes | None]:
    """Every path under the install root, file bytes or None for a folder.

    bifrost_overrides.yaml is the endpoint overlay, written before registration
    and kept on every run, and backups/ is the installer's own folder; neither
    is part of what a failed registration undoes. Files left in backups/ count.
    """
    return {
        str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
        for p in sorted(root.rglob("*"))
        if p.name != "bifrost_overrides.yaml" and p != root / "backups"
    }


@pytest.mark.unit
def test_failed_plugin_install_leaves_the_install_tree_and_a_working_uninstall(
    tmp_path: Path,
) -> None:
    """A classic install whose upgrade fails in Claude's installer must stay a
    classic install: hooks-delegation.json, plugin/ and the marketplace files
    as they were, so a later --uninstall takes the classic path and removes
    the classic rows instead of deleting plugin/ under a row that still runs."""
    home = tmp_path / "home"
    root = _classic_install(home)
    settings = home / ".claude/settings.json"
    before_tree, before_settings = _tree(root), settings.read_bytes()
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log", install_exit=1)

    failed = _run_stub_install(home, bin_dir)

    assert failed.returncode != 0, failed.stdout + failed.stderr
    assert "restored" in failed.stderr, failed.stderr
    assert settings.read_bytes() == before_settings
    assert _tree(root) == before_tree

    _stub_claude(bin_dir, tmp_path / "calls.log")
    removed = subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            "--uninstall",
            "--python",
            sys.executable,
        ],
        env={"HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert removed.returncode == 0, removed.stdout + removed.stderr
    commands = [
        h["command"]
        for groups in json.loads(settings.read_text())["hooks"].values()
        for g in groups
        for h in g["hooks"]
    ]
    assert commands == ["/unrelated/guard.sh"], commands


@pytest.mark.unit
@pytest.mark.parametrize("step", ["merge-fails", "terminated-during-claude"])
def test_an_interrupted_install_restores_settings_and_removes_its_snapshot(
    tmp_path: Path, step: str
) -> None:
    """A run that stops between the settings snapshot and a successful Claude
    install, by an error under set -e or by a signal, must leave settings.json,
    the install tree and the backups folder as they were before the run."""
    home = tmp_path / "home"
    # A non-group entry makes the settings merge raise after the snapshot.
    root = _classic_install(
        home, {"Stop": ["not-a-group"]} if step == "merge-fails" else None
    )
    settings = home / ".claude/settings.json"
    before_tree, before_settings = _tree(root), settings.read_bytes()
    on_install = ""
    if step == "terminated-during-claude":
        # Strip the profile as a vendor writer would, then stop the installer.
        on_install = "echo '{}' > \"$HOME/.claude/settings.json\"; kill -TERM $PPID"
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log", on_install=on_install)

    result = _run_stub_install(home, bin_dir)

    assert result.returncode != 0, result.stdout + result.stderr
    if step == "terminated-during-claude":
        assert "[plugin][install]" in (tmp_path / "calls.log").read_text()
    assert settings.read_bytes() == before_settings
    assert _tree(root) == before_tree
    assert not list((root / "backups").glob("*.run.*"))


@pytest.mark.unit
def test_removing_an_owned_row_keeps_non_ascii_values_as_written(
    tmp_path: Path,
) -> None:
    """The merge cannot rewrite JSON and keep the user's whitespace, so when an
    owned row is removed only the formatting changes (two-space indent); every
    value, non-ASCII included, is kept as written, not escaped. A file holding
    no owned row is never rewritten."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    root = home / ".omninode/delegation"
    owned = {
        "hooks": [
            {
                "type": "command",
                "command": f"{root}/plugin/plugins/onex/hooks/scripts/pre_tool_use_delegation.sh",
            }
        ]
    }
    settings = home / ".claude/settings.json"
    settings.write_bytes(
        json.dumps(
            {"model": "kept-é→✓", "hooks": {"UserPromptSubmit": [GUARD, owned]}},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    )
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")

    result = _run_stub_install(home, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    expected = {"model": "kept-é→✓", "hooks": {"UserPromptSubmit": [GUARD]}}
    assert (
        settings.read_bytes()
        == (json.dumps(expected, indent=2, ensure_ascii=False) + "\n").encode()
    )


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("already_removed", [False, True])
def test_native_install_upgrade_repeat_and_off(
    tmp_path: Path, legacy: bool, already_removed: bool, monkeypatch
):
    if not shutil.which("claude"):
        pytest.skip(
            "needs a real Claude Code CLI on PATH; the installer's registration call "
            "is covered without one by "
            "test_installer_registers_the_native_plugin_through_claude_cli"
        )
    home = tmp_path / "home"
    profile = home / ".claude"
    profile.mkdir(parents=True)
    install_root = home / ".omninode/delegation"
    settings = {
        "model": "preserve-model",
        "hooks": {"UserPromptSubmit": [GUARD]},
        "enabledPlugins": {"unrelated@market": True},
    }
    if legacy:
        settings["hooks"]["UserPromptSubmit"].extend(
            [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{install_root}/plugin/plugins/onex/hooks/scripts/pre_tool_use_delegation.sh",
                        }
                    ]
                },
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{install_root}/plugin/plugins/onex/hooks/lib/delegation_hook_runner.py --history-only",
                        }
                    ]
                },
            ]
        )
    path = profile / "settings.json"
    path.write_text(json.dumps(settings))
    env = {
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(profile),
        "PATH": os.environ["PATH"],
        "DISABLE_AUTOUPDATER": "1",
    }

    def run(action):
        result = subprocess.run(
            [
                "bash",
                str(ROOT / "scripts/install-delegation.sh"),
                action,
                "--skip-pip",
                "--skip-smoke",
                "--python",
                sys.executable,
            ],
            env=env,
            cwd=home,
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
        assert result.returncode == 0, (result.stdout + result.stderr)[-5000:]
        return json.loads(path.read_text())

    first = run("--apply")
    assert first.get("enabledPlugins", {}).get(PLUGIN) is True
    assert first["model"] == "preserve-model"
    assert first["enabledPlugins"]["unrelated@market"] is True
    assert first["hooks"]["UserPromptSubmit"] == [GUARD]
    registry = json.loads((profile / "plugins/installed_plugins.json").read_text())
    rows = registry["plugins"][PLUGIN]
    assert len(rows) == 1 and rows[0]["scope"] == "user"
    loaded = Path(rows[0]["installPath"])
    assert loaded.is_relative_to(profile)
    assert json.loads((loaded / "hooks/hooks.json").read_text()) == {
        "modules": ["./lib/native_delegation_mod.js"]
    }
    assert (loaded / "hooks/lib/native_delegation_mod.js").read_bytes() == (
        ROOT / "src/index.ts"
    ).read_bytes()
    runtime = json.loads((loaded / "hooks/delegation-runtime.json").read_text())
    assert runtime["python"] == sys.executable
    # Consumer readiness and tamper refusal belong to omnimarket's real CLI
    # lifecycle suite; this package's lock also supports older consumers.
    assert run("--apply") == first
    if already_removed:
        removed = subprocess.run(
            ["claude", "plugin", "uninstall", PLUGIN, "--scope", "user", "--json"],
            env=env,
            cwd=home,
            capture_output=True,
            text=True,
            check=False,
        )
        assert removed.returncode == 0, removed.stderr
    stopped = run("--uninstall")
    assert run("--uninstall") == stopped
    assert stopped.get("enabledPlugins", {}).get(PLUGIN) is not True
    assert stopped["model"] == "preserve-model"
    assert stopped["enabledPlugins"]["unrelated@market"] is True
    assert stopped["hooks"]["UserPromptSubmit"] == [GUARD]
    assert "onex-delegation-local" not in stopped.get("extraKnownMarketplaces", {})
    known = json.loads((profile / "plugins/known_marketplaces.json").read_text())
    assert "onex-delegation-local" not in known


_NO_OMNIMARKET = """\
import sys


class _NoOmnimarket:
    @staticmethod
    def find_spec(name, path=None, target=None):
        if name == "omnimarket" or name.startswith("omnimarket."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


sys.meta_path.insert(0, _NoOmnimarket)
"""


@pytest.mark.unit
@pytest.mark.parametrize("action", ["--uninstall", "--pause"])
def test_classic_install_rolls_back_without_omnimarket(
    tmp_path: Path, action: str
) -> None:
    """A classic (command-hook) install made before the native port must still
    roll back on a host where omnimarket is not importable: the old uninstall
    had no such dependency. --pause keeps the history helper row, as before."""
    home = tmp_path / "home"
    profile = home / ".claude"
    profile.mkdir(parents=True)
    root = home / ".omninode/delegation"
    root.mkdir(parents=True)
    scripts = f"{root}/plugin/plugins/onex/hooks"
    owned = {
        "UserPromptSubmit": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"ONEX_DELEGATION_HOOK=prompts {scripts}/scripts/pre_tool_use_delegation.sh",
                        "timeout": 300,
                    }
                ]
            },
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{sys.executable} {scripts}/lib/delegation_hook_runner.py --history-only 2>/dev/null || true",
                        "timeout": 10,
                    }
                ]
            },
        ],
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": f"{scripts}/scripts/session-start.sh",
                    }
                ]
            }
        ],
    }
    (root / "hooks-delegation.json").write_text(json.dumps({"hooks": owned}))
    settings = profile / "settings.json"
    hooks = {
        "UserPromptSubmit": [GUARD, *owned["UserPromptSubmit"]],
        "SessionStart": owned["SessionStart"],
    }
    settings.write_text(json.dumps({"model": "keep", "hooks": hooks}))
    (root / "rollback-manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "install_root": str(root),
                "claude_settings": str(settings),
                "settings_backup": None,
                "installed_hook_config": str(root / "hooks-delegation.json"),
                "package": "omninode-claude",
            }
        )
    )
    blocker = tmp_path / "no-omnimarket"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(_NO_OMNIMARKET)
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(blocker)}
    probe = subprocess.run(
        [sys.executable, "-c", "import omnimarket"],
        env=env,
        capture_output=True,
        check=False,
    )
    assert probe.returncode != 0, "the scenario needs omnimarket not importable"

    result = subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            action,
            "--python",
            sys.executable,
        ],
        env=env,
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    after = json.loads(settings.read_text())
    assert after["model"] == "keep"
    commands = [
        h["command"]
        for groups in after["hooks"].values()
        for g in groups
        for h in g["hooks"]
    ]
    kept = [c for c in commands if str(root) in c]
    if action == "--pause":
        assert (
            len(kept) == 1 and "delegation_hook_runner.py --history-only" in kept[0]
        ), kept
    else:
        assert kept == [], kept
        assert not (root / "hooks-delegation.json").exists()
    assert "/unrelated/guard.sh" in commands


@pytest.mark.unit
def test_installer_registers_the_native_plugin_through_claude_cli(
    tmp_path: Path,
) -> None:
    """Registration without a real CLI: the installer makes exactly one user-scope
    plugin install call naming its own marketplace, and that marketplace holds
    the native plugin (module-only hooks.json, the shipped mod, an absolute
    interpreter binding) the call installs."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    root = home / ".omninode/delegation"
    calls = tmp_path / "calls.log"
    _stub_claude(tmp_path / "bin", calls)

    result = _run_stub_install(home, tmp_path / "bin")

    assert result.returncode == 0, result.stdout + result.stderr
    installs = [line for line in calls.read_text().splitlines() if "[install]" in line]
    assert installs == [
        f"[--setting-sources][][plugin][install][onex-delegation]"
        f"[--marketplace][{root}][--scope][user][--json]"
    ], installs
    market = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    assert market["name"] == "onex-delegation-local"
    assert market["plugins"] == [
        {"name": "onex-delegation", "source": "./plugin/plugins/onex"}
    ]
    plugin = root / "plugin/plugins/onex"
    assert (
        json.loads((plugin / ".claude-plugin/plugin.json").read_text())["name"]
        == "onex-delegation"
    )
    assert json.loads((plugin / "hooks/hooks.json").read_text()) == {
        "modules": ["./lib/native_delegation_mod.js"]
    }
    assert (plugin / "hooks/lib/native_delegation_mod.js").read_bytes() == (
        ROOT / "src/index.ts"
    ).read_bytes()
    runtime = json.loads((plugin / "hooks/delegation-runtime.json").read_text())
    assert runtime == {"python": sys.executable}
    owned = json.loads((root / "hooks-delegation.json").read_text())
    assert owned["entrypoint"] == "native" and owned["plugin_id"] == PLUGIN
    manifest = json.loads((root / "rollback-manifest.json").read_text())
    assert manifest["entrypoint"] == "native"
    assert manifest["claude_settings"] == str(home / ".claude/settings.json")


@pytest.mark.unit
@pytest.mark.parametrize(
    "planted",
    [
        "hooks-delegation.json",
        ".claude-plugin",
        ".claude-plugin/marketplace.json",
        "plugin/plugins/onex/.claude-plugin",
        "plugin/plugins/onex/.claude-plugin/plugin.json",
        "plugin/plugins/onex/hooks/hooks.json",
        "plugin/plugins/onex/hooks/delegation-runtime.json",
        "plugin/plugins/onex/hooks/lib/native_delegation_mod.js",
    ],
)
def test_prepare_refuses_a_symlink_planted_at_an_owned_path(
    tmp_path: Path, planted: str
) -> None:
    """A symlink at a fixed path under the install root must not redirect the
    write to its target; prepare refuses before writing anything."""
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.handler_native_delegation import (
        HandlerNativeDelegation,
    )
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_native_delegation import (
        ModelNativeDelegationRequest,
    )

    root = tmp_path / "root"
    (root / "plugin/plugins/onex/hooks/lib").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    victim = outside / "victim.json"
    victim.write_text("victim original\n")
    link = root / planted
    link.parent.mkdir(parents=True, exist_ok=True)
    is_dir = not planted.endswith((".json", ".js"))
    link.symlink_to(outside if is_dir else victim, target_is_directory=is_dir)
    request = ModelNativeDelegationRequest(
        operation="prepare",
        install_root=root,
        claude_settings=tmp_path / "profile/settings.json",
        python_bin=sys.executable,
    )

    with pytest.raises(ValueError, match="symlink"):
        HandlerNativeDelegation().handle(request)

    assert victim.read_text() == "victim original\n"
    assert sorted(p.name for p in outside.iterdir()) == ["victim.json"]
    written = [
        p for p in root.rglob("*") if p.is_file() and not p.is_symlink() and p != link
    ]
    assert written == [], written


@pytest.mark.unit
@pytest.mark.parametrize("spelling", ["bare", "relative"])
def test_installer_binds_an_absolute_interpreter(tmp_path: Path, spelling: str) -> None:
    """native_delegation_mod.js refuses a non-absolute python binding, so --python
    given as a bare name or a relative path must be bound as an absolute path,
    or every delegated prompt silently stays with Claude."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")
    folder = bin_dir if spelling == "bare" else home / "tools"
    folder.mkdir(parents=True, exist_ok=True)
    wrapper = folder / "python-fixture"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    wrapper.chmod(0o755)
    given = "python-fixture" if spelling == "bare" else "./tools/python-fixture"

    result = _run_stub_install(home, bin_dir, given)

    assert result.returncode == 0, result.stdout + result.stderr
    runtime = json.loads(
        (
            home
            / ".omninode/delegation/plugin/plugins/onex/hooks/delegation-runtime.json"
        ).read_text()
    )
    assert runtime == {"python": str(wrapper)}
