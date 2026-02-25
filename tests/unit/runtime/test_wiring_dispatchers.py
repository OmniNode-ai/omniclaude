# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Unit tests for wiring_dispatchers.py (OMN-2802).

Covers:
    - claude_code contract routes to SubprocessClaudeCodeSessionBackend
    - local_llm/CODE_ANALYSIS contract routes to VllmInferenceBackend
    - Missing dispatch engine returns skipped
    - Missing service registry returns skipped
    - Backend unavailable returns FAILED with error_code=BACKEND_UNAVAILABLE
    - Unknown skill_id returns FAILED with error_code=UNKNOWN_SKILL
    - Route matcher test (mandatory)
    - Contract loading and threshold validation
    - Skill ID extraction from topic
    - Skill ID extraction from contract name
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import yaml
from omnibase_core.enums import EnumMessageCategory

from omniclaude.nodes.shared.models.model_skill_node_contract import (
    ModelSkillNodeContract,
    ModelSkillNodeExecution,
)
from omniclaude.nodes.shared.models.model_skill_result import SkillResultStatus
from omniclaude.runtime.wiring_dispatchers import (
    ContractLoadError,
    SkillCommandDispatcher,
    _build_skill_route,
    _extract_skill_id_from_name,
    load_skill_contracts,
    wire_skill_dispatchers,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_contract(
    name: str = "node_skill_local_review_orchestrator",
    backend: str = "claude_code",
    model_purpose: str | None = None,
) -> ModelSkillNodeContract:
    """Create a test skill node contract."""
    return ModelSkillNodeContract(
        name=name,
        node_type="ORCHESTRATOR_GENERIC",
        execution=ModelSkillNodeExecution(
            backend=backend,
            model_purpose=model_purpose,
        ),
        event_bus={
            "subscribe": {
                "topic": f"onex.cmd.omniclaude.{_extract_skill_id_from_name(name)}.v1",
            },
            "publish": {
                "success_topic": f"onex.evt.omniclaude.{_extract_skill_id_from_name(name)}-completed.v1",
            },
        },
    )


def _make_materialized_envelope(
    topic: str,
    payload: dict[str, Any] | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Create a materialized dispatch dict matching the engine output format."""
    return {
        "payload": payload or {},
        "__bindings": {},
        "__debug_trace": {
            "topic": topic,
            "correlation_id": correlation_id or str(uuid4()),
            "event_type": None,
            "trace_id": None,
        },
    }


def _mock_claude_code_backend(
    output: str = "RESULT:\nstatus: success\nerror:\n",
) -> Any:
    """Create a mock SubprocessClaudeCodeSessionBackend."""
    backend = MagicMock()
    backend.handler_key = "subprocess"

    result = MagicMock()
    result.output = output
    result.status = SkillResultStatus.SUCCESS
    backend.session_query = AsyncMock(return_value=result)

    return backend


def _mock_vllm_backend(output: str = "RESULT:\nstatus: success\nerror:\n") -> Any:
    """Create a mock VllmInferenceBackend."""
    backend = MagicMock()
    backend.handler_key = "vllm"

    result = MagicMock()
    result.output = output
    result.status = SkillResultStatus.SUCCESS
    backend.infer = AsyncMock(return_value=result)

    return backend


# ---------------------------------------------------------------------------
# Route matcher tests (mandatory per ticket)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRouteMatcher:
    """Route matcher tests — mandatory per OMN-2802 definition of done."""

    def test_route_matches_onex_status_topic(self) -> None:
        """Route matches onex.cmd.omniclaude.onex-status.v1."""
        route = _build_skill_route()
        assert route.matches_topic("onex.cmd.omniclaude.onex-status.v1")

    def test_route_matches_create_ticket_topic(self) -> None:
        """Route matches onex.cmd.omniclaude.create-ticket.v1."""
        route = _build_skill_route()
        assert route.matches_topic("onex.cmd.omniclaude.create-ticket.v1")

    def test_route_does_not_match_other_domain(self) -> None:
        """Route does NOT match topics from other domains."""
        route = _build_skill_route()
        assert not route.matches_topic("onex.cmd.omniintelligence.foo.v1")

    def test_route_does_not_match_event_topic(self) -> None:
        """Route does NOT match event topics (only command topics)."""
        route = _build_skill_route()
        assert not route.matches_topic("onex.evt.omniclaude.onex-status-completed.v1")

    def test_route_has_correct_handler_id(self) -> None:
        """Route references the skill command dispatcher."""
        route = _build_skill_route()
        assert route.handler_id == "dispatcher.skill.command"

    def test_route_has_command_category(self) -> None:
        """Route is configured for COMMAND category."""
        route = _build_skill_route()
        assert route.message_category == EnumMessageCategory.COMMAND

    def test_route_accepts_all_message_types(self) -> None:
        """Route has message_type=None (matches all types)."""
        route = _build_skill_route()
        assert route.message_type is None


# ---------------------------------------------------------------------------
# Skill ID extraction tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractSkillId:
    """Tests for _extract_skill_id_from_name()."""

    def test_standard_name_extraction(self) -> None:
        """Standard convention extracts skill_id with hyphens."""
        result = _extract_skill_id_from_name("node_skill_local_review_orchestrator")
        assert result == "local-review"

    def test_single_word_skill(self) -> None:
        """Single-word skill name."""
        result = _extract_skill_id_from_name("node_skill_commit_orchestrator")
        assert result == "commit"

    def test_multi_word_skill(self) -> None:
        """Multi-word skill with underscores becomes hyphens."""
        result = _extract_skill_id_from_name("node_skill_pr_review_dev_orchestrator")
        assert result == "pr-review-dev"

    def test_fallback_for_non_standard_name(self) -> None:
        """Non-standard names fall back to hyphenated full name."""
        result = _extract_skill_id_from_name("some_other_node")
        assert result == "some-other-node"


@pytest.mark.unit
class TestExtractSkillIdFromTopic:
    """Tests for SkillCommandDispatcher._extract_skill_id()."""

    def test_valid_topic(self) -> None:
        result = SkillCommandDispatcher._extract_skill_id(
            "onex.cmd.omniclaude.local-review.v1"
        )
        assert result == "local-review"

    def test_none_topic(self) -> None:
        result = SkillCommandDispatcher._extract_skill_id(None)
        assert result is None

    def test_wrong_domain(self) -> None:
        result = SkillCommandDispatcher._extract_skill_id(
            "onex.cmd.omniintelligence.foo.v1"
        )
        assert result is None

    def test_event_topic(self) -> None:
        result = SkillCommandDispatcher._extract_skill_id(
            "onex.evt.omniclaude.local-review-completed.v1"
        )
        assert result is None

    def test_too_few_segments(self) -> None:
        result = SkillCommandDispatcher._extract_skill_id("onex.cmd.omniclaude")
        assert result is None


# ---------------------------------------------------------------------------
# Contract loading tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContractLoading:
    """Tests for load_skill_contracts()."""

    def test_loads_valid_contracts(self, tmp_path: Path) -> None:
        """Valid contracts are loaded and keyed by skill_id."""
        node_dir = tmp_path / "node_skill_commit_orchestrator"
        node_dir.mkdir()
        contract_data = {
            "name": "node_skill_commit_orchestrator",
            "node_type": "ORCHESTRATOR_GENERIC",
            "execution": {"backend": "claude_code", "model_purpose": None},
            "event_bus": {
                "subscribe": {"topic": "onex.cmd.omniclaude.commit.v1"},
                "publish": {"success_topic": "onex.evt.omniclaude.commit-completed.v1"},
            },
        }
        (node_dir / "contract.yaml").write_text(yaml.dump(contract_data))

        contracts, total = load_skill_contracts(tmp_path)
        assert "commit" in contracts
        assert contracts["commit"].execution.backend == "claude_code"
        assert total == 1

    def test_threshold_failure_raises(self, tmp_path: Path) -> None:
        """Parse rate below 80% raises ContractLoadError."""
        # Create 5 dirs, 4 with invalid contracts
        for i in range(5):
            node_dir = tmp_path / f"node_skill_test{i}_orchestrator"
            node_dir.mkdir()
            if i == 0:
                # Valid
                data = {
                    "name": f"node_skill_test{i}_orchestrator",
                    "node_type": "ORCHESTRATOR_GENERIC",
                    "execution": {"backend": "claude_code"},
                    "event_bus": {"subscribe": {}, "publish": {}},
                }
            else:
                # Invalid (missing required fields)
                data = {"invalid": True}
            (node_dir / "contract.yaml").write_text(yaml.dump(data))

        with pytest.raises(ContractLoadError) as exc_info:
            load_skill_contracts(tmp_path)
        assert exc_info.value.parsed == 1
        assert exc_info.value.total == 5

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        """No skill node directories returns empty dict."""
        contracts, total = load_skill_contracts(tmp_path)
        assert contracts == {}
        assert total == 0


# ---------------------------------------------------------------------------
# Dispatcher routing tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkillCommandDispatcher:
    """Tests for SkillCommandDispatcher.handle()."""

    @pytest.mark.asyncio
    async def test_claude_code_routes_to_subprocess_backend(self) -> None:
        """claude_code contract routes to SubprocessClaudeCodeSessionBackend."""
        cc_backend = _mock_claude_code_backend()
        contracts = {
            "local-review": _make_contract(
                name="node_skill_local_review_orchestrator",
                backend="claude_code",
            ),
        }
        dispatcher = SkillCommandDispatcher(
            contracts=contracts,
            claude_code_backend=cc_backend,
            vllm_backend=None,
        )

        envelope = _make_materialized_envelope(
            topic="onex.cmd.omniclaude.local-review.v1",
        )
        result = await dispatcher.handle(envelope)

        assert result is not None
        assert "dispatched:local-review:" in result
        cc_backend.session_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_local_llm_routes_to_vllm_backend(self) -> None:
        """local_llm/CODE_ANALYSIS contract routes to VllmInferenceBackend."""
        vllm_backend = _mock_vllm_backend()
        contracts = {
            "code-analysis": _make_contract(
                name="node_skill_code_analysis_orchestrator",
                backend="local_llm",
                model_purpose="CODE_ANALYSIS",
            ),
        }
        dispatcher = SkillCommandDispatcher(
            contracts=contracts,
            claude_code_backend=None,
            vllm_backend=vllm_backend,
        )

        envelope = _make_materialized_envelope(
            topic="onex.cmd.omniclaude.code-analysis.v1",
        )
        result = await dispatcher.handle(envelope)

        assert result is not None
        assert "dispatched:code-analysis:" in result
        vllm_backend.infer.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_skill_returns_none(self) -> None:
        """Unknown skill_id results in None return (UNKNOWN_SKILL)."""
        dispatcher = SkillCommandDispatcher(
            contracts={},
            claude_code_backend=_mock_claude_code_backend(),
            vllm_backend=None,
        )

        envelope = _make_materialized_envelope(
            topic="onex.cmd.omniclaude.nonexistent.v1",
        )
        result = await dispatcher.handle(envelope)
        assert result is None

    @pytest.mark.asyncio
    async def test_claude_code_backend_unavailable(self) -> None:
        """BACKEND_UNAVAILABLE when claude_code backend is None."""
        contracts = {
            "commit": _make_contract(backend="claude_code"),
        }
        dispatcher = SkillCommandDispatcher(
            contracts=contracts,
            claude_code_backend=None,  # Unavailable
            vllm_backend=None,
        )

        envelope = _make_materialized_envelope(
            topic="onex.cmd.omniclaude.commit.v1",
        )
        # Should not raise; returns None indicating failure
        result = await dispatcher.handle(envelope)
        assert result is None

    @pytest.mark.asyncio
    async def test_vllm_backend_unavailable(self) -> None:
        """BACKEND_UNAVAILABLE when vllm backend is None for local_llm contract."""
        contracts = {
            "code-analysis": _make_contract(
                name="node_skill_code_analysis_orchestrator",
                backend="local_llm",
                model_purpose="CODE_ANALYSIS",
            ),
        }
        dispatcher = SkillCommandDispatcher(
            contracts=contracts,
            claude_code_backend=None,
            vllm_backend=None,  # Unavailable
        )

        envelope = _make_materialized_envelope(
            topic="onex.cmd.omniclaude.code-analysis.v1",
        )
        result = await dispatcher.handle(envelope)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_topic_in_envelope(self) -> None:
        """Envelope with no topic returns None."""
        dispatcher = SkillCommandDispatcher(
            contracts={"commit": _make_contract()},
            claude_code_backend=_mock_claude_code_backend(),
            vllm_backend=None,
        )

        envelope = {
            "payload": {},
            "__bindings": {},
            "__debug_trace": {"topic": None},
        }
        result = await dispatcher.handle(envelope)
        assert result is None


# ---------------------------------------------------------------------------
# wire_skill_dispatchers integration tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWireSkillDispatchers:
    """Tests for wire_skill_dispatchers()."""

    @pytest.mark.asyncio
    async def test_missing_contracts_root_returns_empty(self) -> None:
        """No OMNICLAUDE_CONTRACTS_ROOT and no explicit root returns empty summary."""
        mock_engine = MagicMock()
        mock_container = MagicMock()

        # Ensure env var is not set
        env = os.environ.copy()
        env.pop("OMNICLAUDE_CONTRACTS_ROOT", None)
        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("OMNICLAUDE_CONTRACTS_ROOT", raising=False)
            summary = await wire_skill_dispatchers(
                mock_container,
                mock_engine,
            )

        assert summary["dispatchers"] == []
        assert summary["contracts_loaded"] == 0

    @pytest.mark.asyncio
    async def test_wires_with_valid_contracts(self, tmp_path: Path) -> None:
        """With valid contracts, dispatcher and route are registered."""
        # Create a contract
        node_dir = tmp_path / "node_skill_commit_orchestrator"
        node_dir.mkdir()
        contract_data = {
            "name": "node_skill_commit_orchestrator",
            "node_type": "ORCHESTRATOR_GENERIC",
            "execution": {"backend": "claude_code", "model_purpose": None},
            "event_bus": {
                "subscribe": {"topic": "onex.cmd.omniclaude.commit.v1"},
                "publish": {"success_topic": "onex.evt.omniclaude.commit-completed.v1"},
            },
        }
        (node_dir / "contract.yaml").write_text(yaml.dump(contract_data))

        mock_engine = MagicMock()
        mock_container = MagicMock()
        mock_container.service_registry = None

        summary = await wire_skill_dispatchers(
            mock_container,
            mock_engine,
            contracts_root=tmp_path,
        )

        assert summary["dispatchers"] == ["dispatcher.skill.command"]
        assert summary["routes"] == ["skill-command-router"]
        assert summary["contracts_loaded"] == 1
        mock_engine.register_dispatcher.assert_called_once()
        mock_engine.register_route.assert_called_once()


# ---------------------------------------------------------------------------
# Plugin wire_dispatchers tests (skipped/missing scenarios)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPluginWireDispatchers:
    """Tests for PluginClaude.wire_dispatchers() skip paths."""

    @pytest.mark.asyncio
    async def test_missing_dispatch_engine_returns_skipped(self) -> None:
        """wire_dispatchers returns skipped when dispatch_engine is None."""
        from omniclaude.runtime.plugin import PluginClaude

        plugin = PluginClaude()
        config = MagicMock()
        config.dispatch_engine = None

        result = await plugin.wire_dispatchers(config)

        # skipped() sets success=True but message indicates skip
        assert "dispatch_engine" in (result.message or "")
        assert result.resources_created == []

    @pytest.mark.asyncio
    async def test_missing_service_registry_returns_skipped(self) -> None:
        """wire_dispatchers returns skipped when no contracts root is set."""
        from omniclaude.runtime.plugin import PluginClaude

        plugin = PluginClaude()
        config = MagicMock()
        config.dispatch_engine = MagicMock()
        config.container = MagicMock()
        config.container.service_registry = None
        config.correlation_id = uuid4()

        with pytest.MonkeyPatch.context() as mp:
            mp.delenv("OMNICLAUDE_CONTRACTS_ROOT", raising=False)
            result = await plugin.wire_dispatchers(config)

        # Should be skipped because no contracts root set
        assert result.resources_created == []
        assert (
            "skipped" in (result.message or "").lower()
            or "no skill dispatchers" in (result.message or "").lower()
        )
