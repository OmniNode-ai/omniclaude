#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill - classify prompt and dispatch through local runtime ingress.

Invoked when the user runs /onex:delegate.  Classifies the prompt via
TaskClassifier, wraps it in a ModelRuntimeSkillRequest, and sends it to the
runtime-owned Pattern B broker path via LocalRuntimeSkillClient.

When the runtime socket is unavailable (no Docker, no Kafka), the skill falls
back to running the delegation pipeline in-process via DelegationRunner.  The
``--local`` flag forces this in-process path without attempting the runtime.

Wire schema (plain dict - runtime-side validation by ModelDelegationCommand):
  {
    "prompt": str,
    "correlation_id": str (UUID4),
    "session_id": str,
    "prompt_length": int,
    "source_file_path": str | None,
    "max_tokens": int,
    "recipient": "auto" | "claude" | "opencode" | "codex",
    "wait_for_result": bool,
    "working_directory": str | None,
    "codex_sandbox_mode": str | None,
  }
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).parent  # delegate/_lib/
_SKILL_DIR = _LIB_DIR.parent  # delegate/
_PLUGIN_ROOT = _SKILL_DIR.parent.parent  # plugins/onex/
_HOOKS_LIB = _PLUGIN_ROOT / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _PLUGIN_ROOT.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
try:
    from omniclaude.lib.task_classifier import TaskClassifier

    _HAS_CLASSIFIER = True
except ImportError:
    _HAS_CLASSIFIER = False

try:
    from omnibase_core.models.runtime import ModelRuntimeSkillRequest
    from omnibase_infra.clients.runtime_skill_client import LocalRuntimeSkillClient

    _RUNTIME_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    ModelRuntimeSkillRequest = None  # type: ignore[assignment]
    LocalRuntimeSkillClient = None  # type: ignore[assignment]
    _RUNTIME_IMPORT_ERROR = exc

try:
    from omniclaude.delegation.runner import DelegationRunner, DelegationRunnerError

    _HAS_DELEGATION_RUNNER = True
except ImportError:
    DelegationRunner = None  # type: ignore[assignment,misc]
    DelegationRunnerError = Exception  # type: ignore[assignment,misc]
    _HAS_DELEGATION_RUNNER = False

try:
    from omniclaude.hooks.topics import TopicBase as _TopicBase

    # Use DELEGATE_TASK - the canonical topic that node_delegation_orchestrator
    # subscribes to (contract.yaml:39). Aligned in OMN-10050.
    _DELEGATION_REQUEST_TOPIC: str = _TopicBase.DELEGATE_TASK
except (ImportError, AttributeError):
    _DELEGATION_REQUEST_TOPIC = ""  # fallback; emit still works via event_type key

DELEGATABLE: frozenset[object] = (
    TaskClassifier.DELEGATABLE_INTENTS if _HAS_CLASSIFIER else frozenset()
)

_DELEGATION_COMMAND_NAME = "node_delegation_orchestrator"


def _resolve_correlation_id(correlation_id: str | None) -> uuid.UUID:
    raw_correlation_id = correlation_id or os.environ.get("ONEX_RUN_ID")
    if raw_correlation_id:
        try:
            return uuid.UUID(str(raw_correlation_id))
        except ValueError:
            pass
    return uuid.uuid4()


def _runtime_import_error(exc: ImportError) -> dict:
    return {
        "success": False,
        "error": (
            "Runtime skill client unavailable - install omnibase_core and "
            f"omnibase_infra in the plugin environment: {exc}"
        ),
    }


def _inprocess_fallback(
    *,
    prompt: str,
    intent_value: str,
    correlation_id: str,
    source_file: str | None,
    max_tokens: int,
) -> dict:
    """Run delegation pipeline in-process via DelegationRunner.

    Used when runtime socket is unavailable or --local is requested.
    """
    if not _HAS_DELEGATION_RUNNER or DelegationRunner is None:
        return {
            "success": False,
            "error": (
                "DelegationRunner unavailable - omniclaude.delegation.runner "
                "not importable (branch jonah/omn-10610 may not be merged)"
            ),
            "correlation_id": correlation_id,
        }

    try:
        runner = DelegationRunner()
        result = runner.run(
            task_type=intent_value,
            prompt=prompt,
            source_file_path=source_file,
            source_session_id=os.environ.get("CLAUDE_SESSION_ID"),
            max_tokens=max_tokens,
        )
    except DelegationRunnerError as exc:
        return {
            "success": False,
            "error": str(exc),
            "correlation_id": correlation_id,
            "path": "inprocess",
        }

    return {
        "success": True,
        "correlation_id": str(result.correlation_id),
        "task_type": result.task_type,
        "model_used": result.model_used,
        "endpoint_url": result.endpoint_url,
        "content": result.content,
        "quality_passed": result.quality_passed,
        "quality_score": result.quality_score,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "fallback_to_claude": result.fallback_to_claude,
        "failure_reason": result.failure_reason,
        "path": "inprocess",
    }


# ---------------------------------------------------------------------------
# Core dispatch function
# ---------------------------------------------------------------------------


