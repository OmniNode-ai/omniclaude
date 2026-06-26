# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Read the contract-declared diagnostics service endpoints.

OMN-13560 Wave-1 endpoint->overlay migration (epic OMN-13556). The
``lib/utils/diagnostics`` health-check tool previously read its service
endpoints (``INTELLIGENCE_SERVICE_URL`` / ``MAIN_SERVER_URL`` /
``MCP_SERVER_URL``) via scattered direct ``os.environ.get(...)`` calls. They
are now declared in ``contracts/contract_omniclaude_runtime.yaml`` under
``descriptor.*`` with the ``${env.VAR}`` overlay convention so an operator
overlay / the per-lane service env supplies the real endpoint per lane — never a
hardcoded ``http://localhost:...`` in source.

Resolution goes through ``_expand_contract_env_refs`` — the single sanctioned
``os.environ`` boundary in this module, mirroring the canonical
``omnibase_infra.runtime.overlay.contract_env_ref.expand_contract_env_refs``
semantics (a local copy is used because the pinned ``omnibase_infra`` release
does not yet vendor that helper). The descriptor never scatters ``os.environ``
reads through ``diagnostics.py``.

Two accessors are provided:

* :func:`resolve_diagnostics_endpoint_strict` — fails closed: an unset/blank
  value raises ``ValueError`` rather than silently defaulting to localhost.
  This is the canonical fail-closed seam proven by the resolution-equivalence
  test.
* :func:`resolve_diagnostics_endpoint` — fail-soft: resolves to the empty
  string when unset, preserving the pre-migration behavior of the diagnostics
  health-check tool (which must never crash on import or run; an unconfigured
  endpoint is reported as not-configured, not raised).

This module imports only ``os`` / ``re`` / ``pathlib`` / ``yaml`` and the local
enum — it must NOT import ``omniclaude.config.settings`` (that would
reintroduce the circular import the original module-level env reads were
written to avoid).
"""

from __future__ import annotations

import os
import re
from enum import StrEnum
from pathlib import Path

import yaml

# ``${env.VAR}`` / ``${env.VAR:default}`` — the same env-overlay convention the
# canonical overlay resolver (``contract_env_ref.expand_contract_env_refs``)
# uses. An unset var with no inline default expands to the empty string so the
# caller's fail-closed check rejects it rather than passing a literal placeholder
# downstream.
_ENV_REF = re.compile(
    r"\$\{env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<default>[^}]*))?\}"
)

# The omniclaude runtime contract that declares the diagnostics endpoints.
# Resolved relative to this module so it is portable across machines / install
# layouts (no hardcoded absolute path).
_CONTRACT = (
    Path(__file__).resolve().parents[2]
    / "contracts"
    / "contract_omniclaude_runtime.yaml"
)


class DiagnosticsEndpoint(StrEnum):
    """The diagnostics service endpoints declared in the runtime contract."""

    INTELLIGENCE_SERVICE = "intelligence_service"
    MAIN_SERVER = "main_server"
    MCP_SERVER = "mcp_server"


# Map each logical endpoint to the ordered list of ``descriptor.*`` contract
# fields to resolve. MCP preserves the legacy alias chain
# (MCP_SERVER_URL -> ONEX_MCP_URL -> ARCHON_MCP_URL): the first field that
# resolves to a non-empty value wins.
_ENDPOINT_FIELDS: dict[DiagnosticsEndpoint, tuple[str, ...]] = {
    DiagnosticsEndpoint.INTELLIGENCE_SERVICE: ("diagnostics_intelligence_service_url",),
    DiagnosticsEndpoint.MAIN_SERVER: ("diagnostics_main_server_url",),
    DiagnosticsEndpoint.MCP_SERVER: (
        "diagnostics_mcp_server_url",
        "diagnostics_mcp_server_url_legacy_onex",
        "diagnostics_mcp_server_url_legacy_archon",
    ),
}

# Map each endpoint to the env var an operator sets, for actionable error text.
_ENDPOINT_ENV_HINT: dict[DiagnosticsEndpoint, str] = {
    DiagnosticsEndpoint.INTELLIGENCE_SERVICE: "INTELLIGENCE_SERVICE_URL",
    DiagnosticsEndpoint.MAIN_SERVER: "MAIN_SERVER_URL",
    DiagnosticsEndpoint.MCP_SERVER: "MCP_SERVER_URL (or legacy ONEX_MCP_URL / ARCHON_MCP_URL)",
}


def _expand_contract_env_refs(value: str) -> str:
    """Expand ``${env.VAR}`` / ``${env.VAR:default}`` references in ``value``.

    The single sanctioned ``os.environ`` boundary in this module. An unset var
    with no inline default expands to the empty string so the caller fails
    closed rather than passing a literal ``${env.…}`` placeholder downstream.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group("name")
        default = match.group("default")
        return os.environ.get(name, default if default is not None else "")

    return _ENV_REF.sub(_sub, value)


def _load_descriptor(contract_path: Path = _CONTRACT) -> dict[str, object]:
    with contract_path.open(encoding="utf-8") as contract_file:
        raw = yaml.safe_load(contract_file)
    if not isinstance(raw, dict):
        raise ValueError(f"contract {contract_path} must contain a mapping")
    descriptor = raw.get("descriptor")
    if not isinstance(descriptor, dict):
        raise ValueError(
            f"contract {contract_path} must declare a descriptor mapping with "
            "the diagnostics_* endpoint fields"
        )
    return descriptor


def resolve_diagnostics_endpoint(
    endpoint: DiagnosticsEndpoint, contract_path: Path = _CONTRACT
) -> str:
    """Resolve a diagnostics endpoint URL (fail-soft).

    Returns the overlay-resolved value for the first declared contract field
    that resolves to a non-empty string. Returns the empty string when no field
    resolves (unset/blank) — diagnostics is a fail-soft tool and must not raise
    on an unconfigured endpoint.
    """
    descriptor = _load_descriptor(contract_path)
    for field in _ENDPOINT_FIELDS[endpoint]:
        declared = descriptor.get(field)
        if not isinstance(declared, str):
            raise ValueError(
                f"contract {contract_path} must declare a string "
                f"descriptor.{field} (the ${{env.VAR}} overlay value the "
                "diagnostics health-check uses as an endpoint)"
            )
        resolved = _expand_contract_env_refs(declared).strip()
        if resolved:
            return resolved
    return ""


def resolve_diagnostics_endpoint_strict(
    endpoint: DiagnosticsEndpoint, contract_path: Path = _CONTRACT
) -> str:
    """Resolve a diagnostics endpoint URL (fail-closed).

    Raises ``ValueError`` when the endpoint resolves empty, so a caller that
    requires a configured endpoint never silently falls back to localhost when
    the env var is unset.
    """
    resolved = resolve_diagnostics_endpoint(endpoint, contract_path)
    if not resolved:
        raise ValueError(
            f"diagnostics endpoint {endpoint.value} resolved empty — set "
            f"{_ENDPOINT_ENV_HINT[endpoint]} (the endpoint the diagnostics "
            "health-check connects to). The strict accessor fails closed rather "
            "than silently default to localhost."
        )
    return resolved


__all__: list[str] = [
    "DiagnosticsEndpoint",
    "resolve_diagnostics_endpoint",
    "resolve_diagnostics_endpoint_strict",
]
