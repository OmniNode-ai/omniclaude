# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Own the native plugin artifact and its vendor registration lifecycle."""

from __future__ import annotations

import datetime
import fcntl
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
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
    # Plugin management, no prompt or model call: this node's contract declares
    # descriptor.agent_invocation for it (canonical-inference gate carve-out).
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


# The paths under the install root a run replaces: the hook config (or native
# marker), the plugin tree, the old flat copy and the marketplace metadata.
RUN_OWNED_PATHS = ("hooks-delegation.json", "plugin", "hook-scripts", ".claude-plugin")


def _delete(path: Path) -> None:
    """``rm -rf`` of one path: a link is removed, never followed."""
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _snapshot(root: Path, settings: Path) -> Path:
    """Move this run's owned paths aside so a stopped run can put them back.

    The folder is the whole run state on disk, so a run killed outright, even
    part way through a restore, is put back by the next one (``_recover``):
    .claude-settings names the profile this run edits, each owned path is moved
    in or marked .absent.<name>, .settings.saved or .settings.absent is
    settings.json before this run, and .run-backup names the pre-install backup
    this run made.
    """
    folder = Path(tempfile.mkdtemp(prefix="install-tree.run.", dir=root / "backups"))
    (folder / ".claude-settings").write_text(f"{settings}\n")
    for name in RUN_OWNED_PATHS:
        if (root / name).exists() or (root / name).is_symlink():
            (root / name).rename(folder / name)
        else:
            (folder / f".absent.{name}").touch()
    return folder


def _restore(folder: Path, root: Path, settings: Path) -> Path:
    """Put back what the run that owns ``folder`` replaced.

    settings.json (to the profile that run edited), the owned install paths and,
    when that run made it, the pre-install backup no manifest names. Read only
    from the folder, so it serves a stopped run and a stale one alike. Returns
    the profile written back.
    """
    named = folder / ".claude-settings"
    if named.is_file():
        settings = Path(named.read_text().rstrip("\n"))
    saved, absent = folder / ".settings.saved", folder / ".settings.absent"
    # .settings.saved appears only once whole (renamed from .settings.part).
    if saved.is_file():
        shutil.copyfile(saved, settings)
    elif absent.exists():
        settings.unlink(missing_ok=True)
    saved.unlink(missing_ok=True)
    absent.unlink(missing_ok=True)
    for name in RUN_OWNED_PATHS:
        kept, marker = folder / name, folder / f".absent.{name}"
        if kept.exists() or kept.is_symlink():
            _delete(root / name)
            kept.rename(root / name)
        elif marker.exists():
            # Absent before that run: whatever is there now is that run's.
            _delete(root / name)
            marker.unlink()
        # Otherwise it is already back, or the snapshot never reached it.
    backup = None
    if (folder / ".run-backup").is_file():
        backup = Path((folder / ".run-backup").read_text().rstrip("\n"))
    shutil.rmtree(folder)
    # Only ever a backup this installer names; never a path from elsewhere.
    if (
        backup is not None
        and str(backup.parent) == str(root / "backups")
        and fnmatch.fnmatch(backup.name, "settings.json.*.bak")
    ):
        backup.unlink(missing_ok=True)
    return settings


def _recover(root: Path, settings: Path, dry: bool) -> None:
    """Put back the before-state of every run killed outright (no trap ran).

    Done before this run snapshots anything, or this run would save the
    half-installed state as its own before-state and orphan the old snapshot.
    """
    for run in sorted((root / "backups").glob("install-tree.run.*")):
        if not run.is_dir() or run.is_symlink():
            continue
        if dry:
            sys.stdout.write(
                "[DRY ] would restore a stale run snapshot left by an "
                f"interrupted run: {run}\n"
            )
            continue
        profile = _restore(run, root, settings)
        sys.stderr.write(
            f"[WARN] restored a stale run snapshot left by an interrupted run ({run}): "
            f"{profile} and the delegation files in {root} are back to their state "
            "before that run.\n"
        )


