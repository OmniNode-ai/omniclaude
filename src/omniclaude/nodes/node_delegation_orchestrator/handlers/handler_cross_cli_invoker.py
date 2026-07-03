# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Handler that dispatches tasks to claude, opencode, or codex CLI subprocesses.

Only valid when recipient is an explicit CLI (not 'auto'). The 'auto' path
now uses omnimarket's node_delegate_skill_orchestrator with bifrost config
routing. The legacy handle_delegation_dispatch() in handler_delegation_dispatch.py
is deprecated.
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from omniclaude.nodes.node_delegation_orchestrator.enums.enum_cli_recipient import (
    EnumCliRecipient,
)
from omniclaude.nodes.node_delegation_orchestrator.models.model_cross_cli_invocation_result import (
    ModelCrossCLIInvocationResult,
)
from omniclaude.nodes.node_delegation_orchestrator.models.model_delegation_command import (
    ModelDelegationCommand,
)

_MUTATION_TASK_TYPES = frozenset({"code_generation", "refactor", "test", "document"})


def _infer_task_type(task_type: str | None) -> str:
    if task_type in _MUTATION_TASK_TYPES:
        return "code_generation"
    return "research"


class HandlerCrossCLIInvoker:
    """Invoke claude, opencode, or codex CLI and return a structured result."""

    def __init__(self, timeout: int = 300) -> None:
        self._timeout = timeout

    # ------------------------------------------------------------------ #
    # Arg builders                                                         #
    # ------------------------------------------------------------------ #

    def _build_claude_args(self, prompt: str) -> list[str]:
        return ["claude", "-p", "--output-format", "json", prompt]

    def _build_opencode_args(self, prompt: str, working_directory: str) -> list[str]:
        return [
            "opencode",
            "run",
            "--format",
            "json",
            "--pure",
            "--dir",
            working_directory,
            prompt,
        ]

    def _build_codex_args(
        self,
        prompt: str,
        task_type: str,
        working_directory: str,
        sandbox_override: str | None,
    ) -> list[str]:
        if sandbox_override is not None:
            mode = sandbox_override
        elif task_type in _MUTATION_TASK_TYPES:
            mode = "workspace-write"
        else:
            mode = "read-only"

        args = ["codex", "exec", "-C", working_directory, "-s", mode, "--json", prompt]

        socket_path = os.environ.get("ONEX_EMIT_SOCKET_PATH")
        if socket_path:
            args.extend(["--allow-unix-socket", socket_path])

        return args

    # ------------------------------------------------------------------ #
    # Output parsers                                                       #
    # ------------------------------------------------------------------ #

    def _parse_claude_output(
        self,
        raw: str,
        stderr: str,
        exit_code: int,
        runtime_seconds: float,
        correlation_id: str,
        working_directory: str | None,
    ) -> ModelCrossCLIInvocationResult:
        stdout = ""
        error_detail = ""
        try:
            data = json.loads(raw)
            result_text = data.get("result", "")
            if data.get("is_error"):
                error_detail = result_text
            else:
                stdout = result_text
        except (json.JSONDecodeError, KeyError):
            stdout = raw

        return ModelCrossCLIInvocationResult(
            correlation_id=correlation_id,
            recipient=EnumCliRecipient.CLAUDE,
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            runtime_seconds=runtime_seconds,
            working_directory=working_directory,
            error_detail=error_detail,
        )

    def _parse_opencode_output(
        self,
        raw: str,
        stderr: str,
        exit_code: int,
        runtime_seconds: float,
        correlation_id: str,
        working_directory: str | None,
    ) -> ModelCrossCLIInvocationResult:
        text_parts: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "text":
                    part = obj.get("part", {})
                    if isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
            except json.JSONDecodeError:
                continue

        return ModelCrossCLIInvocationResult(
            correlation_id=correlation_id,
            recipient=EnumCliRecipient.OPENCODE,
            stdout="\n".join(text_parts),
            stderr=stderr,
            exit_code=exit_code,
            runtime_seconds=runtime_seconds,
            working_directory=working_directory,
        )

    def _parse_codex_output(
        self,
        raw: str,
        stderr: str,
        exit_code: int,
        runtime_seconds: float,
        correlation_id: str,
        working_directory: str | None,
    ) -> ModelCrossCLIInvocationResult:
        agent_messages: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get("type") == "item.completed":
                    item = obj.get("item", {})
                    if isinstance(item, dict) and item.get("type") == "agent_message":
                        text = item.get("text", "")
                        if text:
                            agent_messages.append(text)
            except json.JSONDecodeError:
                continue

        return ModelCrossCLIInvocationResult(
            correlation_id=correlation_id,
            recipient=EnumCliRecipient.CODEX,
            stdout="\n".join(agent_messages),
            stderr=stderr,
            exit_code=exit_code,
            runtime_seconds=runtime_seconds,
            working_directory=working_directory,
        )

    # ------------------------------------------------------------------ #
    # Main dispatch                                                        #
    # ------------------------------------------------------------------ #

    def invoke(self, command: ModelDelegationCommand) -> ModelCrossCLIInvocationResult:
        """Dispatch to the specified CLI and return a structured result."""
        cwd = str(command.working_directory) if command.working_directory else None
        correlation_id = command.correlation_id or ""

        recipient: str = command.recipient
        prompt = command.prompt

        if recipient == EnumCliRecipient.CLAUDE:
            args = self._build_claude_args(prompt)
        elif recipient == EnumCliRecipient.OPENCODE:
            args = self._build_opencode_args(prompt, cwd or ".")
        elif recipient == EnumCliRecipient.CODEX:
            task_type = _infer_task_type(command.task_type)
            args = self._build_codex_args(
                prompt,
                task_type=task_type,
                working_directory=cwd or ".",
                sandbox_override=command.codex_sandbox_mode,
            )
        else:
            return ModelCrossCLIInvocationResult(
                correlation_id=correlation_id,
                recipient=EnumCliRecipient.CLAUDE,
                stdout="",
                stderr=f"Unknown recipient: {recipient!r}",
                exit_code=1,
                error_detail=f"Unknown recipient: {recipient!r}",
            )

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ModelCrossCLIInvocationResult(
                correlation_id=correlation_id,
                recipient=EnumCliRecipient(recipient),
                stdout="",
                stderr="timeout",
                exit_code=1,
                error_detail="subprocess timed out",
            )
        except FileNotFoundError:
            return ModelCrossCLIInvocationResult(
                correlation_id=correlation_id,
                recipient=EnumCliRecipient(recipient),
                stdout="",
                stderr=f"{recipient} binary not found",
                exit_code=127,
                error_detail=f"{recipient} binary not found on PATH",
            )

        runtime = time.monotonic() - t0

        if recipient == EnumCliRecipient.CLAUDE:
            return self._parse_claude_output(
                proc.stdout, proc.stderr, proc.returncode, runtime, correlation_id, cwd
            )
        elif recipient == EnumCliRecipient.OPENCODE:
            return self._parse_opencode_output(
                proc.stdout, proc.stderr, proc.returncode, runtime, correlation_id, cwd
            )
        else:
            return self._parse_codex_output(
                proc.stdout, proc.stderr, proc.returncode, runtime, correlation_id, cwd
            )


__all__ = ["HandlerCrossCLIInvoker"]
