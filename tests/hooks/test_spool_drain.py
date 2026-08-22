# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the hook-event spool drain / shipper (OMN-16090).

Covers: spool parsing, batching/dedupe, sha computation, 202/4xx/5xx
handling, partial-drain resume, and fail-fast credential/env resolution.
Uses httpx.MockTransport — no real network, no real Kafka/gateway.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from omniclaude.hooks.models_spool_drain import canonical_sha_input
from omniclaude.hooks.spool_drain import (
    DrainConfig,
    GatewayTransport,
    SpoolDrainError,
    SpoolFrameError,
    build_batch,
    compute_batch_sha,
    drain_spool,
    frame_spool_file,
    key_fingerprint,
    poll_status,
    resolve_api_base_url,
    resolve_api_key,
    resolve_spool_dir,
    submit_batch_with_retry,
)

pytestmark = pytest.mark.unit


def _write_spool_file(
    spool_dir: Path,
    name: str,
    *,
    event_type: str = "artifact.captured",
    payload: dict[str, object] | None = None,
    spooled_at_utc: str = "2026-06-28T17:25:25.517566+00:00",
    spool_reason: str = "FileNotFoundError: nope",
) -> Path:
    spool_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "event_type": event_type,
        "payload": payload if payload is not None else {"x": 1},
        "spooled_at_utc": spooled_at_utc,
        "spool_reason": spool_reason,
    }
    path = spool_dir / name
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _no_sleep(_seconds: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Env / credential resolution
# ---------------------------------------------------------------------------


class TestResolveSpoolDir:
    def test_explicit_path_wins(self, tmp_path: Path) -> None:
        assert resolve_spool_dir(tmp_path) == tmp_path

    def test_fails_fast_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONEX_STATE_DIR", raising=False)
        with pytest.raises(SpoolDrainError, match="ONEX_STATE_DIR"):
            resolve_spool_dir(None)

    def test_derives_from_state_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from omnibase_infra.cli.receipt_mode import SPOOL_DIR_NAME

        monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path))
        assert resolve_spool_dir(None) == tmp_path / SPOOL_DIR_NAME


class TestResolveApiBaseUrl:
    def test_explicit_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_API_BASE_URL", "https://env.example")
        assert (
            resolve_api_base_url("https://explicit.example")
            == "https://explicit.example"
        )

    def test_reads_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ONEX_API_BASE_URL", "https://env.example")
        assert resolve_api_base_url(None) == "https://env.example"

    def test_fails_fast_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONEX_API_BASE_URL", raising=False)
        with pytest.raises(SpoolDrainError, match="ONEX_API_BASE_URL"):
            resolve_api_base_url(None)


