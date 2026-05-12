#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""merge_sweep skill — dispatch through runtime ingress.

Invoked when the user runs /onex:merge_sweep. Builds a ModelPrLifecycleStartCommand
payload and dispatches to the runtime via transport priority:
  1. SSH socket (ONEX_RUNTIME_SSH_HOST + ONEX_RUNTIME_SOCKET_PATH both set)
  2. HTTP (ONEX_RUNTIME_URL is set and non-empty)
  3. Kafka (contract-driven, topic onex.cmd.omnimarket.pr-lifecycle-orchestrator-start.v1)
     Uses KAFKA_BOOTSTRAP_SERVERS — fail-fast if unset.

Optional env vars:
  ONEX_RUNTIME_SSH_HOST    — SSH target for remote socket dispatch, e.g. user@host
  ONEX_RUNTIME_SOCKET_PATH — Unix socket path on the SSH host
  ONEX_RUNTIME_URL         — HTTP endpoint for direct HTTP dispatch
  KAFKA_BOOTSTRAP_SERVERS  — Required for the Kafka fallback transport
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path setup — mirror the delegate skill pattern exactly
# ---------------------------------------------------------------------------
_LIB_DIR = Path(__file__).parent  # merge_sweep/_lib/
_SKILL_DIR = _LIB_DIR.parent  # merge_sweep/
_PLUGIN_ROOT = _SKILL_DIR.parent.parent  # plugins/onex/
_HOOKS_LIB = _PLUGIN_ROOT / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _PLUGIN_ROOT.parent.parent / "src"
if _SRC_PATH.exists() and str(_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(_SRC_PATH))

# ---------------------------------------------------------------------------
# Runtime model imports — graceful fallback if package unavailable
# ---------------------------------------------------------------------------
try:
    from omnibase_core.models.runtime import (
        ModelRuntimeSkillRequest,
        ModelRuntimeSkillResponse,
    )
    from omnibase_infra.clients.runtime_skill_client import LocalRuntimeSkillClient

    _RUNTIME_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:
    ModelRuntimeSkillRequest = None  # type: ignore[assignment]
    ModelRuntimeSkillResponse = None  # type: ignore[assignment]
    LocalRuntimeSkillClient = None  # type: ignore[assignment]
    _RUNTIME_IMPORT_ERROR = exc

_PR_LIFECYCLE_COMMAND_NAME = "node_pr_lifecycle_orchestrator"
_CONTRACT_RELATIVE_PATH = (
    "omnimarket/src/omnimarket/nodes/node_pr_lifecycle_orchestrator/contract.yaml"
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


def _resolve_correlation_id(correlation_id: str | None) -> uuid.UUID:
    raw = correlation_id or os.environ.get("ONEX_RUN_ID")
    if raw:
        try:
            return uuid.UUID(str(raw))
        except ValueError:
            pass
    return uuid.uuid4()


def _runtime_import_error(exc: ImportError) -> dict:  # type: ignore[type-arg]
    return {
        "success": False,
        "error": (
            "Runtime skill client unavailable - install omnibase_core and "
            f"omnibase_infra in the plugin environment: {exc}"
        ),
    }


def _dispatch_via_ssh_socket(
    payload_json: str,
    ssh_host: str,
    socket_path: str,
    timeout_seconds: float,
) -> dict:  # type: ignore[type-arg]
    import base64  # noqa: PLC0415

    script_src = f"""import socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect({socket_path!r})
sock.settimeout({timeout_seconds})
data = sys.stdin.buffer.read()
sock.sendall(data if data.endswith(b'\\n') else data + b'\\n')
resp = b''
while True:
    chunk = sock.recv(65536)
    if not chunk:
        break
    resp += chunk
    if b'\\n' in resp:
        break
sock.close()
print(resp.decode('utf-8', errors='replace').strip())
"""
    encoded = base64.b64encode(script_src.encode()).decode()
    remote_cmd = f"python3 -c \"import base64,sys; exec(base64.b64decode('{encoded}').decode())\""

    proc = subprocess.run(  # noqa: S603
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_host, remote_cmd],
        input=payload_json.encode("utf-8"),
        capture_output=True,
        timeout=timeout_seconds + 15,
        check=False,
    )

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OSError(f"SSH dispatch failed (exit {proc.returncode}): {stderr}")

    raw_output = proc.stdout.decode("utf-8", errors="replace").strip()
    if not raw_output:
        raise OSError("SSH dispatch returned empty response")

    return json.loads(raw_output)  # type: ignore[return-value]


