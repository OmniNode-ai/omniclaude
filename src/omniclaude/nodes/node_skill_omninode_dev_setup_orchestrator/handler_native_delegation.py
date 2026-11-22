# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Own the native plugin artifact and its vendor registration lifecycle."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
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


def _owned(root: Path, relative: str) -> Path:
    """``root / relative``, refusing a symlink at it or at any folder below root.

    A link planted at a fixed install path would send the write to its target.
    """
    path = root
    for part in Path(relative).parts:
        path = path / part
        if path.is_symlink():
            raise ValueError(f"Refusing to write through a symlink at {path}.")
    return path


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


def _clear_pending_prompt_history() -> None:
    """Remove every pending prompt history file omnimarket's prompt handler kept.

    The store is HandlerPromptDelegate's: one JSON list per session at
    ``${ONEX_STATE_DIR:-~/.onex_state}/claude_prompt_history/<hash>.json``,
    written under an flock on the sibling ``<hash>.lock``. Each file is removed
    under that same lock, so a hook writing at this moment is not lost half
    way; the lock files stay. A ``<hash>.tmp`` is the handler's write in
    flight (it writes the .tmp, then renames it over the .json); a hook killed
    between the two leaves it, so it is cleared the same way (OMN-23413
    Amendment 17, round 4).

    The directory is resolved exactly as ``HandlerPromptDelegate._history_file``
    in omnimarket resolves it, from this process's environment. What that
    cannot cover: a hook that ran with a different ``ONEX_STATE_DIR`` (or
    ``HOME``) than the process running off wrote elsewhere and is not found; and
    a Claude session already running keeps the hooks it loaded and can record
    again after off. Both are known limits, not built around.
    """
    state = Path(os.environ.get("ONEX_STATE_DIR", str(Path.home() / ".onex_state")))
    store = state / "claude_prompt_history"
    if not store.is_dir():
        return
    for pending in (*store.glob("*.json"), *store.glob("*.tmp")):
        with open(pending.with_suffix(".lock"), "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            pending.unlink(missing_ok=True)


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
        # Every fixed path is checked before anything is written.
        owned = {
            name: _owned(root, name)
            for name in (
                "plugin/plugins/onex/hooks/lib/native_delegation_mod.js",
                "plugin/plugins/onex/hooks/hooks.json",
                "plugin/plugins/onex/hooks/delegation-runtime.json",
                "plugin/plugins/onex/.claude-plugin/plugin.json",
                ".claude-plugin/marketplace.json",
                "hooks-delegation.json",
            )
        }
        # A source checkout keeps the module as a file directly in src/: a
        # second directory there renames the repo in the contract scanner.
        # Only a checkout (src/ beside the repo's pyproject.toml) reads it; in
        # an installed wheel parents[3] is site-packages, where an index.ts is
        # not ours, so the packaged module is used (OMN-23413 review).
        here = Path(__file__).parents
        asset = (
            here[2]
            / "resources/customer/plugins/onex/hooks/lib/native_delegation_mod.js"
        )
        if here[3].name == "src" and (here[4] / "pyproject.toml").is_file():
            asset = here[3] / "index.ts"
        shutil.copyfile(
            asset,
            owned["plugin/plugins/onex/hooks/lib/native_delegation_mod.js"],
        )
        modules = {"modules": ["./lib/native_delegation_mod.js"]}
        _write(owned["plugin/plugins/onex/hooks/hooks.json"], modules)
        _write(
            owned["plugin/plugins/onex/hooks/delegation-runtime.json"],
            {"python": request.python_bin},
        )
        digest = hashlib.sha256()
        for path in sorted(plugin.rglob("*")):
            if path.is_file() and path.relative_to(plugin).parts[0] in ("hooks", "lib"):
                digest.update(str(path.relative_to(plugin)).encode())
                digest.update(path.read_bytes())
        metadata = owned["plugin/plugins/onex/.claude-plugin/plugin.json"]
        metadata.parent.mkdir(exist_ok=True)
        _write(
            metadata,
            {"name": "onex-delegation", "version": "0.0.1-r" + digest.hexdigest()[:16]},
        )
        market = owned[".claude-plugin/marketplace.json"]
        market.parent.mkdir(exist_ok=True)
        _write(
            market,
            {
                "name": MARKETPLACE,
                "owner": {"name": "OmniNode"},
                "plugins": [
                    {"name": "onex-delegation", "source": "./plugin/plugins/onex"}
                ],
            },
        )
        _write(
            owned["hooks-delegation.json"],
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
        # The native turn is the history: off leaves nothing for the prompt
        # hook or a history helper to hand Claude again (Amendment 17).
        _clear_pending_prompt_history()
        return True
