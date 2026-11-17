# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Own the native plugin artifact and its vendor registration lifecycle."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from omniclaude.nodes.node_skill_omninode_dev_setup_orchestrator.models.model_native_delegation import (
    ModelNativeDelegationRequest,
    ModelNativeDelegationResult,
)

PLUGIN_ID = "onex-delegation@onex-delegation-local"
MARKETPLACE = "onex-delegation-local"


def _read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.is_file() else {}


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def _vendor(*args: str) -> None:
    completed = subprocess.run(
        ["claude", "--setting-sources", "", "plugin", *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr or completed.stdout)


class HandlerNativeDelegation:
    """Keep source, copied closure and vendor-owned cache on one identity."""

    def handle(
        self, request: ModelNativeDelegationRequest
    ) -> ModelNativeDelegationResult:
        if request.operation == "prepare":
            self._prepare(request)
            return ModelNativeDelegationResult(native=True)
        return ModelNativeDelegationResult(native=self._remove(request))

    def _prepare(self, request: ModelNativeDelegationRequest) -> None:
        root = request.install_root
        plugin = root / "plugin/plugins/onex"
        asset = Path(__file__).parents[3] / "handlers/native_delegation.ts"
        if not asset.is_file():
            asset = (
                Path(__file__).parents[2]
                / "resources/customer/plugins/onex/hooks/lib/native_delegation_mod.js"
            )
        shutil.copyfile(
            asset,
            plugin / "hooks/lib/native_delegation_mod.js",
        )
        modules = {"modules": ["./lib/native_delegation_mod.js"]}
        _write(plugin / "hooks/hooks.json", modules)
        _write(plugin / "hooks/delegation-runtime.json", {"python": request.python_bin})
        digest = hashlib.sha256()
        for path in sorted(plugin.rglob("*")):
            if path.is_file() and path.relative_to(plugin).parts[0] in ("hooks", "lib"):
                digest.update(str(path.relative_to(plugin)).encode())
                digest.update(path.read_bytes())
        metadata = plugin / ".claude-plugin"
        metadata.mkdir(exist_ok=True)
        _write(
            metadata / "plugin.json",
            {"name": "onex-delegation", "version": "0.0.1-r" + digest.hexdigest()[:16]},
        )
        market = root / ".claude-plugin"
        market.mkdir(exist_ok=True)
        _write(
            market / "marketplace.json",
            {
                "name": MARKETPLACE,
                "owner": {"name": "OmniNode"},
                "plugins": [
                    {"name": "onex-delegation", "source": "./plugin/plugins/onex"}
                ],
            },
        )
        _write(
            root / "hooks-delegation.json",
            {"entrypoint": "native", "plugin_id": PLUGIN_ID, "hooks": {}, **modules},
        )

    def _remove(self, request: ModelNativeDelegationRequest) -> bool:
        root, settings = request.install_root, request.claude_settings
        manifest = _read(root / "rollback-manifest.json")
        profile = manifest.get("claude_settings")
        if not isinstance(profile, str) or not profile:
            raise ValueError(
                "Rollback manifest is missing its Claude profile; refusing uninstall."
            )
        if Path(profile).resolve() != settings.resolve():
            raise ValueError(
                "Delegation belongs to another Claude profile; refusing uninstall."
            )
        if (
            manifest.get("entrypoint") != "native"
            and _read(root / "hooks-delegation.json").get("entrypoint") != "native"
        ):
            return False
        registry = _read(settings.parent / "plugins/installed_plugins.json").get(
            "plugins", {}
        )
        rows = [
            row for row in registry.get(PLUGIN_ID, []) if row.get("scope") == "user"
        ]
        if len(rows) > 1 or any(
            name != PLUGIN_ID
            and name.endswith("@" + MARKETPLACE)
            and any(row.get("scope") == "user" for row in entries)
            for name, entries in registry.items()
        ):
            raise ValueError(
                "The delegation marketplace has unexpected registrations; preserve them before removal."
            )
        known = _read(settings.parent / "plugins/known_marketplaces.json").get(
            MARKETPLACE
        )
        declared = _read(settings).get("extraKnownMarketplaces", {}).get(MARKETPLACE)
        for entry in (known, declared):
            if entry is not None:
                source = entry.get("source", {})
                if (
                    source.get("source") != "directory"
                    or Path(source.get("path", "")).resolve() != root.resolve()
                ):
                    raise ValueError(
                        "The delegation marketplace belongs to another source; refusing removal."
                    )
        if rows:
            _vendor("uninstall", PLUGIN_ID, "--scope", "user", "--json")
        if known is not None or declared is not None:
            _vendor("marketplace", "remove", MARKETPLACE)
        return True
