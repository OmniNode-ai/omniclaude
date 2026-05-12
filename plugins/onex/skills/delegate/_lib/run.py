#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Delegate skill - classify prompt and dispatch through runtime ingress.

Invoked when the user runs /onex:delegate.  Classifies the prompt via
TaskClassifier, then dispatches to the runtime via:
  1. SSH socket (ONEX_RUNTIME_SSH_HOST + ONEX_RUNTIME_SOCKET_PATH both set)
  2. HTTP (ONEX_RUNTIME_URL is set and non-empty)
  3. Kafka (contract-driven — topic and event_type resolved from the deployed
     omnibase_infra node_delegation_orchestrator contract.yaml at import time;
     falls back to TopicBase.DELEGATE_TASK if the contract is unavailable)
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
import shlex
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
_HOOKS_LIB = _PLUGIN_ROOT / "hooks" / "lib"
if _HOOKS_LIB.exists() and str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))

_SRC_PATH = _PLUGIN_ROOT.parent.parent / "src"
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


def _load_infra_orchestrator_contract() -> dict:  # type: ignore[type-arg]
    """Load the omnibase_infra node_delegation_orchestrator contract.yaml.

    Searches for the contract relative to the omnibase_infra package location,
    falling back gracefully if not installed or not findable. Returns an empty
    dict on any failure so callers can apply their own defaults.
    """
    search_roots: list[Path] = []

    # 1. Try via installed package location
    try:
        import omnibase_infra as _obi  # noqa: PLC0415

        pkg_root = Path(_obi.__file__).parent
        search_roots.append(pkg_root)
    except ImportError:
        pass

    # 2. Try common repo paths relative to this skill file
    _repo_candidates = [
        _PLUGIN_ROOT.parent.parent.parent.parent
        / "omnibase_infra"
        / "src"
        / "omnibase_infra",
        _PLUGIN_ROOT.parent.parent.parent.parent.parent
        / "omnibase_infra"
        / "src"
        / "omnibase_infra",
    ]
    search_roots.extend(_repo_candidates)

    for root in search_roots:
        candidate = root / "nodes" / "node_delegation_orchestrator" / "contract.yaml"
        if candidate.exists():
            try:
                import yaml  # noqa: PLC0415

                with candidate.open() as f:
                    return yaml.safe_load(f) or {}
            except Exception:  # noqa: BLE001
                return {}

    return {}


def _resolve_delegation_topic_and_event_type() -> tuple[str, str]:
    """Return (topic, event_type) from the deployed omnibase_infra contract.

    Priority:
      1. omnibase_infra node_delegation_orchestrator contract.yaml subscribe_topics[0]
      2. TopicBase.DELEGATE_TASK (omniclaude fallback)
      3. Empty string (last resort; Kafka path will fail-fast anyway)

    event_type defaults to the first consumed_event's event_type, then
    "omnibase-infra.delegation-request" (matching DispatcherDelegationRequest.message_types).
    """
    contract = _load_infra_orchestrator_contract()

    # Extract topic
    topic: str = ""
    try:
        subscribe_topics = contract.get("event_bus", {}).get("subscribe_topics", [])
        if subscribe_topics:
            # First subscribe topic is the primary inbound command topic
            topic = str(subscribe_topics[0])
    except Exception:  # noqa: BLE001
        pass

    # Extract event_type from consumed_events or published_events
    event_type: str = ""
    try:
        consumed = contract.get("consumed_events", [])
        if consumed:
            event_type = str(consumed[0].get("event_type", ""))
    except Exception:  # noqa: BLE001
        pass

    # Fallback chain for topic
    if not topic:
        try:
            from omniclaude.hooks.topics import TopicBase as _TopicBase  # noqa: PLC0415

            topic = _TopicBase.DELEGATE_TASK
        except (ImportError, AttributeError):
            topic = ""

    # Fallback for event_type — must match dispatcher_delegation_request.message_types
    if not event_type:
        event_type = "omnibase-infra.delegation-request"

    return topic, event_type


_DELEGATION_REQUEST_TOPIC: str
_DELEGATION_EVENT_TYPE: str
_DELEGATION_REQUEST_TOPIC, _DELEGATION_EVENT_TYPE = (
    _resolve_delegation_topic_and_event_type()
)


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


def _runtime_import_error(exc: ImportError) -> dict:  # type: ignore[type-arg]
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


