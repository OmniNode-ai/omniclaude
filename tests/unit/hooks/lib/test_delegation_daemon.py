# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for the delegation daemon with Valkey caching.

These tests verify:
- Classification caching via Valkey (hit/miss/key uniqueness)
- Request handling (valid/invalid/missing fields)
- Valkey failure modes (unavailable/timeout/schema mismatch)

All Valkey and orchestration dependencies are mocked — no live services needed.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestClassifyWithCache:
    """Tests for _classify_with_cache()."""

    def _import_module(self) -> Any:
        """Import delegation_daemon module (deferred so tests fail cleanly if missing)."""
        # The module lives under plugins/onex/hooks/lib/ which is added to sys.path
        # at import time.  We import by name since the module sets up its own paths.
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_classify_and_cache_miss(self) -> None:
        """Cache miss: calls TaskClassifier, stores result in Valkey."""
        mod = self._import_module()

        fake_classification = {
            "intent": "document",
            "confidence": 0.92,
            "delegatable": True,
        }
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = None  # cache miss

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                classified_intent="document",
                confidence=0.92,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write docs for the API", "corr-123")

        assert result is not None
        assert result["intent"] == "document"
        # Verify Valkey set was called
        mock_valkey.set.assert_called_once()

    def test_classify_and_cache_hit(self) -> None:
        """Cache hit: returns cached classification without calling TaskClassifier."""
        mod = self._import_module()

        cached_data = json.dumps(
            {
                "schema_version": 1,
                "intent": "test",
                "confidence": 0.88,
                "delegatable": True,
                "cached_at": "2026-01-01T00:00:00Z",
            }
        )
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = cached_data.encode()

        with patch.object(mod, "_get_valkey", return_value=mock_valkey):
            result = mod._classify_with_cache("Write unit tests", "corr-456")

        assert result is not None
        assert result["intent"] == "test"
        assert result["confidence"] == 0.88

    def test_cache_key_differs_for_different_prompts(self) -> None:
        """Different prompts produce different cache keys."""
        prompt_a = "Write documentation"
        prompt_b = "Fix the bug in auth"

        key_a = (
            f"delegation:classify:{hashlib.sha256(prompt_a[:500].encode()).hexdigest()}"
        )
        key_b = (
            f"delegation:classify:{hashlib.sha256(prompt_b[:500].encode()).hexdigest()}"
        )

        assert key_a != key_b


@pytest.mark.unit
class TestHandleRequest:
    """Tests for _handle_request()."""

    def _import_module(self) -> Any:
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_handle_request_valid_json(self) -> None:
        """Valid JSON request returns orchestration result."""
        mod = self._import_module()

        request = json.dumps(
            {
                "prompt": "Write docs",
                "correlation_id": "corr-789",
                "session_id": "sess-001",
            }
        ).encode()

        fake_result = {"delegated": True, "response": "Here are docs"}

        with patch.object(
            mod, "orchestrate_delegation", return_value=fake_result
        ) as mock_orch:
            response = mod._handle_request(request)

        parsed = json.loads(response)
        assert parsed["delegated"] is True
        mock_orch.assert_called_once()

    def test_handle_request_invalid_json(self) -> None:
        """Garbage input returns error JSON."""
        mod = self._import_module()

        response = mod._handle_request(b"not json at all {{{")
        parsed = json.loads(response)
        assert parsed.get("delegated") is False
        assert "error" in parsed or "reason" in parsed

    def test_handle_request_missing_fields(self) -> None:
        """JSON without 'prompt' field returns error."""
        mod = self._import_module()

        request = json.dumps({"correlation_id": "corr-000"}).encode()
        response = mod._handle_request(request)
        parsed = json.loads(response)
        assert parsed.get("delegated") is False


