#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Truthful plugin-deploy readback [OMN-15274].

Answers "which hooks does a Claude Code session on this workstation actually
run right now?" by resolving the load path **the way Claude Code resolves it**
-- ``known_marketplaces.json`` -> marketplace source type -> ``installLocation``
-> ``.claude-plugin/marketplace.json`` plugin ``source`` -- instead of trusting
``~/.claude/plugins/installed_plugins.json``.

Why this module exists (OMN-15274, from the OMN-15244 investigation):
``installed_plugins.json`` records ``onex@omninode-tools`` at
``~/.claude/plugins/cache/omninode-tools/onex/<version>``. For a ``directory``
source marketplace that directory is **not** the load path -- ``$CLAUDE_PLUGIN_ROOT``
resolves to the canonical clone. On 2026-07-27 the recorded cache tree had an
``atime`` of 2026-07-03 (unread for 24 days) and carried ``hooks.json`` v1.3.0
while the executing tree carried v1.5.0. The registry is not merely stale, it is
*actively misleading*: it is the obvious surface to read, it returns a plausible
answer, and the answer is wrong. Every prior "is this hook deployed?" verdict
built on reading that directory reasoned from a dead tree.

The naive read is preserved here as :func:`naive_registry_load_path` -- not as a
fallback, but as the thing this module exists to contradict. It is the RED anchor
in ``tests/hooks/test_plugin_deploy_readback.py`` and the left-hand side of the
:data:`EnumReadbackTripwire.LOAD_PATH_MISMATCH` tripwire. Do not use it as truth.

Reported per agent class (main session / ``Task()`` subagent / Workflow-tool
``agent()`` subagent):

* the **resolved** load path (marketplace source chain, not the registry),
* the ``hooks.json`` version actually loaded from that path,
* every registered hook, with an EXEC-OK check on the resolved command,
* which of those registrations can fire for that class,
* behind/ahead/dirty state of the load-path tree vs its upstream -- the
  merged-not-deployed signal OMN-15244 proved (a merged hook is not a live hook;
  for a ``directory`` source there is no install step, so ``git pull`` in the
  clone *is* the deploy).

Honesty caveat, carried from OMN-15244 and not resolved here: published Claude
Code docs state that marketplace plugins *are* copied to the cache "rather than
using them in-place". Observed behavior on this workstation contradicts that for
a ``directory`` source. File presence, registration and execution are
**observation**; "directory-source marketplaces resolve in place" is
**inference** from the config files. If that ever changes, the load path moves --
:data:`EnumReadbackTripwire.RESOLUTION_RULE_CHANGED` is what catches it.

Scope: ``local_macos_claude_hooks`` runtime profile only. Not CI runners, not
Docker, not ``.201``. Read-only: no writes, no network beyond an optional
``git fetch`` of the load-path tree's own upstream (skip with ``--no-fetch``).