def _dispatch_via_ssh_socket(
    payload_json: str,
    ssh_host: str,
    socket_path: str,
    timeout_seconds: float,
) -> dict:  # type: ignore[type-arg]
    """Send newline-delimited JSON to a remote Unix socket via SSH.

    Protocol: write JSON + newline, read response line.
    Raises OSError on transport failure, json.JSONDecodeError on bad response.
    Returns the parsed response dict on success.
    """
    import base64  # noqa: PLC0415

    script_src = f"""import socket, sys
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect({socket_path!r})
sock.settimeout({timeout_seconds})
data = sys.stdin.buffer.read()
sock.send(data if data.endswith(b'\\n') else data + b'\\n')
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
    """POST a ModelRuntimeSkillRequest to the runtime HTTP ingress.

    Returns a ModelRuntimeSkillResponse on success.
    Raises urllib.error.URLError on transport failure.
    """
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
    delegation_payload: dict,  # type: ignore[type-arg]
    correlation_id_str: str,
    topic: str,
    task_type: str,
) -> dict:  # type: ignore[type-arg]
    """Publish delegation command to Kafka topic.

    Uses confluent_kafka.Producer (sync). Fails fast if KAFKA_BOOTSTRAP_SERVERS
    is unset — no silent fallback.

    Returns a result dict with success/error keys.
    """
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

    emitted_at = datetime.now(UTC).isoformat()
    envelope = {
        "event_type": _DELEGATION_EVENT_TYPE,
        "envelope_id": str(uuid4()),
        "envelope_timestamp": emitted_at,
        "correlation_id": correlation_id_str,
        "payload": _build_delegation_request_payload(
            delegation_payload, task_type, emitted_at
        ),
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


def _dispatch_via_pandaproxy(
    delegation_payload: dict,  # type: ignore[type-arg]
    correlation_id_str: str,
    topic: str,
    task_type: str,
    pandaproxy_url: str,
    timeout_seconds: float,
) -> dict:  # type: ignore[type-arg]
    """Publish delegation command via Redpanda HTTP proxy (pandaproxy).

    Uses curl subprocess — Python sockets lack the macOS LAN grant on uv-managed
    interpreters, but the curl binary has it. Builds a ModelEventEnvelope-compatible
    payload and POSTs to /topics/<topic> with application/vnd.kafka.json.v2+json.

    pandaproxy_url example: http://192.168.86.201:28082  # onex-allow-internal-ip # kafka-fallback-ok

    Returns a result dict with success/error keys.
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    emitted_at = datetime.now(UTC).isoformat()
    envelope = {
        "event_type": _DELEGATION_EVENT_TYPE,
        "envelope_id": str(uuid4()),
        "envelope_timestamp": emitted_at,
        "correlation_id": correlation_id_str,
        "payload": _build_delegation_request_payload(
            delegation_payload, task_type, emitted_at
        ),
    }
    body = json.dumps({"records": [{"value": envelope}]})
    url = f"{pandaproxy_url.rstrip('/')}/topics/{topic}"

    try:
        proc = subprocess.run(  # noqa: S603
            [
                "curl",
                "-fsS",
                "-X",
                "POST",
                url,
                "-H",
                "Content-Type: application/vnd.kafka.json.v2+json",
                "-d",
                body,
                "--max-time",
                str(int(timeout_seconds)),
            ],
            capture_output=True,
            timeout=timeout_seconds + 5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "success": False,
            "error": f"Pandaproxy curl failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "pandaproxy",
        }

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        return {
            "success": False,
            "error": f"Pandaproxy curl exited {proc.returncode}: {stderr}",
            "correlation_id": correlation_id_str,
            "path": "pandaproxy",
        }

    try:
        raw = json.loads(proc.stdout.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Pandaproxy response parse failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "pandaproxy",
        }

    offsets = raw.get("offsets", [])
    if not offsets or offsets[0].get("error_code", 0) != 0:
        err = offsets[0].get("error", "unknown") if offsets else "no offsets returned"
        return {
            "success": False,
            "error": f"Pandaproxy produce failed: {err}",
            "correlation_id": correlation_id_str,
            "path": "pandaproxy",
        }

    return {
        "success": True,
        "correlation_id": correlation_id_str,
        "topic": topic,
        "path": "pandaproxy",
        "dispatch_status": "published",
        "partition": offsets[0].get("partition"),
        "offset": offsets[0].get("offset"),
    }


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


