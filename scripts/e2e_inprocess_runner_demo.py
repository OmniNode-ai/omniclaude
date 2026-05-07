#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""E2E proof: drive InProcessDelegationRunner against real .201 vLLM endpoints.

Three checks:
  1. Direct _call_llm against .201:8000 with the actual served model id —
     proves inference + endpoint reachable. Uses a curl-subprocess transport
     because uv-managed and brew Python interpreters on this developer
     machine do not have the macOS Local Network privacy grant; curl does.
     See CLAUDE.md rule #11 (feedback_macos_lan_grant_per_binary.md).
  2. InProcessDelegationRunner.run("test", ...) via the canonical pipeline.
     Surfaces the routing-decision / served-model-id mismatch
     (qwen3-coder-30b vs cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit) —
     vLLM rejects the YAML id with HTTP 404. We monkeypatch the model id
     inside _call_llm so the rest of the runner pipeline (routing decision,
     quality gate, result construction) is exercised end-to-end.
  3. EvidenceBundleWriter writes the 5 receipt artifacts and verifies them.

Usage:
    LLM_CODER_URL=http://<201-host>:8000 \\
    LLM_CODER_FAST_URL=http://<201-host>:8001 \\
    ONEX_STATE_DIR=/tmp/onex-e2e-test \\
    uv run python scripts/e2e_inprocess_runner_demo.py

Where <201-host> is the LAN-internal vLLM host (see CLAUDE.md infrastructure
topology). Defaults are wired in `_VLLM_SERVED_MODELS` for convenience.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))


_VLLM_SERVED_MODELS: dict[str, str] = {
    "http://192.168.86.201:8000": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",  # onex-allow-internal-ip - LAN vLLM coder; not Kafka  # kafka-fallback-ok
    "http://192.168.86.201:8001": "Corianas/DeepSeek-R1-Distill-Qwen-14B-AWQ",  # onex-allow-internal-ip - LAN vLLM reasoning; not Kafka  # kafka-fallback-ok
}