Placement note (rule 7a / no-new-scripts): this is a workstation hook-tooling
module, so it lives beside the other hook logic in ``plugins/onex/hooks/lib/``
and is invoked directly, rather than as a ``scripts/**`` addition or a bus node.
It must run with zero third-party imports from a bare hook/skill context where
no venv, bus or runtime is guaranteed.

Usage::

    python3 plugins/onex/hooks/lib/plugin_deploy_readback.py
    python3 plugins/onex/hooks/lib/plugin_deploy_readback.py --json
    python3 plugins/onex/hooks/lib/plugin_deploy_readback.py --no-fetch --strict

Exit codes: 0 = readback produced, no alarm-level tripwire; 3 = alarm-level
tripwire (or any tripwire under ``--strict``); 1 = the load path could not be
resolved at all, which is itself the loudest possible answer.

Refs: OMN-15274, OMN-15244, OMN-15273, OMN-15213, OMN-15062.
See also: ``omni_home/docs/reference/hook-load-path-and-deploy-readback.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

__all__ = [
    "AGENT_CLASSES",
    "DEFAULT_PLUGIN_ID",
    "EnumSeverity",
    "EnumReadbackTripwire",
    "ModelAgentClassReadback",
    "ModelGitState",
    "ModelHookRegistration",
    "ModelHooksConfig",
    "ModelLoadPathResolution",
    "ModelReadback",
    "ModelRegistryEntry",
    "ModelTripwire",
    "build_readback",
    "naive_registry_load_path",
    "read_hooks_config",
    "read_registry_entries",
    "render_text",
    "resolve_load_path",
]

DEFAULT_PLUGIN_ID = "onex@omninode-tools"

_PLUGIN_ROOT_TOKENS = ("${CLAUDE_PLUGIN_ROOT}", "$CLAUDE_PLUGIN_ROOT")


class EnumSeverity(StrEnum):
    """Tripwire severity. ALARM means a stated assumption stopped holding."""

    ALARM = "ALARM"
    WARN = "WARN"
    INFO = "INFO"


class EnumReadbackTripwire(StrEnum):
    """Named tripwires. Each one is a specific way the readback can go wrong."""

    #: ``installed_plugins.json`` records a path that is not the resolved load
    #: path. Expected on this box today; loud because reading the recorded path
    #: is exactly the mistake OMN-15274 exists to stop.
    LOAD_PATH_MISMATCH = "LOAD_PATH_MISMATCH"

    #: A recorded ``installPath`` does not exist on this machine at all (e.g. a
    #: Linux ``/home/<user>/...`` path recorded for
    #: ``code-review@claude-plugins-official`` on a Mac). Surfaced rather than
    #: silently ignored -- it is the second instance, which makes the stale
    #: registry a pattern rather than a one-off.
    REGISTRY_PATH_MISSING = "REGISTRY_PATH_MISSING"

    #: The resolution rule derived in OMN-15244 no longer describes this box:
    #: either the resolved root is now inside the plugin cache, or the recorded
    #: path and the resolved path agree while a divergent cache tree still
    #: exists. Re-derive the load path before trusting any verdict.
    RESOLUTION_RULE_CHANGED = "RESOLUTION_RULE_CHANGED"

    #: A registered hook command is not executable at the resolved load path.
    HOOK_SCRIPT_MISSING = "HOOK_SCRIPT_MISSING"

    #: The load-path tree is behind its upstream. For a ``directory`` source
    #: there is no install step, so this is the merged-not-deployed signal:
    #: commits that are merged but not yet present in what executes.
    MERGED_NOT_DEPLOYED = "MERGED_NOT_DEPLOYED"

    #: The load-path tree has uncommitted changes, so the live enforcement set
    #: does not correspond to any commit (OMN-15273).
    DIRTY_LOAD_PATH = "DIRTY_LOAD_PATH"

    #: The behind/ahead counts could not be refreshed from the remote, so they
    #: describe the last local fetch rather than current truth.
    UPSTREAM_UNVERIFIED = "UPSTREAM_UNVERIFIED"

    #: A stale cache tree exists alongside the resolved load path and differs
    #: from it. Inert while the cache is not the load path -- reported so that
    #: the *absence* of drift can be noticed, since silence here would mean the
    #: cache had become live.
    CACHE_DRIFT = "CACHE_DRIFT"


@dataclass(frozen=True)
class ModelTripwire:
    """One tripwire firing, with the evidence that made it fire."""

    tripwire: EnumReadbackTripwire
    severity: EnumSeverity
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tripwire": self.tripwire.value,
            "severity": self.severity.value,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ModelRegistryEntry:
    """One ``installed_plugins.json`` record. A *recorded* path, not a resolved one."""

    plugin_id: str
    scope: str
    install_path: str
    version: str
    exists: bool
    last_updated: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "scope": self.scope,
            "install_path": self.install_path,
            "version": self.version,
            "exists": self.exists,
            "last_updated": self.last_updated,
        }


@dataclass(frozen=True)
class ModelLoadPathResolution:
    """The resolved load path plus every hop that produced it."""

    plugin_id: str
    resolved_root: str | None
    marketplace: str
    plugin_name: str
    source_type: str | None
    install_location: str | None
    plugin_source: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.resolved_root is not None and self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "resolved_root": self.resolved_root,
            "marketplace": self.marketplace,
            "plugin_name": self.plugin_name,
            "source_type": self.source_type,
            "install_location": self.install_location,
            "plugin_source": self.plugin_source,
            "error": self.error,
            "chain": (
                "known_marketplaces.json -> source type -> installLocation -> "
                "marketplace.json plugins[].source"
            ),
        }


@dataclass(frozen=True)
class ModelHookRegistration:
    """A single registered hook, resolved against a concrete plugin root."""

    event: str
    matcher: str
    hook_type: str
    command: str
    script_path: str | None
    exec_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "matcher": self.matcher,
            "type": self.hook_type,
            "command": self.command,
            "script_path": self.script_path,
            "exec_ok": self.exec_ok,
        }


@dataclass(frozen=True)
class ModelHooksConfig:
    """A parsed ``hooks.json``, tagged with the root it was read from."""

    path: str
    version: str | None
    registrations: tuple[ModelHookRegistration, ...] = ()
    error: str | None = None

    @property
    def exists(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "version": self.version,
            "registrations": [r.to_dict() for r in self.registrations],
            "error": self.error,
        }


@dataclass(frozen=True)
class ModelGitState:
    """Behind/ahead/dirty state of the load-path tree vs its upstream."""

    is_repo: bool
    branch: str | None = None
    head: str | None = None
    upstream: str | None = None
    behind: int | None = None
    ahead: int | None = None
    dirty_files: int | None = None
    fetched: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_repo": self.is_repo,
            "branch": self.branch,
            "head": self.head,
            "upstream": self.upstream,
            "behind": self.behind,
            "ahead": self.ahead,
            "dirty_files": self.dirty_files,
            "fetched": self.fetched,
            "error": self.error,
        }


@dataclass(frozen=True)
class ModelAgentClass:
    """A dispatch surface, and which hook events can fire on it."""

    key: str
    label: str
    fires: frozenset[str]
    excluded: frozenset[str]
    attestation: str


#: Which hook events reach which dispatch surface.
#:
#: Source: live probe on this workstation 2026-07-27 (OMN-15244), recorded in
#: ``omni_home/docs/reference/hook-load-path-and-deploy-readback.md`` section 2.
#: All three surfaces read the *same* ``hooks.json`` from the *same* resolved
#: root -- there is no per-surface hook config on this box. The classes differ
#: only in which events fire and in what attestation surface exists for them.
AGENT_CLASSES: tuple[ModelAgentClass, ...] = (
    ModelAgentClass(
        key="main_session",
        label="main session",
        fires=frozenset(
            {
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "Notification",
                "UserPromptSubmit",
                "SessionStart",
                "SessionEnd",
                "PreCompact",
            }
        ),
        excluded=frozenset({"SubagentStart", "SubagentStop"}),
        attestation='grep "$(date -u +%Y-%m-%d)" "$ONEX_STATE_DIR/logs/hooks.log"',
    ),
    ModelAgentClass(
        key="task_subagent",
        label="Task()/Agent-tool subagent",
        fires=frozenset(
            {
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
                "Notification",
                "PreCompact",
            }
        ),
        excluded=frozenset({"Stop", "UserPromptSubmit", "SessionStart", "SessionEnd"}),
        attestation="grep -rl '<allow-path breadcrumb>' ~/.claude/projects/*/*.jsonl",
    ),
    ModelAgentClass(
        key="workflow_subagent",
        label="Workflow-tool agent() subagent",
        fires=frozenset(
            {
                "PreToolUse",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
                "Notification",
                "PreCompact",
            }
        ),
        excluded=frozenset({"Stop", "UserPromptSubmit", "SessionStart", "SessionEnd"}),
        attestation=(
            "find ~/.claude/projects -path '*/subagents/workflows/wf_*/agent-*.jsonl' "
            "| xargs grep -l '<allow-path breadcrumb>'"
        ),
    ),
)


