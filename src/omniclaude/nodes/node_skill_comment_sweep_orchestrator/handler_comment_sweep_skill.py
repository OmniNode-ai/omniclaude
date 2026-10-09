# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Canonical handler for the comment_sweep skill orchestrator."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

from omniclaude.nodes.node_skill_comment_sweep_orchestrator.models.model_comment_sweep_result import (
    ModelCommentSweepResult,
)
from omniclaude.nodes.node_skill_comment_sweep_orchestrator.models.model_render_delegation import (
    ModelRenderDelegation,
)
from omniclaude.shared.handler_skill_requested import (
    _parse_result_block,
    handle_skill_requested,
)
from omniclaude.shared.models import (
    ModelSkillRequest,
    SkillResultStatus,
)

TaskDispatcher = Callable[[str], Awaitable[str]]
EventEmitter = Callable[[str, dict[str, object]], bool]

# Same bounded deployed-lane budget as the delegate CLI: 240 s + delivery margin.
_DELEGATE_TIMEOUT_SECONDS = 330
_OUTPUT_CONTRACT = (
    "Output contract: reply with the finished text only, exactly as it will be pasted. "
    "Begin directly with the text's own first line (for a commit message, its subject line; "
    "otherwise the first line or section the instructions ask for). Put nothing above it: "
    'no title, label or heading of your own such as "Title:", "Subject:", "Commit message", '
    '"PART 1", "PR Body", a "# <title>" line or a bold title line, and no code fence around '
    "the text. Keep the sections, headings and lists the instructions ask for, and use them "
    "inside the text wherever they help. When the instructions ask for several parts and "
    "give a separator, separate the parts with it."
)


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("delegation output must be a JSON object")
    return value


