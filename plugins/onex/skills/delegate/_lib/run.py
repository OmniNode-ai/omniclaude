#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill - classify prompt and dispatch through the market delegation adapter.

Invoked when the user runs /onex:delegate.  Classifies the prompt via
TaskClassifier, then dispatches through:
  1. DelegationDispatchAdapter → contract-declared runtime dispatch →
     node_delegate_skill_orchestrator (canonical market adapter path)
  2. Local in-process runner when --local is passed (debug/demo path only)

Topic resolution and transport wiring are owned by omnimarket's
DelegationDispatchAdapter; this shim has no transport logic.
"""

from __future__ import annotations

import json
import os
import subprocess
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
_REPO_ROOT = _PLUGIN_ROOT.parent.parent  # repository root
if _REPO_ROOT.exists() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_HOOKS_LIB = _PLUGIN_ROOT / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _REPO_ROOT / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# ---------------------------------------------------------------------------
# Classifier import
# ---------------------------------------------------------------------------
try:
    from omniclaude.lib.task_classifier import TaskClassifier

    _HAS_CLASSIFIER = True
except ImportError:
    _HAS_CLASSIFIER = False

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
    from omniclaude.delegation.inprocess_runner import (  # fallback-removed
        InProcessDelegationRunner,  # fallback-removed
    )

    _HAS_INPROCESS_RUNNER = True
except ImportError:
    _HAS_INPROCESS_RUNNER = False

try:
    from omnimarket.adapters.claude_code.delegate import (
        DelegationDispatchAdapter,
    )

    _HAS_MARKET_ADAPTER = True
    _MARKET_ADAPTER_IMPORT_ERROR: ImportError | None = None
except ImportError as _exc:
    DelegationDispatchAdapter = None  # type: ignore[assignment,misc]
    _HAS_MARKET_ADAPTER = False
    _MARKET_ADAPTER_IMPORT_ERROR = _exc


# ---------------------------------------------------------------------------
# curl-based LLM shim for Mac LAN grant (uv-managed Python lacks the grant)
# ---------------------------------------------------------------------------


def _call_llm_via_curl(
    *,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    correlation_id: uuid.UUID,
) -> tuple[str, dict, int, str]:  # type: ignore[type-arg]
    """Drop-in replacement for _call_llm using curl subprocess.  # fallback-removed

    macOS Local Network privacy grant is per-binary. uv-managed Python venvs
    (used by the plugin) do not carry the grant and get EHOSTUNREACH when
    connecting to 192.168.x.x. curl does carry the grant. This shim provides  # onex-allow-internal-ip
    the same return contract as _call_llm.
    """
    import time  # noqa: PLC0415

    # Model-id rewrite: routing_tiers.yaml uses short IDs that vLLM rejects.
    # vLLM serves the full HuggingFace ID; map short → served at the wire.
    _VLLM_MODEL_REWRITES: dict[str, str] = {
        "qwen3-coder-30b": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        "deepseek-r1-14b": "Corianas/DeepSeek-R1-Distill-Qwen-14B-AWQ",
    }
    served_model = _VLLM_MODEL_REWRITES.get(model, model)

    payload = {
        "model": served_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = f"{endpoint_url.rstrip('/')}/v1/chat/completions"

    t0 = time.monotonic_ns()
    proc = subprocess.run(  # noqa: S603
        [
            "curl",
            "-fsS",
            "--max-time",
            "120",
            "-H",
            "Content-Type: application/json",
            "-X",
            "POST",
            url,
            "-d",
            json.dumps(payload),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    latency_ms = (time.monotonic_ns() - t0) // 1_000_000

    if proc.returncode != 0:
        raise RuntimeError(
            f"curl LLM call failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"vLLM returned invalid JSON: {exc}\nstdout={proc.stdout[:400]}"
        ) from exc

    try:
        content: str = data["choices"][0]["message"]["content"] or ""
        model_used: str = data.get("model", served_model)
        usage: dict[str, int] = {
            "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
            "total_tokens": data.get("usage", {}).get("total_tokens", 0),
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(
            f"vLLM response missing expected fields: {exc} — keys: {list(data)}"
        ) from exc

    return content, usage, int(latency_ms), model_used


_DELEGATION_COMMAND_NAME = "node_delegate_skill_orchestrator"
_CONTRACT_RELATIVE_PATH = (
    "omnimarket/src/omnimarket/nodes/node_delegate_skill_orchestrator/contract.yaml"
)


def _resolve_command_topic() -> str:
    """Return the subscribe topic from the node's contract.yaml.

    Locates the contract via OMNI_HOME, loads it with yaml.safe_load, and
    returns event_bus.subscribe_topics[0]. Returns an empty string on any
    failure so callers can produce a clear error rather than silently misbehaving.
    """
    omni_home = os.environ.get("OMNI_HOME", "").strip()
    if not omni_home:
        return ""
    contract_path = Path(omni_home) / _CONTRACT_RELATIVE_PATH
    if not contract_path.is_file():
        return ""
    try:
        import yaml  # noqa: PLC0415

        data = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
        topics = (data or {}).get("event_bus", {}).get("subscribe_topics", [])
        return str(topics[0]) if topics else ""
    except Exception:  # noqa: BLE001
        return ""


_DELEGATION_REQUEST_TOPIC: str = _resolve_command_topic()


DELEGATABLE: frozenset[object] = (
    TaskClassifier.DELEGATABLE_INTENTS if _HAS_CLASSIFIER else frozenset()
)
_RUNTIME_TASK_TYPES = frozenset({"test", "document", "research"})


def _resolve_correlation_id(correlation_id: str | None) -> uuid.UUID:
    raw_correlation_id = correlation_id or os.environ.get("ONEX_RUN_ID")
    if raw_correlation_id:
        try:
            return uuid.UUID(str(raw_correlation_id))
        except ValueError:
            pass
    return uuid.uuid4()


def _resolve_runtime_task_type(intent_value: str, prompt: str) -> str:
    """Map classifier intents onto the runtime's supported task_type literals."""
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


