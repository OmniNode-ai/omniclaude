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
import signal
import subprocess
import sys
import time
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
    install, by an error under set -e or by a signal during a Claude install
    that then fails, must leave settings.json, the install tree and the backups
    folder as they were before the run."""
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
    _stub_claude(bin_dir, tmp_path / "calls.log", install_exit=1, on_install=on_install)

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


def _spawn_stub_install(
    home: Path, bin_dir: Path, python: str = sys.executable
) -> subprocess.Popen[str]:
    """Start the installer without waiting, in its own session, so a test can
    signal the installer alone (os.kill) or its whole group (os.killpg)."""
    return subprocess.Popen(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            "--apply",
            "--skip-pip",
            "--skip-smoke",
            "--python",
            python,
        ],
        env={"HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        cwd=home,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )


def _wait_until_started(marker: Path, proc: subprocess.Popen[str]) -> None:
    """Block until a stub has written ``marker``; fail if the installer exits first."""
    deadline = time.monotonic() + 60
    while not marker.exists():
        if proc.poll() is not None:
            out, err = proc.communicate()
            raise AssertionError(
                f"installer exited {proc.returncode} first: {out}{err}"
            )
        if time.monotonic() > deadline:
            os.killpg(proc.pid, signal.SIGKILL)
            raise AssertionError(f"{marker.name} never appeared")
        time.sleep(0.05)


def _run_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "backups").glob("*.run.*"))


def _uninstall(
    home: Path, bin_dir: Path, python: str = sys.executable
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            "--uninstall",
            "--python",
            python,
        ],
        env={"HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}/usr/bin:/bin"},
        cwd=home,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def _registered_commands(settings: Path) -> list[str]:
    return [
        h["command"]
        for groups in json.loads(settings.read_text()).get("hooks", {}).values()
        for g in groups
        for h in g["hooks"]
    ]


@pytest.mark.unit
def test_a_signal_while_claude_installs_keeps_an_install_claude_finished(
    tmp_path: Path,
) -> None:
    """bash runs a trap only after the foreground command exits. A TERM that
    arrives while Claude's installer runs must not undo an install Claude then
    finished: Claude has registered the plugin from the new tree, so restoring
    the old tree would leave it pointing at deleted files with no manifest. The
    run keeps its changes, writes its manifest and then exits 143."""
    home = tmp_path / "home"
    root = _classic_install(home)
    settings = home / ".claude/settings.json"
    bin_dir = tmp_path / "bin"
    started = tmp_path / "claude-started"
    _stub_claude(
        bin_dir, tmp_path / "calls.log", on_install=f'touch "{started}"; sleep 3'
    )

    proc = _spawn_stub_install(home, bin_dir)
    _wait_until_started(started, proc)
    os.kill(proc.pid, signal.SIGTERM)  # the installer alone, not the stub
    out, err = proc.communicate(timeout=120)

    assert proc.returncode == 143, out + err
    market = json.loads((root / ".claude-plugin/marketplace.json").read_text())
    assert market["plugins"] == [
        {"name": "onex-delegation", "source": "./plugin/plugins/onex"}
    ]
    assert (root / "plugin/plugins/onex/hooks/hooks.json").is_file()
    assert json.loads((root / "hooks-delegation.json").read_text())["entrypoint"] == (
        "native"
    )
    assert json.loads((root / "rollback-manifest.json").read_text())["entrypoint"] == (
        "native"
    )
    assert _registered_commands(settings) == ["/unrelated/guard.sh"]
    assert _run_files(root) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "next_run", ["claude-succeeds", "claude-fails", "killed-mid-restore-then-fails"]
)
def test_a_run_after_sigkill_restores_the_stale_snapshot_first(
    tmp_path: Path, next_run: str
) -> None:
    """A run killed outright (SIGKILL: no trap runs) leaves the tree stripped
    and its snapshots in backups/. The next run must put that before-state back
    before it snapshots anything: otherwise it saves the half-installed state
    as its own before-state, a failure 'restores' to it, and the old snapshot is
    orphaned. A failing next run therefore ends exactly where the killed run
    started; a succeeding one installs cleanly. Neither leaves a *.run.* behind.
    A restore can itself be killed after putting some paths back: those must
    not then be taken for paths the killed run created and deleted."""
    home = tmp_path / "home"
    root = _classic_install(home)
    settings = home / ".claude/settings.json"
    before_tree, before_settings = _tree(root), settings.read_bytes()
    bin_dir = tmp_path / "bin"
    started = tmp_path / "claude-started"
    _stub_claude(
        bin_dir, tmp_path / "calls.log", on_install=f'touch "{started}"; sleep 60'
    )
    proc = _spawn_stub_install(home, bin_dir)
    _wait_until_started(started, proc)
    os.killpg(proc.pid, signal.SIGKILL)
    proc.communicate(timeout=60)
    # The state kill -9 leaves: the old rows gone, the old tree moved aside.
    assert _run_files(root), "the killed run left no snapshot; nothing to test"
    assert settings.read_bytes() != before_settings
    if next_run == "killed-mid-restore-then-fails":
        # What a restore killed after moving plugin/ back leaves behind.
        (snapshot,) = (root / "backups").glob("install-tree.run.*")
        shutil.rmtree(root / "plugin")
        (snapshot / "plugin").rename(root / "plugin")

    _stub_claude(
        bin_dir,
        tmp_path / "calls.log",
        install_exit=0 if next_run == "claude-succeeds" else 1,
    )
    result = _run_stub_install(home, bin_dir)

    if next_run != "claude-succeeds":
        assert result.returncode != 0, result.stdout + result.stderr
        assert settings.read_bytes() == before_settings
        assert _tree(root) == before_tree
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert _registered_commands(settings) == ["/unrelated/guard.sh"]
        assert (root / ".claude-plugin/marketplace.json").is_file()
        owned = json.loads((root / "hooks-delegation.json").read_text())
        assert owned["entrypoint"] == "native"
    assert _run_files(root) == []
    assert "stale run snapshot" in result.stderr, result.stdout + result.stderr


@pytest.mark.unit
def test_uninstall_removes_the_marketplace_metadata_with_the_plugin(
    tmp_path: Path,
) -> None:
    """.claude-plugin/marketplace.json names ./plugin/plugins/onex as its
    source; an uninstall that deletes plugin/ must not leave it behind."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    root = home / ".omninode/delegation"
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")
    installed = _run_stub_install(home, bin_dir)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert (root / ".claude-plugin/marketplace.json").is_file()

    removed = _uninstall(home, bin_dir)

    assert removed.returncode == 0, removed.stdout + removed.stderr
    for name in ("hooks-delegation.json", "plugin", "hook-scripts", ".claude-plugin"):
        assert not (root / name).exists(), name


