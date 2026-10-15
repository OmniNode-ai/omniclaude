# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HandlerClaudeCodeBindingRender: client_bindings -> the mod module text (OMN-18531, T0.3).

Pure. Deterministic: the same rows and maximum mode render byte-identical text. A row
whose argument is not drawn from the hook input, or whose name could carry code, fails
the render. Every contract value enters the text as a quoted literal; the module has no
branching beyond table lookups.
"""

from __future__ import annotations

import hashlib
import json
import re

from omniclaude.nodes.node_claude_code_binding_render_compute.handlers import (
    template_claude_code_binding as tpl,
)
from omniclaude.nodes.node_claude_code_binding_render_compute.models import (
    ModelBindingRegistration,
    ModelBindingRenderRequest,
    ModelBindingRenderResult,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.binding_render_error import (
    BindingRenderError,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumBindingKind,
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientBinding,
)

ADAPTER_COMMAND = "onex-claude-code-hook"
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_HOOK_INPUT_PATH = re.compile(r"^\$(\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _fill(template: str, **tokens: str) -> str:
    for key, value in tokens.items():
        template = template.replace(f"@@{key}@@", value)
    return template


def _literal(value: str) -> str:
    return json.dumps(value)


def validate_binding(binding: ModelClientBinding) -> None:
    if not _NAME.match(binding.name):
        raise BindingRenderError(
            f"binding name {binding.name!r} is not a lower-case identifier"
        )
    for argument in binding.arguments:
        if not _HOOK_INPUT_PATH.match(argument.source):
            raise BindingRenderError(
                f"binding {binding.name!r} argument {argument.name!r} source "
                f"{argument.source!r} is not drawn from the hook input (a $.path)"
            )


def _failure_lines(
    binding: ModelClientBinding, mode: EnumClientMaxMode
) -> tuple[str, str]:
    deny = _literal(binding.deny_text)
    required = mode is EnumClientMaxMode.REQUIRED
    never_started = (
        _fill(tpl.REQUIRED_NEVER_STARTED, deny_text=deny)
        if required
        else tpl.NATIVE_NEVER_STARTED
    )
    # Anything else (timeout, throw, reload) is {deny} unless the host maximum is observe,
    # where native execution is always safe because the server cannot dispatch.
    other = (
        tpl.NATIVE_OTHER
        if mode is EnumClientMaxMode.OBSERVE
        else _fill(tpl.REQUIRED_OTHER, deny_text=deny)
    )
    return never_started, other


def registration_for(binding: ModelClientBinding) -> ModelBindingRegistration:
    return ModelBindingRegistration(
        event=binding.hook_event,
        matcher=binding.matcher_tool,
        command=f"{ADAPTER_COMMAND} --binding {binding.name}",
    )


class HandlerClaudeCodeBindingRender:
    """handle(request) -> result."""

    def handle(self, request: ModelBindingRenderRequest) -> ModelBindingRenderResult:
        replacing = tuple(
            b for b in request.bindings if b.kind is EnumBindingKind.REPLACING
        )
        additive = tuple(
            b for b in request.bindings if b.kind is EnumBindingKind.ADDITIVE
        )
        for binding in request.bindings:
            validate_binding(binding)
        # One failure table per module: the strictest row decides the fixed literals.
        table_binding = replacing[0] if replacing else None
        never_started, other = (
            _failure_lines(table_binding, request.max_mode)
            if table_binding is not None
            else (tpl.NATIVE_NEVER_STARTED, tpl.NATIVE_OTHER)
        )
        parts = [
            _fill(
                tpl.MODULE_HEADER,
                max_mode=request.max_mode.value,
                never_started_line=never_started,
                other_line=other,
            )
        ]
        for binding in replacing:
            argv = f"['{ADAPTER_COMMAND}', '--binding', '{binding.name}']"
            parts.append(
                _fill(
                    tpl.BINDING_CONSTANTS,
                    name=binding.name,
                    argv=argv,
                    pattern=_literal(binding.never_started_pattern),
                    deadline_ms=str(binding.deadline_ms),
                )
            )
        parts.append(tpl.REGISTER_OPEN)
        for binding in replacing:
            matcher = (
                "{ tool: " + _literal(binding.matcher_tool) + " }"
                if binding.matcher_tool is not None
                else "{}"
            )
            parts.append(
                _fill(
                    tpl.BINDING_HOOK,
                    name=binding.name,
                    event=_literal(binding.hook_event),
                    matcher=matcher,
                )
            )
        parts.append(tpl.REGISTER_CLOSE)
        text = "".join(parts)
        return ModelBindingRenderResult(
            module_text=text,
            module_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            registrations=tuple(registration_for(b) for b in additive),
        )
