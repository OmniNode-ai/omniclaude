# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit tests verifying the delegate skill stays dispatch-only."""

from __future__ import annotations

from pathlib import Path

_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent.parent.parent
_DELEGATE_SKILL = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate"
_PROMPT_PATH = _DELEGATE_SKILL / "prompt.md"
_SKILL_PATH = _DELEGATE_SKILL / "SKILL.md"
_RUN_PATH = _DELEGATE_SKILL / "_lib" / "run.py"


def test_run_py_has_no_legacy_transport_tokens() -> None:
    source = _PROMPT_PATH.read_text(encoding="utf-8")
    forbidden = (
        "confluent_kafka",
        "urllib.request",
        "ssh",
        "pandaproxy",
        "InProcessDelegationRunner",
        "_call_llm_via_curl",
        "emit_event",
    )

    for token in forbidden:
        assert token not in source


def test_run_py_has_no_legacy_dispatch_helpers() -> None:
    source = _PROMPT_PATH.read_text(encoding="utf-8")
    forbidden_helpers = (
        "_dispatch_via_",
        "_run_inprocess",
        "_resolve_transport_config",
        "_resolve_command_topic",
        "_DELEGATION_REQUEST_TOPIC",
        "_HAS_INPROCESS_RUNNER",
    )

    for helper in forbidden_helpers:
        assert helper not in source


def test_legacy_python_bridge_is_deleted() -> None:
    assert not _RUN_PATH.exists()
    skill = _SKILL_PATH.read_text(encoding="utf-8")
    prompt = _PROMPT_PATH.read_text(encoding="utf-8")
    assert "node_delegate_skill_orchestrator" in skill
    assert "uv run onex node node_delegate_skill_orchestrator" in prompt


def test_no_runtime_transport_env_vars_read_by_skill_surface() -> None:
    source = _PROMPT_PATH.read_text(encoding="utf-8")
    for name in (
        "KAFKA_BOOTSTRAP_SERVERS",
        "ONEX_RUNTIME_URL",
        "ONEX_PANDAPROXY_URL",
        "ONEX_RUNTIME_SSH_HOST",
        "LLM_CODER_URL",
        "LLM_DEEPSEEK_R1_URL",
    ):
        assert name not in source
