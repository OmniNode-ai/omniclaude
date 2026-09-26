# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Typed, deterministic capture contract for Claude Code hook stdin."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_validator,
    model_validator,
)

HOOK_CAPTURE_NAMESPACE = UUID("9449178f-fb63-5b0d-b17d-379aafbcfe67")
HOOK_EVENT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"


class UnknownHookEventError(ValueError):
    """Raised when stdin names a hook event outside the captured contract."""


class InvalidHookInputError(ValueError):
    """Raised when hook stdin does not satisfy the captured contract."""


class MissingHookFieldError(InvalidHookInputError):
    """Raised when hook stdin omits a field required by Claude Code's schema."""


class EnumClaudeHookEventName(StrEnum):
    """Claude Code 2.1.283 hook event names."""

    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    POST_TOOL_BATCH = "PostToolBatch"
    NOTIFICATION = "Notification"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    USER_PROMPT_EXPANSION = "UserPromptExpansion"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    STOP = "Stop"
    STOP_FAILURE = "StopFailure"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_STOP = "SubagentStop"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    PRE_MODEL_SWITCH = "PreModelSwitch"
    POST_MODEL_SWITCH = "PostModelSwitch"
    PERMISSION_REQUEST = "PermissionRequest"
    PERMISSION_DENIED = "PermissionDenied"
    SETUP = "Setup"
    TEAMMATE_IDLE = "TeammateIdle"
    TASK_CREATED = "TaskCreated"
    TASK_COMPLETED = "TaskCompleted"
    ELICITATION = "Elicitation"
    ELICITATION_RESULT = "ElicitationResult"
    CONFIG_CHANGE = "ConfigChange"
    WORKTREE_CREATE = "WorktreeCreate"
    WORKTREE_REMOVE = "WorktreeRemove"
    INSTRUCTIONS_LOADED = "InstructionsLoaded"
    CWD_CHANGED = "CwdChanged"
    FILE_CHANGED = "FileChanged"
    DIRECTORY_ADDED = "DirectoryAdded"
    MESSAGE_DISPLAY = "MessageDisplay"


class _FrozenModel(BaseModel):
    """Bus-crossing event schema: frozen, additive-tolerant (repo invariant)."""

    model_config = ConfigDict(frozen=True, extra="ignore", from_attributes=True)


class _StrictModel(BaseModel):
    """Local input parser or result holder: frozen, and rejects unknown keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelContentScrubResult(_StrictModel):
    """Output of the producer's span scrub over one serialised content value."""

    value: str
    redaction_state: Literal["clean", "secret_detected"]
    matched_pattern_names: tuple[str, ...]

    @model_validator(mode="after")
    def validate_state(self) -> ModelContentScrubResult:
        if (self.redaction_state == "secret_detected") != bool(
            self.matched_pattern_names
        ):
            raise ValueError(
                "redaction_state is secret_detected exactly when a pattern matched"
            )
        return self


ContentScrubber = Callable[[str], ModelContentScrubResult]


class ModelHookContentRef(_FrozenModel):
    field: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    length: int = Field(ge=0)
    content_record_id: UUID


class ModelHookContentRecord(_FrozenModel):
    content_record_id: UUID
    event_id: UUID
    session_id: str = Field(min_length=1)
    agent_id: str | None
    hook_event_name: EnumClaudeHookEventName
    field: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    length: int = Field(ge=0)
    redaction_state: Literal["clean", "secret_detected"]
    matched_pattern_names: tuple[str, ...]
    value: str


