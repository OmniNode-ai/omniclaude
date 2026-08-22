# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Drain the local hook-event spool to the cloud gateway (OMN-16090).

This is the operator-machine producer half of the hook-event-capture path.
It reads the spool ``omnibase_infra.cli.receipt_mode`` writes on emit-daemon
failure, frames each file into the ``hook-event-capture`` gateway contract
shape, batches them, and submits each batch as one workflow via
``POST {base_url}/v1/workflows``.

Doctrine (operator-confirmed, OMN-16090): clients never speak Kafka. This
module talks ONLY to the gateway HTTPS surface — never a broker, never a
direct DB write.

Durability contract:
    - A spool file is only ever MOVED (to ``<spool>/shipped/``), never
      deleted. The spool is the only copy of these events anywhere.
    - HTTP 202 is NOT treated as delivery — the gateway's publish is
      fail-open. Files move only after ``GET /v1/workflows/{id}/status``
      reports a state in ``accept_status`` (default: ``completed``).
    - A batch submission that fails with a transient error (connection
      failure or 5xx) is retried with exponential backoff up to
      ``retry_attempts`` times. A 4xx is treated as poison (not retried) —
      identical redelivery would fail identically — and the batch's files
      stay in the spool for operator triage; the drain continues with the
      next batch rather than aborting the whole run.
    - Dedupe is at-least-once safe: the server's dedupe key is
      ``(tenant, event_sha)``, so a resubmitted batch after a crash between
      "confirmed" and "moved to shipped/" is a safe no-op server-side.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

# omnibase_infra.cli.receipt_mode.SPOOL_DIR_NAME — the single source of truth
# for the directory name the spool writer uses under ONEX_STATE_DIR. Imported
# rather than re-literaled so a rename on that side is a visible import error
# here, not a silent divergence.
from omnibase_infra.cli.receipt_mode import SPOOL_DIR_NAME
from pydantic import ValidationError

from omniclaude.hooks.models_spool_drain import (
    MAX_EVENTS_PER_BATCH,
    MAX_PAYLOAD_JSON_CHARS,
    JsonObject,
    ModelCapturedHookEvent,
    ModelDrainBatchResult,
    ModelDrainSkip,
    ModelDrainSummary,
    ModelHookEventCaptureBatch,
    ModelSpoolRecord,
    canonical_sha_input,
)

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "hook-event-capture"
DEFAULT_SOURCE = "local_macos_claude_hooks"
SHIPPED_DIR_NAME = "shipped"

TERMINAL_ACCEPT_STATUSES = ("completed",)
PUBLISHED_ACCEPT_STATUSES = ("published", "completed")

# Env vars the credential and base URL are resolved from BY NAME. No literal
# default value is ever substituted for a missing one — see resolve_api_key /
# resolve_api_base_url. (Rule 8, omni_home/CLAUDE.md: fail-fast on missing
# env, not silent fallback.)
ENV_API_BASE_URL = "ONEX_API_BASE_URL"
ENV_API_KEY = "ONEX_GATEWAY_API_KEY"  # pragma: allowlist secret; secret-ok: env var NAME constant, not a secret value
ENV_API_KEY_FILE = "ONEX_GATEWAY_API_KEY_FILE"  # pragma: allowlist secret; secret-ok: env var NAME constant, not a secret value
ENV_STATE_DIR = "ONEX_STATE_DIR"


class SpoolDrainError(RuntimeError):
    """Fatal, actionable drain error. Never carries the API key."""


class SpoolFrameError(SpoolDrainError):
    """One spool file could not be framed into a contract-shaped event."""


# ---------------------------------------------------------------------------
# Environment / credential resolution (fail-fast, name-based, no defaults)
# ---------------------------------------------------------------------------


