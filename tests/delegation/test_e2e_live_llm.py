# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Live-LLM integration test for the delegation pipeline (OMN-10610).

Drives the full delegation chain — delegate skill → classifier → real
InProcessDelegationRunner → real routing → REAL HTTP call to a vLLM endpoint
on the LAN → real quality gate → real EvidenceBundleWriter — and asserts that
the evidence bundle on disk contains real model-generated content with
non-zero token usage.

Opt-in: this test only runs when ``OMNINODE_LLM_LIVE=1`` is set in the
environment AND the configured ``LLM_CODER_URL`` (default points at the LAN
vLLM coder host on the .201 box) responds to ``/health`` within 5 seconds.
Otherwise the test is skipped — CI never depends on a LAN endpoint.

Why a curl-subprocess transport: per CLAUDE.md rule #11, uv-managed and brew
Python interpreters on developer macs do not carry the macOS Local Network
privacy grant; their connections to the .201 LAN range fail with
``EHOSTUNREACH``. ``curl`` does carry the grant. To exercise the real Python
runner without depending on a yet-to-be-issued GUI privacy grant, this test
patches the runner's HTTP boundary (``inprocess_runner._call_llm``) with a
curl-subprocess shim that returns the same tuple contract as the real
function. Every layer above the HTTP transport is real.

Why the model-id rewrite: ``routing_tiers.yaml`` declares model ids like
``qwen3-coder-30b`` that vLLM rejects with HTTP 404 — vLLM only accepts the
HuggingFace served-model id (e.g.
``cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit``). The shim rewrites the
YAML id to the served id at the wire boundary. This is a documented
production gap (see PR #1523 commit message); rewriting here lets the live
test prove the pipeline rather than the routing-config drift.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Skip-conditions
# ---------------------------------------------------------------------------
_LIVE_FLAG = "OMNINODE_LLM_LIVE"
_DEFAULT_LLM_CODER_URL = "http://192.168.86.201:8000"  # onex-allow-internal-ip - LAN vLLM Qwen3-Coder; not Kafka  # kafka-fallback-ok


def _live_endpoint() -> str | None:
    """Resolve the live LLM endpoint, or return None if the test should skip."""
    if os.environ.get(_LIVE_FLAG) != "1":
        return None
    endpoint = os.environ.get("LLM_CODER_URL", _DEFAULT_LLM_CODER_URL)
    # Probe with curl (carries the LAN grant on developer macs).
    try:
        proc = subprocess.run(
            [
                "curl",
                "-fsS",
                "--max-time",
                "5",
                "-o",
                "/dev/null",
                f"{endpoint}/health",
            ],
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return endpoint


_LIVE_ENDPOINT = _live_endpoint()
pytestmark = pytest.mark.skipif(
    _LIVE_ENDPOINT is None,
    reason=(
        f"Set {_LIVE_FLAG}=1 and ensure LLM_CODER_URL/health is reachable to "
        f"run live LLM integration tests."
    ),
)

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

    See module docstring for why curl is required and why the model id is
    rewritten. Same return contract as the real _call_llm.
    """
    from omniclaude.delegation.inprocess_runner import (  # noqa: PLC0415
        DelegationRunnerError,
    )

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


# ---------------------------------------------------------------------------
# Make the delegate skill _lib module importable as `run`
# ---------------------------------------------------------------------------
_TESTS_DIR = Path(__file__).parent
_REPO_ROOT = _TESTS_DIR.parent.parent
_DELEGATE_LIB = _REPO_ROOT / "plugins" / "onex" / "skills" / "delegate" / "_lib"

if _DELEGATE_LIB.exists() and str(_DELEGATE_LIB) not in sys.path:
    sys.path.insert(0, str(_DELEGATE_LIB))


@pytest.fixture
def delegate_run_module() -> ModuleType:
    sys.modules.pop("run", None)
    import importlib  # noqa: PLC0415

    import run as _run  # noqa: PLC0415

    return importlib.reload(_run)


class TestLiveLLMEvidenceBundle:
    """Real LLM call through the full pipeline produces a real evidence bundle."""

    def test_live_qwen3_coder_writes_evidence_bundle(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        if not getattr(delegate_run_module, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        assert _LIVE_ENDPOINT is not None  # for mypy; pytestmark guarantees this

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_CODER_URL", _LIVE_ENDPOINT)
        monkeypatch.setenv("LLM_CODER_FAST_URL", _LIVE_ENDPOINT)

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_call_llm_via_curl,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt=(
                    "write unit tests for handler_event_emitter.py — cover the "
                    "happy path with a single pytest function using "
                    "@pytest.mark.unit. Output only the test function."
                ),
                source_file="src/handler_event_emitter.py",
                max_tokens=256,
                force_local=True,
            )

        # 1. Pipeline reported success and chose the in-process path
        assert result["success"] is True, f"expected success, got {result}"
        assert result["path"] == "inprocess"
        assert result["task_type"] == "test"

        # 2. Real model returned non-empty content with non-zero tokens
        content: str = result["content"]
        assert len(content) > 0, "live model returned empty content"
        assert result["prompt_tokens"] > 0
        assert result["completion_tokens"] > 0
        assert result["total_tokens"] >= (
            result["prompt_tokens"] + result["completion_tokens"]
        )

        # 3. model_used is the served HF id (rewritten by the curl shim)
        assert result["model_used"] in _VLLM_SERVED_MODELS.values()

        # 4. Evidence bundle exists on disk with all 5 artifacts
        bundle_path = result["evidence_bundle_path"]
        assert bundle_path is not None
        bundle_dir = Path(bundle_path)
        assert bundle_dir.is_dir()
        artifact_names = {p.name for p in bundle_dir.iterdir()}
        assert artifact_names == {
            "run_manifest.json",
            "bifrost_response.json",
            "quality_gate_result.json",
            "cost_event.json",
            "receipt.json",
        }

        # 5. The bifrost_response artifact captured the REAL model output
        bifrost = json.loads((bundle_dir / "bifrost_response.json").read_text())
        assert bifrost["response_content"] == content
        assert bifrost["prompt_tokens"] == result["prompt_tokens"]
        assert bifrost["completion_tokens"] == result["completion_tokens"]
        assert bifrost["model_used"] == result["model_used"]

        # 6. Receipt is well-formed
        receipt = json.loads((bundle_dir / "receipt.json").read_text())
        assert set(receipt["artifact_hashes"]) == {
            "run_manifest.json",
            "bifrost_response.json",
            "quality_gate_result.json",
            "cost_event.json",
        }
        assert len(receipt["bundle_root_hash"]) == 64
        assert receipt["correlation_id"] == result["correlation_id"]

        # 7. Persist as durable evidence under .onex_state/evidence/OMN-10610/
        # so a future reviewer can audit the live proof on disk.
        evidence_root = _REPO_ROOT / ".onex_state" / "evidence" / "OMN-10610"
        evidence_root.mkdir(parents=True, exist_ok=True)
        durable_dir = evidence_root / bundle_dir.name
        durable_dir.mkdir(exist_ok=True)
        for artifact in bundle_dir.iterdir():
            (durable_dir / artifact.name).write_bytes(artifact.read_bytes())
        # Also persist the result dict for the reviewer.
        (durable_dir / "result.json").write_text(
            json.dumps(
                {k: v for k, v in result.items() if k != "content"}
                | {
                    "content_excerpt": content[:500],
                    "endpoint": _LIVE_ENDPOINT,
                },
                indent=2,
            )
        )
