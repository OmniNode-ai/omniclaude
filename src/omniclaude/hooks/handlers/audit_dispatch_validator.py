# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Audit dispatch validator for context integrity contract binding (OMN-5236).

Validates contract binding for dispatched agents. Called by the poly enforcer
shell script after prefix validation passes. Keeps the shell script thin and
pushes logic into a testable Python module.

Validation behaviour:

1. Load the agent YAML config for the dispatched subagent_type.
2. Check whether the agent declares a ``context_integrity`` subcontract.
3. If the subcontract is present:
   - Record the dispatch in the correlation manager with declared scopes.
   - Emit an ``audit.dispatch.validated`` event via ``emit_client_wrapper``.
4. In STRICT or PARANOID mode:
   - The agent config MUST have ``metadata.context_integrity_contract_id`` set.
   - If missing: hard-reject with a discoverable error listing known contract IDs.
   - If present but the contract ID is not in the registry: emit WARN (not block).
5. In PERMISSIVE or WARN mode:
   - Agents without ``metadata.context_integrity_contract_id`` pass with no error.
6. Agents without a ``context_integrity`` subcontract are permissive by default —
   no error, no emit, just pass.

Enforcement levels (from ``AUDIT_ENFORCEMENT_LEVEL`` env var):
    PERMISSIVE  — No contract ID required; only log missing entries.
    WARN        — No contract ID required; emit a warning event.
    STRICT      — contract_id required; unknown IDs are WARN only.
    PARANOID    — contract_id required; unknown IDs are hard-reject.

CLI usage (invoked by pre_tool_use_poly_enforcer.sh):

    python3 -m omniclaude.hooks.handlers.audit_dispatch_validator \\
        --subagent-type onex:polymorphic-agent \\
        [--enforcement-level STRICT]

Exit codes:
    0 — allow (pass or soft-warn)
    2 — block (hard-reject due to misconfiguration in STRICT/PARANOID mode)

Related:
    - OMN-5230: Context Integrity Audit & Enforcement (parent epic)
    - OMN-5234: Audit event schemas
    - OMN-5235: Correlation manager task hierarchy
    - schemas_audit.py: AuditDispatchValidatedEvent
    - topics.py: TopicBase.AUDIT_DISPATCH_VALIDATED
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enforcement level constants
# ---------------------------------------------------------------------------

_LEVEL_PERMISSIVE = "PERMISSIVE"
_LEVEL_WARN = "WARN"
_LEVEL_STRICT = "STRICT"
_LEVEL_PARANOID = "PARANOID"

_KNOWN_LEVELS = {_LEVEL_PERMISSIVE, _LEVEL_WARN, _LEVEL_STRICT, _LEVEL_PARANOID}

# Default enforcement level when env var is not set
_DEFAULT_ENFORCEMENT_LEVEL = _LEVEL_PERMISSIVE


# ---------------------------------------------------------------------------
# Agent config helpers
# ---------------------------------------------------------------------------


def _resolve_agents_config_dir() -> Path | None:
    """Resolve the directory containing agent YAML configs.

    Searches:
    1. ``CLAUDE_PLUGIN_ROOT/agents/configs/``
    2. The plugin root inferred from this file's location.

    Returns:
        Path to the agents/configs directory, or None if not found.
    """
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    candidates: list[Path] = []

    if plugin_root_env:
        candidates.append(Path(plugin_root_env) / "agents" / "configs")

    # Infer from file location: src/omniclaude/hooks/handlers/ →
    # ../../../../plugins/onex/agents/configs/
    here = Path(__file__).parent
    inferred_plugin_root = here.parent.parent.parent.parent / "plugins" / "onex"
    candidates.append(inferred_plugin_root / "agents" / "configs")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    return None


