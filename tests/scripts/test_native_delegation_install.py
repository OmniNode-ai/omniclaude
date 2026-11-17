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
    assert stopped.get("enabledPlugins", {}).get(PLUGIN) is not True
    assert stopped["model"] == "preserve-model"
    assert stopped["enabledPlugins"]["unrelated@market"] is True
    assert stopped["hooks"]["UserPromptSubmit"] == [GUARD]
    assert "onex-delegation-local" not in stopped.get("extraKnownMarketplaces", {})
    known = json.loads((profile / "plugins/known_marketplaces.json").read_text())
    assert "onex-delegation-local" not in known
