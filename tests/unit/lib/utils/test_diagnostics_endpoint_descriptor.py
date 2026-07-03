# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Resolution-equivalence tests for the diagnostics service-endpoint descriptor.

OMN-13560 Wave-1 endpoint->overlay migration (epic OMN-13556). Proves the
overlay-resolved diagnostics service endpoints
(``INTELLIGENCE_SERVICE_URL`` / ``MAIN_SERVER_URL`` / ``MCP_SERVER_URL``)
return exactly the value the old direct ``os.environ.get(...)`` reads in
``lib/utils/diagnostics.py`` returned for the same env, across dev /
stability / prod lane values, and that the strict accessor fails closed when a
var is unset (no silent localhost fallback). The MCP alias chain
(``MCP_SERVER_URL`` -> ``ONEX_MCP_URL`` -> ``ARCHON_MCP_URL``) is preserved.
"""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path

import pytest
import yaml

from omniclaude.lib.utils.diagnostics_endpoint_descriptor import (
    EnumDiagnosticsEndpoint,
    resolve_diagnostics_endpoint,
    resolve_diagnostics_endpoint_strict,
)

pytestmark = pytest.mark.unit


# Representative per-lane endpoint values (the same shape an operator overlay /
# the per-lane service env supplies). Dev, stability-test, and prod each point at
# a distinct endpoint; the overlay must resolve each identically to a raw env read.
_LANE_ENDPOINTS = [
    "http://localhost:8053",  # dev
    "http://intelligence.stability-test.svc:8053",  # stability-test
    "http://intelligence.prod.svc:8053",  # prod
]


@pytest.mark.parametrize("endpoint", _LANE_ENDPOINTS)
def test_intelligence_overlay_resolution_equals_direct_env_read(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Overlay descriptor resolves the same value the old env read produced."""
    monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", endpoint)

    # The value the pre-migration code read directly.
    direct = os.environ.get("INTELLIGENCE_SERVICE_URL", "")
    # The value the migrated overlay seam resolves.
    resolved = resolve_diagnostics_endpoint(
        EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE
    )

    assert resolved == direct == endpoint


@pytest.mark.parametrize("endpoint", _LANE_ENDPOINTS)
def test_main_server_overlay_resolution_equals_direct_env_read(
    endpoint: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MAIN_SERVER_URL resolves identically through the overlay seam."""
    monkeypatch.setenv("MAIN_SERVER_URL", endpoint)

    direct = os.environ.get("MAIN_SERVER_URL", "")
    resolved = resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MAIN_SERVER)

    assert resolved == direct == endpoint


def test_mcp_overlay_resolution_equals_direct_primary_env_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MCP_SERVER_URL primary var resolves identically through the overlay seam."""
    endpoint = "http://mcp.prod.svc:8051"
    monkeypatch.setenv("MCP_SERVER_URL", endpoint)
    monkeypatch.delenv("ONEX_MCP_URL", raising=False)
    monkeypatch.delenv("ARCHON_MCP_URL", raising=False)

    direct = (
        os.environ.get("MCP_SERVER_URL")
        or os.environ.get("ONEX_MCP_URL")
        or os.environ.get("ARCHON_MCP_URL", "")
    )
    resolved = resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MCP_SERVER)

    assert resolved == direct == endpoint


def test_mcp_alias_chain_preserves_legacy_onex_mcp_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP_SERVER_URL is unset, ONEX_MCP_URL is used (legacy alias)."""
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.setenv("ONEX_MCP_URL", "http://legacy-onex-mcp:8051")
    monkeypatch.delenv("ARCHON_MCP_URL", raising=False)

    direct = (
        os.environ.get("MCP_SERVER_URL")
        or os.environ.get("ONEX_MCP_URL")
        or os.environ.get("ARCHON_MCP_URL", "")
    )
    resolved = resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MCP_SERVER)

    assert resolved == direct == "http://legacy-onex-mcp:8051"


def test_mcp_alias_chain_preserves_legacy_archon_mcp_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When MCP_SERVER_URL and ONEX_MCP_URL are unset, ARCHON_MCP_URL is used."""
    monkeypatch.delenv("MCP_SERVER_URL", raising=False)
    monkeypatch.delenv("ONEX_MCP_URL", raising=False)
    monkeypatch.setenv("ARCHON_MCP_URL", "http://legacy-archon-mcp:8051")

    direct = (
        os.environ.get("MCP_SERVER_URL")
        or os.environ.get("ONEX_MCP_URL")
        or os.environ.get("ARCHON_MCP_URL", "")
    )
    resolved = resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MCP_SERVER)

    assert resolved == direct == "http://legacy-archon-mcp:8051"


