#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""In-memory pattern projection cache for context injection (OMN-2425).

Maintains a thread-safe in-memory cache of patterns consumed from the
`onex.evt.omniintelligence.pattern-projection.v1` Kafka topic.

The cache is populated by a background daemon thread that subscribes to the
projection topic. The context injection handler reads from this cache first
before falling back to the HTTP API.

Architecture:
    - Module-level singleton: persists across function calls in the same process
    - Background consumer thread: daemon (does not block process exit)
    - Thread-safe reads/writes via threading.RLock
    - Staleness threshold: configurable via PATTERN_CACHE_STALE_SECONDS (default 600s)
    - Graceful degradation: if Kafka unavailable, consumer silently skips

Kafka Topic:
    onex.evt.omniintelligence.pattern-projection.v1 (no env prefix per OMN-1972)

Part of OMN-2425: consume pattern projection and cache for context injection.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Projection topic (canonical wire name per OMN-1972 — no env prefix)
_PROJECTION_TOPIC = "onex.evt.omniintelligence.pattern-projection.v1"

# Default staleness threshold in seconds (10 minutes)
_DEFAULT_STALE_SECONDS = 600

# Retry configuration for the background projection consumer.
# _MAX_CONSUMER_RETRIES=None keeps current unlimited behaviour — the consumer
# will retry indefinitely as long as the process is alive (daemon thread).
# _CONSUMER_RETRY_SLEEP_S is the flat sleep between retry attempts; there is
# intentionally no exponential backoff because the consumer is a long-lived
# daemon and a flat 30-second pause is acceptable for infrastructure recovery.
_MAX_CONSUMER_RETRIES: int | None = None
_CONSUMER_RETRY_SLEEP_S: int = 30


def _get_stale_threshold() -> int:
    """Read PATTERN_CACHE_STALE_SECONDS from env, returning default on parse failure.

    The environment variable is intentionally re-read on every call so that
    operators can adjust the staleness threshold at runtime without restarting
    the process.  If dynamic reconfiguration is not needed, this value could
    instead be cached at module import time (or at PatternProjectionCache
    construction) for a minor performance improvement.
    """
    raw = os.environ.get("PATTERN_CACHE_STALE_SECONDS", "")
    if not raw:
        return _DEFAULT_STALE_SECONDS
    try:
        val = int(raw)
        if val > 0:
            return val
        logger.warning(
            "PATTERN_CACHE_STALE_SECONDS must be positive, got %r; using default %d",
            raw,
            _DEFAULT_STALE_SECONDS,
        )
        return _DEFAULT_STALE_SECONDS
    except ValueError:
        logger.warning(
            "Invalid PATTERN_CACHE_STALE_SECONDS=%r; using default %d",
            raw,
            _DEFAULT_STALE_SECONDS,
        )
        return _DEFAULT_STALE_SECONDS