@pytest.mark.unit
class TestValkeyFailureModes:
    """Tests for Valkey failure scenarios."""

    def _import_module(self) -> Any:
        import importlib
        import sys
        from pathlib import Path

        lib_dir = str(
            Path(__file__).resolve().parents[4] / "plugins" / "onex" / "hooks" / "lib"
        )
        if lib_dir not in sys.path:
            sys.path.insert(0, lib_dir)
        return importlib.import_module("delegation_daemon")

    def test_valkey_unavailable_falls_back(self) -> None:
        """When Valkey is unreachable, classification proceeds without cache."""
        mod = self._import_module()

        with (
            patch.object(mod, "_get_valkey", return_value=None),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                classified_intent="research",
                confidence=0.85,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Research the topic", "corr-fallback")

        assert result is not None
        assert result["intent"] == "research"

    def test_valkey_timeout_falls_back(self) -> None:
        """When Valkey.get() times out, classification proceeds without cache."""
        mod = self._import_module()

        mock_valkey = MagicMock()
        mock_valkey.get.side_effect = TimeoutError("Connection timed out")

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                classified_intent="test",
                confidence=0.90,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write tests", "corr-timeout")

        assert result is not None
        assert result["intent"] == "test"

    def test_cache_schema_mismatch_ignored(self) -> None:
        """Cached entry with wrong schema_version is treated as cache miss."""
        mod = self._import_module()

        stale_data = json.dumps(
            {
                "schema_version": 999,  # wrong version
                "intent": "document",
                "confidence": 0.99,
                "delegatable": True,
            }
        )
        mock_valkey = MagicMock()
        mock_valkey.get.return_value = stale_data.encode()

        with (
            patch.object(mod, "_get_valkey", return_value=mock_valkey),
            patch.object(mod, "TaskClassifier") as mock_tc_cls,
        ):
            mock_tc = MagicMock()
            mock_tc.is_delegatable.return_value = MagicMock(
                classified_intent="document",
                confidence=0.91,
                delegatable=True,
            )
            mock_tc_cls.return_value = mock_tc

            result = mod._classify_with_cache("Write docs", "corr-schema")

        assert result is not None
        # Should have called classifier (cache miss due to schema mismatch)
        mock_tc_cls.assert_called_once()


@pytest.mark.unit
class TestImportDiagnostics:
    @pytest.mark.parametrize(
        "module_name",
        [
            "omniclaude.lib.task_classifier",
            "delegation_orchestrator",
            "agentic_loop",
            "agentic_quality_gate",
            "hook_quality_gate",
        ],
    )
    def test_missing_import_is_reported_at_start_and_use(
        self,
        module_name: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
        tmp_path: Any,
    ) -> None:
        import builtins
        import importlib
        import logging

        mod = TestClassifyWithCache()._import_module()
        original_import = builtins.__import__

        def blocked_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == module_name:
                raise ImportError("planted missing dependency")
            return original_import(name, *args, **kwargs)

        try:
            with monkeypatch.context() as scoped:
                scoped.setattr(builtins, "__import__", blocked_import)
                importlib.reload(mod)
            assert mod._IMPORT_ERRORS[module_name] == "planted missing dependency"
            # Stop immediately after the real startup diagnostic, before binding.
            monkeypatch.setattr(
                mod,
                "_cleanup_stale",
                MagicMock(side_effect=RuntimeError("stop startup")),
            )
            monkeypatch.setattr(mod, "_get_socket_path", lambda: str(tmp_path / "sock"))
            monkeypatch.setattr(mod, "_get_pid_path", lambda: str(tmp_path / "pid"))
            with caplog.at_level(logging.ERROR):
                with pytest.raises(RuntimeError, match="stop startup"):
                    mod.start_daemon()
            assert module_name in capsys.readouterr().err
            assert any(
                record.levelno == logging.ERROR
                and module_name in record.message
                and "planted missing dependency" in record.message
                for record in caplog.records
            )
            caplog.clear()
            # Exercise a path that would consume each missing symbol.
            with caplog.at_level(logging.ERROR):
                if module_name == "omniclaude.lib.task_classifier":
                    monkeypatch.setattr(mod, "_get_valkey", lambda: None)
                    mod._classify_with_cache("document this", "cid")
                elif module_name == "delegation_orchestrator":
                    mod._handle_request(b'{"prompt": "document this"}')
                elif module_name == "agentic_loop":
                    monkeypatch.setattr(mod, "_classify_with_cache", lambda *a: None)
                    monkeypatch.setattr(
                        mod, "orchestrate_delegation", lambda **kw: {"agentic": True}
                    )
                    mod._handle_request(b'{"prompt": "document this"}')
                elif module_name == "hook_quality_gate":
                    monkeypatch.setattr(mod, "_classify_with_cache", lambda *a: None)
                    monkeypatch.setattr(
                        mod,
                        "orchestrate_delegation",
                        lambda **kw: {"response_content": "documented result"},
                    )
                    mod._handle_request(b'{"prompt": "document this"}')
                else:
                    result = MagicMock(
                        content="documented result", tool_names_used=set()
                    )
                    job = mod.AgenticJob("job", "session", "prompt")
                    job.status = mod.AgenticJobStatus.COMPLETED
                    job.result = result
                    monkeypatch.setattr(mod, "_agentic_jobs", {"job": job})
                    monkeypatch.setattr(mod, "run_hook_quality_gate", None)
                    monkeypatch.setattr(mod, "_emit_delegation_event", None)
                    mod._poll_agentic_jobs("session")
            assert module_name in capsys.readouterr().err
            assert any(
                record.levelno == logging.ERROR and module_name in record.message
                for record in caplog.records
            )
        finally:
            importlib.reload(mod)

    def test_all_importable_is_silent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import importlib
        import logging
        import sys
        from types import ModuleType

        mod = TestClassifyWithCache()._import_module()
        # The retired orchestrator is absent in this checkout; supply an importable
        # dependency to exercise the all-importable branch, without changing runtime.
        orchestrator = ModuleType("delegation_orchestrator")
        setattr(orchestrator, "orchestrate_delegation", MagicMock())
        setattr(orchestrator, "_emit_delegation_event", MagicMock())
        try:
            with monkeypatch.context() as scoped:
                scoped.setitem(sys.modules, "delegation_orchestrator", orchestrator)
                importlib.reload(mod)
                assert not mod._IMPORT_ERRORS
                scoped.setattr(
                    mod,
                    "_cleanup_stale",
                    MagicMock(side_effect=RuntimeError("stop startup")),
                )
                with caplog.at_level(logging.ERROR):
                    with pytest.raises(RuntimeError, match="stop startup"):
                        mod.start_daemon()
                    mod._report_import_errors()
                assert not caplog.records
                assert capsys.readouterr().err == ""
        finally:
            importlib.reload(mod)


@pytest.mark.unit
@pytest.mark.parametrize("cache_is_mapping", [True, False])
def test_only_a_mapping_with_the_current_schema_is_a_cache_hit(
    cache_is_mapping: bool,
) -> None:
    mod = TestClassifyWithCache()._import_module()
    cached = {"schema_version": mod.CACHE_SCHEMA_VERSION, "intent": "cached"}
    client = MagicMock()
    client.get.return_value = json.dumps(cached if cache_is_mapping else [cached])
    with (
        patch.object(mod, "_get_valkey", return_value=client),
        patch.object(mod, "TaskClassifier") as classifier,
    ):
        classifier.return_value.is_delegatable.return_value = MagicMock(
            classified_intent="fresh", confidence=0.9, delegatable=True
        )
        result = mod._classify_with_cache("document this", "correlation")
    assert result is not None
    assert result["intent"] == ("cached" if cache_is_mapping else "fresh")
    assert classifier.called is not cache_is_mapping