@dataclass(frozen=True)
class ModelAgentClassReadback:
    """Per-class view: what this surface actually runs, from the resolved root."""

    agent_class: str
    label: str
    load_path: str | None
    hooks_json_version: str | None
    active: tuple[ModelHookRegistration, ...]
    inert: tuple[ModelHookRegistration, ...]
    attestation: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_class": self.agent_class,
            "label": self.label,
            "load_path": self.load_path,
            "hooks_json_version": self.hooks_json_version,
            "active": [r.to_dict() for r in self.active],
            "inert_for_this_class": [r.to_dict() for r in self.inert],
            "runtime_attestation_recipe": self.attestation,
        }


@dataclass
class ModelReadback:
    """The full truthful readback for one plugin id."""

    plugin_id: str
    claude_home: str
    generated_at_utc: str
    resolution: ModelLoadPathResolution
    naive_registry_path: str | None
    registry_entries: tuple[ModelRegistryEntry, ...]
    live_hooks: ModelHooksConfig | None
    recorded_hooks: ModelHooksConfig | None
    git: ModelGitState | None
    per_agent_class: tuple[ModelAgentClassReadback, ...]
    tripwires: list[ModelTripwire] = field(default_factory=list)

    @property
    def alarms(self) -> list[ModelTripwire]:
        return [t for t in self.tripwires if t.severity is EnumSeverity.ALARM]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "claude_home": self.claude_home,
            "generated_at_utc": self.generated_at_utc,
            "resolved_load_path": self.resolution.resolved_root,
            "resolution": self.resolution.to_dict(),
            "naive_registry_install_path": self.naive_registry_path,
            "registry_entries": [e.to_dict() for e in self.registry_entries],
            "live_hooks": self.live_hooks.to_dict() if self.live_hooks else None,
            "recorded_path_hooks": (
                self.recorded_hooks.to_dict() if self.recorded_hooks else None
            ),
            "load_path_git": self.git.to_dict() if self.git else None,
            "per_agent_class": [c.to_dict() for c in self.per_agent_class],
            "tripwires": [t.to_dict() for t in self.tripwires],
        }