@pytest.mark.unit
def test_term_outside_claudes_installer_exits_143_and_restores(
    tmp_path: Path,
) -> None:
    """The HUP/INT/TERM traps turn a signal into an exit, so the EXIT trap puts
    the tree back. Without the mapping bash dies of the signal (-15) and no trap
    runs, leaving the old tree moved aside. The TERM lands while the --python
    interpreter is in the native prepare step, after the tree snapshot."""
    home = tmp_path / "home"
    root = _classic_install(home)
    settings = home / ".claude/settings.json"
    before_tree, before_settings = _tree(root), settings.read_bytes()
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")
    started = tmp_path / "prepare-started"
    wrapper = tmp_path / "python-fixture"
    wrapper.write_text(
        "#!/bin/bash\n"
        'case "$*" in *container_onboarding_assets\\ prepare*)\n'
        f'  touch "{started}"; sleep 3;;\n'
        "esac\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    wrapper.chmod(0o755)

    proc = _spawn_stub_install(home, bin_dir, str(wrapper))
    _wait_until_started(started, proc)
    os.kill(proc.pid, signal.SIGTERM)
    out, err = proc.communicate(timeout=120)

    assert proc.returncode == 143, out + err
    assert settings.read_bytes() == before_settings
    assert _tree(root) == before_tree
    assert _run_files(root) == []


@pytest.mark.unit
def test_uninstall_reads_the_native_verdict_as_a_string(tmp_path: Path) -> None:
    """The remove step prints its verdict on stdout. The installer must compare
    it as text, not run it as a command: with a stray line ahead of the verdict
    (an interpreter wrapper, a sitecustomize) running it fails, and the native
    uninstall falls into the classic rollback, which rewrites settings.json."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude/settings.json"
    settings.write_text(json.dumps({"model": "keep", "hooks": {"Stop": [GUARD]}}))
    before = settings.read_bytes()
    root = home / ".omninode/delegation"
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")
    installed = _run_stub_install(home, bin_dir)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert settings.read_bytes() == before
    wrapper = tmp_path / "python-fixture"
    wrapper.write_text(
        "#!/bin/bash\n"
        'case "$*" in *container_onboarding_assets\\ remove*) echo "stray output";; esac\n'
        f'exec "{sys.executable}" "$@"\n'
    )
    wrapper.chmod(0o755)

    removed = _uninstall(home, bin_dir, str(wrapper))

    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "command not found" not in removed.stderr, removed.stderr
    assert settings.read_bytes() == before
    assert not (root / "hooks-delegation.json").exists()


@pytest.mark.unit
@pytest.mark.parametrize("layout", ["installed-wheel", "source-checkout"])
def test_prepare_reads_src_index_ts_only_in_a_source_checkout(
    tmp_path: Path, layout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In an installed wheel the handler sits at
    site-packages/omniclaude/nodes/<node>/, so parents[3] is site-packages and
    a stray site-packages/index.ts must not become the plugin module: only a
    source checkout (src/ beside the repo's pyproject.toml) uses src/index.ts."""
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator import (
        handler_native_delegation as module,
    )
    from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_native_delegation import (
        ModelNativeDelegationRequest,
    )

    if layout == "installed-wheel":
        top = tmp_path / "venv/lib/python3.12/site-packages"
    else:
        top = tmp_path / "repo/src"
    node = top / "omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    node.mkdir(parents=True)
    if layout == "source-checkout":
        (top.parent / "pyproject.toml").write_text('[project]\nname = "x"\n')
    (top / "index.ts").write_text("// top-level index.ts\n")
    packaged = (
        top
        / "omniclaude/resources/customer/plugins/onex/hooks/lib/native_delegation_mod.js"
    )
    packaged.parent.mkdir(parents=True)
    packaged.write_text("// packaged module\n")
    monkeypatch.setattr(module, "__file__", str(node / "handler_native_delegation.py"))
    root = tmp_path / "root"
    (root / "plugin/plugins/onex/hooks/lib").mkdir(parents=True)

    module.HandlerNativeDelegation().handle(
        ModelNativeDelegationRequest(
            operation="prepare",
            install_root=root,
            claude_settings=tmp_path / "profile/settings.json",
            python_bin=sys.executable,
        )
    )

    copied = (
        root / "plugin/plugins/onex/hooks/lib/native_delegation_mod.js"
    ).read_text()
    expected = (
        "// packaged module\n"
        if layout == "installed-wheel"
        else "// top-level index.ts\n"
    )
    assert copied == expected


def _owned_history_commands(settings: Path, root: Path) -> list[str]:
    return [
        c
        for c in _registered_commands(settings)
        if "--history-only" in c or f"{root}/" in c
    ]


@pytest.mark.unit
def test_native_on_registers_no_history_helper(tmp_path: Path) -> None:
    """Amendment 17: on the native path the native turn is the history, so on
    registers the plugin and no separate history helper, in settings.json or
    in the plugin's own hook files Claude loads."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude/settings.json"
    settings.write_text(json.dumps({"hooks": {"Stop": [GUARD]}}))
    root = home / ".omninode/delegation"
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")

    result = _run_stub_install(home, bin_dir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _owned_history_commands(settings, root) == []
    plugin = root / "plugin/plugins/onex"
    assert json.loads((plugin / "hooks/hooks.json").read_text()) == {
        "modules": ["./lib/native_delegation_mod.js"]
    }
    assert "hooks" not in json.loads(
        (plugin / ".claude-plugin/plugin.json").read_text()
    )
    assert json.loads((root / "hooks-delegation.json").read_text())["hooks"] == {}


_PENDING = """\
import sys
from omnimarket.nodes.node_hook_delegate_effect.handlers.handler_prompt_delegate import (
    HandlerPromptDelegate as H,
)
action, session = sys.argv[1:3]
if action == "record":
    H._record(session, "what is 2+2", "4", "local-model", "run-" + session)
print(H._pending(session, 100000))
"""


def _pending(home: Path, action: str, session: str) -> str:
    """Write (``record``) or read (``read``) omnimarket's real pending history."""
    done = subprocess.run(
        [sys.executable, "-c", _PENDING, action, session],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return done.stdout.strip()


def _history_helper(home: Path, session: str) -> str:
    """What the classic history helper would hand Claude, with delegation off."""
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "plugins/onex/hooks/lib/delegation_hook_runner.py"),
            "--history-only",
        ],
        input=json.dumps({"session_id": session}),
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "ONEX_HOOKS_MASK": "0"},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return done.stdout.strip()


