# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for audit_dispatch_validator (OMN-5236).

Validates:
- Permissive default: agents without context_integrity subcontract always pass.
- STRICT/PARANOID mode: missing metadata.context_integrity_contract_id is a hard block.
- STRICT mode: unknown contract ID is WARN only (non-blocking).
- PARANOID mode: unknown contract ID is a hard block.
- Agents with context_integrity subcontract and valid contract ID pass.
- Enforcement level resolution from env var and override argument.
- YAML config load failure defaults to permissive pass.
- Agent config without a yaml file defaults to permissive pass.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from omniclaude.hooks.handlers.audit_dispatch_validator import (
    _REGISTRY_LOAD_ERROR,
    DispatchValidationResult,
    _extract_context_integrity_scopes,
    _get_context_integrity_contract_id,
    _has_context_integrity_subcontract,
    _load_agent_yaml,
    _resolve_enforcement_level,
    validate_dispatch,
)

pytestmark = pytest.mark.unit


# =============================================================================
# Fixtures / helpers
# =============================================================================


def _make_agent_config(
    *,
    with_ci_subcontract: bool = False,
    contract_id: str | None = None,
    scopes: dict[str, Any] | None = None,
    ci_in_contracts_key: bool = True,
) -> dict[str, Any]:
    """Build a minimal agent config dict for testing.

    Args:
        with_ci_subcontract: Whether to declare a context_integrity subcontract.
        contract_id: Value for metadata.context_integrity_contract_id.
        scopes: Scope dict to embed in the context_integrity section.
        ci_in_contracts_key: If True, embed under contracts.subcontracts;
            if False, use top-level context_integrity key.

    Returns:
        Agent config dict.
    """
    config: dict[str, Any] = {
        "schema_version": "1.0.0",
        "agent_type": "test_agent",
    }

    if with_ci_subcontract:
        if ci_in_contracts_key:
            ci_data: dict[str, Any] = {}
            if scopes:
                ci_data.update(scopes)
            config["contracts"] = {
                "subcontracts": ["context_integrity"],
                "context_integrity": ci_data,
            }
        else:
            config["context_integrity"] = scopes or {}

    if contract_id is not None:
        config["metadata"] = {"context_integrity_contract_id": contract_id}

    return config


# =============================================================================
# _has_context_integrity_subcontract
# =============================================================================


class TestHasContextIntegritySubcontract:
    """Tests for _has_context_integrity_subcontract."""

    def test_no_subcontract_returns_false(self) -> None:
        config = _make_agent_config(with_ci_subcontract=False)
        assert _has_context_integrity_subcontract(config) is False

    def test_subcontract_in_contracts_subcontracts_list(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, ci_in_contracts_key=True)
        assert _has_context_integrity_subcontract(config) is True

    def test_top_level_context_integrity_key(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, ci_in_contracts_key=False)
        assert _has_context_integrity_subcontract(config) is True

    def test_empty_config_returns_false(self) -> None:
        assert _has_context_integrity_subcontract({}) is False

    def test_unrelated_subcontracts_only_returns_false(self) -> None:
        config: dict[str, Any] = {
            "contracts": {"subcontracts": ["fsm", "event_type"]},
        }
        assert _has_context_integrity_subcontract(config) is False


# =============================================================================
# _get_context_integrity_contract_id
# =============================================================================


class TestGetContextIntegrityContractId:
    """Tests for _get_context_integrity_contract_id."""

    def test_returns_none_when_not_set(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True)
        assert _get_context_integrity_contract_id(config) is None

    def test_returns_contract_id_string(self) -> None:
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="node_poly_enforcer_effect"
        )
        assert _get_context_integrity_contract_id(config) == "node_poly_enforcer_effect"

    def test_missing_metadata_key_returns_none(self) -> None:
        config: dict[str, Any] = {"metadata": {"other_key": "value"}}
        assert _get_context_integrity_contract_id(config) is None

    def test_metadata_not_dict_returns_none(self) -> None:
        config: dict[str, Any] = {"metadata": "invalid"}
        assert _get_context_integrity_contract_id(config) is None


# =============================================================================
# _extract_context_integrity_scopes
# =============================================================================


class TestExtractContextIntegrityScopes:
    """Tests for _extract_context_integrity_scopes."""

    def test_empty_config_returns_empty_dict(self) -> None:
        assert _extract_context_integrity_scopes({}) == {}

    def test_extracts_scopes_from_contracts_key(self) -> None:
        config = _make_agent_config(
            with_ci_subcontract=True,
            scopes={"tool_scope": ["Read", "Glob"], "memory_scope": ["namespace-a"]},
            ci_in_contracts_key=True,
        )
        scopes = _extract_context_integrity_scopes(config)
        assert scopes.get("tool_scope") == ["Read", "Glob"]
        assert scopes.get("memory_scope") == ["namespace-a"]

    def test_extracts_scopes_from_top_level_key(self) -> None:
        config = _make_agent_config(
            with_ci_subcontract=True,
            scopes={"retrieval_sources": ["qdrant"]},
            ci_in_contracts_key=False,
        )
        scopes = _extract_context_integrity_scopes(config)
        assert scopes.get("retrieval_sources") == ["qdrant"]

    def test_ignores_non_scope_keys(self) -> None:
        config: dict[str, Any] = {
            "context_integrity": {
                "tool_scope": ["Bash"],
                "unknown_key": "should_be_ignored",
            }
        }
        scopes = _extract_context_integrity_scopes(config)
        assert "unknown_key" not in scopes
        assert scopes.get("tool_scope") == ["Bash"]


