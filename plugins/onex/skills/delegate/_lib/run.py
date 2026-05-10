#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill - classify prompt and dispatch through local runtime ingress.

Invoked when the user runs /onex:delegate.  Classifies the prompt via
TaskClassifier, wraps it in a ModelRuntimeSkillRequest, and sends it to the
runtime-owned Pattern B broker path via LocalRuntimeSkillClient.

If the runtime socket is unavailable, the skill returns an explicit error.
There is no silent in-process fallback (OMN-10723).

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
    from omniclaude.delegation.evidence_bundle import (
        EvidenceBundleWriter,
        ModelBifrostResponse,
        ModelCostEvent,
        ModelQualityGateArtifact,
        ModelRunManifest,
        hash_prompt,
        new_bundle_id,
    )

    _HAS_EVIDENCE_BUNDLE = True
except ImportError:
    _HAS_EVIDENCE_BUNDLE = False

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


def _write_evidence_bundle(
    *,
    result: object,
    prompt: str,
    started_at: object,
    completed_at: object,
) -> str | None:
    """Write the 5-artifact delegation evidence bundle. Returns bundle dir or None.

    Fail-soft: any error (bundle module missing, ONEX_STATE_DIR unset, write
    failure) returns None without raising. The user-facing delegation result
    must not be broken by an evidence-bundle problem.
    """
    if not _HAS_EVIDENCE_BUNDLE:
        return None
    state_dir = os.environ.get("ONEX_STATE_DIR")
    if not state_dir:
        return None

    try:
        from datetime import UTC, datetime  # noqa: PLC0415
        from pathlib import Path as _Path  # noqa: PLC0415

        cid = str(result.correlation_id)  # type: ignore[attr-defined]
        bundle_root = _Path(state_dir) / "delegation" / "bundles"
        bundle_root.mkdir(parents=True, exist_ok=True)

        manifest = ModelRunManifest(
            correlation_id=cid,
            bundle_id=new_bundle_id(),
            ticket_id=os.environ.get("ONEX_TICKET_ID"),
            session_id=__import__(
                "plugins.onex.hooks.lib.session_id", fromlist=["resolve_session_id"]
            ).resolve_session_id(default=None),
            task_type=str(result.task_type),  # type: ignore[attr-defined]
            prompt_hash=hash_prompt(prompt),
            started_at=started_at,  # type: ignore[arg-type]
            completed_at=completed_at,  # type: ignore[arg-type]
            runner="inprocess",
        )
        bifrost = ModelBifrostResponse(
            correlation_id=cid,
            backend_selected=str(result.endpoint_url),  # type: ignore[attr-defined]
            model_used=str(result.model_used),  # type: ignore[attr-defined]
            latency_ms=int(result.latency_ms),  # type: ignore[attr-defined]
            prompt_tokens=int(result.prompt_tokens),  # type: ignore[attr-defined]
            completion_tokens=int(result.completion_tokens),  # type: ignore[attr-defined]
            total_tokens=int(result.total_tokens),  # type: ignore[attr-defined]
            response_content=str(result.content),  # type: ignore[attr-defined]
        )
        gate = ModelQualityGateArtifact(
            correlation_id=cid,
            passed=bool(result.quality_passed),  # type: ignore[attr-defined]
            quality_score=result.quality_score,  # type: ignore[attr-defined]
            failure_reasons=(
                (result.failure_reason,)  # type: ignore[attr-defined]
                if result.failure_reason  # type: ignore[attr-defined]
                else ()
            ),
            fallback_to_claude=bool(result.fallback_to_claude),  # type: ignore[attr-defined]
        )
        cost = ModelCostEvent(
            correlation_id=cid,
            session_id=__import__(
                "plugins.onex.hooks.lib.session_id", fromlist=["resolve_session_id"]
            ).resolve_session_id(default=None),
            model_local=str(result.model_used),  # type: ignore[attr-defined]
            baseline_model="claude-sonnet-4-6",
            local_cost_usd=None,
            cloud_cost_usd=None,
            savings_usd=None,
            savings_method="not_computed_inprocess",
            token_provenance="vllm_usage_block",  # secret-ok: provenance label, not a secret  # noqa: S106
            pricing_manifest_version="unset",
            prompt_tokens=int(result.prompt_tokens),  # type: ignore[attr-defined]
            completion_tokens=int(result.completion_tokens),  # type: ignore[attr-defined]
        )
        writer = EvidenceBundleWriter(root_dir=bundle_root)
        writer.write(
            manifest=manifest,
            bifrost_response=bifrost,
            quality_gate=gate,
            cost_event=cost,
            issued_at=datetime.now(UTC),
        )
        return str(bundle_root / cid)
    except Exception:  # noqa: BLE001
        return None