def classify_and_publish(
    prompt: str,
    source_file: str | None = None,
    max_tokens: int = 2048,
    correlation_id: str | None = None,
    recipient: Literal["auto", "claude", "opencode", "codex"] = "auto",
    wait_for_result: bool = False,
    working_directory: str | None = None,
    codex_sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"]
    | None = None,
    timeout_ms: int = 300_000,
    force_local: bool = False,
) -> dict:
    """Classify *prompt* and dispatch a delegation request.

    Primary path: LocalRuntimeSkillClient (Unix socket → runtime → Kafka).
    Fallback path: DelegationRunner in-process (no Docker/Kafka required).

    Set ``force_local=True`` (or pass ``--local`` via CLI) to skip the
    runtime attempt and run in-process directly.

    Returns a result dict with keys: success, correlation_id, task_type, path.
    On failure, returns success=False with an error message.
    """
    if not _HAS_CLASSIFIER:
        return {
            "success": False,
            "error": "TaskClassifier unavailable - omniclaude package not on sys.path",
        }

    classifier = TaskClassifier()
    result = classifier.classify(prompt)

    intent = result.primary_intent
    if intent not in DELEGATABLE:
        return {
            "success": False,
            "error": (
                f"Task type '{intent.value}' is not delegatable. "
                "Only test/document/research tasks can be delegated."
            ),
        }

    correlation_uuid = _resolve_correlation_id(correlation_id)
    correlation_id = str(correlation_uuid)

    if force_local:
        return _inprocess_fallback(
            prompt=prompt,
            intent_value=intent.value,
            correlation_id=correlation_id,
            source_file=source_file,
            max_tokens=max_tokens,
        )

    delegation_payload = {
        "prompt": prompt,
        "correlation_id": correlation_id,
        "session_id": os.environ.get("CLAUDE_SESSION_ID") or "",
        "prompt_length": len(prompt),
        "source_file_path": source_file,
        "max_tokens": max_tokens,
        "recipient": recipient,
        "wait_for_result": wait_for_result,
        "working_directory": working_directory,
        "codex_sandbox_mode": codex_sandbox_mode,
    }

    if (
        _RUNTIME_IMPORT_ERROR is not None
        or ModelRuntimeSkillRequest is None
        or LocalRuntimeSkillClient is None
    ):
        return _inprocess_fallback(
            prompt=prompt,
            intent_value=intent.value,
            correlation_id=correlation_id,
            source_file=source_file,
            max_tokens=max_tokens,
        )

    request = ModelRuntimeSkillRequest(
        command_name=_DELEGATION_COMMAND_NAME,
        payload=delegation_payload,
        correlation_id=correlation_uuid,
        timeout_ms=timeout_ms,
    )

    try:
        response = LocalRuntimeSkillClient().dispatch_sync(request)
    except Exception:
        return _inprocess_fallback(
            prompt=prompt,
            intent_value=intent.value,
            correlation_id=correlation_id,
            source_file=source_file,
            max_tokens=max_tokens,
        )

    if not response.ok:
        error = response.error
        error_code = error.code if error else "dispatch_error"
        # Connection errors indicate runtime is down — fall back in-process.
        if error_code in ("socket_unavailable", "connection_refused", "timeout"):
            return _inprocess_fallback(
                prompt=prompt,
                intent_value=intent.value,
                correlation_id=correlation_id,
                source_file=source_file,
                max_tokens=max_tokens,
            )
        return {
            "success": False,
            "error": error.message if error else "runtime dispatch failed",
            "error_code": error_code,
            "retryable": error.retryable if error else False,
            "correlation_id": correlation_id,
            "command_name": _DELEGATION_COMMAND_NAME,
            "topic": response.command_topic or _DELEGATION_REQUEST_TOPIC,
            "path": "runtime",
        }

    return {
        "success": True,
        "correlation_id": correlation_id,
        "task_type": intent.value,
        "command_name": response.command_name,
        "resolved_node_name": response.resolved_node_name,
        "topic": response.command_topic or _DELEGATION_REQUEST_TOPIC,
        "terminal_event": response.terminal_event,
        "dispatch_status": response.dispatch_result.status
        if response.dispatch_result
        else None,
        "output_payloads": response.output_payloads,
        "path": "runtime",
    }


# ---------------------------------------------------------------------------
# CLI entry point (called from SKILL.md dispatch)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for /onex:delegate."""
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Delegate skill - dispatch through local runtime ingress"
    )
    parser.add_argument("prompt", nargs="+", help="The task to delegate")
    parser.add_argument("--source-file", default=None)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument(
        "--recipient",
        choices=("auto", "claude", "opencode", "codex"),
        default="auto",
    )
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--working-directory", default=None)
    parser.add_argument(
        "--codex-sandbox-mode",
        choices=("read-only", "workspace-write", "danger-full-access"),
        default=None,
    )
    parser.add_argument("--timeout-ms", type=int, default=300_000)
    parser.add_argument(
        "--local",
        action="store_true",
        help="Force in-process DelegationRunner (skip runtime socket attempt)",
    )
    args = parser.parse_args()

    prompt = " ".join(args.prompt)
    result = classify_and_publish(
        prompt=prompt,
        source_file=args.source_file,
        max_tokens=args.max_tokens,
        correlation_id=args.correlation_id,
        recipient=args.recipient,
        wait_for_result=args.wait,
        working_directory=args.working_directory,
        codex_sandbox_mode=args.codex_sandbox_mode,
        timeout_ms=args.timeout_ms,
        force_local=args.local,
    )

    print(json.dumps(result, indent=2))

    if result.get("success"):
        path = result.get("path", "runtime")
        print(
            f"\nDelegation dispatched ({path}) - correlation_id={result['correlation_id']}\n"
            f"task_type={result['task_type']}",
            file=sys.stderr,
        )
        if path == "runtime":
            print(
                f"command_name={result.get('command_name')}\n"
                f"dispatch_status={result.get('dispatch_status')}",
                file=sys.stderr,
            )
        else:
            print(
                f"model_used={result.get('model_used')}\n"
                f"quality_passed={result.get('quality_passed')}\n"
                f"latency_ms={result.get('latency_ms')}",
                file=sys.stderr,
            )
    else:
        print(f"\nDelegation failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