# =============================================================================
# _resolve_enforcement_level
# =============================================================================


class TestResolveEnforcementLevel:
    """Tests for _resolve_enforcement_level."""

    def test_override_takes_priority(self) -> None:
        assert _resolve_enforcement_level("STRICT") == "STRICT"

    def test_env_var_used_when_no_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("AUDIT_ENFORCEMENT_LEVEL", "PARANOID")
        assert _resolve_enforcement_level(None) == "PARANOID"

    def test_default_is_permissive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUDIT_ENFORCEMENT_LEVEL", raising=False)
        assert _resolve_enforcement_level(None) == "PERMISSIVE"

    def test_unknown_level_falls_back_to_permissive(self) -> None:
        assert _resolve_enforcement_level("UNKNOWN_LEVEL") == "PERMISSIVE"

    def test_case_insensitive_override(self) -> None:
        assert _resolve_enforcement_level("strict") == "STRICT"

    def test_all_known_levels_accepted(self) -> None:
        for level in ("PERMISSIVE", "WARN", "STRICT", "PARANOID"):
            assert _resolve_enforcement_level(level) == level


# =============================================================================
# validate_dispatch — permissive default
# =============================================================================


class TestValidateDispatchPermissiveDefault:
    """Tests that agents without context_integrity pass by default."""

    def test_no_ci_subcontract_permissive_pass(self) -> None:
        config = _make_agent_config(with_ci_subcontract=False)
        with patch(
            "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
            return_value=config,
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True
        assert result.has_context_integrity is False

    def test_agent_config_not_found_passes(self) -> None:
        with patch(
            "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
            return_value=None,
        ):
            result = validate_dispatch(
                "onex:missing-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True
        assert result.has_context_integrity is False


# =============================================================================
# validate_dispatch — STRICT mode
# =============================================================================


class TestValidateDispatchStrictMode:
    """Tests for STRICT enforcement level."""

    def test_missing_contract_id_is_blocked(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is False
        assert "context_integrity_contract_id" in result.reason
        assert "node_poly_enforcer_effect" in result.reason

    def test_valid_contract_id_passes(self) -> None:
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="node_poly_enforcer_effect"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True
        assert result.contract_id == "node_poly_enforcer_effect"

    def test_unknown_contract_id_is_warn_only_in_strict(self) -> None:
        """STRICT mode: stale/unknown contract IDs emit WARN but do not block."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="stale-contract-id"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True

    def test_empty_registry_skips_unknown_check(self) -> None:
        """When registry is empty, no unknown-ID check is performed."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="any-contract-id"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=[],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True

    def test_block_message_lists_known_contract_ids(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["id-one", "id-two"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is False
        assert "id-one" in result.reason
        assert "id-two" in result.reason


# =============================================================================
# validate_dispatch — PARANOID mode
# =============================================================================


class TestValidateDispatchParanoidMode:
    """Tests for PARANOID enforcement level."""

    def test_missing_contract_id_is_blocked(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="PARANOID",
                quiet_emit=True,
            )
        assert result.allowed is False

    def test_unknown_contract_id_is_blocked(self) -> None:
        """PARANOID mode: unknown contract ID is a hard block."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="unknown-stale-id"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="PARANOID",
                quiet_emit=True,
            )
        assert result.allowed is False
        assert "unknown-stale-id" in result.reason

    def test_valid_contract_id_passes(self) -> None:
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="node_poly_enforcer_effect"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="PARANOID",
                quiet_emit=True,
            )
        assert result.allowed is True


# =============================================================================
# validate_dispatch — PERMISSIVE and WARN mode
# =============================================================================


class TestValidateDispatchPermissiveWarnModes:
    """Tests for PERMISSIVE and WARN enforcement levels."""

    def test_permissive_no_block_for_missing_contract_id(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="PERMISSIVE",
                quiet_emit=True,
            )
        assert result.allowed is True

    def test_warn_no_block_for_missing_contract_id(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="WARN",
                quiet_emit=True,
            )
        assert result.allowed is True


# =============================================================================
# validate_dispatch — misconfiguration is hard block
# =============================================================================


class TestValidateDispatchMisconfiguration:
    """Tests verifying misconfiguration results in a hard block (not soft warn)."""

    def test_strict_missing_contract_id_results_in_block_not_warn(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["valid-id"],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        # allowed=False means hard block, not soft warn
        assert result.allowed is False
        assert result.has_context_integrity is True

    def test_result_contains_enforcement_level(self) -> None:
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=[],
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.enforcement_level == "STRICT"


# =============================================================================
# DispatchValidationResult
# =============================================================================


class TestDispatchValidationResult:
    """Tests for DispatchValidationResult."""

    def test_allowed_result_attributes(self) -> None:
        r = DispatchValidationResult(
            allowed=True,
            reason="passed",
            contract_id="contract-abc",
            has_context_integrity=True,
            enforcement_level="STRICT",
        )
        assert r.allowed is True
        assert r.reason == "passed"
        assert r.contract_id == "contract-abc"
        assert r.has_context_integrity is True
        assert r.enforcement_level == "STRICT"

    def test_blocked_result_attributes(self) -> None:
        r = DispatchValidationResult(
            allowed=False,
            reason="contract_id missing",
            contract_id="",
            has_context_integrity=True,
            enforcement_level="PARANOID",
        )
        assert r.allowed is False
        assert r.contract_id == ""


# =============================================================================
# Path-traversal guard in _load_agent_yaml
# =============================================================================


class TestLoadAgentYamlPathSafety:
    """Tests that _load_agent_yaml rejects unsafe agent name suffixes."""

    @pytest.mark.parametrize(
        "subagent_type",
        [
            "onex:../../hooks/context_integrity_contracts",
            "onex:../some/path",
            "onex:agent name with spaces",
            "onex:agent!name",
            "onex:agent/name",
            "onex:agent\\name",
        ],
    )
    def test_unsafe_agent_name_returns_none(self, subagent_type: str) -> None:
        """Crafted subagent_type values with path-traversal characters must return None."""
        result = _load_agent_yaml(subagent_type)
        assert result is None, (
            f"Expected None for unsafe subagent_type {subagent_type!r}"
        )

    @pytest.mark.parametrize(
        "subagent_type",
        [
            "onex:polymorphic-agent",
            "onex:my-agent",
            "onex:agent_name",
            "onex:AgentName123",
            "plain-agent",
        ],
    )
    def test_safe_agent_name_proceeds_to_file_lookup(self, subagent_type: str) -> None:
        """Safe agent names should proceed to file lookup (not crash on name validation)."""
        # We don't have a real configs dir in tests — just verify no ValueError is raised
        # from the name-validation step itself. The function returns None when config
        # dir or file is absent, which is the expected permissive-pass behaviour.
        result = _load_agent_yaml(subagent_type)
        # Result is None (file not found) or a dict (if config exists) — never an exception
        assert result is None or isinstance(result, dict)


# =============================================================================
# PARANOID registry-fail-closed behaviour
# =============================================================================


class TestParanoidRegistryFailClosed:
    """Tests that PARANOID mode fails closed when the registry cannot be loaded."""

    def test_paranoid_blocks_when_registry_load_error(self) -> None:
        """PARANOID: registry file exists but is unreadable → hard block."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="any-contract-id"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=_REGISTRY_LOAD_ERROR,
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="PARANOID",
                quiet_emit=True,
            )
        assert result.allowed is False
        assert "registry" in result.reason.lower()

    def test_strict_allows_when_registry_load_error(self) -> None:
        """STRICT: registry file exists but is unreadable → allow with warning (non-blocking)."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="any-contract-id"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=_REGISTRY_LOAD_ERROR,
            ),
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True


# =============================================================================
# Correlation manager called only after block decision
# =============================================================================


class TestCorrelationManagerOrderOfOperations:
    """Tests that _record_dispatch_in_correlation_manager is only called for allowed dispatches."""

    def test_correlation_manager_not_called_when_blocked_strict(self) -> None:
        """Blocked dispatch (STRICT, missing contract_id) must NOT record in correlation manager."""
        config = _make_agent_config(with_ci_subcontract=True, contract_id=None)
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=[],
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ) as mock_record,
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is False
        mock_record.assert_not_called()

    def test_correlation_manager_called_when_allowed(self) -> None:
        """Allowed dispatch (valid contract_id) MUST record in correlation manager."""
        config = _make_agent_config(
            with_ci_subcontract=True, contract_id="node_poly_enforcer_effect"
        )
        with (
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_agent_yaml",
                return_value=config,
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._load_known_contract_ids",
                return_value=["node_poly_enforcer_effect"],
            ),
            patch(
                "omniclaude.hooks.handlers.audit_dispatch_validator._record_dispatch_in_correlation_manager",
            ) as mock_record,
        ):
            result = validate_dispatch(
                "onex:test-agent",
                enforcement_level="STRICT",
                quiet_emit=True,
            )
        assert result.allowed is True
        mock_record.assert_called_once()