@pytest.mark.parametrize(
    "endpoint",
    [
        EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE,
        EnumDiagnosticsEndpoint.MAIN_SERVER,
        EnumDiagnosticsEndpoint.MCP_SERVER,
    ],
)
def test_strict_accessor_fails_closed_when_env_unset(
    endpoint: EnumDiagnosticsEndpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strict accessor raises rather than returning a localhost default."""
    for var in (
        "INTELLIGENCE_SERVICE_URL",
        "MAIN_SERVER_URL",
        "MCP_SERVER_URL",
        "ONEX_MCP_URL",
        "ARCHON_MCP_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(ValueError, match=r"resolved empty"):
        resolve_diagnostics_endpoint_strict(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE,
        EnumDiagnosticsEndpoint.MAIN_SERVER,
        EnumDiagnosticsEndpoint.MCP_SERVER,
    ],
)
def test_strict_accessor_fails_closed_when_env_blank(
    endpoint: EnumDiagnosticsEndpoint, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Whitespace-only values are treated as unset and fail closed."""
    monkeypatch.setenv("INTELLIGENCE_SERVICE_URL", "   ")
    monkeypatch.setenv("MAIN_SERVER_URL", "   ")
    monkeypatch.setenv("MCP_SERVER_URL", "   ")
    monkeypatch.delenv("ONEX_MCP_URL", raising=False)
    monkeypatch.delenv("ARCHON_MCP_URL", raising=False)

    with pytest.raises(ValueError, match=r"resolved empty"):
        resolve_diagnostics_endpoint_strict(endpoint)


def test_non_strict_resolution_returns_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-strict resolution returns empty string when unset.

    Diagnostics is a fail-soft tool: it must never crash on import or run. The
    non-strict accessor preserves the pre-migration empty-string behavior so an
    unconfigured endpoint is reported as not-configured rather than raising.
    """
    for var in (
        "INTELLIGENCE_SERVICE_URL",
        "MAIN_SERVER_URL",
        "MCP_SERVER_URL",
        "ONEX_MCP_URL",
        "ARCHON_MCP_URL",
    ):
        monkeypatch.delenv(var, raising=False)

    assert (
        resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE) == ""
    )
    assert resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MAIN_SERVER) == ""
    assert resolve_diagnostics_endpoint(EnumDiagnosticsEndpoint.MCP_SERVER) == ""


def test_non_strict_resolution_returns_empty_when_contract_missing(
    tmp_path: Path,
) -> None:
    """Non-strict resolution fails soft if the contract cannot be opened."""
    missing_contract = tmp_path / "missing.yaml"

    assert (
        resolve_diagnostics_endpoint(
            EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE, missing_contract
        )
        == ""
    )


def test_non_strict_resolution_returns_empty_when_contract_malformed(
    tmp_path: Path,
) -> None:
    """Non-strict resolution fails soft if descriptor data is malformed."""
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump({"descriptor": {"diagnostics_intelligence_service_url": 7}}),
        encoding="utf-8",
    )

    assert (
        resolve_diagnostics_endpoint(
            EnumDiagnosticsEndpoint.INTELLIGENCE_SERVICE, contract
        )
        == ""
    )


def test_descriptor_reads_os_environ_only_inside_overlay_expander() -> None:
    """The descriptor module routes env access through the overlay expander only.

    Guards the canonical-seam invariant: the only ``os.environ`` *access* in the
    descriptor module is inside the ``${env.VAR}`` overlay expander
    (``_expand_contract_env_refs``), not bare reads scattered through the module.
    Counts real ``os.environ`` AST attribute accesses (not comment/docstring
    mentions).
    """
    mod = importlib.import_module(
        "omniclaude.lib.utils.diagnostics_endpoint_descriptor"
    )
    source = mod.__file__
    assert source is not None
    tree = ast.parse(Path(source).read_text(encoding="utf-8"))

    def _count_os_environ(node: ast.AST) -> int:
        return sum(
            1
            for n in ast.walk(node)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name)
            and n.value.id == "os"
            and n.attr == "environ"
        )

    total = _count_os_environ(tree)
    assert total == 1, (
        f"diagnostics_endpoint_descriptor must access os.environ exactly once "
        f"(inside the ${{env.VAR}} overlay expander); found {total} accesses"
    )

    expander = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "_expand_contract_env_refs"
        ),
        None,
    )
    assert expander is not None, "expected _expand_contract_env_refs expander function"
    assert _count_os_environ(expander) == 1, (
        "the single os.environ access must live inside the "
        "_expand_contract_env_refs overlay expander"
    )