# ---------------------------------------------------------------------------
# Registry reads (the surface this module exists to contradict)
# ---------------------------------------------------------------------------


def _load_json(path: pathlib.Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def read_registry_entries(claude_home: pathlib.Path) -> tuple[ModelRegistryEntry, ...]:
    """Read every ``installed_plugins.json`` record, flagging non-existent paths.

    These are *recorded* paths. They are reported for the tripwires and to
    surface stale entries; they are never used to answer "what is loaded?".
    """
    registry = claude_home / "plugins" / "installed_plugins.json"
    try:
        data = _load_json(registry)
    except (OSError, ValueError):
        return ()

    entries: list[ModelRegistryEntry] = []
    for plugin_id, records in (data.get("plugins") or {}).items():
        if isinstance(records, dict):  # tolerate a non-list shape
            records = [records]
        for record in records or []:
            if not isinstance(record, dict):
                continue
            install_path = str(record.get("installPath") or "")
            entries.append(
                ModelRegistryEntry(
                    plugin_id=str(plugin_id),
                    scope=str(record.get("scope") or "unknown"),
                    install_path=install_path,
                    version=str(record.get("version") or "unknown"),
                    exists=bool(install_path) and pathlib.Path(install_path).is_dir(),
                    last_updated=record.get("lastUpdated"),
                )
            )
    return tuple(entries)


def naive_registry_load_path(
    claude_home: pathlib.Path, plugin_id: str = DEFAULT_PLUGIN_ID
) -> str | None:
    """The **wrong** read, preserved deliberately.

    Returns the ``installPath`` recorded in ``installed_plugins.json`` -- the
    surface every pre-OMN-15274 "is this hook deployed?" verdict used. It is
    kept here so the defect is executable rather than narrated: the RED test
    drives this function against a fixture registry pointing at a dead cache and
    shows it reporting a hook as deployed that the load path does not carry.

    Never call this to determine hook state. Call :func:`resolve_load_path`.
    """
    for entry in read_registry_entries(claude_home):
        if entry.plugin_id == plugin_id:
            return entry.install_path or None
    return None


# ---------------------------------------------------------------------------
# Truthful resolution (the way Claude Code resolves it)
# ---------------------------------------------------------------------------


def resolve_load_path(
    claude_home: pathlib.Path, plugin_id: str = DEFAULT_PLUGIN_ID
) -> ModelLoadPathResolution:
    """Resolve ``$CLAUDE_PLUGIN_ROOT`` from the marketplace source chain.

    ``known_marketplaces.json[marketplace].installLocation`` joined with the
    matching ``.claude-plugin/marketplace.json`` ``plugins[].source``. This is
    the chain that produced the executing tree on 2026-07-27; every hop is
    reported so a future divergence is attributable to a specific hop rather
    than to "the tool said so".
    """
    name, _, marketplace = plugin_id.partition("@")
    if not marketplace:
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace="",
            plugin_name=name,
            source_type=None,
            install_location=None,
            plugin_source=None,
            error=f"plugin id {plugin_id!r} is not of the form <name>@<marketplace>",
        )

    known = claude_home / "plugins" / "known_marketplaces.json"
    try:
        marketplaces = _load_json(known)
    except (OSError, ValueError) as exc:
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace=marketplace,
            plugin_name=name,
            source_type=None,
            install_location=None,
            plugin_source=None,
            error=f"cannot read {known}: {exc}",
        )

    record = (marketplaces or {}).get(marketplace)
    if not isinstance(record, dict):
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace=marketplace,
            plugin_name=name,
            source_type=None,
            install_location=None,
            plugin_source=None,
            error=f"marketplace {marketplace!r} absent from {known}",
        )

    source = record.get("source")
    source_type = (
        str(source.get("source")) if isinstance(source, dict) else None
    ) or None
    install_location = str(record.get("installLocation") or "") or None
    if not install_location:
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace=marketplace,
            plugin_name=name,
            source_type=source_type,
            install_location=None,
            plugin_source=None,
            error=f"marketplace {marketplace!r} records no installLocation",
        )

    manifest = pathlib.Path(install_location) / ".claude-plugin" / "marketplace.json"
    try:
        manifest_data = _load_json(manifest)
    except (OSError, ValueError) as exc:
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace=marketplace,
            plugin_name=name,
            source_type=source_type,
            install_location=install_location,
            plugin_source=None,
            error=f"cannot read {manifest}: {exc}",
        )

    plugin_entry: dict[str, Any] | None = None
    for candidate in (manifest_data or {}).get("plugins") or []:
        if isinstance(candidate, dict) and candidate.get("name") == name:
            plugin_entry = candidate
            break
    if plugin_entry is None:
        return ModelLoadPathResolution(
            plugin_id=plugin_id,
            resolved_root=None,
            marketplace=marketplace,
            plugin_name=name,
            source_type=source_type,
            install_location=install_location,
            plugin_source=None,
            error=f"plugin {name!r} absent from {manifest}",
        )

    raw_source = plugin_entry.get("source")
    plugin_source: str | None
    if isinstance(raw_source, str):
        plugin_source = raw_source
    elif isinstance(raw_source, dict):
        plugin_source = (
            raw_source.get("path") or raw_source.get("source") or None
        ) and str(raw_source.get("path") or raw_source.get("source"))
    else:
        plugin_source = None
    if not plugin_source:
        plugin_source = "."

    resolved = os.path.normpath(os.path.join(install_location, plugin_source))
    return ModelLoadPathResolution(
        plugin_id=plugin_id,
        resolved_root=resolved,
        marketplace=marketplace,
        plugin_name=name,
        source_type=source_type,
        install_location=install_location,
        plugin_source=plugin_source,
    )