def _build_delegation_request_payload(
    delegation_payload: dict,  # type: ignore[type-arg]
    task_type: str,
    emitted_at: str,
) -> dict:  # type: ignore[type-arg]
    """Build a ModelDelegationRequest-compatible payload dict.

    ModelDelegationRequest uses extra="forbid", so only known fields may be sent.
    Maps delegation_payload's field names to ModelDelegationRequest's names.
    """
    return {
        "prompt": delegation_payload.get("prompt", ""),
        "task_type": task_type,
        "source_session_id": delegation_payload.get("session_id"),
        "source_file_path": delegation_payload.get("source_file_path"),
        "correlation_id": delegation_payload.get("correlation_id"),
        "max_tokens": delegation_payload.get("max_tokens", 2048),
        "emitted_at": emitted_at,
    }


# ---------------------------------------------------------------------------
# In-process local execution (explicit --local demo path, not silent fallback)
# ---------------------------------------------------------------------------


def _run_inprocess(
    *,
    prompt: str,
    task_type: str,
    correlation_id_str: str,
    correlation_uuid: uuid.UUID,
    source_file: str | None,
    max_tokens: int,
) -> dict:  # type: ignore[type-arg]
    """Run the local delegation pipeline with a curl LLM shim.  # fallback-removed

    Uses a curl subprocess for the LLM HTTP call so this works from
    uv-managed plugin venvs on Mac (which lack the macOS Local Network grant).

    Returns a result dict with path="inprocess" and the same keys that
    classify_and_publish returns for other transports.
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from unittest.mock import patch  # noqa: PLC0415

    started_at = datetime.now(UTC)
    runner = InProcessDelegationRunner()  # fallback-removed

    try:
        session_id: str | None
        try:
            from plugins.onex.hooks.lib.session_id import (  # noqa: PLC0415
                resolve_session_id,
            )

            session_id = resolve_session_id(default=None)
        except (ModuleNotFoundError, ImportError):
            try:
                from session_id import (
                    resolve_session_id as _rs,  # type: ignore[no-redef] # noqa: PLC0415
                )

                session_id = _rs(default=None)
            except (ModuleNotFoundError, ImportError):
                session_id = None

        _TARGET = "omniclaude.delegation.inprocess_runner._call_llm"  # fallback-removed
        with patch(_TARGET, side_effect=_call_llm_via_curl):
            result = runner.run(
                task_type=task_type,
                prompt=prompt,
                source_session_id=session_id,
                source_file_path=source_file,
                max_tokens=max_tokens,
            )

    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": f"In-process delegation pipeline failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "inprocess",
        }

    completed_at = datetime.now(UTC)

    bundle_path = _write_evidence_bundle(
        result=result,
        prompt=prompt,
        started_at=started_at,
        completed_at=completed_at,
    )

    _emit_task_delegated_event(
        result=result,
        fallback_correlation_id=correlation_id_str,
        session_id=session_id,
    )

    return {
        "success": True,
        "correlation_id": str(result.correlation_id),
        "task_type": str(result.task_type),
        "path": "inprocess",
        "content": result.content,
        "model_used": result.model_used,
        "endpoint_url": result.endpoint_url,
        "quality_passed": result.quality_passed,
        "quality_score": result.quality_score,
        "failure_reason": result.failure_reason,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "total_tokens": result.total_tokens,
        "fallback_to_claude": result.fallback_to_claude,
        "evidence_bundle_path": bundle_path,
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
) -> dict:  # type: ignore[type-arg]
    """Classify *prompt* and dispatch a delegation request through the market adapter.

    Canonical path: DelegationDispatchAdapter → contract-declared runtime dispatch
    → node_delegate_skill_orchestrator.

    force_local=True dispatches via the local runner with a curl LLM shim  # fallback-removed
    (no Kafka or runtime socket required). Intended for debug/demo use only.
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
    runtime_task_type = _resolve_runtime_task_type(intent.value, prompt)

    correlation_uuid = _resolve_correlation_id(correlation_id)
    correlation_id_str = str(correlation_uuid)

    if force_local:
        if not _HAS_INPROCESS_RUNNER:
            return {
                "success": False,
                "error": (
                    "Local in-process runner unavailable — omniclaude or omnimarket "  # fallback-removed
                    "packages not on sys.path. Install the plugin venv dependencies."
                ),
                "correlation_id": correlation_id_str,
                "path": "inprocess",
            }
        return _run_inprocess(
            prompt=prompt,
            task_type=runtime_task_type,
            correlation_id_str=correlation_id_str,
            correlation_uuid=correlation_uuid,
            source_file=source_file,
            max_tokens=max_tokens,
        )

    if not _HAS_MARKET_ADAPTER:
        return {
            "success": False,
            "error": (
                "DelegationDispatchAdapter unavailable — omnimarket package not on "
                f"sys.path. Install the plugin venv dependencies: "
                f"{_MARKET_ADAPTER_IMPORT_ERROR}"
            ),
            "correlation_id": correlation_id_str,
            "path": "market_adapter",
        }

    if timeout_ms <= 0:
        return {
            "success": False,
            "error": f"timeout_ms must be positive, got {timeout_ms}",
            "correlation_id": correlation_id_str,
        }

    try:
        session_id: str | None
        try:
            from plugins.onex.hooks.lib.session_id import (  # noqa: PLC0415
                resolve_session_id,
            )

            session_id = resolve_session_id(default=None)
        except (ModuleNotFoundError, ImportError):
            try:
                from session_id import resolve_session_id as _rs  # type: ignore[no-redef] # noqa: I001, PLC0415

                session_id = _rs(default=None)
            except (ModuleNotFoundError, ImportError):
                session_id = None

        # Map recipient to source for the market adapter
        source = "codex" if recipient == "codex" else "claude-code"

        adapter = DelegationDispatchAdapter()
        response = adapter.dispatch_sync(
            prompt=prompt,
            task_type=runtime_task_type,
            source=source,
            cwd=working_directory,
            wait=wait_for_result,
            max_tokens=max_tokens,
            correlation_id=correlation_uuid,
            timeout_ms=timeout_ms,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Market adapter dispatch failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "market_adapter",
        }

    ok = response.get("ok", False)
    if not ok:
        return {
            "success": False,
            "error": response.get("error") or "market adapter dispatch failed",
            "correlation_id": response.get("correlation_id", correlation_id_str),
            "command_name": _DELEGATION_COMMAND_NAME,
            "topic": response.get("command_topic") or _DELEGATION_REQUEST_TOPIC,
            "path": "market_adapter",
        }

    return {
        "success": True,
        "correlation_id": response.get("correlation_id", correlation_id_str),
        "task_type": runtime_task_type,
        "command_name": _DELEGATION_COMMAND_NAME,
        "topic": response.get("command_topic") or _DELEGATION_REQUEST_TOPIC,
        "terminal_events": response.get("terminal_events"),
        "dispatch_status": response.get("status"),
        "path": "market_adapter",
    }


# ---------------------------------------------------------------------------
# CLI entry point (called from SKILL.md dispatch)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for /onex:delegate."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Delegate skill - dispatch through omnimarket DelegationDispatchAdapter"
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
        help="Run delegation in-process using local vLLM endpoint (no Kafka/runtime required).",
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
            f"\nDelegation dispatched ({result.get('path')}) - "
            f"correlation_id={result['correlation_id']}\n"
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
