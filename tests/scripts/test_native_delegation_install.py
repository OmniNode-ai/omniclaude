# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Real installer + real Claude registry, isolated from the operator's profile.

Catch classic/mod double registration, stale cache, destructive merges,
non-idempotent install, and native enablement surviving OFF.
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


def _stub_claude(bin_dir: Path, calls: Path, install_exit: int = 0) -> None:
    """A claude CLI stand-in: logs each call's arguments; plugin install exits as told.

    A failing install first writes to the profile, as a vendor writer that dies
    part way would, so a test can tell a restore from an untouched file.
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


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("already_removed", [False, True])
def test_native_install_upgrade_repeat_and_off(
    tmp_path: Path, legacy: bool, already_removed: bool, monkeypatch
):
    assert shutil.which("claude"), "Real Claude CLI required for install verification"
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
        ROOT / "src/handlers/native_delegation.ts"
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
