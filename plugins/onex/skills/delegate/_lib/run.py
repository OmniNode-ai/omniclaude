#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill compatibility wrapper over the market-owned adapter.

This module keeps the historical /onex:delegate CLI shape while delegating all
runtime dispatch to ``omnimarket.adapters.claude_code.delegate``.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Literal

_LIB_DIR = Path(__file__).parent
_SKILL_DIR = _LIB_DIR.parent
_PLUGIN_ROOT = _SKILL_DIR.parent.parent
_REPO_ROOT = _PLUGIN_ROOT.parent.parent

for _path in (
    _REPO_ROOT,
    _PLUGIN_ROOT / "hooks" / "lib",
    _REPO_ROOT / "src",
):
    if _path.exists() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

_omni_home = os.environ.get("OMNI_HOME")
if _omni_home:
    _market_src = Path(_omni_home) / "omnimarket" / "src"
    if _market_src.exists() and str(_market_src) not in sys.path:
        sys.path.insert(0, str(_market_src))

try:
    from omniclaude.lib.task_classifier import TaskClassifier

    _HAS_CLASSIFIER = True
except ImportError:
    TaskClassifier = None  # type: ignore[assignment]
    _HAS_CLASSIFIER = False

DelegationDispatchAdapter: type[Any] | None = None

_DELEGATION_COMMAND_NAME = "delegate_skill.orchestrate"
_DELEGATION_NODE_NAME = "node_delegate_skill_orchestrator"
_RUNTIME_TASK_TYPES = frozenset({"test", "document", "research"})


def _load_adapter_class() -> tuple[type[Any] | None, Exception | None]:
    if DelegationDispatchAdapter is not None:
        return DelegationDispatchAdapter, None
    try:
        from omnimarket.adapters.claude_code.delegate import (
            DelegationDispatchAdapter as AdapterClass,
        )
    except Exception as exc:  # noqa: BLE001
        return None, exc
    return AdapterClass, None


def _resolve_correlation_id(correlation_id: str | None) -> uuid.UUID:
    raw_correlation_id = correlation_id or os.environ.get("ONEX_RUN_ID")
    if raw_correlation_id:
        try:
            return uuid.UUID(str(raw_correlation_id))
        except ValueError:
            pass
    return uuid.uuid4()


def _resolve_session_id() -> str:
    for env_name in (
        "ONEX_SESSION_ID",
        "CLAUDE_SESSION_ID",
        "CLAUDE_CODE_SESSION_ID",
    ):
        value = os.environ.get(env_name, "").strip()
        if value:
            return value

    try:
        from plugins.onex.hooks.lib.session_id import resolve_session_id
    except ImportError:
        try:
            from session_id import resolve_session_id  # type: ignore[no-redef]
        except ImportError:
            return ""
    return str(resolve_session_id(default="") or "")


def _delegatable_intents() -> frozenset[object]:
    if not _HAS_CLASSIFIER or TaskClassifier is None:
        return frozenset()
    return frozenset(getattr(TaskClassifier, "DELEGATABLE_INTENTS", frozenset()))


DELEGATABLE: frozenset[object] = _delegatable_intents()


def _resolve_runtime_task_type(intent_value: str, prompt: str) -> str:
    if intent_value in _RUNTIME_TASK_TYPES:
        return intent_value

    prompt_lower = prompt.lower()
    if any(marker in prompt_lower for marker in ("test", "pytest", "unit test")):
        return "test"
    if any(
        marker in prompt_lower
        for marker in ("doc", "docs", "docstring", "documentation", "readme")
    ):
        return "document"
    return "research"


def _build_metadata(
    *,
    source_file: str | None,
    session_id: str,
    recipient: str,
    wait_for_result: bool,
    working_directory: str | None,
    codex_sandbox_mode: str | None,
    timeout_ms: int,
) -> dict[str, str]:
    metadata = {
        "adapter": "omniclaude.delegate-skill",
        "session_id": session_id,
        "recipient": recipient,
        "wait_for_result": str(wait_for_result).lower(),
        "timeout_ms": str(timeout_ms),
    }
    if source_file:
        metadata["source_file_path"] = source_file
    if working_directory:
        metadata["working_directory"] = working_directory
    if codex_sandbox_mode:
        metadata["codex_sandbox_mode"] = codex_sandbox_mode
    return metadata


