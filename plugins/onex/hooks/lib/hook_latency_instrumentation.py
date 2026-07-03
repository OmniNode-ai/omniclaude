# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Per-hook wall-clock latency instrumentation (OMN-13847).

Wraps a hook's execution with a monotonic start/stop timer and emits a
structured ``hook.executed`` telemetry event via the existing emit-daemon
socket path (:func:`emit_client_wrapper.emit_event`). The event carries::

    hook_name, event, duration_ms, blocked, correlation_id, session_id

so hook usefulness can be measured (p50/p95 latency per hook) with data instead
of guessed. The OMN-13244 measurement baseline had no way to measure per-hook
wall-clock latency (gap identified in the hook-usefulness analysis); this module
closes that gap on the emit side.

Design constraints:
    * **Inert when hooks are disabled.** Nothing runs at import time and no
      timer is scheduled. Duration is measured *only* while a hook body runs
      inside :func:`instrument_hook` / :func:`instrumented_hook`. A repo with an
      empty hook baseline emits nothing -- this module never re-enables a hook,
      it only measures hooks that actually run.
    * **Non-blocking / fail-open.** Emission uses the same fire-and-forget
      contract as every other hook emitter: it never raises and never blocks the
      hook, mirroring the ``DEFAULT_TIMEOUT_MS`` behaviour in
      ``emit_client_wrapper``.
    * **Canonical event bus only.** No bespoke REST/HTTP. The event flows through
      the emit daemon exactly like ``skill.started`` / ``hook.health.error``.

Fast-follow (tracked on OMN-13847): register ``hook.executed`` in the daemon
topic registry (omnimarket ``node_emit_daemon/registries/topics.yaml``) together
with the mirrored omniclaude ``EVENT_REGISTRY`` / ``TopicBase`` surfaces as one
coordinated cross-repo change -- the ``event_registry_drift`` gate requires both
sides to move together -- then land the ``hook_executions`` time-series
projection (migration + consumer, mirroring ``skill_executions``) keyed for
p50/p95 latency per hook, plus the ``/api/hook-health/summary`` endpoint the
``hook_health_alert`` skill already expects. Until that lands the emit is a
graceful no-op (an unregistered event type is rejected client-side by
``SUPPORTED_EVENT_TYPES``), so this emit-side primitive is safe to ship ahead of
the projection.
"""

from __future__ import annotations

import functools
import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar

logger = logging.getLogger(__name__)

# Semantic event type for per-hook execution telemetry. Registered in
# SUPPORTED_EVENT_TYPES + EVENT_REGISTRY + the daemon topic registry by the
# OMN-13847 fast-follow (see module docstring); emit is a graceful no-op until.
HOOK_EXECUTION_EVENT_TYPE = "hook.executed"


# ---------------------------------------------------------------------------
# Optional emit_event import -- graceful degradation when the daemon client or
# the plugin venv is unavailable. Mirrors the import pattern used by the other
# hooks/lib emitters (e.g. extraction_event_emitter).
# ---------------------------------------------------------------------------
try:  # deployed plugin: lib dir is on sys.path directly
    from emit_client_wrapper import emit_event as _emit_event
except ImportError:
    try:  # source tree / test invocation
        from plugins.onex.hooks.lib.emit_client_wrapper import (
            emit_event as _emit_event,
        )
    except ImportError:  # pragma: no cover - emit path genuinely unavailable
        _emit_event = None


T = TypeVar("T")


def build_hook_execution_payload(
    *,
    hook_name: str,
    event: str,
    duration_ms: int,
    blocked: bool,
    correlation_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, object]:
    """Build the ``hook.executed`` event payload.

    ``correlation_id`` defaults to a fresh UUID when not supplied. ``session_id``
    is included only when explicitly passed; when omitted, ``emit_event`` injects
    the canonical session id from ``CLAUDE_CODE_SESSION_ID`` at emit time, so the
    field still lands on the wire without this module reading session env vars.

    Args:
        hook_name: Stable hook identifier (e.g. ``"bash_guard"``).
        event: Hook lifecycle event (``"PreToolUse"``, ``"PostToolUse"``, ...).
        duration_ms: Measured wall-clock execution time in milliseconds.
        blocked: Whether the hook blocked/denied the operation.
        correlation_id: Optional correlation id; generated if omitted.
        session_id: Optional session id; injected by emit_event from env if omitted.

    Returns:
        A JSON-serialisable payload dict.
    """
    payload: dict[str, object] = {
        "hook_name": hook_name,
        "event": event,
        "duration_ms": int(duration_ms),
        "blocked": bool(blocked),
        "correlation_id": correlation_id or str(uuid.uuid4()),
    }
    if session_id:
        payload["session_id"] = session_id
    return payload


def emit_hook_execution(
    *,
    hook_name: str,
    event: str,
    duration_ms: int,
    blocked: bool = False,
    correlation_id: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Emit a ``hook.executed`` telemetry event. Never raises; returns success.

    Returns ``True`` if the event was queued by the daemon, ``False`` otherwise
    (daemon unavailable, event type not yet registered, or emission error).
    """
    if _emit_event is None:
        logger.debug("emit_event unavailable; %s dropped", HOOK_EXECUTION_EVENT_TYPE)
        return False
    try:
        payload = build_hook_execution_payload(
            hook_name=hook_name,
            event=event,
            duration_ms=duration_ms,
            blocked=blocked,
            correlation_id=correlation_id,
            session_id=session_id,
        )
        return bool(_emit_event(HOOK_EXECUTION_EVENT_TYPE, payload))
    except Exception as exc:  # noqa: BLE001 - telemetry must never break a hook
        logger.debug("hook.executed emission failed: %r", exc)
        return False