def _emit_task_delegated_event(
    *,
    result: object,
    fallback_correlation_id: str,
    session_id: str | None,
) -> bool:
    """Emit the canonical task.delegated event for projection consumers."""
    try:
        from datetime import UTC, datetime  # noqa: PLC0415

        from emit_client_wrapper import (
            emit_event,  # type: ignore[import-not-found] # noqa: PLC0415
        )

        from omniclaude.hooks.schemas import ModelTaskDelegatedPayload  # noqa: PLC0415

        raw_correlation_id = getattr(result, "correlation_id", fallback_correlation_id)
        correlation_uuid = uuid.UUID(str(raw_correlation_id))
        quality_passed = bool(getattr(result, "quality_passed", False))
        failure_reason = str(getattr(result, "failure_reason", "") or "")
        model_used = str(getattr(result, "model_used", "") or "local-delegation-runner")

        payload = ModelTaskDelegatedPayload(
            session_id=session_id or "local-inprocess",
            correlation_id=correlation_uuid,
            emitted_at=datetime.now(UTC),
            task_type=str(getattr(result, "task_type", "") or "delegation"),
            delegated_to=model_used,
            delegated_by="onex.delegate-skill.inprocess",
            quality_gate_passed=quality_passed,
            quality_gate_reason=None if quality_passed else failure_reason,
            delegation_success=bool(getattr(result, "content", "")) and quality_passed,
            cost_savings_usd=0.0,
            delegation_latency_ms=int(getattr(result, "latency_ms", 0) or 0),
        )
        return bool(emit_event("task.delegated", payload.model_dump(mode="json")))
    except Exception:  # noqa: BLE001
        return False


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
    """Classify *prompt* and dispatch a delegation request via runtime socket.

    Returns a result dict with keys: success, correlation_id, task_type, path.
    On failure, returns success=False with an error message.
    The ``--local`` flag (force_local=True) is no longer supported (OMN-10723).
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
        runtime_socket_path = os.environ.get(
            "ONEX_LOCAL_RUNTIME_SOCKET_PATH", "<unset>"
        )
        return {
            "success": False,
            "error": (
                "In-process fallback removed (OMN-10723). "
                "Use the runtime path: start the runtime and ensure "
                f"ONEX_LOCAL_RUNTIME_SOCKET_PATH is set (current value: {runtime_socket_path})."
            ),
            "correlation_id": correlation_id,
        }

    from plugins.onex.hooks.lib.session_id import resolve_session_id  # noqa: PLC0415

    delegation_payload = {
        "prompt": prompt,
        "correlation_id": correlation_id,
        "session_id": resolve_session_id(default=""),
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
        return _runtime_import_error(
            _RUNTIME_IMPORT_ERROR or ImportError("missing runtime classes")
        )

    request = ModelRuntimeSkillRequest(
        command_name=_DELEGATION_COMMAND_NAME,
        payload=delegation_payload,
        correlation_id=correlation_uuid,
        timeout_ms=timeout_ms,
    )

    try:
        response = LocalRuntimeSkillClient().dispatch_sync(request)
    except Exception as exc:
        return {
            "success": False,
            "error": f"Runtime socket unavailable: {exc}. Start the runtime or set ONEX_LOCAL_RUNTIME_SOCKET_PATH.",
            "correlation_id": correlation_id,
            "path": "runtime",
        }

    if not response.ok:
        error = response.error
        error_code = error.code if error else "dispatch_error"
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
        help="[removed] In-process fallback removed (OMN-10723). Returns an error.",
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
        print(
            f"\nDelegation dispatched (runtime) - correlation_id={result['correlation_id']}\n"
            f"task_type={result['task_type']}\n"
            f"command_name={result.get('command_name')}\n"
            f"dispatch_status={result.get('dispatch_status')}",
            file=sys.stderr,
        )
    else:
        print(f"\nDelegation failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