def _normalize_adapter_result(
    raw: dict[str, Any],
    *,
    correlation_id: str,
    task_type: str,
) -> dict[str, Any]:
    success = bool(raw.get("ok", raw.get("success", False)))
    result: dict[str, Any] = {
        "success": success,
        "correlation_id": str(raw.get("correlation_id") or correlation_id),
        "task_type": task_type,
        "command_name": _DELEGATION_COMMAND_NAME,
        "resolved_node_name": _DELEGATION_NODE_NAME,
        "path": "omnimarket_adapter",
    }
    result.update(raw)
    result["success"] = success
    result.setdefault("ok", success)
    result.setdefault("command_name", _DELEGATION_COMMAND_NAME)
    result.setdefault("resolved_node_name", _DELEGATION_NODE_NAME)
    result.setdefault("path", "omnimarket_adapter")
    result.setdefault("task_type", task_type)
    return result


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
) -> dict[str, Any]:
    """Classify *prompt* and hand the request to the market adapter."""
    if not prompt.strip():
        return {"success": False, "ok": False, "error": "prompt must not be empty"}
    if max_tokens < 1:
        return {
            "success": False,
            "ok": False,
            "error": f"max_tokens must be positive, got {max_tokens}",
        }
    if timeout_ms <= 0:
        return {
            "success": False,
            "ok": False,
            "error": f"timeout_ms must be positive, got {timeout_ms}",
        }
    if not _HAS_CLASSIFIER or TaskClassifier is None:
        return {
            "success": False,
            "ok": False,
            "error": "TaskClassifier unavailable - omniclaude package not on sys.path",
        }

    classifier = TaskClassifier()
    classification = classifier.classify(prompt)
    intent = classification.primary_intent
    if intent not in DELEGATABLE:
        intent_value = getattr(intent, "value", str(intent))
        return {
            "success": False,
            "ok": False,
            "error": (
                f"Task type '{intent_value}' is not delegatable. "
                "Only test/document/research tasks can be delegated."
            ),
        }

    adapter_cls, import_error = _load_adapter_class()
    if adapter_cls is None:
        return {
            "success": False,
            "ok": False,
            "error": (
                "Market delegation adapter unavailable - install omnimarket in "
                f"the plugin environment: {import_error}"
            ),
        }

    correlation_uuid = _resolve_correlation_id(correlation_id)
    correlation_id_str = str(correlation_uuid)
    runtime_task_type = _resolve_runtime_task_type(
        getattr(intent, "value", str(intent)),
        prompt,
    )
    session_id = _resolve_session_id()
    metadata = _build_metadata(
        source_file=source_file,
        session_id=session_id,
        recipient=recipient,
        wait_for_result=wait_for_result,
        working_directory=working_directory,
        codex_sandbox_mode=codex_sandbox_mode,
        timeout_ms=timeout_ms,
    )

    try:
        adapter = adapter_cls()
        raw_result = adapter.dispatch_sync(
            prompt=prompt,
            task_type=runtime_task_type,
            source="claude-code",
            cwd=working_directory,
            wait=wait_for_result,
            max_tokens=max_tokens,
            correlation_id=correlation_uuid,
            metadata=metadata,
            timeout_ms=timeout_ms,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "ok": False,
            "error": str(exc),
            "correlation_id": correlation_id_str,
            "task_type": runtime_task_type,
            "command_name": _DELEGATION_COMMAND_NAME,
            "resolved_node_name": _DELEGATION_NODE_NAME,
            "path": "omnimarket_adapter",
        }

    if not isinstance(raw_result, dict):
        raw_result = {
            "ok": False,
            "error": f"adapter returned {type(raw_result).__name__}",
        }

    return _normalize_adapter_result(
        raw_result,
        correlation_id=correlation_id_str,
        task_type=runtime_task_type,
    )


def main() -> None:
    """CLI entry point for /onex:delegate."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Delegate a classified task through the market delegation adapter."
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
    args = parser.parse_args()

    result = classify_and_publish(
        prompt=" ".join(args.prompt),
        source_file=args.source_file,
        max_tokens=args.max_tokens,
        correlation_id=args.correlation_id,
        recipient=args.recipient,
        wait_for_result=args.wait,
        working_directory=args.working_directory,
        codex_sandbox_mode=args.codex_sandbox_mode,
        timeout_ms=args.timeout_ms,
    )

    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(
            f"\nDelegation dispatched ({result.get('path')}) - "
            f"correlation_id={result['correlation_id']}\n"
            f"task_type={result['task_type']}\n"
            f"command_name={result.get('command_name')}",
            file=sys.stderr,
        )
    else:
        print(f"\nDelegation failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