class TestResolveApiKey:
    def test_inline_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY_FILE", raising=False)
        monkeypatch.setenv("ONEX_GATEWAY_API_KEY", "secret-key")
        assert resolve_api_key() == "secret-key"

    def test_file_env_var(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cred = tmp_path / "cred"
        cred.write_text("secret-from-file\n")
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.setenv("ONEX_GATEWAY_API_KEY_FILE", str(cred))
        assert resolve_api_key() == "secret-from-file"

    def test_missing_cred_file_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.setenv("ONEX_GATEWAY_API_KEY_FILE", str(tmp_path / "missing"))
        with pytest.raises(SpoolDrainError, match="does not exist"):
            resolve_api_key()

    def test_empty_cred_file_raises(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        cred = tmp_path / "cred"
        cred.write_text("   \n")
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.setenv("ONEX_GATEWAY_API_KEY_FILE", str(cred))
        with pytest.raises(SpoolDrainError, match="empty"):
            resolve_api_key()

    def test_fails_fast_when_neither_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY_FILE", raising=False)
        with pytest.raises(SpoolDrainError, match="ONEX_GATEWAY_API_KEY"):
            resolve_api_key()

    def test_never_defaults_to_a_hardcoded_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No silent fallback to any operator-specific credential path."""
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY", raising=False)
        monkeypatch.delenv("ONEX_GATEWAY_API_KEY_FILE", raising=False)
        with pytest.raises(SpoolDrainError):
            resolve_api_key()

    def test_key_fingerprint_is_short_and_non_reversible(self) -> None:
        fp = key_fingerprint("super-secret-value")
        assert len(fp) == 8
        assert "super-secret-value" not in fp


# ---------------------------------------------------------------------------
# spool file -> contract event (framing + sha)
# ---------------------------------------------------------------------------


class TestFrameSpoolFile:
    def test_valid_file_frames_correctly(self, tmp_path: Path) -> None:
        payload = {"artifact_hash": "abc", "correlation_id": "corr-1"}
        path = _write_spool_file(
            tmp_path, "artifact-captured-a-0.json", payload=payload
        )
        event = frame_spool_file(path)
        assert event.event_type == "artifact.captured"
        assert event.correlation_id == "corr-1"
        expected_sha = hashlib.sha256(
            canonical_sha_input(
                "artifact.captured", payload, "2026-06-28T17:25:25.517566+00:00"
            ).encode("utf-8")
        ).hexdigest()
        assert event.event_sha == expected_sha
        assert event.spool_reason == "FileNotFoundError: nope"

    def test_occurred_at_prefers_emitted_at_over_spooled_at(
        self, tmp_path: Path
    ) -> None:
        payload = {"emitted_at": "2026-01-01T00:00:00.000000+00:00"}
        path = _write_spool_file(tmp_path, "f.json", payload=payload)
        event = frame_spool_file(path)
        assert event.occurred_at == "2026-01-01T00:00:00.000000+00:00"

    def test_occurred_at_falls_back_to_timestamp(self, tmp_path: Path) -> None:
        spool_dir = tmp_path
        spool_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "event_type": "artifact.captured",
            "payload": {"timestamp": "2026-02-02T00:00:00.000000+00:00"},
        }
        path = spool_dir / "f.json"
        path.write_text(json.dumps(record))
        event = frame_spool_file(path)
        assert event.occurred_at == "2026-02-02T00:00:00.000000+00:00"

    def test_unparseable_json_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(SpoolFrameError, match="unreadable/unparseable"):
            frame_spool_file(path)

    def test_missing_event_type_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"payload": {}}))
        with pytest.raises(SpoolFrameError, match="malformed spool record"):
            frame_spool_file(path)

    def test_no_usable_occurred_at_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"event_type": "artifact.captured", "payload": {}}))
        with pytest.raises(SpoolFrameError, match="occurred_at"):
            frame_spool_file(path)

    def test_oversized_payload_json_raises(self, tmp_path: Path) -> None:
        payload = {"blob": "x" * 40000}
        path = _write_spool_file(tmp_path, "big.json", payload=payload)
        with pytest.raises(SpoolFrameError, match="over the"):
            frame_spool_file(path)

    def test_identical_content_produces_identical_sha(self, tmp_path: Path) -> None:
        payload = {"a": 1}
        p1 = _write_spool_file(tmp_path, "one.json", payload=payload)
        p2 = _write_spool_file(tmp_path, "two.json", payload=payload)
        e1 = frame_spool_file(p1)
        e2 = frame_spool_file(p2)
        assert e1.event_sha == e2.event_sha


class TestComputeBatchSha:
    def test_matches_sha256_of_newline_joined_event_shas(self) -> None:
        from omniclaude.hooks.models_spool_drain import ModelCapturedHookEvent

        e1 = ModelCapturedHookEvent(
            event_type="a.b",
            event_sha="a" * 64,
            occurred_at="2026-01-01T00:00:00Z",
            payload_json="{}",
        )
        e2 = ModelCapturedHookEvent(
            event_type="a.b",
            event_sha="b" * 64,
            occurred_at="2026-01-01T00:00:00Z",
            payload_json="{}",
        )
        expected = hashlib.sha256(f"{'a' * 64}\n{'b' * 64}".encode()).hexdigest()
        assert compute_batch_sha([e1, e2]) == expected

    def test_order_sensitive(self) -> None:
        from omniclaude.hooks.models_spool_drain import ModelCapturedHookEvent

        e1 = ModelCapturedHookEvent(
            event_type="a.b",
            event_sha="a" * 64,
            occurred_at="2026-01-01T00:00:00Z",
            payload_json="{}",
        )
        e2 = ModelCapturedHookEvent(
            event_type="a.b",
            event_sha="b" * 64,
            occurred_at="2026-01-01T00:00:00Z",
            payload_json="{}",
        )
        assert compute_batch_sha([e1, e2]) != compute_batch_sha([e2, e1])


# ---------------------------------------------------------------------------
# submit_batch_with_retry / poll_status (HTTP handling)
# ---------------------------------------------------------------------------


def _client_with_transport(handler: object) -> GatewayTransport:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return GatewayTransport(
        "https://gw.example", "test-key", timeout=5.0, client=http_client
    )


class TestSubmitBatchWithRetry:
    def test_202_returns_immediately_no_retry(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(202, json={"workflow_id": "wf-1"})

        client = _client_with_transport(handler)
        batch = build_batch(
            [_event()],
            source="local_macos_claude_hooks",
        )
        sleeps: list[float] = []
        status, body, error = submit_batch_with_retry(
            client,
            batch,
            retry_attempts=3,
            backoff_base_seconds=1.0,
            max_backoff_seconds=10.0,
            sleep_fn=sleeps.append,
        )
        assert status == 202
        assert isinstance(body, dict)
        assert body["workflow_id"] == "wf-1"
        assert error is None
        assert len(calls) == 1
        assert sleeps == []

    def test_4xx_is_poison_no_retry(self) -> None:
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(400, json={"detail": "bad request"})

        client = _client_with_transport(handler)
        batch = build_batch([_event()], source="local_macos_claude_hooks")
        sleeps: list[float] = []
        status, body, error = submit_batch_with_retry(
            client,
            batch,
            retry_attempts=3,
            backoff_base_seconds=1.0,
            max_backoff_seconds=10.0,
            sleep_fn=sleeps.append,
        )
        assert status == 400
        assert len(calls) == 1
        assert sleeps == []

    def test_5xx_retries_with_exponential_backoff_then_succeeds(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 3:
                return httpx.Response(503, json={"detail": "unavailable"})
            return httpx.Response(202, json={"workflow_id": "wf-2"})

        client = _client_with_transport(handler)
        batch = build_batch([_event()], source="local_macos_claude_hooks")
        sleeps: list[float] = []
        status, body, error = submit_batch_with_retry(
            client,
            batch,
            retry_attempts=5,
            backoff_base_seconds=1.0,
            max_backoff_seconds=10.0,
            sleep_fn=sleeps.append,
        )
        assert status == 202
        assert attempts["n"] == 3
        assert sleeps == [1.0, 2.0]

    def test_5xx_exhausts_retries_and_reports_last_failure(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"detail": "still down"})

        client = _client_with_transport(handler)
        batch = build_batch([_event()], source="local_macos_claude_hooks")
        sleeps: list[float] = []
        status, body, error = submit_batch_with_retry(
            client,
            batch,
            retry_attempts=3,
            backoff_base_seconds=1.0,
            max_backoff_seconds=10.0,
            sleep_fn=sleeps.append,
        )
        assert status == 500
        assert sleeps == [1.0, 2.0]

    def test_connection_error_retries(self) -> None:
        attempts = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(202, json={"workflow_id": "wf-3"})

        client = _client_with_transport(handler)
        batch = build_batch([_event()], source="local_macos_claude_hooks")
        status, body, error = submit_batch_with_retry(
            client,
            batch,
            retry_attempts=3,
            backoff_base_seconds=0.01,
            max_backoff_seconds=1.0,
            sleep_fn=_no_sleep,
        )
        assert status == 202


class TestPollStatus:
    def test_returns_true_on_accepted_status(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "completed"})

        client = _client_with_transport(handler)
        ok, last = poll_status(
            client,
            "wf-1",
            accept=("completed",),
            attempts=3,
            interval=0.01,
            sleep_fn=_no_sleep,
        )
        assert ok is True
        assert last == "completed"

    def test_returns_false_on_failed_status(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "failed"})

        client = _client_with_transport(handler)
        ok, last = poll_status(
            client,
            "wf-1",
            accept=("completed",),
            attempts=3,
            interval=0.01,
            sleep_fn=_no_sleep,
        )
        assert ok is False
        assert last == "failed"

    def test_exhausts_attempts_when_never_terminal(self) -> None:
        calls = {"n": 0}

        def handler(_request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"status": "pending"})

        client = _client_with_transport(handler)
        sleeps: list[float] = []
        ok, last = poll_status(
            client,
            "wf-1",
            accept=("completed",),
            attempts=4,
            interval=2.0,
            sleep_fn=sleeps.append,
        )
        assert ok is False
        assert last == "pending"
        assert calls["n"] == 4
        assert sleeps == [2.0, 2.0, 2.0]


# ---------------------------------------------------------------------------
# drain_spool orchestration
# ---------------------------------------------------------------------------


def _event() -> object:
    from omniclaude.hooks.models_spool_drain import ModelCapturedHookEvent

    return ModelCapturedHookEvent(
        event_type="artifact.captured",
        event_sha="a" * 64,
        occurred_at="2026-01-01T00:00:00Z",
        payload_json="{}",
    )


class TestDrainSpoolDryRun:
    def test_dry_run_makes_no_network_call_and_moves_nothing(
        self, tmp_path: Path
    ) -> None:
        p1 = _write_spool_file(tmp_path, "a.json", payload={"x": 1})
        _write_spool_file(tmp_path, "b.json", payload={"x": 2})

        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="unused",
            dry_run=True,
        )
        summary = drain_spool(config)

        assert summary.dry_run is True
        assert summary.files_present == 2
        assert summary.unique_events == 2
        assert p1.exists()
        assert not (tmp_path / "shipped").exists() or not list(
            (tmp_path / "shipped").glob("*")
        )

    def test_dry_run_collapses_duplicate_content(self, tmp_path: Path) -> None:
        _write_spool_file(tmp_path, "a.json", payload={"x": 1})
        _write_spool_file(tmp_path, "b.json", payload={"x": 1})
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="unused",
            dry_run=True,
        )
        summary = drain_spool(config)
        assert summary.unique_events == 1
        assert summary.duplicate_files_collapsed == 1

    def test_missing_spool_dir_raises(self, tmp_path: Path) -> None:
        config = DrainConfig(
            spool_dir=tmp_path / "nope",
            base_url="https://gw.example",
            api_key="unused",
            dry_run=True,
        )
        with pytest.raises(SpoolDrainError, match="spool directory not found"):
            drain_spool(config)

    def test_malformed_file_is_skipped_and_left_in_spool(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        _write_spool_file(tmp_path, "good.json", payload={"x": 1})

        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="unused",
            dry_run=True,
        )
        summary = drain_spool(config)
        assert len(summary.skipped) == 1
        assert summary.unique_events == 1
        assert bad.exists()


class TestDrainSpoolLive:
    def test_successful_batch_moves_files_to_shipped(self, tmp_path: Path) -> None:
        p1 = _write_spool_file(tmp_path, "a.json", payload={"x": 1})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "completed"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )

        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert summary.events_shipped == 1
        assert not p1.exists()
        assert (tmp_path / "shipped" / "a.json").exists()
        assert summary.remaining_in_spool == 0
        assert summary.batches[0].confirmed is True

    def test_dedupe_moves_both_files_for_shared_sha(self, tmp_path: Path) -> None:
        payload = {"x": 1}
        p1 = _write_spool_file(tmp_path, "a.json", payload=payload)
        p2 = _write_spool_file(tmp_path, "b.json", payload=payload)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "completed"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert summary.unique_events == 1
        assert summary.duplicate_files_collapsed == 1
        assert not p1.exists()
        assert not p2.exists()
        assert (tmp_path / "shipped" / "a.json").exists()
        assert (tmp_path / "shipped" / "b.json").exists()

    def test_4xx_batch_left_in_spool_but_drain_continues(self, tmp_path: Path) -> None:
        p_bad = _write_spool_file(tmp_path, "a.json", payload={"x": 1})
        p_good = _write_spool_file(tmp_path, "b.json", payload={"x": 2})

        seen_shas: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                body = json.loads(request.content)
                sha = body["payload"]["batch_sha"]
                if sha not in seen_shas:
                    seen_shas.append(sha)
                # First batch submitted -> reject. Second -> accept.
                if len(seen_shas) == 1:
                    return httpx.Response(400, json={"detail": "bad"})
                return httpx.Response(202, json={"workflow_id": "wf-ok"})
            return httpx.Response(200, json={"status": "completed"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            batch_size=1,
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert len(summary.batches) == 2
        confirmed = [b for b in summary.batches if b.confirmed]
        failed = [b for b in summary.batches if not b.confirmed]
        assert len(confirmed) == 1
        assert len(failed) == 1
        assert failed[0].http_status == 400
        # Exactly one of the two original files should remain (the failed one).
        remaining = list(tmp_path.glob("*.json"))
        assert len(remaining) == 1
        shipped = list((tmp_path / "shipped").glob("*.json"))
        assert len(shipped) == 1
        assert {p.name for p in remaining + shipped} == {p_bad.name, p_good.name}

    def test_202_with_no_workflow_id_leaves_files_in_spool(
        self, tmp_path: Path
    ) -> None:
        p1 = _write_spool_file(tmp_path, "a.json", payload={"x": 1})

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(202, json={})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert p1.exists()
        assert summary.batches[0].confirmed is False
        assert summary.batches[0].status == "no_workflow_id"

    def test_unconfirmed_status_leaves_files_in_spool(self, tmp_path: Path) -> None:
        p1 = _write_spool_file(tmp_path, "a.json", payload={"x": 1})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "pending"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            poll_attempts=2,
            poll_interval=0.01,
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert p1.exists()
        assert summary.batches[0].confirmed is False
        assert "unconfirmed" in summary.batches[0].status
        assert summary.remaining_in_spool == 1

    def test_published_accepted_when_require_status_published(
        self, tmp_path: Path
    ) -> None:
        p1 = _write_spool_file(tmp_path, "a.json", payload={"x": 1})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "published"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            require_status="published",
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary = drain_spool(config, client=client)

        assert not p1.exists()
        assert summary.batches[0].confirmed is True

    def test_partial_drain_resume(self, tmp_path: Path) -> None:
        """A --limit run ships some events; a follow-up run picks up the rest,
        never re-shipping the already-shipped ones."""
        _write_spool_file(tmp_path, "a.json", payload={"x": 1})
        _write_spool_file(tmp_path, "b.json", payload={"x": 2})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "completed"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )

        config1 = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            limit=1,
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary1 = drain_spool(config1, client=client)
        assert summary1.events_shipped == 1
        assert summary1.remaining_in_spool == 1

        config2 = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        summary2 = drain_spool(config2, client=client)
        assert summary2.events_shipped == 1
        assert summary2.remaining_in_spool == 0

        shipped = list((tmp_path / "shipped").glob("*.json"))
        assert len(shipped) == 2

    def test_never_deletes_only_moves(self, tmp_path: Path) -> None:
        _write_spool_file(tmp_path, "a.json", payload={"x": 1})

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/v1/workflows"):
                return httpx.Response(202, json={"workflow_id": "wf-1"})
            return httpx.Response(200, json={"status": "completed"})

        http_client = httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
        client = GatewayTransport(
            "https://gw.example", "test-key", timeout=5.0, client=http_client
        )
        config = DrainConfig(
            spool_dir=tmp_path,
            base_url="https://gw.example",
            api_key="test-key",
            poll_attempts=1,
            sleep_fn=_no_sleep,
        )
        drain_spool(config, client=client)

        total_after = len(list(tmp_path.rglob("*.json")))
        assert total_after == 1  # moved, not deleted, not duplicated