def _load_agent_yaml(subagent_type: str) -> dict[str, Any] | None:
    """Load the YAML config for a subagent_type.

    The config file is resolved as:
        ``{agents_config_dir}/{agent_name}.yaml``

    where ``agent_name`` is the part after the ``onex:`` prefix (if present),
    or the full ``subagent_type`` value.

    Args:
        subagent_type: The agent type string, e.g. ``onex:polymorphic-agent``.

    Returns:
        Parsed YAML dict, or None if not loadable (missing file, parse error).
    """
    # Strip the onex: prefix to get the file name stem
    if ":" in subagent_type:
        agent_name = subagent_type.split(":", 1)[1]
    else:
        agent_name = subagent_type

    # Reject agent names that are not safe identifiers. This prevents path
    # traversal attacks (e.g. "onex:../../hooks/context_integrity_contracts")
    # from walking out of the configs directory.
    if not re.fullmatch(r"[A-Za-z0-9_-]+", agent_name):
        logger.warning(
            "Agent name %r contains unsafe characters; rejecting YAML load",
            agent_name,
        )
        return None

    config_dir = _resolve_agents_config_dir()
    if config_dir is None:
        logger.debug("No agents config dir found; skipping agent YAML load")
        return None

    config_path = config_dir / f"{agent_name}.yaml"
    # Paranoia double-check: ensure the resolved path stays inside config_dir
    try:
        config_path.resolve().relative_to(config_dir.resolve())
    except ValueError:
        logger.warning(
            "Resolved config path %s escapes config dir %s; rejecting",
            config_path,
            config_dir,
        )
        return None
    if not config_path.is_file():
        logger.debug("Agent config not found: %s", config_path)
        return None

    try:
        import yaml

        with open(config_path, encoding="utf-8") as fh:
            result: dict[str, Any] = yaml.safe_load(fh) or {}
            return result
    except Exception:  # noqa: BLE001
        logger.debug("Failed to load agent config %s", config_path, exc_info=True)
        return None


def _has_context_integrity_subcontract(agent_config: dict[str, Any]) -> bool:
    """Return True if the agent config declares a context_integrity subcontract.

    Checks the following YAML paths:
    - ``contracts.subcontracts`` list contains ``"context_integrity"``
    - ``context_integrity`` top-level key is present (legacy schema)

    Args:
        agent_config: Parsed agent YAML as a dict.

    Returns:
        True if a context_integrity subcontract is declared.
    """
    # Path 1: contracts.subcontracts list
    contracts = agent_config.get("contracts", {})
    if isinstance(contracts, dict):
        subcontracts = contracts.get("subcontracts", [])
        if isinstance(subcontracts, list) and "context_integrity" in subcontracts:
            return True

    # Path 2: top-level context_integrity key
    if "context_integrity" in agent_config:
        return True

    return False


def _extract_context_integrity_scopes(agent_config: dict[str, Any]) -> dict[str, Any]:
    """Extract declared scopes from the context_integrity subcontract.

    Returns an empty dict if not present. Scopes are best-effort; a missing
    scope key means unconstrained.

    Args:
        agent_config: Parsed agent YAML as a dict.

    Returns:
        Dict with optional keys: tool_scope, memory_scope, retrieval_sources.
    """
    # Look under contracts.context_integrity first, then top-level
    scopes: dict[str, Any] = {}

    contracts = agent_config.get("contracts", {})
    if isinstance(contracts, dict):
        ci = contracts.get("context_integrity", {})
        if isinstance(ci, dict):
            scopes.update({k: v for k, v in ci.items() if k in _SCOPE_KEYS})

    top_level_ci = agent_config.get("context_integrity", {})
    if isinstance(top_level_ci, dict):
        # Only fill in missing keys from top-level (contracts wins)
        for key in _SCOPE_KEYS:
            if key not in scopes and key in top_level_ci:
                scopes[key] = top_level_ci[key]

    return scopes


_SCOPE_KEYS = {"tool_scope", "memory_scope", "retrieval_sources"}


def _get_context_integrity_contract_id(agent_config: dict[str, Any]) -> str | None:
    """Extract metadata.context_integrity_contract_id from agent config.

    Args:
        agent_config: Parsed agent YAML as a dict.

    Returns:
        The contract ID string, or None if not present.
    """
    metadata = agent_config.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    contract_id = metadata.get("context_integrity_contract_id")
    return str(contract_id) if contract_id is not None else None