def _save_settings(root: Path, settings: Path, folder: Path) -> str:
    """Back settings.json up once, snapshot it for this run, drop owned rows.

    The first install's backup is kept across re-installs, so --uninstall
    always reaches the true pre-install state; it is returned for the rollback
    manifest. The run's own snapshot lets a failed Claude install restore it
    exactly. Every unrelated hook and setting is preserved: the file is written
    only when an owned row was removed, and "hooks" itself is never added or
    dropped, so settings holding nothing of ours stay byte for byte the same.
    Values, non-ASCII included, are written as read, never escaped.
    """
    try:
        prior = _read(root / "rollback-manifest.json").get("settings_backup") or ""
    except (OSError, ValueError, AttributeError):
        prior = ""
    settings.parent.mkdir(parents=True, exist_ok=True)
    if not prior and settings.is_file():
        stamp = time.strftime("%Y%m%dT%H%M%S")
        backup = root / "backups" / f"settings.json.{stamp}.bak"
        (folder / ".run-backup").write_text(f"{backup}\n")
        shutil.copyfile(settings, backup)
        sys.stderr.write(f"[INFO] backed up existing settings → {backup}\n")
        prior = str(backup)
    if settings.is_file():
        shutil.copyfile(settings, folder / ".settings.part")
        (folder / ".settings.part").rename(folder / ".settings.saved")
    else:
        (folder / ".settings.absent").touch()
        return prior
    current = json.loads(settings.read_text(encoding="utf-8"))
    existing = current.get("hooks")
    if existing is None:
        return prior
    removed = False
    for event in list(existing):
        groups, changed = [], False
        for group in existing[event]:
            hooks = group.get("hooks", [])
            kept = [h for h in hooks if f"{root}/" not in (h.get("command") or "")]
            if len(kept) != len(hooks):
                changed = True
                if not kept:
                    continue
            groups.append({**group, "hooks": kept})
        if changed:
            removed = True
            existing[event] = groups
            if not groups:
                existing.pop(event)
    if removed:
        settings.write_text(
            json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return prior


def _write_manifest(root: Path, settings: Path, backup: str) -> None:
    """Record what --uninstall needs; created_at and the first backup persist."""
    manifest = root / "rollback-manifest.json"
    created_at = datetime.datetime.now(datetime.UTC).isoformat()
    prior_backup = None
    try:
        prior = _read(manifest)
        created_at = prior.get("created_at", created_at)
        prior_backup = prior.get("settings_backup")
    except (OSError, ValueError, AttributeError):
        pass
    data = {
        "version": 1,
        "entrypoint": "native",
        "created_at": created_at,
        "install_root": str(root),
        "claude_settings": str(settings),
        "settings_backup": (backup or prior_backup) or None,
        "installed_hook_config": str(root / "hooks-delegation.json"),
        "package": "omninode-claude",
    }
    manifest.write_text(json.dumps(data, indent=2) + "\n")


def _classic_rollback(manifest_path: Path, preserve_history: bool) -> str:
    """Remove the exact command rows an older (classic) install registered.

    The same exact-command removal the classic installer always did, and the
    same as omnimarket's HandlerSetupClaude.rollback_hook_registration, so a
    classic install rolls back with or without omnimarket installed and this
    handler imports no other handler module (handler DI gate, OMN-21531).
    """
    manifest = json.loads(manifest_path.read_text())
    backup = manifest.get("settings_backup")
    settings = manifest.get("claude_settings")
    hooks_config = manifest.get("installed_hook_config")
    if not settings:
        raise SystemExit("rollback manifest missing claude_settings")
    settings_path = Path(settings)
    if not settings_path.exists():
        if backup and Path(backup).exists():
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(Path(backup).read_text())
            return f"restored missing {settings} from {backup}"
        return ""
    current = json.loads(settings_path.read_text())
    hook_cfg = {}
    if hooks_config and Path(hooks_config).exists():
        hook_cfg = json.loads(Path(hooks_config).read_text()).get("hooks", {})
    owned = {
        hook.get("command")
        for groups in hook_cfg.values()
        for group in groups
        for hook in group.get("hooks", [])
        if hook.get("command")
        and not (preserve_history and "--history-only" in hook["command"])
    }
    hooks = current.get("hooks", {})
    for event in list(hooks):
        filtered = []
        for group in hooks.get(event, []):
            kept = [h for h in group.get("hooks", []) if h.get("command") not in owned]
            if kept:
                filtered.append({**group, "hooks": kept})
        if filtered:
            hooks[event] = filtered
        else:
            hooks.pop(event, None)
    if hooks:
        current["hooks"] = hooks
    else:
        current.pop("hooks", None)
    if current:
        settings_path.write_text(json.dumps(current, indent=2) + "\n")
        return f"removed delegation hooks from {settings}"
    settings_path.unlink()
    return f"removed {settings} after clearing installer-managed hooks"


class HandlerNativeDelegation:
    """Keep source, copied closure and vendor-owned cache on one identity."""

    def handle(
        self, request: ModelNativeDelegationRequest
    ) -> ModelNativeDelegationResult:
        root, settings = request.install_root, request.claude_settings
        operation, argument = request.operation, request.argument
        output = ""
        if operation == "prepare":
            self._prepare(request)
        elif operation == "remove":
            return ModelNativeDelegationResult(native=self._remove(request))
        elif operation == "snapshot":
            output = str(_snapshot(root, settings))
        elif operation == "restore":
            _restore(Path(argument), root, settings)
        elif operation == "recover":
            _recover(root, settings, argument == "dry")
        elif operation == "settings":
            output = _save_settings(root, settings, Path(argument))
        elif operation == "manifest":
            _write_manifest(root, settings, argument)
        else:
            output = _classic_rollback(
                root / "rollback-manifest.json", argument == "true"
            )
        return ModelNativeDelegationResult(native=True, output=output)

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