def _string(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("delegation receipt requires a non-empty route field")
    return value


def _receipt_response(
    receipt: dict[str, object], *, prompt: str, correlation_id: UUID
) -> str:
    inner = _object(receipt["receipt"])
    if inner.get("exit_code") != 0:
        raise ValueError("delegation receipt does not carry a successful exit")
    result = _object(inner["result"])
    # The deployed CLI records its envelope; the sanctioned in-process retry
    # records the same terminal payload directly.
    if "terminal_payload" in result:
        terminal = _object(result["terminal_payload"])
        payload = _object(terminal["payload"])
    else:
        payload = result
    if payload.get("status") != "completed":
        raise ValueError("delegation terminal did not complete")
    if (
        payload.get("correlation_id") != str(correlation_id)
        or payload.get("prompt_text") != prompt
    ):
        raise ValueError("delegation terminal does not match this render request")
    response = payload.get("response")
    if not isinstance(response, str) or not response.strip():
        raise ValueError("delegation terminal contains no rendered reply")
    return response


class HandlerCommentSweepSkill:
    """Adapter that keeps comment_sweep on the shared skill dispatch path."""

    handler_key: str = "default"

    def __init__(
        self,
        task_dispatcher: TaskDispatcher | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self._task_dispatcher = task_dispatcher
        self._event_emitter = event_emitter

    async def handle(self, request: ModelSkillRequest) -> ModelCommentSweepResult:
        """Dispatch the skill request through the shared skill handler."""
        if self._task_dispatcher is None:
            raise RuntimeError("task_dispatcher is required for comment_sweep")
        if "render-prompt" in request.args:
            for field in ("render-prompt", "work-unit-id", "delegation-lane"):
                if not request.args.get(field, "").strip():
                    raise ValueError(f"{field} is required")
            home = os.environ.get("OMNI_HOME")
            if home and Path(home).is_absolute():
                venv = Path(
                    os.environ.get("ONEX_DISPATCH_VENV")
                    or Path(home) / ".onex-dispatch-venv"
                )
                pending = self._persist(
                    request,
                    ModelCommentSweepResult(
                        skill_name=request.skill_name,
                        status=SkillResultStatus.PARTIAL,
                        correlation_id=request.correlation_id,
                        error="render pending",
                        render_delegation=ModelRenderDelegation(
                            work_unit_id=request.args["work-unit-id"],
                            outcome="pending",
                            onex_binary=str(venv / "bin/onex"),
                            searched_venv=str(venv),
                        ),
                    ),
                )
                if pending.status == SkillResultStatus.FAILED:
                    return pending
            result = await self._render(request)
            return self._persist(request, result)
        result = await handle_skill_requested(
            request,
            task_dispatcher=self._task_dispatcher,
            event_emitter=self._event_emitter,
        )
        return ModelCommentSweepResult(**result.model_dump())

    @staticmethod
    def _persist(
        request: ModelSkillRequest,
        result: ModelCommentSweepResult,
    ) -> ModelCommentSweepResult:
        """Keep a work-side result even when the delegation wrote no receipt."""
        home = os.environ.get("OMNI_HOME")
        if not home or not Path(home).is_absolute():
            return result
        artifact = (
            Path(home) / ".onex_state/comment-sweep" / f"{request.correlation_id}.json"
        )
        assert result.render_delegation is not None
        record = result.render_delegation.model_copy(
            update={"artifact_path": str(artifact)}
        )
        result = ModelCommentSweepResult(
            **{**result.model_dump(), "render_delegation": record},
        )
        try:
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        except OSError:
            return ModelCommentSweepResult(
                **{
                    **result.model_dump(),
                    "status": SkillResultStatus.FAILED,
                    "error": "work-side render evidence could not be written",
                    "render_delegation": record.model_copy(
                        update={"artifact_path": None},
                    ),
                },
            )
        return result

    async def _render(self, request: ModelSkillRequest) -> ModelCommentSweepResult:
        """Try the declared CLI; preserve useful fallback work with explicit evidence."""
        prompt = request.args["render-prompt"]
        work_unit = request.args.get("work-unit-id", "")
        lane = request.args.get("delegation-lane", "")

        # Bootstrap locations only. Never resolve onex in the hooks venv or on PATH.
        home_value = os.environ.get("OMNI_HOME")
        if not home_value or not Path(home_value).is_absolute():
            return await self._fallback(
                request,
                binary="onex",
                venv="undeclared",
                reason="unconfigured_cli",
                detail="onex requires an absolute OMNI_HOME",
            )
        home = Path(home_value)
        venv = Path(
            os.environ.get("ONEX_DISPATCH_VENV") or home / ".onex-dispatch-venv"
        )
        binary = venv / "bin/onex"
        wrapper = home / "omnibase_infra/scripts/onex"
        if not venv.is_absolute() or not os.access(binary, os.X_OK):
            return await self._fallback(
                request,
                binary=str(binary),
                venv=str(venv),
                reason="missing_binary",
                detail=f"onex is unavailable at {binary}; searched CLI venv {venv}",
            )
        if not os.access(wrapper, os.X_OK):
            return await self._fallback(
                request,
                binary=str(binary),
                venv=str(venv),
                reason="missing_wrapper",
                detail=f"onex wrapper is unavailable at {wrapper}; CLI venv {venv}",
            )

        argv = [
            str(wrapper),
            "delegate",
            f"{prompt}\n\n{_OUTPUT_CONTRACT}",
            "--json",
            "--task-type",
            "document",
            "--bus",
            "kafka",
            "--lane",
            lane,
            "--locus",
            "deployed-lane",
            "--state-root",
            str(home / ".onex_state"),
        ]
        if ticket := request.args.get("ticket"):
            argv.extend(["--ticket", ticket])
        started = time.time()
        deadline = time.monotonic() + _DELEGATE_TIMEOUT_SECONDS
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=_DELEGATE_TIMEOUT_SECONDS,
            )
            if process.returncode != 0 and b"no bound consumer" in stderr.lower():
                # One sanctioned retry while a deployed consumer is being replaced.
                retry_argv = argv[: argv.index("--bus")] + [
                    "--bus",
                    "inmemory",
                    "--locus",
                    "in-process",
                    "--state-root",
                    str(home / ".onex_state"),
                ]
                if ticket:
                    retry_argv.extend(["--ticket", ticket])
                process = await asyncio.create_subprocess_exec(
                    *retry_argv,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, retry_stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=max(0.001, deadline - time.monotonic()),
                )
                stderr += b"\nIn-process retry: " + retry_stderr
            if process.returncode != 0:
                raise ValueError(
                    f"onex exited {process.returncode}: {stderr.decode(errors='replace')[-1000:]}"
                )
            cli = _object(json.loads(stdout))
            run_id = UUID(str(cli["run_id"]))
            correlation_id = UUID(str(cli["correlation_id"]))
            receipt_path = home / ".onex_state/runs" / str(run_id) / "receipt.json"
            if receipt_path.stat().st_mtime < started:
                raise ValueError("delegation receipt predates this render attempt")
            receipt = _object(json.loads(receipt_path.read_text()))
            inner = _object(receipt.get("receipt"))
            if (
                cli.get("status") != "success"
                or receipt.get("status") != "success"
                or receipt.get("run_id") != str(run_id)
                or receipt.get("correlation_id") != str(correlation_id)
                or inner.get("correlation_id") != str(correlation_id)
                or inner.get("run_id") != str(run_id)
                or inner.get("status") != "success"
            ):
                raise ValueError(
                    "delegation receipt does not match a successful CLI run"
                )
            record = ModelRenderDelegation(
                work_unit_id=work_unit,
                outcome="delegated",
                onex_binary=str(binary),
                searched_venv=str(venv),
                run_id=run_id,
                delegation_correlation_id=correlation_id,
                endpoint=_string(receipt.get("endpoint")),
                model=_string(receipt.get("model")),
            )
            return ModelCommentSweepResult(
                skill_name=request.skill_name,
                status=SkillResultStatus.SUCCESS,
                output=_receipt_response(
                    receipt, prompt=argv[2], correlation_id=correlation_id
                ),
                correlation_id=request.correlation_id,
                render_delegation=record,
            )
        except asyncio.CancelledError:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            raise
        except (OSError, ValueError, KeyError, TimeoutError) as exc:
            if process is not None and process.returncode is None:
                process.kill()
                await process.communicate()
            return await self._fallback(
                request,
                binary=str(binary),
                venv=str(venv),
                reason="delegate_failed",
                detail=f"onex at {binary} could not render the reply: {str(exc)[:1000]}",
            )

    async def _fallback(
        self,
        request: ModelSkillRequest,
        *,
        binary: str,
        venv: str,
        reason: str,
        detail: str,
    ) -> ModelCommentSweepResult:
        record = ModelRenderDelegation(
            work_unit_id=request.args["work-unit-id"],
            outcome="fallback",
            onex_binary=binary,
            searched_venv=venv,
            reason=reason,
            detail=detail,
        )
        # The output is a substitute, never relabelled as an onex response.
        prompt = (
            f"Render this comment reply locally because delegation is unavailable: {detail}.\n"
            f"{request.args['render-prompt']}\n\n"
            "Include a RESULT: block with status: success|failed|partial and error: detail."
        )
        assert self._task_dispatcher is not None
        try:
            output = await self._task_dispatcher(prompt)
            status, error = _parse_result_block(output)
        except (OSError, RuntimeError, ValueError):
            output = None
            status, error = (
                SkillResultStatus.FAILED,
                "fallback renderer raised an exception",
            )
        return ModelCommentSweepResult(
            skill_name=request.skill_name,
            status=status,
            output=output,
            error=error,
            correlation_id=request.correlation_id,
            render_delegation=record,
        )


__all__ = ["HandlerCommentSweepSkill"]