# ---------------------------------------------------------------------------
# Contract registry helpers
# ---------------------------------------------------------------------------


_REGISTRY_LOAD_ERROR = object()  # sentinel: registry path found but failed to load


def _load_known_contract_ids() -> list[str] | object:
    """Load the list of known contract handler IDs from the registry.

    Currently reads from a dedicated ``context_integrity_contracts.yaml`` if
    present. Returns the sentinel ``_REGISTRY_LOAD_ERROR`` when a registry
    file exists but cannot be parsed — callers in PARANOID mode must treat
    this as a hard-failure rather than an allow.  Returns an empty list only
    when no registry file exists at all (registry not yet populated).

    Returns:
        List of known contract ID strings, empty list if registry absent, or
        ``_REGISTRY_LOAD_ERROR`` sentinel on parse/IO error.
    """
    registry_paths = [
        Path(__file__).parent.parent / "context_integrity_contracts.yaml",
    ]

    for path in registry_paths:
        if not path.is_file():
            continue
        # Registry file exists — must succeed or we return error sentinel
        try:
            import yaml

            with open(path, encoding="utf-8") as fh:
                data: Any = yaml.safe_load(fh) or {}
            if isinstance(data, dict):
                ids = data.get("contract_ids", [])
                if isinstance(ids, list):
                    str_ids: list[str] = [str(i) for i in ids if i]
                    return str_ids
            # File parsed but structure unexpected — treat as error
            logger.debug("Contract registry %s has unexpected structure", path)
            return _REGISTRY_LOAD_ERROR
        except Exception:  # noqa: BLE001
            logger.debug("Failed to load contract registry %s", path, exc_info=True)
            return _REGISTRY_LOAD_ERROR

    # No registry file found at all — not an error, just unregistered
    return []


# ---------------------------------------------------------------------------
# Event emission helpers
# ---------------------------------------------------------------------------