def _dispatch_via_ssh_rpk(
    delegation_payload: dict,  # type: ignore[type-arg]
    correlation_id_str: str,
    topic: str,
    task_type: str,
    ssh_host: str,
    bridge_script: str,
    timeout_seconds: float,
) -> dict:  # type: ignore[type-arg]
    """Publish delegation command to Kafka via SSH + rpk bridge script on the remote host.

    Builds a ModelEventEnvelope-compatible JSON payload and pipes it through SSH to
    bridge_script on ssh_host, which publishes it via `rpk topic produce`.

    Returns a result dict with success/error keys.
    """
    from datetime import UTC, datetime  # noqa: PLC0415
    from uuid import uuid4  # noqa: PLC0415

    emitted_at = datetime.now(UTC).isoformat()
    envelope = {
        "event_type": _DELEGATION_EVENT_TYPE,
        "envelope_id": str(uuid4()),
        "envelope_timestamp": emitted_at,
        "correlation_id": correlation_id_str,
        "payload": _build_delegation_request_payload(
            delegation_payload, task_type, emitted_at
        ),
    }
    message = json.dumps(envelope)

    try:
        proc = subprocess.run(  # noqa: S603
            [
                "ssh",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                ssh_host,
                f"bash {shlex.quote(bridge_script)} {shlex.quote(topic)}",
            ],
            input=message.encode("utf-8"),
            capture_output=True,
            timeout=timeout_seconds + 15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "success": False,
            "error": f"SSH rpk bridge failed: {exc}",
            "correlation_id": correlation_id_str,
            "path": "ssh_rpk",
        }

    stdout = proc.stdout.decode("utf-8", errors="replace").strip()
    stderr = proc.stderr.decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        return {
            "success": False,
            "error": f"SSH rpk bridge exited {proc.returncode}: {stderr or stdout}",
            "correlation_id": correlation_id_str,
            "path": "ssh_rpk",
        }

    # rpk outputs "Produced to partition N at offset M..." on success
    if "Produced to partition" not in stdout:
        return {
            "success": False,
            "error": f"SSH rpk bridge unexpected output: {stdout or stderr}",
            "correlation_id": correlation_id_str,
            "path": "ssh_rpk",
        }

    return {
        "success": True,
        "correlation_id": correlation_id_str,
        "topic": topic,
        "path": "ssh_rpk",
        "dispatch_status": "published",
        "bridge_output": stdout,
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
    """Classify *prompt* and dispatch a delegation request to the runtime.

    Transport priority:
      1. SSH socket (ONEX_RUNTIME_SSH_HOST + ONEX_RUNTIME_SOCKET_PATH)
      2. HTTP (ONEX_RUNTIME_URL)
      3. Pandaproxy HTTP (ONEX_PANDAPROXY_URL) — preferred for Mac→.201 LAN
      4. SSH rpk bridge (ONEX_RUNTIME_SSH_HOST + ONEX_KAFKA_BRIDGE_SCRIPT) — fallback
      5. Kafka (contract-driven; topic resolved from omnibase_infra contract at import time)

    force_local=True returns an explicit error (OMN-10723).
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
    correlation_id_str = str(correlation_uuid)

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
            "correlation_id": correlation_id_str,
        }

    from plugins.onex.hooks.lib.session_id import resolve_session_id  # noqa: PLC0415

    delegation_payload = {
        "prompt": prompt,
        "correlation_id": correlation_id_str,
        "session_id": resolve_session_id(default=""),
        "prompt_length": len(prompt),
        "source_file_path": source_file,
        "max_tokens": max_tokens,
        "recipient": recipient,
        "wait_for_result": wait_for_result,
        "working_directory": working_directory,
        "codex_sandbox_mode": codex_sandbox_mode,
    }

    if timeout_ms <= 0:
        return {
            "success": False,
            "error": f"timeout_ms must be positive, got {timeout_ms}",
            "correlation_id": correlation_id_str,
        }
    timeout_seconds = timeout_ms / 1000.0
    ssh_host = os.environ.get("ONEX_RUNTIME_SSH_HOST", "").strip()
    ssh_socket_path = os.environ.get("ONEX_RUNTIME_SOCKET_PATH", "").strip()
    kafka_bridge_script = os.environ.get("ONEX_KAFKA_BRIDGE_SCRIPT", "").strip()
    pandaproxy_url = os.environ.get("ONEX_PANDAPROXY_URL", "").strip()
    runtime_url = os.environ.get("ONEX_RUNTIME_URL", "").strip()

    if ssh_host and ssh_socket_path:
        ssh_payload = {
            "command_name": _DELEGATION_COMMAND_NAME,
            "payload": delegation_payload,
            "correlation_id": correlation_id_str,
            "timeout_ms": timeout_ms,
        }
        try:
            raw = _dispatch_via_ssh_socket(
                payload_json=json.dumps(ssh_payload),
                ssh_host=ssh_host,
                socket_path=ssh_socket_path,
                timeout_seconds=timeout_seconds,
            )
        except (OSError, json.JSONDecodeError) as exc:
            return {
                "success": False,
                "error": str(exc),
                "error_code": "dispatch_error",
                "retryable": False,
                "correlation_id": correlation_id_str,
                "command_name": _DELEGATION_COMMAND_NAME,
                "topic": _DELEGATION_REQUEST_TOPIC,
                "path": "ssh",
            }
        ok = raw.get("ok", False)
        if not ok:
            error = raw.get("error") or {}
            return {
                "success": False,
                "error": error.get("message", "runtime dispatch failed")
                if isinstance(error, dict)
                else str(error),
                "error_code": error.get("code", "dispatch_error")
                if isinstance(error, dict)
                else "dispatch_error",
                "retryable": error.get("retryable", False)
                if isinstance(error, dict)
                else False,
                "correlation_id": raw.get("correlation_id", correlation_id_str),
                "command_name": raw.get("command_name", _DELEGATION_COMMAND_NAME),
                "topic": raw.get("command_topic") or _DELEGATION_REQUEST_TOPIC,
                "path": "ssh",
            }
        return {
            "success": True,
            "correlation_id": raw.get("correlation_id", correlation_id_str),
            "task_type": getattr(intent, "value", str(intent)),
            "command_name": raw.get("command_name", _DELEGATION_COMMAND_NAME),
            "resolved_node_name": raw.get("resolved_node_name"),
            "topic": raw.get("command_topic") or _DELEGATION_REQUEST_TOPIC,
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
            command_name=_DELEGATION_COMMAND_NAME,
            payload=delegation_payload,
            correlation_id=correlation_uuid,
            timeout_ms=timeout_ms,
        )
        import urllib.error  # noqa: PLC0415

        try:
            response = _dispatch_via_http(request, runtime_url, timeout_seconds)
        except urllib.error.URLError as exc:
            return {
                "success": False,
                "error": f"HTTP dispatch to ONEX_RUNTIME_URL failed: {exc.reason}",
                "path": "http",
            }
        if not response.ok:  # type: ignore[union-attr]
            error = response.error  # type: ignore[union-attr]
            error_code = error.code if error else "dispatch_error"
            return {
                "success": False,
                "error": error.message if error else "runtime dispatch failed",
                "error_code": error_code,
                "retryable": error.retryable if error else False,
                "correlation_id": str(
                    getattr(response, "correlation_id", None) or correlation_uuid
                ),
                "command_name": getattr(
                    response, "command_name", _DELEGATION_COMMAND_NAME
                ),
                "topic": getattr(response, "command_topic", None)
                or _DELEGATION_REQUEST_TOPIC,
                "path": "http",
            }
        return {
            "success": True,
            "correlation_id": str(
                getattr(response, "correlation_id", None) or correlation_uuid
            ),
            "task_type": intent.value,
            "command_name": getattr(response, "command_name", _DELEGATION_COMMAND_NAME),
            "resolved_node_name": getattr(response, "resolved_node_name", None),
            "topic": getattr(response, "command_topic", None)
            or _DELEGATION_REQUEST_TOPIC,
            "terminal_event": getattr(response, "terminal_event", None),
            "dispatch_status": response.dispatch_result.status  # type: ignore[union-attr]
            if getattr(response, "dispatch_result", None)
            else None,
            "output_payloads": getattr(response, "output_payloads", None),
            "path": "http",
        }

    # Pandaproxy HTTP: preferred Mac→.201 transport (curl/urllib have LAN grant)
    if pandaproxy_url:
        pp_result = _dispatch_via_pandaproxy(
            delegation_payload=delegation_payload,
            correlation_id_str=correlation_id_str,
            topic=_DELEGATION_REQUEST_TOPIC,
            task_type=intent.value,
            pandaproxy_url=pandaproxy_url,
            timeout_seconds=timeout_seconds,
        )
        if pp_result["success"]:
            pp_result["task_type"] = intent.value
            pp_result["command_name"] = _DELEGATION_COMMAND_NAME
        return pp_result

    # SSH rpk bridge: fallback Mac→.201 Kafka via SSH when direct Kafka is unreachable
    if ssh_host and kafka_bridge_script:
        rpk_result = _dispatch_via_ssh_rpk(
            delegation_payload=delegation_payload,
            correlation_id_str=correlation_id_str,
            topic=_DELEGATION_REQUEST_TOPIC,
            task_type=intent.value,
            ssh_host=ssh_host,
            bridge_script=kafka_bridge_script,
            timeout_seconds=timeout_seconds,
        )
        if rpk_result["success"]:
            rpk_result["task_type"] = intent.value
            rpk_result["command_name"] = _DELEGATION_COMMAND_NAME
        return rpk_result

    # Kafka: contract-driven transport (OMN-10834)
    kafka_result = _dispatch_via_kafka(
        delegation_payload=delegation_payload,
        correlation_id_str=correlation_id_str,
        topic=_DELEGATION_REQUEST_TOPIC,
        task_type=intent.value,
    )
    if kafka_result["success"]:
        kafka_result["task_type"] = intent.value
        kafka_result["command_name"] = _DELEGATION_COMMAND_NAME
    return kafka_result


# ---------------------------------------------------------------------------
# CLI entry point (called from SKILL.md dispatch)
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for /onex:delegate."""
    import argparse  # noqa: PLC0415

    parser = argparse.ArgumentParser(
        description="Delegate skill - dispatch through runtime SSH socket, HTTP, or Kafka"
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
