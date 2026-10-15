# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HandlerClaudeCodeBindingInstall: render, write, read back, register (OMN-18531, T0.3).

The rendered module is written to the Claude Code mods location and tracked nowhere: the
install refuses a target inside any git work tree. Its sha256 is recorded, and the bytes
read back from disk must equal the render's. Additive rows are written into the user's
settings.json only; every registration this effect wrote earlier is dropped first, so a row
removed from the contract is removed from the settings on the next install. Only rows whose
probe rows the capability report marks supported are installed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from omniclaude.nodes.node_claude_code_binding_install_effect.errors import (
    BindingInstallError,
)
from omniclaude.nodes.node_claude_code_binding_install_effect.models import (
    ModelBindingInstallRequest,
    ModelBindingInstallResult,
)
from omniclaude.nodes.node_claude_code_binding_render_compute.handlers.handler_binding_render import (
    ADAPTER_COMMAND,
    HandlerClaudeCodeBindingRender,
)
from omniclaude.nodes.node_claude_code_binding_render_compute.models import (
    ModelBindingRenderRequest,
    ModelBindingRenderResult,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumBindingKind,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientBinding,
)

_OWN_COMMAND_PREFIX = f"{ADAPTER_COMMAND} --binding "
RECORD_NAME = "install_record.json"


def _inside_a_work_tree(path: Path) -> bool:
    return any((p / ".git").exists() for p in (path, *path.parents))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _is_installed(binding: ModelClientBinding, supported: frozenset[str]) -> bool:
    return set(binding.probe_rows) <= supported


def _own_entry(entry: dict[str, object]) -> bool:
    hooks = entry.get("hooks")
    return isinstance(hooks, list) and any(
        isinstance(h, dict)
        and str(h.get("command", "")).startswith(_OWN_COMMAND_PREFIX)
        for h in hooks
    )


def _own_commands(entry: dict[str, object]) -> list[str]:
    hooks = entry.get("hooks")
    assert isinstance(hooks, list)
    return [
        str(h["command"])
        for h in hooks
        if isinstance(h, dict)
        and str(h.get("command", "")).startswith(_OWN_COMMAND_PREFIX)
    ]


class HandlerClaudeCodeBindingInstall:
    """handle(request) -> result."""

    def handle(self, request: ModelBindingInstallRequest) -> ModelBindingInstallResult:
        mods_dir = Path(request.mods_dir)
        settings_path = Path(request.settings_path)
        if _inside_a_work_tree(mods_dir):
            raise BindingInstallError(
                f"{mods_dir} is inside a git work tree; a rendered module is tracked in no repository"
            )
        if settings_path.name != "settings.json":
            raise BindingInstallError(
                f"{settings_path} is not a user settings.json; additive rows go to the user settings only"
            )
        supported = frozenset(request.supported_probe_rows)
        eligible = tuple(b for b in request.bindings if _is_installed(b, supported))
        skipped = tuple(
            b.name for b in request.bindings if not _is_installed(b, supported)
        )
        rendered = HandlerClaudeCodeBindingRender().handle(
            ModelBindingRenderRequest(bindings=eligible, max_mode=request.max_mode)
        )
        replacing = [b for b in eligible if b.kind is EnumBindingKind.REPLACING]

        plugin_dir = mods_dir / request.plugin_name
        module_path: Path | None = None
        installed_sha: str | None = None
        render_sha: str | None = None
        if replacing:
            module_path = plugin_dir / "hooks" / "register.ts"
            _atomic_write(module_path, rendered.module_text.encode("utf-8"))
            _atomic_write(
                plugin_dir / ".claude-plugin" / "plugin.json",
                json.dumps(
                    {
                        "name": request.plugin_name,
                        "version": "0.1.0",
                        "description": "Generated Claude Code bindings; do not edit.",
                    },
                    indent=2,
                ).encode(),
            )
            _atomic_write(
                plugin_dir / "hooks" / "hooks.json",
                json.dumps({"modules": ["./register.ts"]}, indent=2).encode(),
            )
            render_sha = rendered.module_sha256
            installed_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
            if installed_sha != render_sha:
                raise BindingInstallError(
                    f"installed sha256 {installed_sha} differs from the render's {render_sha}"
                )
            _atomic_write(
                plugin_dir / RECORD_NAME,
                json.dumps(
                    {
                        "render_sha256": render_sha,
                        "events": [
                            {"event": b.hook_event, "matcher": b.matcher_tool}
                            for b in replacing
                        ],
                        "bindings": [b.name for b in replacing],
                    },
                    indent=2,
                ).encode(),
            )
        elif plugin_dir.exists():
            shutil.rmtree(plugin_dir)

        removed, registered = self._write_settings(settings_path, rendered)
        return ModelBindingInstallResult(
            module_path=str(module_path) if module_path else None,
            render_sha256=render_sha,
            installed_sha256=installed_sha,
            installed_bindings=tuple(b.name for b in eligible),
            skipped_bindings=skipped,
            registered_commands=registered,
            removed_commands=removed,
        )

    @staticmethod
    def _write_settings(
        settings_path: Path, rendered: ModelBindingRenderResult
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        settings: dict[str, object] = (
            json.loads(settings_path.read_text(encoding="utf-8"))
            if settings_path.exists()
            else {}
        )
        hooks = settings.get("hooks")
        hooks = hooks if isinstance(hooks, dict) else {}
        removed: list[str] = []
        for event, entries in list(hooks.items()):
            kept = []
            for entry in entries:
                if isinstance(entry, dict) and _own_entry(entry):
                    removed.extend(_own_commands(entry))
                else:
                    kept.append(entry)
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
        registered: list[str] = []
        for reg in rendered.registrations:
            added: dict[str, object] = {
                "hooks": [{"type": "command", "command": reg.command}]
            }
            if reg.matcher is not None:
                added["matcher"] = reg.matcher
            hooks.setdefault(reg.event, []).append(added)
            registered.append(reg.command)
        if hooks:
            settings["hooks"] = hooks
        else:
            settings.pop("hooks", None)
        if hooks or removed or settings_path.exists():
            _atomic_write(
                settings_path,
                (json.dumps(settings, indent=2, sort_keys=True) + "\n").encode(),
            )
        return tuple(removed), tuple(registered)
