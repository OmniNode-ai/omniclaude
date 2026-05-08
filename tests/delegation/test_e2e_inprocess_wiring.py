# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""End-to-end integration test for the in-process delegation pipeline (OMN-10610).

Drives the full chain that ships with PR #1523:
    delegate skill (force_local=True)
        → TaskClassifier
        → InProcessDelegationRunner.run
            → routing_delta (real, reads env vars)
            → _call_llm (patched — the only HTTP boundary)
            → quality_gate_delta (real)
        → _write_evidence_bundle (real)
            → EvidenceBundleWriter.write (real, writes 5 artifacts to disk)

No live LLM, no .201, no Kafka, no Docker. The pipeline runs in-process with
the only mock at the HTTP transport boundary, so every other layer
(classifier → routing config → quality gate → evidence bundle writer) is
exercised against real production code.

What this test proves the corrected scope (per team-lead 2026-05-07):
    - WIRING is end-to-end correct: delegate → runner → quality gate → bundle
    - Real evidence artifacts are produced on disk with the right shape
    - ONEX_STATE_DIR controls bundle emission (set → bundle, unset → no bundle)
    - The result dict surfaces evidence_bundle_path back to the caller
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import patch

import pytest

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
    """Reload the delegate skill's run module fresh for each test."""
    sys.modules.pop("run", None)
    import importlib  # noqa: PLC0415

    import run as _run  # noqa: PLC0415

    return importlib.reload(_run)


_MOCK_LLM_CONTENT = (
    "@pytest.mark.unit\n"
    "def test_add_happy_path() -> None:\n"
    "    assert add(2, 3) == 5\n"
    "    assert add(0, 0) == 0\n"
    "    assert add(-1, 1) == 0\n"
)
_MOCK_LLM_USAGE: dict[str, int] = {
    "prompt_tokens": 50,
    "completion_tokens": 80,
    "total_tokens": 130,
}
_MOCK_LATENCY_MS = 42
_MOCK_MODEL_USED = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"


def _patched_call_llm(**_: Any) -> tuple[str, dict[str, int], int, str]:
    """Drop-in replacement for the runner's HTTP boundary.

    Same return contract as inprocess_runner._call_llm so quality_gate_delta
    and result-construction code paths are exercised normally.
    """
    return (_MOCK_LLM_CONTENT, _MOCK_LLM_USAGE, _MOCK_LATENCY_MS, _MOCK_MODEL_USED)


@pytest.mark.unit
class TestInprocessWiringEndToEnd:
    """Full chain: delegate skill → runner → quality gate → evidence bundle."""

    def test_force_local_writes_evidence_bundle_with_all_artifacts(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        if not getattr(delegate_run_module, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://test-backend.invalid:8001")

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                source_file="src/foo.py",
                max_tokens=512,
                force_local=True,
            )

        assert result["success"] is True, f"expected success, got {result}"
        assert result["path"] == "inprocess"
        assert result["task_type"] == "test"
        assert result["model_used"] == _MOCK_MODEL_USED
        assert result["content"] == _MOCK_LLM_CONTENT
        assert result["prompt_tokens"] == _MOCK_LLM_USAGE["prompt_tokens"]
        assert result["completion_tokens"] == _MOCK_LLM_USAGE["completion_tokens"]
        assert result["total_tokens"] == _MOCK_LLM_USAGE["total_tokens"]
        assert result["quality_passed"] is True

        bundle_path = result["evidence_bundle_path"]
        assert bundle_path is not None
        bundle_dir = Path(bundle_path)
        assert bundle_dir.is_dir()
        assert bundle_dir.parent == tmp_path / "delegation" / "bundles"
        uuid.UUID(bundle_dir.name)  # path segment is the correlation_id

        artifact_names = {p.name for p in bundle_dir.iterdir()}
        assert artifact_names == {
            "run_manifest.json",
            "bifrost_response.json",
            "quality_gate_result.json",
            "cost_event.json",
            "receipt.json",
        }

    def test_run_manifest_has_correct_fields(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        if not getattr(delegate_run_module, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://test-backend.invalid:8001")

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        assert result["success"] is True
        bundle_dir = Path(result["evidence_bundle_path"])
        manifest = json.loads((bundle_dir / "run_manifest.json").read_text())
        assert manifest["correlation_id"] == result["correlation_id"]
        assert manifest["task_type"] == "test"
        assert manifest["runner"] == "inprocess"
        assert manifest["bundle_schema_version"] == "1.0.0"
        assert len(manifest["prompt_hash"]) == 64
        assert manifest["started_at"] <= manifest["completed_at"]

    def test_bifrost_response_captures_routing_decision(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        if not getattr(delegate_run_module, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        # Routing delta reads endpoint from LLM_CODER_* env vars (OMN-10657)
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://test-backend.invalid:8001")
        import omnibase_infra.nodes.node_delegation_routing_reducer.handlers.handler_delegation_routing as _h

        _h._config = None

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        _h._config = None

        bundle_dir = Path(result["evidence_bundle_path"])
        bifrost = json.loads((bundle_dir / "bifrost_response.json").read_text())
        assert bifrost["backend_selected"].startswith("http://test-backend.invalid:")
        assert bifrost["model_used"] == _MOCK_MODEL_USED
        assert bifrost["prompt_tokens"] == _MOCK_LLM_USAGE["prompt_tokens"]
        assert bifrost["response_content"] == _MOCK_LLM_CONTENT

    def test_receipt_hashes_cover_all_four_other_artifacts(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        if not getattr(delegate_run_module, "_HAS_EVIDENCE_BUNDLE", False):
            pytest.skip("evidence_bundle module not importable in this venv")

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://test-backend.invalid:8001")

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        bundle_dir = Path(result["evidence_bundle_path"])
        receipt = json.loads((bundle_dir / "receipt.json").read_text())
        assert set(receipt["artifact_hashes"]) == {
            "run_manifest.json",
            "bifrost_response.json",
            "quality_gate_result.json",
            "cost_event.json",
        }
        for digest in receipt["artifact_hashes"].values():
            assert len(digest) == 64
        assert len(receipt["bundle_root_hash"]) == 64
        assert receipt["correlation_id"] == result["correlation_id"]

    def test_no_bundle_when_state_dir_unset(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
        monkeypatch.setenv("LLM_CODER_URL", "http://test-backend.invalid:8000")
        monkeypatch.setenv("LLM_CODER_FAST_URL", "http://test-backend.invalid:8001")

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ):
            result = delegate_run_module.classify_and_publish(
                prompt="write unit tests for handler_event_emitter.py",
                force_local=True,
            )

        assert result["success"] is True
        assert result["evidence_bundle_path"] is None

    def test_non_delegatable_intent_returns_error_no_bundle(
        self,
        delegate_run_module: ModuleType,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Intent rejection runs BEFORE the runner — no bundle should be written."""
        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))

        with patch(
            "omniclaude.delegation.inprocess_runner._call_llm",
            side_effect=_patched_call_llm,
        ) as mock_call:
            result = delegate_run_module.classify_and_publish(
                prompt="debug the broken database connection",
                force_local=True,
            )

        assert result["success"] is False
        assert "not delegatable" in result["error"]
        assert mock_call.call_count == 0
        bundles_dir = tmp_path / "delegation" / "bundles"
        assert not bundles_dir.exists() or not any(bundles_dir.iterdir())