class PatternProjectionCache:
    """Thread-safe in-memory cache of patterns keyed by domain.

    Populated by a background Kafka consumer subscribed to the pattern
    projection topic. Read by the context injection handler before falling
    back to the HTTP API.

    Attributes:
        _lock: Reentrant lock protecting all mutable state.
        _data: Mapping of domain → list of pattern dicts.
        _last_updated_at: Monotonic clock value (time.monotonic()) of the most recent update, or None.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # domain → list of raw pattern dicts (as received from the projection event)
        self._data: dict[str, list[dict[str, Any]]] = {}
        self._last_updated_at: float | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, domain: str | None) -> list[dict[str, Any]]:
        """Return cached patterns for the given domain.

        Args:
            domain: Domain key (e.g. "general"). If None or empty string,
                returns patterns from the "general" domain.

        Returns:
            List of pattern dicts (never None). Returns empty list if the
            domain is not in the cache.
        """
        key = domain or "general"
        with self._lock:
            return list(self._data.get(key, []))

    def update(self, domain: str, patterns: list[dict[str, Any]]) -> None:
        """Replace the cached patterns for a domain.

        Also updates `last_updated_at` to the current monotonic time, which
        resets the staleness clock.

        Args:
            domain: Domain key.
            patterns: List of pattern dicts to cache.
        """
        with self._lock:
            self._data[domain] = list(patterns)
            self._last_updated_at = time.monotonic()
        logger.debug("pattern_cache updated domain=%r count=%d", domain, len(patterns))

    def is_warm(self) -> bool:
        """Return True if the cache has been populated at least once."""
        with self._lock:
            return self._last_updated_at is not None

    def is_stale(self) -> bool:
        """Return True if the cache has not been updated within the stale threshold.

        Always returns True when the cache is cold (not yet populated).

        Note: ``_get_stale_threshold()`` is intentionally re-read on every call
        so the threshold can be changed at runtime via the environment variable
        without restarting the process.
        """
        with self._lock:
            if self._last_updated_at is None:
                return True
            elapsed = time.monotonic() - self._last_updated_at
            return elapsed > _get_stale_threshold()

    def clear(self) -> None:
        """Reset the cache to empty (cold) state."""
        with self._lock:
            self._data.clear()
            self._last_updated_at = None
        logger.debug("pattern_cache cleared")


# =============================================================================
# Module-level singleton
# =============================================================================

_cache: PatternProjectionCache | None = None
_cache_lock = threading.Lock()


def get_pattern_cache() -> PatternProjectionCache:
    """Return the module-level PatternProjectionCache singleton.

    Initializes the cache on first call (thread-safe). Subsequent calls
    return the same instance.
    """
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                _cache = PatternProjectionCache()
    return _cache


# =============================================================================
# Background Kafka consumer
# =============================================================================

# Guards against double-starting the consumer thread
_consumer_started = False
_consumer_lock = threading.Lock()


def _parse_projection_event(
    raw: str | bytes,
) -> tuple[str, list[dict[str, Any]]] | None:
    """Parse a projection event payload.

    Returns (domain, patterns) on success, or None if the payload cannot be
    parsed or is missing required fields.

    Expected shape (consume defensively):
        {
          "patterns": [
            {
              "id": "uuid",
              "pattern_signature": "...",
              "confidence": 0.85,
              "domain_id": "general",
              "quality_score": 0.9,
              "status": "validated"
            }
          ],
          "domain": "general",
          "snapshot_at": "2026-02-20T10:00:00Z"
        }
    """
    try:
        if isinstance(raw, bytes):
            text = raw.decode("utf-8")
        else:
            text = raw
        payload = json.loads(text)
    except Exception as exc:
        logger.warning("pattern_cache: failed to decode projection event: %s", exc)
        return None

    if not isinstance(payload, dict):
        logger.warning(
            "pattern_cache: projection event is not a JSON object; got %s",
            type(payload).__name__,
        )
        return None

    raw_patterns = payload.get("patterns")
    if not isinstance(raw_patterns, list):
        logger.warning(
            "pattern_cache: projection event missing 'patterns' list; got %s",
            type(raw_patterns).__name__,
        )
        return None

    # Domain: use the top-level "domain" field if present; fall back to "general"
    domain = payload.get("domain")
    if not isinstance(domain, str) or not domain.strip():
        domain = "general"
    domain = domain.strip()

    # Validate individual pattern entries — include only those with required fields
    valid: list[dict[str, Any]] = []
    for entry in raw_patterns:
        if not isinstance(entry, dict):
            logger.warning(
                "pattern_cache: skipping non-dict pattern entry: %s",
                type(entry).__name__,
            )
            continue
        pattern_id = entry.get("id")
        signature = entry.get("pattern_signature")
        confidence = entry.get("confidence")
        if not pattern_id or not signature or confidence is None:
            logger.warning(
                "pattern_cache: skipping pattern missing required fields "
                "(id=%r, pattern_signature=%r, confidence=%r)",
                pattern_id,
                signature,
                confidence,
            )
            continue
        valid.append(entry)

    return domain, valid


def _run_projection_consumer(kafka_bootstrap_servers: str) -> None:
    """Target for the background consumer daemon thread.

    Subscribes to the pattern projection topic and keeps the cache updated.
    Silently handles Kafka unavailability — never raises.

    Args:
        kafka_bootstrap_servers: Kafka bootstrap server address(es).
    """
    try:
        # kafka-python is an optional dependency — import lazily so the module
        # remains importable even when Kafka is not installed.
        from kafka import KafkaConsumer
        from kafka.errors import KafkaError
    except ImportError:
        logger.warning(
            "pattern_cache: kafka-python not installed; projection consumer disabled"
        )
        return

    cache = get_pattern_cache()

    logger.info(
        "pattern_cache: starting projection consumer topic=%r bootstrap=%r",
        _PROJECTION_TOPIC,
        kafka_bootstrap_servers,
    )

    retry_count = 0
    while True:
        # Reset consumer reference at the top of every iteration so the except
        # handlers below never see a stale reference from a previous iteration
        # that has already been closed (fixes potential double-close race).
        consumer = None
        try:
            consumer = KafkaConsumer(
                _PROJECTION_TOPIC,
                bootstrap_servers=kafka_bootstrap_servers,
                auto_offset_reset="latest",
                enable_auto_commit=True,
                group_id=f"omniclaude-pattern-cache-{os.getpid()}",
                value_deserializer=lambda v: v,  # raw bytes; we decode ourselves
                consumer_timeout_ms=5000,  # poll loop timeout
            )

            logger.info("pattern_cache: projection consumer connected")

            for message in consumer:
                try:
                    result = _parse_projection_event(message.value)
                    if result is not None:
                        domain, patterns = result
                        cache.update(domain, patterns)
                        logger.info(
                            "pattern_cache: received projection domain=%r count=%d",
                            domain,
                            len(patterns),
                        )
                except Exception as exc:
                    logger.warning(
                        "pattern_cache: error processing projection message: %s", exc
                    )

        except KafkaError as exc:
            retry_count += 1
            logger.warning(
                "pattern_cache: Kafka error in projection consumer: %s; "
                "retrying in %ds (retry_count=%d)",
                exc,
                _CONSUMER_RETRY_SLEEP_S,
                retry_count,
            )
            if consumer is not None:
                try:
                    consumer.close()
                except Exception:
                    pass
            if (
                _MAX_CONSUMER_RETRIES is not None
                and retry_count > _MAX_CONSUMER_RETRIES
            ):
                logger.error(
                    "pattern_cache: projection consumer exceeded max retries "
                    "(%d); giving up",
                    _MAX_CONSUMER_RETRIES,
                )
                return
            time.sleep(_CONSUMER_RETRY_SLEEP_S)
        except Exception as exc:
            retry_count += 1
            logger.warning(
                "pattern_cache: unexpected error in projection consumer: %s; "
                "retrying in %ds (retry_count=%d)",
                exc,
                _CONSUMER_RETRY_SLEEP_S,
                retry_count,
            )
            if consumer is not None:
                try:
                    consumer.close()
                except Exception:
                    pass
            if (
                _MAX_CONSUMER_RETRIES is not None
                and retry_count > _MAX_CONSUMER_RETRIES
            ):
                logger.error(
                    "pattern_cache: projection consumer exceeded max retries "
                    "(%d); giving up",
                    _MAX_CONSUMER_RETRIES,
                )
                return
            time.sleep(_CONSUMER_RETRY_SLEEP_S)


def _start_projection_consumer(kafka_bootstrap_servers: str) -> None:
    """Start the background projection consumer thread.

    The thread is a daemon so it will not block process exit.

    Private: use start_projection_consumer_if_configured() as the public entry
    point. Calling this function directly bypasses the _consumer_started guard
    and can cause duplicate consumer threads competing on the singleton cache.

    Args:
        kafka_bootstrap_servers: Kafka bootstrap server address(es), e.g.
            "192.168.86.200:29092".
    """
    thread = threading.Thread(
        target=_run_projection_consumer,
        args=(kafka_bootstrap_servers,),
        name="pattern-projection-consumer",
        daemon=True,
    )
    thread.start()
    logger.debug(
        "pattern_cache: projection consumer thread started bootstrap=%r",
        kafka_bootstrap_servers,
    )


def start_projection_consumer_if_configured() -> None:
    """Start the projection consumer if Kafka is configured and not already running.

    Reads KAFKA_BOOTSTRAP_SERVERS from the environment. If not set, returns
    immediately (no-op). Guards against double-starting with a module-level flag.

    This function is safe to call multiple times — only the first call starts
    the consumer thread.
    """
    global _consumer_started

    if _consumer_started:
        return

    with _consumer_lock:
        # Re-check inside the lock (double-checked locking pattern).
        # We use a separate local variable here so mypy does not consider the
        # inner branch unreachable (it cannot infer that another thread may
        # have mutated _consumer_started between the outer and inner checks).
        already_started: bool = _consumer_started
        if not already_started:
            bootstrap = os.environ.get("KAFKA_BOOTSTRAP_SERVERS", "").strip()
            if not bootstrap:
                logger.debug(
                    "pattern_cache: KAFKA_BOOTSTRAP_SERVERS not set; "
                    "projection consumer disabled"
                )
                # Do NOT set _consumer_started here: if Kafka is configured
                # later at runtime a subsequent call must still be able to
                # start the consumer.
                return

            _start_projection_consumer(bootstrap)
            _consumer_started = True