def read_hooks_config(root: pathlib.Path) -> ModelHooksConfig:
    """Parse ``<root>/hooks/hooks.json`` and EXEC-check every registered command.

    The command is resolved against ``root`` (the same substitution Claude Code
    performs for ``${CLAUDE_PLUGIN_ROOT}``), so ``exec_ok`` answers "would this
    hook actually run from *this* tree", not "does a file with that name exist
    somewhere".
    """
    path = root / "hooks" / "hooks.json"
    try:
        data = _load_json(path)
    except (OSError, ValueError) as exc:
        return ModelHooksConfig(path=str(path), version=None, error=str(exc))

    registrations: list[ModelHookRegistration] = []
    for event, blocks in ((data or {}).get("hooks") or {}).items():
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            matcher = str(block.get("matcher") or "*")
            for hook in block.get("hooks") or []:
                if not isinstance(hook, dict):
                    continue
                command = str(hook.get("command") or "")
                hook_type = str(hook.get("type") or "unknown")
                script_path = _resolve_command_path(command, root)
                registrations.append(
                    ModelHookRegistration(
                        event=str(event),
                        matcher=matcher,
                        hook_type=hook_type,
                        command=command,
                        script_path=script_path,
                        exec_ok=bool(script_path and os.access(script_path, os.X_OK)),
                    )
                )
    return ModelHooksConfig(
        path=str(path),
        version=(str(data.get("version")) if (data or {}).get("version") else None),
        registrations=tuple(registrations),
    )


def _resolve_command_path(command: str, root: pathlib.Path) -> str | None:
    """Substitute ``${CLAUDE_PLUGIN_ROOT}`` and return argv[0] as a path."""
    if not command:
        return None
    expanded = command
    for token in _PLUGIN_ROOT_TOKENS:
        expanded = expanded.replace(token, str(root))
    try:
        parts = shlex.split(expanded)
    except ValueError:
        parts = expanded.split()
    if not parts:
        return None
    return os.path.normpath(parts[0])


# ---------------------------------------------------------------------------
# Git readback (the merged-not-deployed signal)
# ---------------------------------------------------------------------------