def resolve_spool_dir(explicit: Path | None) -> Path:
    """Resolve the spool directory.

    An explicit path always wins (tests, operator override). Otherwise
    ``ONEX_STATE_DIR`` MUST be set — there is no default (Rule 8).
    """
    if explicit is not None:
        return explicit
    state_dir = os.environ.get(ENV_STATE_DIR)
    if not state_dir:
        raise SpoolDrainError(
            f"{ENV_STATE_DIR} is not set and no --spool-dir was given. "
            "Refusing to guess a spool location."
        )
    return Path(state_dir) / str(SPOOL_DIR_NAME)


def resolve_api_base_url(explicit: str | None) -> str:
    """Resolve the gateway base URL. Fail fast if neither source is set."""
    if explicit:
        return explicit
    value = os.environ.get(ENV_API_BASE_URL)
    if not value:
        raise SpoolDrainError(
            f"{ENV_API_BASE_URL} is not set and no --base-url was given. "
            "Refusing to fall back to a hardcoded gateway URL."
        )
    return value


def resolve_api_key(explicit: str | None = None) -> str:
    """Resolve the gateway x-api-key credential BY NAME, fail-fast.

    Resolution order: an explicit value (tests only) > ``ONEX_GATEWAY_API_KEY``
    (raw value) > ``ONEX_GATEWAY_API_KEY_FILE`` (path to a file containing the
    key). Neither set -> raise. Never substitutes a default credential path.
    """
    if explicit:
        return explicit
    inline = os.environ.get(ENV_API_KEY)
    if inline:
        return inline
    key_file = os.environ.get(ENV_API_KEY_FILE)
    if key_file:
        path = Path(key_file)
        if not path.exists():
            raise SpoolDrainError(
                f"{ENV_API_KEY_FILE} names a file that does not exist: {path}"
            )
        value = path.read_text(encoding="utf-8").strip()
        if not value:
            raise SpoolDrainError(
                f"{ENV_API_KEY_FILE} names an empty credential file: {path}"
            )
        return value
    raise SpoolDrainError(
        f"Neither {ENV_API_KEY} nor {ENV_API_KEY_FILE} is set. Refusing to "
        "submit without an explicit credential (no silent default)."
    )


def key_fingerprint(key: str) -> str:
    """Non-reversible short fingerprint, safe to log."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


# ---------------------------------------------------------------------------
# spool file -> contract event
# ---------------------------------------------------------------------------


def frame_spool_file(path: Path) -> ModelCapturedHookEvent:
    """Convert one spool file into a contract-shaped event.

    Raises SpoolFrameError naming the offending path on any framing failure.
    The caller is responsible for leaving the file in place on failure.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpoolFrameError(f"{path.name}: unreadable/unparseable: {exc}") from exc

    try:
        record = ModelSpoolRecord.model_validate(raw)
    except ValidationError as exc:
        raise SpoolFrameError(f"{path.name}: malformed spool record: {exc}") from exc

    payload = record.payload
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if len(payload_json) > MAX_PAYLOAD_JSON_CHARS:
        raise SpoolFrameError(
            f"{path.name}: payload_json is {len(payload_json)} chars, over the "
            f"{MAX_PAYLOAD_JSON_CHARS}-char contract ceiling"
        )

    # occurred_at: the producer's own timestamp when it has one, else the
    # spool time. Never "now" — these events are historical.
    occurred_at = (
        payload.get("emitted_at") or record.spooled_at_utc or payload.get("timestamp")
    )
    if not isinstance(occurred_at, str) or not (20 <= len(occurred_at) <= 40):
        raise SpoolFrameError(
            f"{path.name}: no usable occurred_at (got {occurred_at!r}); "
            "contract requires a 20-40 char timestamp"
        )

    event_sha = hashlib.sha256(
        canonical_sha_input(record.event_type, payload, occurred_at).encode("utf-8")
    ).hexdigest()

    fields: JsonObject = {
        "event_type": record.event_type,
        "event_sha": event_sha,
        "occurred_at": occurred_at,
        "payload_json": payload_json,
    }
    for src_key, dst_key in (
        ("event_id", "event_id"),
        ("correlation_id", "correlation_id"),
        ("run_id", "run_id"),
    ):
        value = payload.get(src_key)
        if isinstance(value, str) and value:
            fields[dst_key] = value[:64]
    if record.spooled_at_utc:
        fields["spooled_at"] = record.spooled_at_utc[:40]
    if record.spool_reason:
        fields["spool_reason"] = record.spool_reason[:512]

    try:
        return ModelCapturedHookEvent.model_validate(fields)
    except ValidationError as exc:
        raise SpoolFrameError(
            f"{path.name}: framed event fails contract shape: {exc}"
        ) from exc