class ModelSubagentSidecar(_StrictModel):
    """Parsed harness sidecar; ``workflow_run_id`` comes from its path."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        populate_by_name=True,
    )

    agent_type: str = Field(
        min_length=1,
        validation_alias=AliasChoices("agent_type", "agentType"),
    )
    description: str
    model: str = Field(min_length=1)
    request_non_interactive: bool = Field(
        validation_alias=AliasChoices(
            "request_non_interactive", "requestNonInteractive"
        )
    )
    request_shape: str = Field(
        validation_alias=AliasChoices("request_shape", "requestShape")
    )
    spawn_depth: int = Field(
        ge=0,
        validation_alias=AliasChoices("spawn_depth", "spawnDepth"),
    )
    tool_use_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("tool_use_id", "toolUseId"),
    )
    workflow_phase: str | None = Field(
        default=None,
        validation_alias=AliasChoices("workflow_phase", "workflowPhase"),
    )
    workflow_run_id: str | None = None

    @model_validator(mode="after")
    def validate_origin(self) -> ModelSubagentSidecar:
        has_tool = self.tool_use_id is not None
        has_workflow = self.workflow_phase is not None
        if has_tool == has_workflow:
            raise ValueError(
                "sidecar requires exactly one of toolUseId or workflowPhase"
            )
        if has_workflow and self.workflow_run_id is None:
            raise ValueError("workflowPhase requires caller-supplied workflow_run_id")
        if has_tool and self.workflow_run_id is not None:
            raise ValueError("workflow_run_id is only valid for workflow sidecars")
        return self


class ModelHookLineage(_FrozenModel):
    session_id: str = Field(min_length=1)
    agent_id: str | None
    agent_type: str | None
    is_subagent: bool
    parent_tool_use_id: str | None
    workflow_run_id: str | None
    spawn_depth: int | None = Field(ge=0)
    tool_use_id: str | None
    prompt_id: str | None
    turn_id: str | None
    correlation_id: UUID
    causation_id: UUID | None

    @model_validator(mode="after")
    def validate_subagent_flag(self) -> ModelHookLineage:
        if self.is_subagent != (self.agent_id is not None):
            raise ValueError("is_subagent must equal (agent_id is not None)")
        return self


class ModelPreToolUsePayload(_FrozenModel):
    hook_event_name: Literal["PreToolUse"]
    tool_name: str
    mcp_server: str | None
    tool_call_key: UUID
    tool_input_ref: ModelHookContentRef
    tool_input_keys: tuple[str, ...]


class ModelPostToolUsePayload(_FrozenModel):
    hook_event_name: Literal["PostToolUse"]
    tool_name: str
    duration_ms: int | float | None
    interrupted: bool | None
    tool_response_ref: ModelHookContentRef


class ModelPostToolUseFailurePayload(_FrozenModel):
    hook_event_name: Literal["PostToolUseFailure"]
    tool_name: str
    duration_ms: int | float | None
    is_interrupt: bool | None
    error_ref: ModelHookContentRef


class ModelPostToolBatchPayload(_FrozenModel):
    hook_event_name: Literal["PostToolBatch"]
    tool_use_ids: tuple[str, ...]
    tool_names: tuple[str, ...]


class ModelNotificationPayload(_FrozenModel):
    hook_event_name: Literal["Notification"]
    notification_type: str
    title_ref: ModelHookContentRef | None
    message_ref: ModelHookContentRef


class ModelUserPromptSubmitPayload(_FrozenModel):
    hook_event_name: Literal["UserPromptSubmit"]
    prompt_length: int = Field(ge=0)
    prompt_ref: ModelHookContentRef
    source: (
        Literal["user", "sdk", "system", "loop_wakeup", "schedule_wakeup", "poll_event"]
        | None
    )
    session_title_ref: ModelHookContentRef | None


class ModelUserPromptExpansionPayload(_FrozenModel):
    hook_event_name: Literal["UserPromptExpansion"]
    expansion_type: Literal["slash_command", "mcp_prompt"]
    command_name: str
    command_source: str | None
    command_args_ref: ModelHookContentRef
    prompt_ref: ModelHookContentRef


class ModelSessionStartPayload(_FrozenModel):
    hook_event_name: Literal["SessionStart"]
    source: Literal["startup", "resume", "clear", "compact", "fork"]
    model: str | None
    context_tokens: int | None
    seconds_since_last_response: float | None
    prompt_cache_likely_expired: bool | None


class ModelSessionEndPayload(_FrozenModel):
    hook_event_name: Literal["SessionEnd"]
    reason: Literal["clear", "resume", "logout", "prompt_input_exit", "other"]


class ModelStopPayload(_FrozenModel):
    hook_event_name: Literal["Stop"]
    stop_hook_active: bool
    last_assistant_message_ref: ModelHookContentRef | None
    background_task_count: int | None = Field(ge=0)
    session_cron_count: int | None = Field(ge=0)


class ModelStopFailurePayload(_FrozenModel):
    hook_event_name: Literal["StopFailure"]
    error: str
    error_details_ref: ModelHookContentRef | None
    last_assistant_message_ref: ModelHookContentRef | None


class ModelSubagentStartPayload(_FrozenModel):
    hook_event_name: Literal["SubagentStart"]
    agent_id: str
    agent_type: str


class ModelSubagentStopPayload(_FrozenModel):
    hook_event_name: Literal["SubagentStop"]
    stop_hook_active: bool
    agent_id: str
    agent_type: str
    agent_transcript_ref: ModelHookContentRef
    last_assistant_message_ref: ModelHookContentRef | None


class ModelPreCompactPayload(_FrozenModel):
    hook_event_name: Literal["PreCompact"]
    trigger: Literal["manual", "auto"]
    custom_instructions_ref: ModelHookContentRef | None


class ModelPostCompactPayload(_FrozenModel):
    hook_event_name: Literal["PostCompact"]
    trigger: Literal["manual", "auto"]
    compact_summary_ref: ModelHookContentRef


class ModelPreModelSwitchPayload(_FrozenModel):
    hook_event_name: Literal["PreModelSwitch"]


class ModelPostModelSwitchPayload(_FrozenModel):
    hook_event_name: Literal["PostModelSwitch"]


class ModelPermissionRequestPayload(_FrozenModel):
    hook_event_name: Literal["PermissionRequest"]
    tool_name: str
    suggestion_count: int | None = Field(ge=0)


class ModelPermissionDeniedPayload(_FrozenModel):
    hook_event_name: Literal["PermissionDenied"]
    tool_name: str
    reason_ref: ModelHookContentRef


class ModelSetupPayload(_FrozenModel):
    hook_event_name: Literal["Setup"]
    trigger: Literal["init", "maintenance"]


class ModelTeammateIdlePayload(_FrozenModel):
    hook_event_name: Literal["TeammateIdle"]
    teammate_name: str
    team_name: str


class ModelTaskCreatedPayload(_FrozenModel):
    hook_event_name: Literal["TaskCreated"]
    task_id: str
    teammate_name: str | None
    team_name: str | None
    task_subject_ref: ModelHookContentRef
    task_description_ref: ModelHookContentRef | None


class ModelTaskCompletedPayload(_FrozenModel):
    hook_event_name: Literal["TaskCompleted"]
    task_id: str
    teammate_name: str | None
    team_name: str | None
    task_subject_ref: ModelHookContentRef
    task_description_ref: ModelHookContentRef | None


class ModelElicitationPayload(_FrozenModel):
    hook_event_name: Literal["Elicitation"]
    mcp_server_name: str
    mode: Literal["form", "url"] | None
    elicitation_id: str | None
    message_ref: ModelHookContentRef
    requested_schema_keys: tuple[str, ...]


class ModelElicitationResultPayload(_FrozenModel):
    hook_event_name: Literal["ElicitationResult"]
    mcp_server_name: str
    mode: Literal["form", "url"] | None
    elicitation_id: str | None
    action: Literal["accept", "decline", "cancel"]
    content_ref: ModelHookContentRef | None


class ModelConfigChangePayload(_FrozenModel):
    hook_event_name: Literal["ConfigChange"]
    source: str
    file_path_ref: ModelHookContentRef | None


class ModelWorktreeCreatePayload(_FrozenModel):
    hook_event_name: Literal["WorktreeCreate"]
    name_ref: ModelHookContentRef


class ModelWorktreeRemovePayload(_FrozenModel):
    hook_event_name: Literal["WorktreeRemove"]
    worktree_path_ref: ModelHookContentRef


class ModelInstructionsLoadedPayload(_FrozenModel):
    hook_event_name: Literal["InstructionsLoaded"]
    memory_type: str
    load_reason: str
    file_path_ref: ModelHookContentRef
    glob_count: int | None = Field(ge=0)


class ModelCwdChangedPayload(_FrozenModel):
    hook_event_name: Literal["CwdChanged"]
    old_cwd_ref: ModelHookContentRef
    new_cwd_ref: ModelHookContentRef


class ModelFileChangedPayload(_FrozenModel):
    hook_event_name: Literal["FileChanged"]
    event: Literal["change", "add", "unlink"]
    file_path_ref: ModelHookContentRef


class ModelDirectoryAddedPayload(_FrozenModel):
    hook_event_name: Literal["DirectoryAdded"]
    source: Literal["slash_command", "register_repo_root"]
    directory_ref: ModelHookContentRef


class ModelMessageDisplayPayload(_FrozenModel):
    hook_event_name: Literal["MessageDisplay"]
    turn_id: str
    message_id: str
    index: int
    final: bool
    delta_length: int = Field(ge=0)
    delta_ref: ModelHookContentRef


ModelHookPayload = Annotated[
    ModelPreToolUsePayload
    | ModelPostToolUsePayload
    | ModelPostToolUseFailurePayload
    | ModelPostToolBatchPayload
    | ModelNotificationPayload
    | ModelUserPromptSubmitPayload
    | ModelUserPromptExpansionPayload
    | ModelSessionStartPayload
    | ModelSessionEndPayload
    | ModelStopPayload
    | ModelStopFailurePayload
    | ModelSubagentStartPayload
    | ModelSubagentStopPayload
    | ModelPreCompactPayload
    | ModelPostCompactPayload
    | ModelPreModelSwitchPayload
    | ModelPostModelSwitchPayload
    | ModelPermissionRequestPayload
    | ModelPermissionDeniedPayload
    | ModelSetupPayload
    | ModelTeammateIdlePayload
    | ModelTaskCreatedPayload
    | ModelTaskCompletedPayload
    | ModelElicitationPayload
    | ModelElicitationResultPayload
    | ModelConfigChangePayload
    | ModelWorktreeCreatePayload
    | ModelWorktreeRemovePayload
    | ModelInstructionsLoadedPayload
    | ModelCwdChangedPayload
    | ModelFileChangedPayload
    | ModelDirectoryAddedPayload
    | ModelMessageDisplayPayload,
    Field(discriminator="hook_event_name"),
]
HOOK_PAYLOAD_ADAPTER: TypeAdapter[ModelHookPayload] = TypeAdapter(ModelHookPayload)


def _validated_payload[PayloadModelT: _FrozenModel](
    model_type: type[PayloadModelT], **values: object
) -> PayloadModelT:
    """Validate runtime strings while retaining the concrete return type."""

    return model_type.model_validate(values)


class ModelClaudeHookEvent(_FrozenModel):
    event_id: UUID
    schema_version: Literal["1.0.0"]
    hook_event_name: EnumClaudeHookEventName
    emitted_at: datetime
    actor: Literal["claude"]
    claude_code_version: str | None
    lineage: ModelHookLineage
    payload: ModelHookPayload
    content_refs: tuple[ModelHookContentRef, ...]

    @field_validator("emitted_at")
    @classmethod
    def validate_emitted_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("emitted_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_payload_name(self) -> ModelClaudeHookEvent:
        if self.payload.hook_event_name != self.hook_event_name.value:
            raise ValueError("payload hook_event_name must match envelope")
        payload_refs = {
            value.content_record_id
            for value in self.payload.__dict__.values()
            if isinstance(value, ModelHookContentRef)
        }
        envelope_refs = {value.content_record_id for value in self.content_refs}
        if payload_refs != envelope_refs:
            raise ValueError("content_refs must list each payload content ref once")
        if len(envelope_refs) != len(self.content_refs):
            raise ValueError("content_refs must not contain duplicates")
        return self


class ModelHookCaptureResult(_StrictModel):
    event: ModelClaudeHookEvent
    content_records: tuple[ModelHookContentRecord, ...]


def canonical_json(value: object) -> str:
    """Serialize JSON-compatible stdin values deterministically."""

    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise InvalidHookInputError("hook content is not JSON-serializable") from exc


def make_correlation_id(session_id: str) -> UUID:
    return uuid5(HOOK_CAPTURE_NAMESPACE, session_id)


def make_tool_call_key(session_id: str, tool_use_id: str) -> UUID:
    return uuid5(HOOK_CAPTURE_NAMESPACE, f"{session_id}|{tool_use_id}")


def make_event_id(
    *,
    session_id: str,
    agent_id: str | None,
    hook_event_name: str,
    tool_use_id: str | None,
    prompt_id: str | None,
    emitted_at: datetime,
) -> UUID:
    identity = [
        session_id,
        agent_id or "",
        hook_event_name,
        tool_use_id or "",
        prompt_id or "",
        emitted_at.isoformat(),
    ]
    return uuid5(HOOK_CAPTURE_NAMESPACE, canonical_json(identity))


def _required(stdin: Mapping[str, object], field: str, hook_name: str) -> object:
    if field not in stdin:
        raise MissingHookFieldError(f"{hook_name} is missing required field {field!r}")
    return stdin[field]


def _string(stdin: Mapping[str, object], field: str, hook_name: str) -> str:
    value = _required(stdin, field, hook_name)
    if not isinstance(value, str) or not value:
        raise InvalidHookInputError(f"{hook_name}.{field} must be a non-blank string")
    return value


def _optional_string(stdin: Mapping[str, object], field: str) -> str | None:
    value = stdin.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidHookInputError(f"{field} must be a string when present")
    return value


def _bool(stdin: Mapping[str, object], field: str, hook_name: str) -> bool:
    value = _required(stdin, field, hook_name)
    if not isinstance(value, bool):
        raise InvalidHookInputError(f"{hook_name}.{field} must be a boolean")
    return value


def _optional_bool(stdin: Mapping[str, object], field: str) -> bool | None:
    value = stdin.get(field)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise InvalidHookInputError(f"{field} must be a boolean when present")
    return value


def _int(stdin: Mapping[str, object], field: str, hook_name: str) -> int:
    value = _required(stdin, field, hook_name)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidHookInputError(f"{hook_name}.{field} must be an integer")
    return value


def _optional_int(stdin: Mapping[str, object], field: str) -> int | None:
    value = stdin.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidHookInputError(f"{field} must be an integer when present")
    return value


def _optional_number(stdin: Mapping[str, object], field: str) -> float | None:
    value = stdin.get(field)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidHookInputError(f"{field} must be a number when present")
    return float(value)


def _optional_duration(stdin: Mapping[str, object]) -> int | float | None:
    value = stdin.get("duration_ms")
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise InvalidHookInputError("duration_ms must be a number when present")
    return value


def _sequence(stdin: Mapping[str, object], field: str, hook_name: str) -> list[object]:
    value = _required(stdin, field, hook_name)
    if not isinstance(value, list):
        raise InvalidHookInputError(f"{hook_name}.{field} must be a list")
    return value


def _optional_count(stdin: Mapping[str, object], field: str) -> int | None:
    value = stdin.get(field)
    if value is None:
        return None
    if not isinstance(value, list):
        raise InvalidHookInputError(f"{field} must be a list when present")
    return len(value)


def _mapping_keys(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    keys: list[str] = []
    for key in value:
        if not isinstance(key, str):
            raise InvalidHookInputError(f"{field} keys must be strings")
        keys.append(key)
    return tuple(sorted(keys))


def _mcp_server_name(stdin: Mapping[str, object]) -> str | None:
    value = stdin.get("mcp_server")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        name = value.get("name")
        if isinstance(name, str):
            return name
    raise InvalidHookInputError("mcp_server must be a name or an object with a name")


def _tool_response_interrupted(value: object) -> bool | None:
    if not isinstance(value, Mapping):
        return None
    interrupted = value.get("interrupted")
    if interrupted is None:
        return None
    if not isinstance(interrupted, bool):
        raise InvalidHookInputError("tool_response.interrupted must be a boolean")
    return interrupted


def _payload_from_stdin(
    *,
    stdin: Mapping[str, object],
    hook_name: EnumClaudeHookEventName,
    capture: _ContentCapture,
    session_id: str,
) -> ModelHookPayload:
    name = hook_name.value
    if hook_name is EnumClaudeHookEventName.PRE_TOOL_USE:
        tool_input = _required(stdin, "tool_input", name)
        tool_use_id = _string(stdin, "tool_use_id", name)
        return _validated_payload(
            ModelPreToolUsePayload,
            hook_event_name=name,
            tool_name=_string(stdin, "tool_name", name),
            mcp_server=_mcp_server_name(stdin),
            tool_call_key=make_tool_call_key(session_id, tool_use_id),
            tool_input_ref=capture.required("tool_input", tool_input),
            tool_input_keys=_mapping_keys(tool_input, "tool_input"),
        )
    if hook_name is EnumClaudeHookEventName.POST_TOOL_USE:
        response = _required(stdin, "tool_response", name)
        return _validated_payload(
            ModelPostToolUsePayload,
            hook_event_name=name,
            tool_name=_string(stdin, "tool_name", name),
            duration_ms=_optional_duration(stdin),
            interrupted=_tool_response_interrupted(response),
            tool_response_ref=capture.required("tool_response", response),
        )
    if hook_name is EnumClaudeHookEventName.POST_TOOL_USE_FAILURE:
        return _validated_payload(
            ModelPostToolUseFailurePayload,
            hook_event_name=name,
            tool_name=_string(stdin, "tool_name", name),
            duration_ms=_optional_duration(stdin),
            is_interrupt=_optional_bool(stdin, "is_interrupt"),
            error_ref=capture.required("error", _string(stdin, "error", name)),
        )
    if hook_name is EnumClaudeHookEventName.POST_TOOL_BATCH:
        calls = _sequence(stdin, "tool_calls", name)
        ids: list[str] = []
        names: list[str] = []
        for index, raw_call in enumerate(calls):
            if not isinstance(raw_call, Mapping):
                raise InvalidHookInputError(f"tool_calls[{index}] must be an object")
            ids.append(_string(raw_call, "tool_use_id", name))
            names.append(_string(raw_call, "tool_name", name))
        return _validated_payload(
            ModelPostToolBatchPayload,
            hook_event_name=name,
            tool_use_ids=tuple(ids),
            tool_names=tuple(names),
        )
    if hook_name is EnumClaudeHookEventName.NOTIFICATION:
        return _validated_payload(
            ModelNotificationPayload,
            hook_event_name=name,
            notification_type=_string(stdin, "notification_type", name),
            title_ref=capture.optional("title", stdin.get("title")),
            message_ref=capture.required("message", _string(stdin, "message", name)),
        )
    if hook_name is EnumClaudeHookEventName.USER_PROMPT_SUBMIT:
        prompt = _string(stdin, "prompt", name)
        return _validated_payload(
            ModelUserPromptSubmitPayload,
            hook_event_name=name,
            prompt_length=len(prompt),
            prompt_ref=capture.required("prompt", prompt),
            source=_optional_string(stdin, "source"),
            session_title_ref=capture.optional(
                "session_title", stdin.get("session_title")
            ),
        )
    if hook_name is EnumClaudeHookEventName.USER_PROMPT_EXPANSION:
        return _validated_payload(
            ModelUserPromptExpansionPayload,
            hook_event_name=name,
            expansion_type=_string(stdin, "expansion_type", name),
            command_name=_string(stdin, "command_name", name),
            command_source=_optional_string(stdin, "command_source"),
            command_args_ref=capture.required(
                "command_args", _string(stdin, "command_args", name)
            ),
            prompt_ref=capture.required("prompt", _string(stdin, "prompt", name)),
        )
    if hook_name is EnumClaudeHookEventName.SESSION_START:
        return _validated_payload(
            ModelSessionStartPayload,
            hook_event_name=name,
            source=_string(stdin, "source", name),
            model=_optional_string(stdin, "model"),
            context_tokens=_optional_int(stdin, "context_tokens"),
            seconds_since_last_response=_optional_number(
                stdin, "seconds_since_last_response"
            ),
            prompt_cache_likely_expired=_optional_bool(
                stdin, "prompt_cache_likely_expired"
            ),
        )
    if hook_name is EnumClaudeHookEventName.SESSION_END:
        return _validated_payload(
            ModelSessionEndPayload,
            hook_event_name=name,
            reason=_string(stdin, "reason", name),
        )
    if hook_name is EnumClaudeHookEventName.STOP:
        return _validated_payload(
            ModelStopPayload,
            hook_event_name=name,
            stop_hook_active=_bool(stdin, "stop_hook_active", name),
            last_assistant_message_ref=capture.optional(
                "last_assistant_message", stdin.get("last_assistant_message")
            ),
            background_task_count=_optional_count(stdin, "background_tasks"),
            session_cron_count=_optional_count(stdin, "session_crons"),
        )
    if hook_name is EnumClaudeHookEventName.STOP_FAILURE:
        return _validated_payload(
            ModelStopFailurePayload,
            hook_event_name=name,
            error=_string(stdin, "error", name),
            error_details_ref=capture.optional(
                "error_details", stdin.get("error_details")
            ),
            last_assistant_message_ref=capture.optional(
                "last_assistant_message", stdin.get("last_assistant_message")
            ),
        )
    if hook_name is EnumClaudeHookEventName.SUBAGENT_START:
        return _validated_payload(
            ModelSubagentStartPayload,
            hook_event_name=name,
            agent_id=_string(stdin, "agent_id", name),
            agent_type=_string(stdin, "agent_type", name),
        )
    if hook_name is EnumClaudeHookEventName.SUBAGENT_STOP:
        return _validated_payload(
            ModelSubagentStopPayload,
            hook_event_name=name,
            stop_hook_active=_bool(stdin, "stop_hook_active", name),
            agent_id=_string(stdin, "agent_id", name),
            agent_type=_string(stdin, "agent_type", name),
            agent_transcript_ref=capture.required(
                "agent_transcript_path",
                _string(stdin, "agent_transcript_path", name),
            ),
            last_assistant_message_ref=capture.optional(
                "last_assistant_message", stdin.get("last_assistant_message")
            ),
        )
    if hook_name is EnumClaudeHookEventName.PRE_COMPACT:
        return _validated_payload(
            ModelPreCompactPayload,
            hook_event_name=name,
            trigger=_string(stdin, "trigger", name),
            custom_instructions_ref=capture.optional(
                "custom_instructions", stdin.get("custom_instructions")
            ),
        )
    if hook_name is EnumClaudeHookEventName.POST_COMPACT:
        return _validated_payload(
            ModelPostCompactPayload,
            hook_event_name=name,
            trigger=_string(stdin, "trigger", name),
            compact_summary_ref=capture.required(
                "compact_summary", _string(stdin, "compact_summary", name)
            ),
        )
    if hook_name is EnumClaudeHookEventName.PRE_MODEL_SWITCH:
        return _validated_payload(ModelPreModelSwitchPayload, hook_event_name=name)
    if hook_name is EnumClaudeHookEventName.POST_MODEL_SWITCH:
        return _validated_payload(ModelPostModelSwitchPayload, hook_event_name=name)
    if hook_name is EnumClaudeHookEventName.PERMISSION_REQUEST:
        suggestions = stdin.get("permission_suggestions")
        if suggestions is not None and not isinstance(suggestions, list):
            raise InvalidHookInputError("permission_suggestions must be a list")
        return _validated_payload(
            ModelPermissionRequestPayload,
            hook_event_name=name,
            tool_name=_string(stdin, "tool_name", name),
            suggestion_count=None if suggestions is None else len(suggestions),
        )
    if hook_name is EnumClaudeHookEventName.PERMISSION_DENIED:
        return _validated_payload(
            ModelPermissionDeniedPayload,
            hook_event_name=name,
            tool_name=_string(stdin, "tool_name", name),
            reason_ref=capture.required("reason", _string(stdin, "reason", name)),
        )
    if hook_name is EnumClaudeHookEventName.SETUP:
        return _validated_payload(
            ModelSetupPayload,
            hook_event_name=name,
            trigger=_string(stdin, "trigger", name),
        )
    if hook_name is EnumClaudeHookEventName.TEAMMATE_IDLE:
        return _validated_payload(
            ModelTeammateIdlePayload,
            hook_event_name=name,
            teammate_name=_string(stdin, "teammate_name", name),
            team_name=_string(stdin, "team_name", name),
        )
    if hook_name in {
        EnumClaudeHookEventName.TASK_CREATED,
        EnumClaudeHookEventName.TASK_COMPLETED,
    }:
        common = {
            "hook_event_name": name,
            "task_id": _string(stdin, "task_id", name),
            "teammate_name": _optional_string(stdin, "teammate_name"),
            "team_name": _optional_string(stdin, "team_name"),
            "task_subject_ref": capture.required(
                "task_subject", _string(stdin, "task_subject", name)
            ),
            "task_description_ref": capture.optional(
                "task_description", stdin.get("task_description")
            ),
        }
        return HOOK_PAYLOAD_ADAPTER.validate_python(common)
    if hook_name is EnumClaudeHookEventName.ELICITATION:
        schema = stdin.get("requested_schema")
        return _validated_payload(
            ModelElicitationPayload,
            hook_event_name=name,
            mcp_server_name=_string(stdin, "mcp_server_name", name),
            mode=_optional_string(stdin, "mode"),
            elicitation_id=_optional_string(stdin, "elicitation_id"),
            message_ref=capture.required("message", _string(stdin, "message", name)),
            requested_schema_keys=_mapping_keys(schema, "requested_schema"),
        )
    if hook_name is EnumClaudeHookEventName.ELICITATION_RESULT:
        return _validated_payload(
            ModelElicitationResultPayload,
            hook_event_name=name,
            mcp_server_name=_string(stdin, "mcp_server_name", name),
            mode=_optional_string(stdin, "mode"),
            elicitation_id=_optional_string(stdin, "elicitation_id"),
            action=_string(stdin, "action", name),
            content_ref=capture.optional("content", stdin.get("content")),
        )
    if hook_name is EnumClaudeHookEventName.CONFIG_CHANGE:
        return _validated_payload(
            ModelConfigChangePayload,
            hook_event_name=name,
            source=_string(stdin, "source", name),
            file_path_ref=capture.optional("file_path", stdin.get("file_path")),
        )
    if hook_name is EnumClaudeHookEventName.WORKTREE_CREATE:
        return _validated_payload(
            ModelWorktreeCreatePayload,
            hook_event_name=name,
            name_ref=capture.required("name", _string(stdin, "name", name)),
        )
    if hook_name is EnumClaudeHookEventName.WORKTREE_REMOVE:
        return _validated_payload(
            ModelWorktreeRemovePayload,
            hook_event_name=name,
            worktree_path_ref=capture.required(
                "worktree_path", _string(stdin, "worktree_path", name)
            ),
        )
    if hook_name is EnumClaudeHookEventName.INSTRUCTIONS_LOADED:
        globs = stdin.get("globs")
        if globs is not None and not isinstance(globs, list):
            raise InvalidHookInputError("globs must be a list")
        return _validated_payload(
            ModelInstructionsLoadedPayload,
            hook_event_name=name,
            memory_type=_string(stdin, "memory_type", name),
            load_reason=_string(stdin, "load_reason", name),
            file_path_ref=capture.required(
                "file_path", _string(stdin, "file_path", name)
            ),
            glob_count=None if globs is None else len(globs),
        )
    if hook_name is EnumClaudeHookEventName.CWD_CHANGED:
        return _validated_payload(
            ModelCwdChangedPayload,
            hook_event_name=name,
            old_cwd_ref=capture.required("old_cwd", _string(stdin, "old_cwd", name)),
            new_cwd_ref=capture.required("new_cwd", _string(stdin, "new_cwd", name)),
        )
    if hook_name is EnumClaudeHookEventName.FILE_CHANGED:
        return _validated_payload(
            ModelFileChangedPayload,
            hook_event_name=name,
            event=_string(stdin, "event", name),
            file_path_ref=capture.required(
                "file_path", _string(stdin, "file_path", name)
            ),
        )
    if hook_name is EnumClaudeHookEventName.DIRECTORY_ADDED:
        return _validated_payload(
            ModelDirectoryAddedPayload,
            hook_event_name=name,
            source=_string(stdin, "source", name),
            directory_ref=capture.required(
                "directory", _string(stdin, "directory", name)
            ),
        )
    if hook_name is EnumClaudeHookEventName.MESSAGE_DISPLAY:
        delta = _string(stdin, "delta", name)
        return _validated_payload(
            ModelMessageDisplayPayload,
            hook_event_name=name,
            turn_id=_string(stdin, "turn_id", name),
            message_id=_string(stdin, "message_id", name),
            index=_int(stdin, "index", name),
            final=_bool(stdin, "final", name),
            delta_length=len(delta),
            delta_ref=capture.required("delta", delta),
        )
    raise UnknownHookEventError(name)


class _ContentCapture:
    def __init__(
        self,
        *,
        event_id: UUID,
        session_id: str,
        agent_id: str | None,
        hook_event_name: EnumClaudeHookEventName,
        scrubber: ContentScrubber,
    ) -> None:
        self._scrubber = scrubber
        self._event_id = event_id
        self._session_id = session_id
        self._agent_id = agent_id
        self._hook_event_name = hook_event_name
        self.refs: list[ModelHookContentRef] = []
        self.records: list[ModelHookContentRecord] = []

    def required(self, field: str, raw_value: object) -> ModelHookContentRef:
        serialised = (
            raw_value if isinstance(raw_value, str) else canonical_json(raw_value)
        )
        # The scrub runs BEFORE hashing, so neither the restricted content record
        # nor the sha256 on the metadata topic is ever derived from a secret.
        scrubbed = self._scrubber(serialised)
        value = scrubbed.value
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        content_record_id = uuid5(
            HOOK_CAPTURE_NAMESPACE,
            f"{self._event_id}|{field}",
        )
        ref = ModelHookContentRef(
            field=field,
            sha256=digest,
            length=len(value),
            content_record_id=content_record_id,
        )
        self.refs.append(ref)
        self.records.append(
            ModelHookContentRecord(
                content_record_id=content_record_id,
                event_id=self._event_id,
                session_id=self._session_id,
                agent_id=self._agent_id,
                hook_event_name=self._hook_event_name,
                field=field,
                sha256=digest,
                length=len(value),
                redaction_state=scrubbed.redaction_state,
                matched_pattern_names=scrubbed.matched_pattern_names,
                value=value,
            )
        )
        return ref

    def optional(self, field: str, raw_value: object) -> ModelHookContentRef | None:
        if raw_value is None:
            return None
        return self.required(field, raw_value)


def map_hook_stdin(
    stdin: Mapping[str, object],
    *,
    emitted_at: datetime,
    sidecar: ModelSubagentSidecar | None,
    claude_code_version: str | None,
    turn_id: str | None,
    content_scrubber: ContentScrubber,
) -> ModelHookCaptureResult:
    """Map one decoded Claude Code hook stdin object without performing I/O.

    ``content_scrubber`` is required with no default: a producer must pass the
    production span scrub of the restricted content family explicitly, so no
    caller can publish unscrubbed content by forgetting an argument.
    """

    raw_name = stdin.get("hook_event_name")
    if not isinstance(raw_name, str):
        raise MissingHookFieldError("hook stdin is missing required hook_event_name")
    try:
        hook_name = EnumClaudeHookEventName(raw_name)
    except ValueError as exc:
        raise UnknownHookEventError(raw_name) from exc

    session_id = _string(stdin, "session_id", raw_name)
    agent_id = _optional_string(stdin, "agent_id")
    agent_type = _optional_string(stdin, "agent_type")
    prompt_id = _optional_string(stdin, "prompt_id")
    tool_use_id = _optional_string(stdin, "tool_use_id")
    effective_turn_id = _optional_string(stdin, "turn_id") or turn_id

    if sidecar is not None and agent_id is None:
        raise InvalidHookInputError("a sidecar may only accompany a subagent event")
    if sidecar is not None and agent_type not in {None, sidecar.agent_type}:
        raise InvalidHookInputError("sidecar agentType conflicts with hook stdin")

    event_id = make_event_id(
        session_id=session_id,
        agent_id=agent_id,
        hook_event_name=raw_name,
        tool_use_id=tool_use_id,
        prompt_id=prompt_id,
        emitted_at=emitted_at,
    )
    capture = _ContentCapture(
        event_id=event_id,
        session_id=session_id,
        agent_id=agent_id,
        hook_event_name=hook_name,
        scrubber=content_scrubber,
    )
    payload = _payload_from_stdin(
        stdin=stdin,
        hook_name=hook_name,
        capture=capture,
        session_id=session_id,
    )

    causation_id = None
    if (
        hook_name
        in {
            EnumClaudeHookEventName.POST_TOOL_USE,
            EnumClaudeHookEventName.POST_TOOL_USE_FAILURE,
            EnumClaudeHookEventName.PERMISSION_DENIED,
            EnumClaudeHookEventName.PERMISSION_REQUEST,
        }
        and tool_use_id is not None
    ):
        causation_id = make_tool_call_key(session_id, tool_use_id)

    lineage = ModelHookLineage(
        session_id=session_id,
        agent_id=agent_id,
        agent_type=agent_type or (sidecar.agent_type if sidecar is not None else None),
        is_subagent=agent_id is not None,
        parent_tool_use_id=sidecar.tool_use_id if sidecar is not None else None,
        workflow_run_id=sidecar.workflow_run_id if sidecar is not None else None,
        spawn_depth=sidecar.spawn_depth if sidecar is not None else None,
        tool_use_id=tool_use_id,
        prompt_id=prompt_id,
        turn_id=effective_turn_id,
        correlation_id=make_correlation_id(session_id),
        causation_id=causation_id,
    )
    event = ModelClaudeHookEvent(
        event_id=event_id,
        schema_version=HOOK_EVENT_SCHEMA_VERSION,
        hook_event_name=hook_name,
        emitted_at=emitted_at,
        actor="claude",
        claude_code_version=claude_code_version,
        lineage=lineage,
        payload=payload,
        content_refs=tuple(capture.refs),
    )
    return ModelHookCaptureResult(
        event=event,
        content_records=tuple(capture.records),
    )


__all__ = [
    "HOOK_CAPTURE_NAMESPACE",
    "HOOK_EVENT_SCHEMA_VERSION",
    "HOOK_PAYLOAD_ADAPTER",
    "ContentScrubber",
    "EnumClaudeHookEventName",
    "InvalidHookInputError",
    "MissingHookFieldError",
    "ModelClaudeHookEvent",
    "ModelContentScrubResult",
    "ModelHookCaptureResult",
    "ModelHookContentRecord",
    "ModelHookContentRef",
    "ModelHookLineage",
    "ModelHookPayload",
    "ModelSubagentSidecar",
    "UnknownHookEventError",
    "canonical_json",
    "make_correlation_id",
    "make_event_id",
    "make_tool_call_key",
    "map_hook_stdin",
]