def _git(root: pathlib.Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def read_git_state(root: pathlib.Path, fetch: bool = True) -> ModelGitState:
    """Behind/ahead/dirty of the load-path tree vs its configured upstream.

    ``behind > 0`` is the merged-not-deployed signal: for a ``directory``-source
    marketplace there is no install step, so commits merged upstream are not
    live until the load-path tree is updated. ``dirty_files > 0`` means the live
    enforcement set corresponds to no commit at all (OMN-15273).
    """
    rc, _ = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0:
        return ModelGitState(is_repo=False, error="not a git work tree")

    _, branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    _, head = _git(root, "rev-parse", "HEAD")
    rc_up, upstream = _git(
        root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
    )
    upstream_ref = upstream if rc_up == 0 else None

    fetched = False
    if fetch and upstream_ref:
        remote = upstream_ref.split("/", 1)[0]
        rc_fetch, _ = _git(root, "fetch", "--quiet", remote, timeout=120)
        fetched = rc_fetch == 0

    behind: int | None = None
    ahead: int | None = None
    if upstream_ref:
        rc_counts, counts = _git(
            root, "rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}"
        )
        if rc_counts == 0:
            parts = counts.split()
            if len(parts) == 2 and all(p.isdigit() for p in parts):
                ahead, behind = int(parts[0]), int(parts[1])

    rc_status, status = _git(root, "status", "--porcelain", "--", ".")
    dirty = (
        len([ln for ln in status.splitlines() if ln.strip()])
        if rc_status == 0
        else None
    )

    return ModelGitState(
        is_repo=True,
        branch=branch or None,
        head=head or None,
        upstream=upstream_ref,
        behind=behind,
        ahead=ahead,
        dirty_files=dirty,
        fetched=fetched,
        error=None if upstream_ref else "no upstream configured for HEAD",
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _cache_root(claude_home: pathlib.Path) -> pathlib.Path:
    return claude_home / "plugins" / "cache"


def _is_under(path: str, parent: pathlib.Path) -> bool:
    try:
        return os.path.commonpath(
            [os.path.normpath(path), os.path.normpath(str(parent))]
        ) == os.path.normpath(str(parent))
    except ValueError:
        return False


def _per_class(
    resolution: ModelLoadPathResolution, hooks: ModelHooksConfig | None
) -> tuple[ModelAgentClassReadback, ...]:
    out: list[ModelAgentClassReadback] = []
    registrations = hooks.registrations if hooks else ()
    for agent_class in AGENT_CLASSES:
        active = tuple(r for r in registrations if r.event in agent_class.fires)
        inert = tuple(r for r in registrations if r.event not in agent_class.fires)
        out.append(
            ModelAgentClassReadback(
                agent_class=agent_class.key,
                label=agent_class.label,
                load_path=resolution.resolved_root,
                hooks_json_version=hooks.version if hooks else None,
                active=active,
                inert=inert,
                attestation=agent_class.attestation,
            )
        )
    return tuple(out)


def build_readback(
    claude_home: pathlib.Path,
    plugin_id: str = DEFAULT_PLUGIN_ID,
    fetch: bool = True,
    now_utc: str | None = None,
) -> ModelReadback:
    """Assemble the truthful readback and evaluate every tripwire."""
    claude_home = pathlib.Path(claude_home)
    resolution = resolve_load_path(claude_home, plugin_id)
    registry_entries = read_registry_entries(claude_home)
    naive_path = naive_registry_load_path(claude_home, plugin_id)

    live_hooks = (
        read_hooks_config(pathlib.Path(resolution.resolved_root))
        if resolution.resolved_root
        else None
    )
    recorded_hooks = read_hooks_config(pathlib.Path(naive_path)) if naive_path else None
    git = (
        read_git_state(pathlib.Path(resolution.resolved_root), fetch=fetch)
        if resolution.resolved_root and pathlib.Path(resolution.resolved_root).is_dir()
        else None
    )

    readback = ModelReadback(
        plugin_id=plugin_id,
        claude_home=str(claude_home),
        generated_at_utc=now_utc or _utc_now(),
        resolution=resolution,
        naive_registry_path=naive_path,
        registry_entries=registry_entries,
        live_hooks=live_hooks,
        recorded_hooks=recorded_hooks,
        git=git,
        per_agent_class=_per_class(resolution, live_hooks),
    )
    readback.tripwires = _evaluate_tripwires(claude_home, readback)
    return readback


def _evaluate_tripwires(
    claude_home: pathlib.Path, rb: ModelReadback
) -> list[ModelTripwire]:
    fired: list[ModelTripwire] = []
    resolved = rb.resolution.resolved_root

    if not rb.resolution.ok:
        fired.append(
            ModelTripwire(
                EnumReadbackTripwire.RESOLUTION_RULE_CHANGED,
                EnumSeverity.ALARM,
                f"load path unresolvable: {rb.resolution.error}",
            )
        )
        return fired

    assert resolved is not None  # narrowed by resolution.ok

    # 1. recorded vs resolved.
    if rb.naive_registry_path:
        recorded_norm = os.path.normpath(rb.naive_registry_path)
        if recorded_norm != os.path.normpath(resolved):
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.LOAD_PATH_MISMATCH,
                    EnumSeverity.WARN,
                    (
                        f"installed_plugins.json records {recorded_norm} but the load "
                        f"path resolves to {resolved}. Any hook verdict read from the "
                        "recorded path is a verdict about a tree that does not execute."
                    ),
                )
            )
        else:
            # They agree. On a directory-source marketplace that is not the state
            # OMN-15244 derived; if a divergent cache tree still exists, the
            # resolution rule changed underneath us.
            stale_cache = _find_cache_tree(claude_home, rb.plugin_id)
            if stale_cache is not None and _hooks_differ(stale_cache, resolved):
                fired.append(
                    ModelTripwire(
                        EnumReadbackTripwire.RESOLUTION_RULE_CHANGED,
                        EnumSeverity.ALARM,
                        (
                            f"recorded installPath and resolved load path now AGREE "
                            f"({resolved}) while a divergent cache tree still exists at "
                            f"{stale_cache}. The OMN-15244 resolution rule no longer "
                            "describes this box -- re-derive it before trusting any "
                            "deploy verdict."
                        ),
                    )
                )

    # 2. resolution has moved into the cache.
    if _is_under(resolved, _cache_root(claude_home)):
        fired.append(
            ModelTripwire(
                EnumReadbackTripwire.RESOLUTION_RULE_CHANGED,
                EnumSeverity.ALARM,
                (
                    f"resolved load path {resolved} is inside the plugin cache. The "
                    "documented copy semantics are now in force; the OMN-15244 "
                    "load-path map is superseded and must be re-derived."
                ),
            )
        )

    # 3. stale/non-existent recorded paths, all plugins (not just this one).
    for entry in rb.registry_entries:
        if entry.install_path and not entry.exists:
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.REGISTRY_PATH_MISSING,
                    EnumSeverity.WARN,
                    (
                        f"{entry.plugin_id} records installPath {entry.install_path} "
                        "which does not exist on this machine."
                    ),
                )
            )

    # 4. registered-but-not-executable hooks at the load path.
    for reg in rb.live_hooks.registrations if rb.live_hooks else ():
        if not reg.exec_ok:
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.HOOK_SCRIPT_MISSING,
                    EnumSeverity.ALARM,
                    (
                        f"{reg.event} hook {reg.command} is registered at the load path "
                        f"but {reg.script_path} is not executable -- it cannot fire."
                    ),
                )
            )
    if rb.live_hooks is not None and rb.live_hooks.error:
        fired.append(
            ModelTripwire(
                EnumReadbackTripwire.HOOK_SCRIPT_MISSING,
                EnumSeverity.ALARM,
                f"no readable hooks.json at the load path: {rb.live_hooks.error}",
            )
        )

    # 5. merged-not-deployed / dirty / unverified upstream.
    git = rb.git
    if git is not None and git.is_repo:
        if not git.fetched:
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.UPSTREAM_UNVERIFIED,
                    EnumSeverity.WARN,
                    (
                        "behind/ahead counts were not refreshed from the remote; they "
                        "describe the last local fetch, not current upstream truth."
                    ),
                )
            )
        if git.behind:
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.MERGED_NOT_DEPLOYED,
                    EnumSeverity.ALARM,
                    (
                        f"load-path tree is {git.behind} commit(s) behind {git.upstream}. "
                        "There is no install step for a directory-source marketplace, so "
                        "anything merged in those commits is NOT live. Deploy = "
                        f"`git -C {rb.resolution.resolved_root} pull --ff-only`."
                    ),
                )
            )
        if git.dirty_files:
            fired.append(
                ModelTripwire(
                    EnumReadbackTripwire.DIRTY_LOAD_PATH,
                    EnumSeverity.WARN,
                    (
                        f"{git.dirty_files} uncommitted change(s) in the load-path tree: "
                        "the live enforcement set corresponds to no commit (OMN-15273)."
                    ),
                )
            )

    # 6. cache drift -- expected and inert; reported so silence is noticeable.
    stale_cache = _find_cache_tree(claude_home, rb.plugin_id)
    if stale_cache is not None and os.path.normpath(stale_cache) != os.path.normpath(
        resolved
    ):
        cache_cfg = read_hooks_config(pathlib.Path(stale_cache))
        live_version = rb.live_hooks.version if rb.live_hooks else None
        fired.append(
            ModelTripwire(
                EnumReadbackTripwire.CACHE_DRIFT,
                EnumSeverity.INFO,
                (
                    f"inert cache tree {stale_cache} carries hooks.json "
                    f"{cache_cfg.version or 'unreadable'} vs live {live_version or 'unknown'}. "
                    "Drift here is expected and harmless; drift going to zero would mean "
                    "the cache had become the load path."
                ),
            )
        )

    return fired