class HookExecutionHandle:
    """Mutable handle yielded by :func:`instrument_hook`.

    The hook body sets ``blocked = True`` when it denies/blocks the operation.
    ``duration_ms`` is populated after the context manager exits (handy in tests
    and for callers that want the measured value without re-timing).
    """

    __slots__ = ("blocked", "duration_ms")

    def __init__(self) -> None:
        self.blocked: bool = False
        self.duration_ms: int | None = None


@contextmanager
def instrument_hook(
    hook_name: str,
    event: str,
    *,
    correlation_id: str | None = None,
    session_id: str | None = None,
    emit: bool = True,
) -> Iterator[HookExecutionHandle]:
    """Time a hook body and emit a ``hook.executed`` event on exit.

    Usage::

        with instrument_hook("bash_guard", "PreToolUse") as h:
            if should_block(command):
                h.blocked = True
                sys.exit(2)

    The timer uses :func:`time.monotonic` and the event is emitted from a
    ``finally`` block so the duration is recorded even when the hook body raises
    or calls :func:`sys.exit`. Emission is fire-and-forget and never propagates
    an exception into the hook; the original exception (if any) still surfaces.

    Args:
        hook_name: Stable hook identifier.
        event: Hook lifecycle event name.
        correlation_id: Optional correlation id (generated if omitted).
        session_id: Optional session id (resolved from env if omitted).
        emit: When ``False``, timing is still recorded on the handle but no event
            is emitted (useful for tests / dry runs).

    Yields:
        A :class:`HookExecutionHandle` the hook body can flag as ``blocked``.
    """
    handle = HookExecutionHandle()
    start = time.monotonic()
    try:
        yield handle
    finally:
        duration_ms = round((time.monotonic() - start) * 1000)
        handle.duration_ms = duration_ms
        if emit:
            emit_hook_execution(
                hook_name=hook_name,
                event=event,
                duration_ms=duration_ms,
                blocked=handle.blocked,
                correlation_id=correlation_id,
                session_id=session_id,
            )


def instrumented_hook(
    hook_name: str,
    event: str,
    *,
    correlation_id: str | None = None,
    session_id: str | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator form of :func:`instrument_hook` for a hook entrypoint callable.

    The wrapped callable is timed end-to-end and a ``hook.executed`` event is
    emitted when it returns or raises. The decorator cannot flag ``blocked`` --
    use the :func:`instrument_hook` context manager when the hook needs to record
    a block decision.
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> T:
            with instrument_hook(
                hook_name,
                event,
                correlation_id=correlation_id,
                session_id=session_id,
            ):
                return func(*args, **kwargs)

        return wrapper

    return decorator


__all__ = [
    "HOOK_EXECUTION_EVENT_TYPE",
    "HookExecutionHandle",
    "build_hook_execution_payload",
    "emit_hook_execution",
    "instrument_hook",
    "instrumented_hook",
]