@pytest.mark.unit
@pytest.mark.parametrize("action", ["--uninstall", "--pause"])
def test_native_off_removes_the_plugin_and_clears_pending_history(
    tmp_path: Path, action: str
) -> None:
    """Amendment 17: off on the native path removes the plugin and clears any
    pending history, so nothing recorded while on is replayed to Claude later
    by the prompt hook or a history helper. The store is omnimarket's prompt
    handler's (~/.onex_state/claude_prompt_history/<session hash>.json)."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    root = home / ".omninode/delegation"
    bin_dir = tmp_path / "bin"
    _stub_claude(bin_dir, tmp_path / "calls.log")
    installed = _run_stub_install(home, bin_dir)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    # Positive control: an entry recorded in the real store is replayed by the
    # real helper (and consumed), so an empty answer later means "cleared".
    assert "run-control" in _pending(home, "record", "control")
    assert "run-control" in _history_helper(home, "control")
    assert "run-s1" in _pending(home, "record", "s1")
    store = home / ".onex_state/claude_prompt_history"
    assert list(store.glob("*.json"))

    removed = subprocess.run(
        [
            "/bin/bash",
            str(ROOT / "scripts/install-delegation.sh"),
            action,
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
    assert not (root / "plugin").exists()
    assert not (root / ".claude-plugin").exists()
    assert [p.name for p in store.glob("*.json")] == []
    assert _pending(home, "read", "s1") == ""
    assert _history_helper(home, "s1") == ""