def _emit_audit_dispatch_event(
    subagent_type: str,
    passed: bool,
    enforcement_level: str,
    contract_id: str,
    correlation_id: str | None,
    *,
    quiet: bool = False,
) -> None:
    """Emit audit.dispatch.validated event via emit_client_wrapper.

    Failures are non-fatal — never raises.

    Args:
        subagent_type: The agent type being dispatched.
        passed: Whether validation passed.
        enforcement_level: The current enforcement level.
        contract_id: The contract ID (may be empty string if unknown).
        correlation_id: Active correlation ID, or None.
        quiet: If True, skip emission (dry-run / test mode).
    """
    if quiet:
        return

    try:
        import uuid
        from datetime import UTC, datetime

        payload: dict[str, Any] = {
            "task_id": str(uuid.uuid4()),
            "contract_id": contract_id or "unknown",
            "parent_task_id": None,
            "agent_type": subagent_type,
            "enforcement_level": enforcement_level,
            "passed": passed,
            "correlation_id": str(uuid.uuid4())
            if correlation_id is None
            else correlation_id,
            "emitted_at": datetime.now(UTC).isoformat(),
        }
        payload_json = json.dumps(payload)

        # Resolve emit_client_wrapper path
        emit_wrapper = _find_emit_wrapper()
        if emit_wrapper is None:
            logger.debug("emit_client_wrapper not found; audit event dropped")
            return

        import subprocess

        subprocess.Popen(  # noqa: S603
            [
                sys.executable,
                str(emit_wrapper),
                "emit",
                "--event-type",
                "audit.dispatch.validated",
                "--payload",
                payload_json,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        logger.debug("Failed to emit audit.dispatch.validated", exc_info=True)


def _find_emit_wrapper() -> Path | None:
    """Locate the emit_client_wrapper.py for event emission.

    Returns:
        Path to emit_client_wrapper.py, or None if not found.
    """
    plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    candidates: list[Path] = []

    if plugin_root_env:
        candidates.append(
            Path(plugin_root_env) / "hooks" / "lib" / "emit_client_wrapper.py"
        )

    here = Path(__file__).parent
    inferred = (
        here.parent.parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "lib"
        / "emit_client_wrapper.py"
    )
    candidates.append(inferred)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


# ---------------------------------------------------------------------------
# Correlation manager integration
# ---------------------------------------------------------------------------


def _record_dispatch_in_correlation_manager(
    subagent_type: str,
    scopes: dict[str, Any],
    contract_id: str | None,
) -> None:
    """Record dispatch in the correlation manager if available.

    This records task hierarchy for the dispatched agent. Failures are
    non-fatal.

    Args:
        subagent_type: The agent type being dispatched.
        scopes: Declared scope constraints from the contract.
        contract_id: The resolved contract ID, or None.
    """
    try:
        import importlib.util
        import uuid

        # Attempt to import from the plugin lib path
        plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
        lib_path: Path | None = None

        if plugin_root_env:
            candidate = (
                Path(plugin_root_env) / "hooks" / "lib" / "correlation_manager.py"
            )
            if candidate.is_file():
                lib_path = candidate

        if lib_path is None:
            here = Path(__file__).parent
            candidate = (
                here.parent.parent.parent.parent
                / "plugins"
                / "onex"
                / "hooks"
                / "lib"
                / "correlation_manager.py"
            )
            if candidate.is_file():
                lib_path = candidate

        if lib_path is None:
            logger.debug("correlation_manager not found; skipping dispatch record")
            return

        spec = importlib.util.spec_from_file_location("correlation_manager", lib_path)
        if spec is None or spec.loader is None:
            return

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        registry: Any = module.get_registry()
        task_id = str(uuid.uuid4())
        effective_contract_id = contract_id or f"unknown:{subagent_type}"
        registry.push_task(task_id, effective_contract_id, scopes)

    except Exception:  # noqa: BLE001
        logger.debug("Failed to record dispatch in correlation manager", exc_info=True)


# ---------------------------------------------------------------------------
# Core validation logic
# ---------------------------------------------------------------------------


class DispatchValidationResult:
    """Result of a dispatch validation run.

    Attributes:
        allowed: Whether the dispatch should be allowed.
        reason: Human-readable explanation (used for block messages).
        contract_id: Resolved contract ID (empty string if unknown).
        has_context_integrity: Whether the agent declares the subcontract.
        enforcement_level: The enforcement level applied.
    """

    def __init__(
        self,
        *,
        allowed: bool,
        reason: str,
        contract_id: str,
        has_context_integrity: bool,
        enforcement_level: str,
    ) -> None:
        self.allowed = allowed
        self.reason = reason
        self.contract_id = contract_id
        self.has_context_integrity = has_context_integrity
        self.enforcement_level = enforcement_level


def validate_dispatch(
    subagent_type: str,
    enforcement_level: str | None = None,
    *,
    quiet_emit: bool = False,
) -> DispatchValidationResult:
    """Validate a task dispatch against its contract binding.

    This is the primary entrypoint used by the shell script (via CLI) and
    by unit tests.

    Args:
        subagent_type: The agent type being dispatched (e.g. ``onex:polymorphic-agent``).
        enforcement_level: Override the enforcement level. Defaults to
            ``AUDIT_ENFORCEMENT_LEVEL`` env var, then ``PERMISSIVE``.
        quiet_emit: If True, suppress all Kafka/event emission (for tests).

    Returns:
        A DispatchValidationResult indicating whether dispatch is allowed.
    """
    resolved_level = _resolve_enforcement_level(enforcement_level)

    agent_config = _load_agent_yaml(subagent_type)

    # If the config cannot be loaded, treat as permissive (no block)
    if agent_config is None:
        return DispatchValidationResult(
            allowed=True,
            reason=f"Agent config not found for {subagent_type!r}; permissive pass",
            contract_id="",
            has_context_integrity=False,
            enforcement_level=resolved_level,
        )

    has_ci = _has_context_integrity_subcontract(agent_config)

    if not has_ci:
        # No context_integrity subcontract declared — permissive by default
        return DispatchValidationResult(
            allowed=True,
            reason=f"Agent {subagent_type!r} has no context_integrity subcontract; permissive pass",
            contract_id="",
            has_context_integrity=False,
            enforcement_level=resolved_level,
        )

    # Agent declares context_integrity subcontract — proceed with validation
    scopes = _extract_context_integrity_scopes(agent_config)
    contract_id = _get_context_integrity_contract_id(agent_config)

    # NOTE: _record_dispatch_in_correlation_manager is intentionally called
    # AFTER all block decisions below to ensure blocked dispatches are never
    # recorded as validated (OMN-5236 CodeRabbit Major finding).

    # STRICT / PARANOID: require metadata.context_integrity_contract_id
    if resolved_level in (_LEVEL_STRICT, _LEVEL_PARANOID):
        if not contract_id:
            raw_ids = _load_known_contract_ids()
            known_ids: list[str] = (
                []
                if (raw_ids is _REGISTRY_LOAD_ERROR or not isinstance(raw_ids, list))
                else raw_ids
            )
            ids_hint = (
                f" Known contract IDs: {', '.join(known_ids)}"
                if known_ids
                else " No contract IDs are currently registered."
            )
            reason = (
                f"Agent {subagent_type!r} declares a context_integrity subcontract but "
                f"metadata.context_integrity_contract_id is not set. "
                f"Set this key to a valid handler_id in the contract registry.{ids_hint}"
            )
            _emit_audit_dispatch_event(
                subagent_type=subagent_type,
                passed=False,
                enforcement_level=resolved_level,
                contract_id="",
                correlation_id=_get_correlation_id_safe(),
                quiet=quiet_emit,
            )
            return DispatchValidationResult(
                allowed=False,
                reason=reason,
                contract_id="",
                has_context_integrity=True,
                enforcement_level=resolved_level,
            )

        # Contract ID is set — validate it against the registry
        raw_ids2 = _load_known_contract_ids()
        if raw_ids2 is _REGISTRY_LOAD_ERROR:
            # Registry file exists but is unreadable/corrupt.
            # In PARANOID: hard-block to preserve the no-unknown-IDs guarantee.
            # In STRICT: warn and allow (registry may be temporarily unavailable).
            if resolved_level == _LEVEL_PARANOID:
                reason = (
                    f"Agent {subagent_type!r}: contract registry could not be loaded. "
                    f"Blocking in PARANOID mode to preserve hard-block guarantee."
                )
                _emit_audit_dispatch_event(
                    subagent_type=subagent_type,
                    passed=False,
                    enforcement_level=resolved_level,
                    contract_id=contract_id,
                    correlation_id=_get_correlation_id_safe(),
                    quiet=quiet_emit,
                )
                return DispatchValidationResult(
                    allowed=False,
                    reason=reason,
                    contract_id=contract_id,
                    has_context_integrity=True,
                    enforcement_level=resolved_level,
                )
            else:
                logger.warning(
                    "Contract registry could not be loaded; allowing in STRICT mode",
                )
        elif isinstance(raw_ids2, list) and raw_ids2 and contract_id not in raw_ids2:
            # Unknown contract ID (registry loaded successfully and is non-empty)
            known_ids2: list[str] = raw_ids2
            if resolved_level == _LEVEL_PARANOID:
                reason = (
                    f"Agent {subagent_type!r} has context_integrity_contract_id={contract_id!r} "
                    f"which is not in the contract registry. "
                    f"Known IDs: {', '.join(known_ids2)}"
                )
                _emit_audit_dispatch_event(
                    subagent_type=subagent_type,
                    passed=False,
                    enforcement_level=resolved_level,
                    contract_id=contract_id,
                    correlation_id=_get_correlation_id_safe(),
                    quiet=quiet_emit,
                )
                return DispatchValidationResult(
                    allowed=False,
                    reason=reason,
                    contract_id=contract_id,
                    has_context_integrity=True,
                    enforcement_level=resolved_level,
                )
            else:
                # STRICT mode: warn but allow for stale/unknown IDs
                logger.warning(
                    "Agent %r has context_integrity_contract_id=%r not in registry; "
                    "allowing (STRICT mode, stale IDs are non-blocking). "
                    "Known IDs: %s",
                    subagent_type,
                    contract_id,
                    ", ".join(known_ids2),
                )

    # All block decisions passed — record dispatch in correlation manager now
    # (after block checks so blocked dispatches are never recorded as validated)
    _record_dispatch_in_correlation_manager(subagent_type, scopes, contract_id)

    # All checks passed — emit success event
    _emit_audit_dispatch_event(
        subagent_type=subagent_type,
        passed=True,
        enforcement_level=resolved_level,
        contract_id=contract_id or "",
        correlation_id=_get_correlation_id_safe(),
        quiet=quiet_emit,
    )

    return DispatchValidationResult(
        allowed=True,
        reason=f"Agent {subagent_type!r} passed contract binding validation",
        contract_id=contract_id or "",
        has_context_integrity=True,
        enforcement_level=resolved_level,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_enforcement_level(override: str | None) -> str:
    """Resolve the effective enforcement level.

    Priority: explicit override > env var AUDIT_ENFORCEMENT_LEVEL > default.

    Args:
        override: Explicit override value (may be None).

    Returns:
        Normalised enforcement level string (upper-case).
    """
    raw = override or os.environ.get(
        "AUDIT_ENFORCEMENT_LEVEL", _DEFAULT_ENFORCEMENT_LEVEL
    )
    normalised = raw.strip().upper()
    if normalised not in _KNOWN_LEVELS:
        logger.warning(
            "Unknown enforcement level %r; falling back to PERMISSIVE",
            raw,
        )
        return _LEVEL_PERMISSIVE
    return normalised


def _get_correlation_id_safe() -> str | None:
    """Get the active correlation ID without raising on import error.

    Returns:
        Correlation ID string, or None if not available.
    """
    try:
        import importlib.util

        plugin_root_env = os.environ.get("CLAUDE_PLUGIN_ROOT")
        lib_path: Path | None = None

        if plugin_root_env:
            candidate = (
                Path(plugin_root_env) / "hooks" / "lib" / "correlation_manager.py"
            )
            if candidate.is_file():
                lib_path = candidate

        if lib_path is None:
            here = Path(__file__).parent
            candidate = (
                here.parent.parent.parent.parent
                / "plugins"
                / "onex"
                / "hooks"
                / "lib"
                / "correlation_manager.py"
            )
            if candidate.is_file():
                lib_path = candidate

        if lib_path is None:
            return None

        spec = importlib.util.spec_from_file_location("correlation_manager", lib_path)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result: str | None = module.get_correlation_id()
        return result
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit dispatch validator: validate contract binding for a dispatched agent.",
        prog="audit_dispatch_validator",
    )
    parser.add_argument(
        "--subagent-type",
        required=True,
        help="The subagent_type being dispatched (e.g. onex:polymorphic-agent).",
    )
    parser.add_argument(
        "--enforcement-level",
        default=None,
        choices=list(_KNOWN_LEVELS),
        help=(
            "Override enforcement level. "
            "Defaults to AUDIT_ENFORCEMENT_LEVEL env var or PERMISSIVE."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for the audit dispatch validator.

    Returns:
        0 if the dispatch is allowed, 2 if it is blocked.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = validate_dispatch(
        subagent_type=args.subagent_type,
        enforcement_level=args.enforcement_level,
    )

    if result.allowed:
        return 0

    # Output block reason as JSON for the shell script to pick up.
    # print() is intentional here: the shell script reads stdout to get the
    # block JSON (same pattern as other hook scripts in this repo).
    block_output = json.dumps(
        {
            "decision": "block",
            "reason": result.reason,
        }
    )
    print(block_output)  # noqa: T201
    return 2


if __name__ == "__main__":
    sys.exit(main())