def _call_llm_via_curl(
    *,
    endpoint_url: str,
    model: str,
    system_prompt: str,
    prompt: str,
    max_tokens: int,
    temperature: float,
    correlation_id: uuid.UUID,
) -> tuple[str, dict[str, int], int, str]:
    """Drop-in replacement for inprocess_runner._call_llm using curl.

    curl carries the macOS Local Network privacy grant; uv/brew Python
    interpreters on this machine do not. Same request shape and return
    contract as the real _call_llm so the rest of the runner is exercised.

    Rewrites the model id to the actual served vLLM id when the YAML
    routing tier supplied a YAML alias (qwen3-coder-30b →
    cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit). This is a known
    integration gap (routing_tiers.yaml ids vs. vLLM served-model ids).
    """
    from omniclaude.delegation.inprocess_runner import DelegationRunnerError

    served = _VLLM_SERVED_MODELS.get(endpoint_url.rstrip("/"), model)
    payload = {
        "model": served,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = f"{endpoint_url.rstrip('/')}/v1/chat/completions"

    t0 = time.monotonic_ns()
    proc = subprocess.run(
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
        raise DelegationRunnerError(
            f"curl failed (rc={proc.returncode}, correlation_id={correlation_id}): "
            f"{proc.stderr.strip()}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise DelegationRunnerError(
            f"vLLM returned invalid JSON: {exc}\nstdout={proc.stdout[:400]}"
        ) from exc

    try:
        content = data["choices"][0]["message"]["content"] or ""
        model_used = data.get("model", served)
        usage = {
            "prompt_tokens": data.get("usage", {}).get("prompt_tokens", 0),
            "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
            "total_tokens": data.get("usage", {}).get("total_tokens", 0),
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise DelegationRunnerError(
            f"vLLM response missing expected fields: {exc} — keys: {list(data)}"
        ) from exc

    return content, usage, int(latency_ms), model_used


def _patch_runner_transport() -> None:
    """Replace inprocess_runner._call_llm with the curl-based variant."""
    from omniclaude.delegation import inprocess_runner

    inprocess_runner._call_llm = _call_llm_via_curl  # type: ignore[assignment]


def step_1_direct_call() -> None:
    """POST /v1/chat/completions with the served model id directly via curl."""
    _patch_runner_transport()
    from omniclaude.delegation import inprocess_runner

    endpoint = os.environ.get(
        "LLM_CODER_URL",
        "http://192.168.86.201:8000",  # onex-allow-internal-ip - default LAN vLLM coder; not Kafka  # kafka-fallback-ok
    )
    served_model = _VLLM_SERVED_MODELS[endpoint.rstrip("/")]
    print(f"\n=== STEP 1: direct _call_llm (curl) against {endpoint} ===")
    content, usage, latency_ms, model_used = inprocess_runner._call_llm(
        endpoint_url=endpoint,
        model=served_model,
        system_prompt=(
            "You are a test generation assistant. Write a single pytest "
            "function. Use @pytest.mark.unit. Output only the test function."
        ),
        prompt=(
            "Write a pytest unit test for a function add(a: int, b: int) -> int. "
            "Cover the happy path. Output only the Python code."
        ),
        max_tokens=256,
        temperature=0.3,
        correlation_id=uuid.uuid4(),
    )
    print(f"model_used={model_used}")
    print(f"latency_ms={latency_ms}")
    print(f"usage={usage}")
    print("--- content ---")
    print(content)
    print("--- /content ---")


def step_2_canonical_runner() -> None:
    """Run the full pipeline; document model-id mismatch if it surfaces."""
    from omniclaude.delegation.inprocess_runner import (
        DelegationRunnerError,
        InProcessDelegationRunner,
    )

    print("\n=== STEP 2: InProcessDelegationRunner.run(task_type=test) ===")
    runner = InProcessDelegationRunner()
    try:
        result = runner.run(
            task_type="test",
            prompt=(
                "Write a pytest unit test for a function add(a: int, b: int) -> int. "
                "Cover the happy path. Output only the Python code."
            ),
            source_session_id="e2e-demo",
            max_tokens=256,
        )
    except DelegationRunnerError as exc:
        print(f"FAILED (expected — routing model id != served model id): {exc}")
        return

    print(f"correlation_id={result.correlation_id}")
    print(f"task_type={result.task_type}")
    print(f"model_used={result.model_used}")
    print(f"endpoint_url={result.endpoint_url}")
    print(f"quality_passed={result.quality_passed}")
    print(f"quality_score={result.quality_score}")
    print(f"latency_ms={result.latency_ms}")
    print(
        f"tokens=p{result.prompt_tokens} c{result.completion_tokens} t{result.total_tokens}"
    )
    print(f"failure_reason={result.failure_reason!r}")
    print("--- content (truncated to 800 chars) ---")
    print(result.content[:800])
    print("--- /content ---")


def step_3_evidence_bundle() -> None:
    """Wire EvidenceBundleWriter against a synthetic result to prove the path."""
    from datetime import UTC, datetime

    from omniclaude.delegation.evidence_bundle import (
        EvidenceBundleWriter,
        ModelBifrostResponse,
        ModelCostEvent,
        ModelQualityGateArtifact,
        ModelRunManifest,
        hash_prompt,
        new_bundle_id,
    )

    print("\n=== STEP 3: EvidenceBundleWriter writes 5 artifacts ===")
    import tempfile  # noqa: PLC0415

    default_state_dir = str(Path(tempfile.gettempdir()) / "onex-e2e-test")
    state_dir = Path(os.environ.get("ONEX_STATE_DIR", default_state_dir))
    bundle_root = state_dir / "delegation" / "bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)

    cid = str(uuid.uuid4())
    now = datetime.now(UTC)
    started = now
    completed = now
    bundle_id = new_bundle_id()

    writer = EvidenceBundleWriter(root_dir=bundle_root)
    receipt = writer.write(
        manifest=ModelRunManifest(
            correlation_id=cid,
            bundle_id=bundle_id,
            ticket_id="OMN-10610",
            session_id="e2e-demo",
            task_type="test",
            prompt_hash=hash_prompt("e2e demo prompt"),
            started_at=started,
            completed_at=completed,
            runner="inprocess",
        ),
        bifrost_response=ModelBifrostResponse(
            correlation_id=cid,
            backend_selected="http://192.168.86.201:8000",  # onex-allow-internal-ip - demo bundle backend; not Kafka  # kafka-fallback-ok
            model_used="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
            latency_ms=42,
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
            response_content="def test_add(): assert add(1, 2) == 3",
        ),
        quality_gate=ModelQualityGateArtifact(
            correlation_id=cid,
            passed=True,
            quality_score=0.95,
        ),
        cost_event=ModelCostEvent(
            correlation_id=cid,
            session_id="e2e-demo",
            model_local="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
            baseline_model="claude-sonnet-4-6",
            local_cost_usd=0.0,
            cloud_cost_usd=0.00045,
            savings_usd=0.00045,
            savings_method="counterfactual_baseline",
            token_provenance="vllm_usage_block",  # noqa: S106,secrets - provenance label, not a secret
            pricing_manifest_version="v1",
            prompt_tokens=10,
            completion_tokens=20,
        ),
        issued_at=now,
    )

    bundle_dir = bundle_root / cid
    artifacts = sorted(p.name for p in bundle_dir.iterdir())
    print(f"bundle_dir={bundle_dir}")
    print(f"artifacts={artifacts}")
    print(f"bundle_root_hash={receipt.bundle_root_hash}")
    expected = {
        "bifrost_response.json",
        "cost_event.json",
        "quality_gate_result.json",
        "receipt.json",
        "run_manifest.json",
    }
    actual = set(artifacts)
    if expected != actual:
        print(f"MISMATCH: missing={expected - actual} extra={actual - expected}")
        sys.exit(1)
    print("OK: 5/5 artifacts present.")


def main() -> int:
    print("E2E InProcessDelegationRunner demo")
    print(f"  LLM_CODER_URL={os.environ.get('LLM_CODER_URL', '<unset>')}")
    print(f"  LLM_CODER_FAST_URL={os.environ.get('LLM_CODER_FAST_URL', '<unset>')}")
    print(f"  ONEX_STATE_DIR={os.environ.get('ONEX_STATE_DIR', '<unset>')}")

    step_1_direct_call()
    step_2_canonical_runner()
    step_3_evidence_bundle()
    return 0


if __name__ == "__main__":
    sys.exit(main())