def compute_batch_sha(events: list[ModelCapturedHookEvent]) -> str:
    """sha256 over the ordered event_sha list — matches the gateway contract."""
    return hashlib.sha256(
        "\n".join(e.event_sha for e in events).encode("utf-8")
    ).hexdigest()


def build_batch(
    events: list[ModelCapturedHookEvent], *, source: str
) -> ModelHookEventCaptureBatch:
    return ModelHookEventCaptureBatch(
        source=source, batch_sha=compute_batch_sha(events), events=events
    )


# ---------------------------------------------------------------------------
# Gateway HTTP client
# ---------------------------------------------------------------------------


class GatewayTransport:
    """Thin POST /v1/workflows + GET .../status client.

    Talks ONLY to the gateway HTTPS surface (doctrine: clients never speak
    Kafka). The api_key is held privately and is never logged or included in
    any raised exception message.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GatewayTransport:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self, *, has_body: bool) -> dict[str, str]:
        headers = {"x-api-key": self._api_key, "accept": "application/json"}
        if has_body:
            headers["content-type"] = "application/json"
        return headers

    def submit_batch(self, batch: ModelHookEventCaptureBatch) -> httpx.Response:
        return self._client.post(
            f"{self._base_url}/v1/workflows",
            json=batch.to_workflow_request(),
            headers=self._headers(has_body=True),
        )

    def get_status(self, workflow_id: str) -> httpx.Response:
        return self._client.get(
            f"{self._base_url}/v1/workflows/{workflow_id}/status",
            headers=self._headers(has_body=False),
        )


def poll_status(
    client: GatewayTransport,
    workflow_id: str,
    *,
    accept: tuple[str, ...],
    attempts: int,
    interval: float,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[bool, str]:
    """Poll GET .../status until it reports a state in ``accept`` or a
    terminal failure, up to ``attempts`` times.
    """
    last = "unknown"
    for i in range(attempts):
        try:
            resp = client.get_status(workflow_id)
        except httpx.HTTPError as exc:
            last = f"transport_error:{type(exc).__name__}"
        else:
            if resp.status_code == 200:
                body = resp.json()
                last = str(body.get("status", "unknown"))
                if last in accept:
                    return True, last
                if last in ("failed", "failed_publish"):
                    return False, last
            else:
                last = f"http_{resp.status_code}"
        if i < attempts - 1:
            sleep_fn(interval)
    return False, last


def _is_retryable_status(status_code: int) -> bool:
    return status_code >= 500


def submit_batch_with_retry(
    client: GatewayTransport,
    batch: ModelHookEventCaptureBatch,
    *,
    retry_attempts: int,
    backoff_base_seconds: float,
    max_backoff_seconds: float,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[int | None, JsonObject | str | None, str | None]:
    """Submit one batch, retrying transient failures with exponential backoff.

    Returns (http_status, body, error). A 4xx status is returned immediately
    (poison, not retried). A connection failure or 5xx is retried up to
    ``retry_attempts`` times; if every attempt fails, the LAST outcome is
    returned.
    """
    last_status: int | None = None
    last_body: JsonObject | str | None = None
    last_error: str | None = None

    for attempt in range(1, retry_attempts + 1):
        try:
            resp = client.submit_batch(batch)
        except httpx.HTTPError as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            last_status = None
            last_body = None
        else:
            last_status = resp.status_code
            last_error = None
            try:
                last_body = resp.json()
            except ValueError:
                last_body = resp.text
            if resp.status_code == 202:
                return last_status, last_body, None
            if not _is_retryable_status(resp.status_code):
                # Poison: identical redelivery fails identically.
                return last_status, last_body, None

        if attempt < retry_attempts:
            backoff = min(
                backoff_base_seconds * (2 ** (attempt - 1)), max_backoff_seconds
            )
            logger.warning(
                "batch submission attempt %d/%d failed (status=%s error=%s); retrying in %ss",
                attempt,
                retry_attempts,
                last_status,
                last_error,
                backoff,
            )
            sleep_fn(backoff)

    return last_status, last_body, last_error


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


@dataclass
class DrainConfig:
    spool_dir: Path
    base_url: str
    api_key: str
    source: str = DEFAULT_SOURCE
    batch_size: int = MAX_EVENTS_PER_BATCH
    limit: int = 0
    max_batches: int = 0
    dry_run: bool = False
    require_status: str = "completed"
    poll_attempts: int = 20
    poll_interval: float = 3.0
    timeout: float = 30.0
    retry_attempts: int = 3
    backoff_base_seconds: float = 1.0
    max_backoff_seconds: float = 60.0
    sleep_fn: Callable[[float], None] = field(default=time.sleep)


def _accept_statuses(require_status: str) -> tuple[str, ...]:
    return (
        TERMINAL_ACCEPT_STATUSES
        if require_status == "completed"
        else PUBLISHED_ACCEPT_STATUSES
    )


def drain_spool(
    config: DrainConfig, client: GatewayTransport | None = None
) -> ModelDrainSummary:
    """Drain the spool: frame, dedupe, batch, submit, confirm, move.

    Never raises on a per-file or per-batch failure — those are reported in
    the returned summary. Raises SpoolDrainError only for setup problems
    (missing spool dir).
    """
    spool_dir = config.spool_dir
    if not spool_dir.is_dir():
        raise SpoolDrainError(f"spool directory not found: {spool_dir}")
    shipped_dir = spool_dir / SHIPPED_DIR_NAME

    files = sorted(p for p in spool_dir.glob("*.json") if p.is_file())
    files_present = len(files)
    if config.limit:
        files = files[: config.limit]

    framed: list[tuple[Path, ModelCapturedHookEvent]] = []
    skipped: list[ModelDrainSkip] = []
    for path in files:
        try:
            framed.append((path, frame_spool_file(path)))
        except SpoolFrameError as exc:
            skipped.append(ModelDrainSkip(path=str(path), reason=str(exc)))

    by_sha: dict[str, list[Path]] = {}
    unique: list[ModelCapturedHookEvent] = []
    for path, event in framed:
        if event.event_sha in by_sha:
            by_sha[event.event_sha].append(path)
            continue
        by_sha[event.event_sha] = [path]
        unique.append(event)
    duplicate_files_collapsed = sum(len(v) - 1 for v in by_sha.values())

    batches: list[list[ModelCapturedHookEvent]] = [
        unique[i : i + config.batch_size]
        for i in range(0, len(unique), config.batch_size)
    ]
    if config.max_batches:
        batches = batches[: config.max_batches]

    if config.dry_run:
        results = [
            ModelDrainBatchResult(
                batch_sha=compute_batch_sha(b),
                event_count=len(b),
                confirmed=False,
                status="dry_run",
            )
            for b in batches
        ]
        return ModelDrainSummary(
            dry_run=True,
            files_present=files_present,
            files_considered=len(files),
            unique_events=len(unique),
            duplicate_files_collapsed=duplicate_files_collapsed,
            skipped=skipped,
            batches=results,
            events_shipped=0,
            remaining_in_spool=len(list(spool_dir.glob("*.json"))),
        )

    owns_client = client is None
    active_client = client or GatewayTransport(
        config.base_url, config.api_key, timeout=config.timeout
    )
    accept = _accept_statuses(config.require_status)
    results = []
    events_shipped = 0
    try:
        shipped_dir.mkdir(parents=True, exist_ok=True)
        for batch_events in batches:
            batch = build_batch(batch_events, source=config.source)
            status, body, error = submit_batch_with_retry(
                active_client,
                batch,
                retry_attempts=config.retry_attempts,
                backoff_base_seconds=config.backoff_base_seconds,
                max_backoff_seconds=config.max_backoff_seconds,
                sleep_fn=config.sleep_fn,
            )

            if status != 202:
                snippet = (
                    json.dumps(body)[:600]
                    if isinstance(body, dict)
                    else str(body)[:600]
                    if body
                    else error
                )
                results.append(
                    ModelDrainBatchResult(
                        batch_sha=batch.batch_sha,
                        event_count=len(batch_events),
                        confirmed=False,
                        status="submit_failed",
                        http_status=status,
                        error=snippet,
                    )
                )
                continue

            workflow_id = body.get("workflow_id") if isinstance(body, dict) else None
            if not workflow_id:
                results.append(
                    ModelDrainBatchResult(
                        batch_sha=batch.batch_sha,
                        event_count=len(batch_events),
                        confirmed=False,
                        status="no_workflow_id",
                        http_status=status,
                        error="202 accepted with no workflow_id in the ack",
                    )
                )
                continue

            confirmed, last_state = poll_status(
                active_client,
                str(workflow_id),
                accept=accept,
                attempts=config.poll_attempts,
                interval=config.poll_interval,
                sleep_fn=config.sleep_fn,
            )
            if not confirmed:
                results.append(
                    ModelDrainBatchResult(
                        batch_sha=batch.batch_sha,
                        event_count=len(batch_events),
                        confirmed=False,
                        status=f"unconfirmed:{last_state}",
                        http_status=status,
                        workflow_id=str(workflow_id),
                    )
                )
                continue

            moved = 0
            for event in batch_events:
                for path in by_sha[event.event_sha]:
                    target = shipped_dir / path.name
                    if target.exists():
                        target = (
                            shipped_dir
                            / f"{path.stem}.{event.event_sha[:8]}{path.suffix}"
                        )
                    shutil.move(str(path), str(target))
                    moved += 1
            events_shipped += len(batch_events)
            results.append(
                ModelDrainBatchResult(
                    batch_sha=batch.batch_sha,
                    event_count=len(batch_events),
                    confirmed=True,
                    status=last_state,
                    http_status=status,
                    workflow_id=str(workflow_id),
                    files_moved=moved,
                )
            )
    finally:
        if owns_client:
            active_client.close()

    return ModelDrainSummary(
        dry_run=False,
        files_present=files_present,
        files_considered=len(files),
        unique_events=len(unique),
        duplicate_files_collapsed=duplicate_files_collapsed,
        skipped=skipped,
        batches=results,
        events_shipped=events_shipped,
        remaining_in_spool=len(list(spool_dir.glob("*.json"))),
    )


__all__ = [
    "DEFAULT_SOURCE",
    "ENV_API_BASE_URL",
    "ENV_API_KEY",
    "ENV_API_KEY_FILE",
    "ENV_STATE_DIR",
    "SHIPPED_DIR_NAME",
    "WORKFLOW_TYPE",
    "DrainConfig",
    "GatewayTransport",
    "SpoolDrainError",
    "SpoolFrameError",
    "build_batch",
    "compute_batch_sha",
    "drain_spool",
    "frame_spool_file",
    "key_fingerprint",
    "poll_status",
    "resolve_api_base_url",
    "resolve_api_key",
    "resolve_spool_dir",
    "submit_batch_with_retry",
]