def _find_cache_tree(claude_home: pathlib.Path, plugin_id: str) -> str | None:
    """Locate the (inert) cache tree for a plugin, if one exists."""
    name, _, marketplace = plugin_id.partition("@")
    base = _cache_root(claude_home) / marketplace / name
    if not base.is_dir():
        return None
    candidates = sorted(p for p in base.iterdir() if p.is_dir())
    if not candidates:
        return None
    current = base / "current"
    if current.exists():
        return str(current.resolve())
    return str(candidates[-1])


def _hooks_differ(left: str, right: str) -> bool:
    lc = read_hooks_config(pathlib.Path(left))
    rc = read_hooks_config(pathlib.Path(right))
    return (lc.version, {r.to_dict()["command"] for r in lc.registrations}) != (
        rc.version,
        {r.to_dict()["command"] for r in rc.registrations},
    )


def _utc_now() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------


def render_text(rb: ModelReadback) -> str:
    """Human-readable readback. Every line is a fact with a named source."""
    lines: list[str] = []
    add = lines.append
    add(f"PLUGIN DEPLOY READBACK  {rb.plugin_id}   ({rb.generated_at_utc})")
    add(f"  scope: local_macos_claude_hooks profile; CLAUDE_HOME={rb.claude_home}")
    add("")
    add("RESOLVED LOAD PATH (marketplace source chain -- authoritative)")
    if rb.resolution.ok:
        add(f"  {rb.resolution.resolved_root}")
        add(
            f"  via: known_marketplaces[{rb.resolution.marketplace}]"
            f".source={rb.resolution.source_type!r} -> installLocation="
            f"{rb.resolution.install_location} -> marketplace.json "
            f"plugins[{rb.resolution.plugin_name}].source={rb.resolution.plugin_source!r}"
        )
    else:
        add(f"  UNRESOLVED: {rb.resolution.error}")
    add("")
    add("RECORDED installPath (installed_plugins.json -- NOT the load path)")
    add(f"  {rb.naive_registry_path or '(no record)'}")
    add("")

    if rb.git is not None and rb.git.is_repo:
        add("LOAD-PATH TREE STATE")
        add(
            f"  branch {rb.git.branch} @ {(rb.git.head or '')[:9]}   upstream "
            f"{rb.git.upstream or '(none)'}   fetched={rb.git.fetched}"
        )
        add(
            f"  behind {rb.git.behind if rb.git.behind is not None else '?'}   "
            f"ahead {rb.git.ahead if rb.git.ahead is not None else '?'}   "
            f"dirty {rb.git.dirty_files if rb.git.dirty_files is not None else '?'} file(s)"
        )
        add("")

    for cls in rb.per_agent_class:
        add(f"AGENT CLASS: {cls.label}")
        add(
            f"  load path: {cls.load_path}   hooks.json version: "
            f"{cls.hooks_json_version or '(unreadable)'}"
        )
        if cls.active:
            for reg in cls.active:
                flag = "EXEC-OK" if reg.exec_ok else "MISSING"
                script = os.path.basename(reg.script_path or reg.command)
                add(f"    {reg.event:<13} {reg.matcher:<46} {flag:<8} {script}")
        else:
            add("    (no registered hook fires for this class)")
        if cls.inert:
            inert_events = sorted({r.event for r in cls.inert})
            add(f"    inert for this class: {', '.join(inert_events)}")
        add(f"    runtime attestation: {cls.attestation}")
        add("")

    add("TRIPWIRES")
    if rb.tripwires:
        for tw in rb.tripwires:
            add(f"  [{tw.severity.value:<5}] {tw.tripwire.value}: {tw.detail}")
    else:
        add("  (none)")
    add("")
    verdict = "ALARM" if rb.alarms else "OK"
    add(f"VERDICT: {verdict}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="plugin_deploy_readback",
        description=(
            "Truthful plugin-deploy readback [OMN-15274]: resolve the load path "
            "the way Claude Code does and report what each agent class actually "
            "runs. Never reads installed_plugins.json as truth."
        ),
    )
    parser.add_argument(
        "--plugin-id",
        default=DEFAULT_PLUGIN_ID,
        help=f"plugin identity to read back (default: {DEFAULT_PLUGIN_ID})",
    )
    parser.add_argument(
        "--claude-home",
        default=None,
        help="Claude Code home (default: $CLAUDE_CONFIG_DIR or ~/.claude)",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the read-only `git fetch` of the load-path tree's upstream",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero on any tripwire, not just alarm-level ones",
    )
    args = parser.parse_args(argv)

    claude_home = pathlib.Path(
        args.claude_home
        or os.environ.get("CLAUDE_CONFIG_DIR")
        or (pathlib.Path.home() / ".claude")
    ).expanduser()

    rb = build_readback(
        claude_home=claude_home, plugin_id=args.plugin_id, fetch=not args.no_fetch
    )

    if args.json:
        print(json.dumps(rb.to_dict(), indent=2, sort_keys=False))
    else:
        print(render_text(rb))

    if not rb.resolution.ok:
        return 1
    if rb.alarms or (args.strict and rb.tripwires):
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