def _dispatch_via_http(
    request: object,
    runtime_url: str,
    timeout_seconds: float,
) -> object:
    import urllib.error  # noqa: PLC0415
    import urllib.request  # noqa: PLC0415

    payload = request.model_dump_json(exclude_none=True).encode("utf-8")  # type: ignore[attr-defined]
    req = urllib.request.Request(  # noqa: S310
        f"{runtime_url.rstrip('/')}/skill",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError:
        raise

    from omnibase_core.models.runtime import ModelRuntimeSkillResponse  # noqa: PLC0415

    return ModelRuntimeSkillResponse.model_validate(raw)


def _dispatch_via_kafka(
    payload: dict,  # type: ignore[type-arg]
    correlation_id_str: str,
    topic: str,
) -> dict:  # type: ignore[type-arg]
    bootstrap_servers = os.environ.get("KAFKA_BOOTSTRAP_SERVERS")
    if not bootstrap_servers:
        return {
            "success": False,
            "error": "KAFKA_BOOTSTRAP_SERVERS is not set — cannot dispatch via Kafka",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    try:
        from confluent_kafka import (
            Producer,  # type: ignore[import-untyped] # noqa: PLC0415
        )
    except ImportError:
        return {
            "success": False,
            "error": "confluent_kafka not installed — cannot dispatch via Kafka",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    envelope = {
        "event_type": "omnimarket.pr-lifecycle-orchestrator-start",
        "event_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "source": "omniclaude.merge-sweep-skill",
        "correlation_id": correlation_id_str,
        "payload": payload,
    }
    message = json.dumps(envelope).encode("utf-8")
    key = correlation_id_str.encode("utf-8")

    delivered: list[bool] = []
    errors: list[str] = []

    def _on_delivery(err: object, _msg: object) -> None:
        if err:
            errors.append(str(err))
            delivered.append(False)
        else:
            delivered.append(True)

    try:
        producer = Producer({"bootstrap.servers": bootstrap_servers})
        producer.produce(topic, value=message, key=key, on_delivery=_on_delivery)
        producer.flush(timeout=10)
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Kafka produce failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    if errors:
        return {
            "success": False,
            "error": f"Kafka delivery failed: {errors[0]}",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    if not delivered:
        return {
            "success": False,
            "error": "Kafka delivery timed out — no confirmation received within 10s",
            "correlation_id": correlation_id_str,
            "path": "kafka",
        }

    return {
        "success": True,
        "correlation_id": correlation_id_str,
        "topic": topic,
        "path": "kafka",
        "dispatch_status": "published",
    }


def dispatch_merge_sweep(
    *,
    run_id: str,
    dry_run: bool = False,
    inventory_only: bool = False,
    fix_only: bool = False,
    merge_only: bool = False,
    repos: str = "",
    max_parallel_polish: int = 20,
    enable_auto_rebase: bool = True,
    use_dag_ordering: bool = True,
    enable_trivial_comment_resolution: bool = True,
    enable_admin_merge_fallback: bool = True,
    admin_fallback_threshold_minutes: int = 15,
    verify: bool = False,
    verify_timeout_seconds: int = 30,
    correlation_id: str | None = None,
    timeout_ms: int = 300_000,
) -> dict:  # type: ignore[type-arg]
    """Dispatch node_pr_lifecycle_orchestrator via runtime ingress.

    Transport priority:
      1. SSH socket (ONEX_RUNTIME_SSH_HOST + ONEX_RUNTIME_SOCKET_PATH)
      2. HTTP (ONEX_RUNTIME_URL)
      3. Kafka (contract-driven topic resolved from node contract.yaml)
    """
    correlation_uuid = _resolve_correlation_id(correlation_id)
    correlation_id_str = str(correlation_uuid)
    timeout_seconds = timeout_ms / 1000.0

    command_topic = _resolve_command_topic()

    payload: dict = {  # type: ignore[type-arg]
        "correlation_id": correlation_id_str,
        "run_id": run_id,
        "dry_run": dry_run,
        "inventory_only": inventory_only,
        "fix_only": fix_only,
        "merge_only": merge_only,
        "repos": repos,
        "max_parallel_polish": max_parallel_polish,
        "enable_auto_rebase": enable_auto_rebase,
        "use_dag_ordering": use_dag_ordering,
        "enable_trivial_comment_resolution": enable_trivial_comment_resolution,
        "enable_admin_merge_fallback": enable_admin_merge_fallback,
        "admin_fallback_threshold_minutes": admin_fallback_threshold_minutes,
        "verify": verify,
        "verify_timeout_seconds": verify_timeout_seconds,
    }

    ssh_host = os.environ.get("ONEX_RUNTIME_SSH_HOST", "").strip()
    ssh_socket_path = os.environ.get("ONEX_RUNTIME_SOCKET_PATH", "").strip()
    runtime_url = os.environ.get("ONEX_RUNTIME_URL", "").strip()

    if ssh_host and ssh_socket_path:
        ssh_payload = {
            "command_name": _PR_LIFECYCLE_COMMAND_NAME,
            "payload": payload,
            "correlation_id": correlation_id_str,
            "timeout_ms": timeout_ms,
        }
        _ssh_transport_error: str | None = None
        try:
            raw = _dispatch_via_ssh_socket(
                payload_json=json.dumps(ssh_payload),
                ssh_host=ssh_host,
                socket_path=ssh_socket_path,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, json.JSONDecodeError) as exc:
            _ssh_transport_error = str(exc)
            raw = None
        if raw is not None:
            ok = raw.get("ok", False)
            if not ok:
                error = raw.get("error") or {}
                is_structured = isinstance(error, dict) and (
                    "code" in error or "message" in error or "retryable" in error
                )
                if is_structured:
                    return {
                        "success": False,
                        "error": error.get("message", "runtime dispatch failed"),
                        "error_code": error.get("code", "dispatch_error"),
                        "retryable": error.get("retryable", False),
                        "correlation_id": raw.get("correlation_id", correlation_id_str),
                        "command_name": _PR_LIFECYCLE_COMMAND_NAME,
                        "topic": raw.get("command_topic") or command_topic,
                        "path": "ssh",
                    }
                _ssh_transport_error = str(error) if error else "runtime unreachable"
            else:
                return {
                    "success": True,
                    "correlation_id": raw.get("correlation_id", correlation_id_str),
                    "command_name": raw.get("command_name", _PR_LIFECYCLE_COMMAND_NAME),
                    "topic": raw.get("command_topic") or command_topic,
                    "terminal_event": raw.get("terminal_event"),
                    "dispatch_status": raw.get("dispatch_result", {}).get("status"),
                    "output_payloads": raw.get("output_payloads"),
                    "path": "ssh",
                }

    if runtime_url:
        if _RUNTIME_IMPORT_ERROR is not None or ModelRuntimeSkillRequest is None:
            return _runtime_import_error(
                _RUNTIME_IMPORT_ERROR or ImportError("missing runtime classes")
            )
        request = ModelRuntimeSkillRequest(
            command_name=_PR_LIFECYCLE_COMMAND_NAME,
            payload=payload,
            correlation_id=correlation_uuid,
            timeout_ms=timeout_ms,
        )
        import urllib.error  # noqa: PLC0415

        _http_transport_error: str | None = None
        try:
            response = _dispatch_via_http(request, runtime_url, timeout_seconds)
        except urllib.error.URLError as exc:
            _http_transport_error = (
                f"HTTP dispatch to ONEX_RUNTIME_URL failed: {exc.reason}"
            )
            response = None  # type: ignore[assignment]
        if response is not None:
            if not response.ok:  # type: ignore[union-attr]
                error = response.error  # type: ignore[union-attr]
                is_structured = error is not None and hasattr(error, "code")
                if is_structured:
                    return {
                        "success": False,
                        "error": error.message if error else "runtime dispatch failed",
                        "error_code": error.code if error else "dispatch_error",
                        "retryable": error.retryable if error else False,
                        "correlation_id": str(
                            getattr(response, "correlation_id", None)
                            or correlation_uuid
                        ),
                        "command_name": getattr(
                            response, "command_name", _PR_LIFECYCLE_COMMAND_NAME
                        ),
                        "topic": getattr(response, "command_topic", None)
                        or command_topic,
                        "path": "http",
                    }
                _http_transport_error = (
                    error.message if error else "runtime unreachable via HTTP"
                )
            else:
                return {
                    "success": True,
                    "correlation_id": str(
                        getattr(response, "correlation_id", None) or correlation_uuid
                    ),
                    "command_name": getattr(
                        response, "command_name", _PR_LIFECYCLE_COMMAND_NAME
                    ),
                    "topic": getattr(response, "command_topic", None) or command_topic,
                    "terminal_event": getattr(response, "terminal_event", None),
                    "dispatch_status": response.dispatch_result.status  # type: ignore[union-attr]
                    if getattr(response, "dispatch_result", None)
                    else None,
                    "output_payloads": getattr(response, "output_payloads", None),
                    "path": "http",
                }

    # Kafka: contract-driven transport — topic resolved from node contract.yaml
    if not command_topic:
        return {
            "success": False,
            "error": (
                "Cannot resolve command topic from node contract.yaml. "
                f"Set OMNI_HOME so run.py can locate {_CONTRACT_RELATIVE_PATH}"
            ),
            "path": "kafka",
        }
    return _dispatch_via_kafka(
        payload=payload,
        correlation_id_str=correlation_id_str,
        topic=command_topic,
    )


def main() -> None:
    """CLI entry point for /onex:merge_sweep."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="merge_sweep skill — dispatch through runtime SSH socket, HTTP, or Kafka"
    )
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--repos", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--fix-only", action="store_true")
    parser.add_argument(
        "--merge-only", "--skip-polish", action="store_true", dest="merge_only"
    )
    parser.add_argument("--max-parallel-polish", type=int, default=20)
    parser.add_argument("--enable-auto-rebase", type=_as_bool_arg, default=True)
    parser.add_argument("--use-dag-ordering", type=_as_bool_arg, default=True)
    parser.add_argument(
        "--enable-trivial-comment-resolution", type=_as_bool_arg, default=True
    )
    parser.add_argument(
        "--enable-admin-merge-fallback", type=_as_bool_arg, default=True
    )
    parser.add_argument("--admin-fallback-threshold-minutes", type=int, default=15)
    parser.add_argument("--verify", type=_as_bool_arg, default=False)
    parser.add_argument("--verify-timeout-seconds", type=int, default=30)
    parser.add_argument("--correlation-id", default=None)
    parser.add_argument("--timeout-ms", type=int, default=300_000)
    args = parser.parse_args()

    from datetime import UTC, datetime  # noqa: PLC0415

    run_id = (
        args.run_id or f"merge-sweep-{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%SZ')}"
    )

    result = dispatch_merge_sweep(
        run_id=run_id,
        dry_run=args.dry_run,
        inventory_only=args.inventory_only,
        fix_only=args.fix_only,
        merge_only=args.merge_only,
        repos=args.repos,
        max_parallel_polish=args.max_parallel_polish,
        enable_auto_rebase=args.enable_auto_rebase,
        use_dag_ordering=args.use_dag_ordering,
        enable_trivial_comment_resolution=args.enable_trivial_comment_resolution,
        enable_admin_merge_fallback=args.enable_admin_merge_fallback,
        admin_fallback_threshold_minutes=args.admin_fallback_threshold_minutes,
        verify=args.verify,
        verify_timeout_seconds=args.verify_timeout_seconds,
        correlation_id=args.correlation_id,
        timeout_ms=args.timeout_ms,
    )

    print(json.dumps(result, indent=2))

    if result.get("success"):
        print(
            f"\nmerge_sweep dispatched ({result.get('path')}) - "
            f"correlation_id={result['correlation_id']}\n"
            f"command_name={result.get('command_name')}\n"
            f"dispatch_status={result.get('dispatch_status')}",
            file=sys.stderr,
        )
    else:
        print(f"\nmerge_sweep dispatch failed: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


def _as_bool_arg(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value!r}")


if __name__ == "__main__":
    main()
