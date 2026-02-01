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

from omniclaude.hooks.contracts.contract_experiment_cohort import (
    Auditability,
    Cohort,
    EnvOverrides,
    Experiment,
    ExperimentCohortContract,
    Invariant,
    Metadata,
    Version,
)
from omniclaude.hooks.contracts.contract_hook_prompt_submitted import (
    HookPromptSubmittedContract,
    Privacy,
)
from omniclaude.hooks.contracts.contract_hook_session_ended import (
    HookSessionEndedContract,
)
from omniclaude.hooks.contracts.contract_hook_session_started import (
    HookSessionStartedContract,
)
from omniclaude.hooks.contracts.contract_hook_tool_executed import (
    Capability,
    Dependency,
    EventBus,
    HookToolExecutedContract,
    ModelReference,
    Runtime,
    TimestampPolicy,
    ToolMatching,
)
from omniclaude.hooks.contracts.schema import (
    ModelJsonSchemaDefinition,
    ModelJsonSchemaProperty,
    assert_no_extra_fields,
)

# Contract directory location
CONTRACTS_DIR = Path(__file__).parent

# Contract file paths
CONTRACT_SESSION_STARTED = CONTRACTS_DIR / "contract_hook_session_started.yaml"
CONTRACT_SESSION_ENDED = CONTRACTS_DIR / "contract_hook_session_ended.yaml"
CONTRACT_PROMPT_SUBMITTED = CONTRACTS_DIR / "contract_hook_prompt_submitted.yaml"
CONTRACT_TOOL_EXECUTED = CONTRACTS_DIR / "contract_hook_tool_executed.yaml"
CONTRACT_EXPERIMENT_COHORT = CONTRACTS_DIR / "contract_experiment_cohort.yaml"

__all__ = [
    # Directory
    "CONTRACTS_DIR",
    # Contract file paths
    "CONTRACT_SESSION_STARTED",
    "CONTRACT_SESSION_ENDED",
    "CONTRACT_PROMPT_SUBMITTED",
    "CONTRACT_TOOL_EXECUTED",
    "CONTRACT_EXPERIMENT_COHORT",
    # Experiment cohort contract models
    "ExperimentCohortContract",
    "Version",
    "Cohort",
    "EnvOverrides",
    "Experiment",
    "Invariant",
    "Auditability",
    "Metadata",
    # Hook prompt submitted contract models
    "HookPromptSubmittedContract",
    "Privacy",
    # Shared JSON Schema models (canonical source)
    "ModelJsonSchemaDefinition",
    "ModelJsonSchemaProperty",
    "assert_no_extra_fields",
    # Hook session started contract
    "HookSessionStartedContract",
    # Hook session ended contract
    "HookSessionEndedContract",
    # Hook tool executed contract models
    "HookToolExecutedContract",
    "ModelReference",
    "EventBus",
    "Runtime",
    "TimestampPolicy",
    "ToolMatching",
    "Dependency",
    "Capability",
]
