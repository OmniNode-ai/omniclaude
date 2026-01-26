# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
#
# ONEX Hook Event Contracts
#
# This module contains YAML contract definitions for Claude Code hook events.
# Contracts define the schema, event bus configuration, and validation rules.

"""ONEX contracts for Claude Code hook events."""

from __future__ import annotations

from pathlib import Path

# Contract directory location
CONTRACTS_DIR = Path(__file__).parent

# Contract file paths
CONTRACT_SESSION_STARTED = CONTRACTS_DIR / "contract_hook_session_started.yaml"
CONTRACT_SESSION_ENDED = CONTRACTS_DIR / "contract_hook_session_ended.yaml"
CONTRACT_PROMPT_SUBMITTED = CONTRACTS_DIR / "contract_hook_prompt_submitted.yaml"
CONTRACT_TOOL_EXECUTED = CONTRACTS_DIR / "contract_hook_tool_executed.yaml"

__all__ = [
    "CONTRACTS_DIR",
    "CONTRACT_SESSION_STARTED",
    "CONTRACT_SESSION_ENDED",
    "CONTRACT_PROMPT_SUBMITTED",
    "CONTRACT_TOOL_EXECUTED",
]
