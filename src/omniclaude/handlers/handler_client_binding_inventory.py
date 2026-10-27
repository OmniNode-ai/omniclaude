# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pure validation of installed Claude Code bindings against the adapter contract.

Both install records and user settings preserve the binding/event/matcher association.
The hook shim injects its Finding record type, so this handler needs only the standard
library and PyYAML, including on the static inventory CI runner.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

ADAPTER_NODE_PACKAGE: Final = "omnimarket.nodes.node_claude_code_hook_adapter_effect"
ADAPTER_CONTRACT_REL: Final = "node_claude_code_hook_adapter_effect/contract.yaml"
_ADAPTER_COMMAND: Final = "onex-claude-code-hook"


def resolve_adapter_contract() -> Path | None:
    """The adapter node's contract.yaml in the installed omnimarket package, or None.

    The node lives in omnimarket; this repository holds no copy of its inventory. A
    package version that predates the node declares no bindings.
    """
    import importlib.util  # local: the rest of this module is stdlib-only at import time

    try:
        spec = importlib.util.find_spec(ADAPTER_NODE_PACKAGE)
    except ImportError:
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    contract = Path(next(iter(spec.submodule_search_locations))) / "contract.yaml"
    return contract if contract.is_file() else None


def declared_client_bindings(contract: Path | None) -> tuple[dict[str, Any], ...]:
    """The rows of ``client_bindings.claude_code.bindings`` in the adapter contract."""
    import yaml  # local: the rest of this module is stdlib-only at import time

    if contract is None or not contract.is_file():
        return ()
    raw = yaml.safe_load(contract.read_text(encoding="utf-8")) or {}
    rows = ((raw.get("client_bindings") or {}).get("claude_code") or {}).get("bindings")
    return tuple(rows or ())


def _binding_command_name(command: str) -> tuple[str | None, bool]:
    """Read argv without executing it; only the binding name belongs in the command."""
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"cannot parse hook command: {exc}") from exc
    if not argv or Path(argv[0]).name != _ADAPTER_COMMAND:
        return None, False
    if len(argv) == 3 and argv[1] == "--binding" and argv[2]:
        return argv[2], False
    return None, True


def _installed_binding_rows(
    artifact: dict[str, Any],
) -> tuple[tuple[tuple[str, str, str | None], ...], tuple[str, ...]]:
    """Preserve each binding's event and matcher in both supported artifact formats.

    The install effect writes parallel bindings/events arrays in render order. User
    settings attach the binding command directly to its event/matcher registration.
    """
    names = artifact.get("bindings") or ()
    events = artifact.get("events") or ()
    if len(names) != len(events):
        raise ValueError("installed binding names and events differ in length")
    rows = [
        (name, event["event"], event.get("matcher"))
        for name, event in zip(names, events, strict=True)
    ]
    malformed: list[str] = []
    hooks = artifact.get("hooks")
    if isinstance(hooks, dict):
        for event, entries in hooks.items():
            for entry in entries:
                for hook in entry.get("hooks", ()):
                    command = str(hook.get("command", ""))
                    name, invalid = _binding_command_name(command)
                    if invalid:
                        malformed.append(command)
                    elif name is not None:
                        rows.append((name, event, entry.get("matcher")))
    return tuple(rows), tuple(malformed)


def client_binding_findings[T](
    contract: Path | None,
    installed_artifacts: tuple[Path, ...] = (),
    *,
    finding_factory: Callable[[str, str, str], T],
) -> tuple[T, ...]:
    """Contract rows are well formed; nothing installed registers what the contract does not declare."""
    findings: list[T] = []
    rows = declared_client_bindings(contract)
    seen: set[str] = set()
    for row in rows:
        name = str(row.get("name", ""))
        if not name or not row.get("hook_event"):
            findings.append(
                finding_factory(
                    "CLIENT_BINDING_MALFORMED",
                    name or "<unnamed>",
                    f"a row of client_bindings.claude_code in the adapter contract ({ADAPTER_CONTRACT_REL}) "
                    "needs a name and a hook_event.",
                )
            )
        if name in seen:
            findings.append(
                finding_factory(
                    "CLIENT_BINDING_DUPLICATE",
                    name,
                    f"declared twice in client_bindings.claude_code of the adapter contract ({ADAPTER_CONTRACT_REL}).",
                )
            )
        seen.add(name)
    declared_events = {(str(r.get("hook_event")), r.get("matcher_tool")) for r in rows}
    declared_by_name = {
        str(row.get("name")): (str(row.get("hook_event")), row.get("matcher_tool"))
        for row in rows
    }
    for artifact_path in installed_artifacts:
        installed, malformed = _installed_binding_rows(
            json.loads(artifact_path.read_text(encoding="utf-8"))
        )
        for command in malformed:
            findings.append(
                finding_factory(
                    "INSTALLED_BINDING_COMMAND_MALFORMED",
                    command,
                    f"{artifact_path} must invoke the adapter with only --binding and its name.",
                )
            )
        for name, event, matcher in installed:
            if name not in seen:
                findings.append(
                    finding_factory(
                        "INSTALLED_BINDING_UNDECLARED",
                        name,
                        f"{artifact_path} registers binding {name!r}, which "
                        f"client_bindings.claude_code in the adapter contract ({ADAPTER_CONTRACT_REL}) does not "
                        "declare. The installed binding is rendered from that section "
                        "alone; re-install, or declare the row.",
                    )
                )
            if (event, matcher) not in declared_events:
                findings.append(
                    finding_factory(
                        "INSTALLED_EVENT_UNDECLARED",
                        f"{event}{{{matcher}}}",
                        f"{artifact_path} registers event {event!r} (matcher {matcher!r}), "
                        f"absent from client_bindings.claude_code in the adapter contract ({ADAPTER_CONTRACT_REL}).",
                    )
                )
            elif name in declared_by_name and declared_by_name[name] != (
                event,
                matcher,
            ):
                findings.append(
                    finding_factory(
                        "INSTALLED_BINDING_EVENT_MISMATCH",
                        name,
                        f"{artifact_path} registers binding {name!r} under {(event, matcher)!r}; "
                        f"its contract row declares {declared_by_name[name]!r}.",
                    )
                )
    return tuple(findings)
