#!/usr/bin/env python3
"""
LatencyGuard - Rolling P95 latency tracking and SLO-based circuit breaker.

Tracks rolling P95 latency of LLM routing calls and automatically disables
LLM routing when the SLO is breached. Also tracks LLM vs fuzzy-match
agreement rate and auto-disables LLM routing when agreement rate falls below
threshold over a 3-day rolling window.

All state is in-memory; no database required.

Design principles:
- Thread-safe: all mutable state protected by locks.
- Never raises: all methods degrade gracefully.
- No side-effects on import: safe to import from hooks.
- Monotonic clock (time.monotonic) for latency; wall-clock (time.time) for
  the 3-day agreement window because that window needs real-world duration.

Usage::

    guard = LatencyGuard.get_instance()

    # Record a latency sample
    guard.record_latency(42.0)   # milliseconds

    # Record an agreement observation
    guard.record_agreement(agreed=True)

    # Check before routing
    if guard.is_enabled():
        result = llm_route(prompt)
    else:
        result = fuzzy_route(prompt)
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SLO thresholds (from ticket spec / E0 SLO)
# ---------------------------------------------------------------------------

# P95 latency limit in milliseconds before circuit opens.
P95_SLO_MS: float = 80.0

# How long the circuit stays open after a breach (seconds).
COOLDOWN_SECONDS: float = 300.0  # 5 minutes

# Minimum number of latency samples required before the guard will trip.
# Prevents false positives on startup.
MIN_SAMPLES_FOR_TRIP: int = 10

# Rolling window size for latency samples (number of observations).
# Keeps the last N latency samples for P95 calculation.
LATENCY_WINDOW_SIZE: int = 100

# ---------------------------------------------------------------------------
# Agreement-rate thresholds
# ---------------------------------------------------------------------------

# Minimum agreement rate (0.0–1.0) over a rolling window.
AGREEMENT_RATE_THRESHOLD: float = 0.60

# Rolling window duration for agreement tracking (seconds).
AGREEMENT_WINDOW_SECONDS: float = 3 * 24 * 3600  # 3 days

# Minimum observations required before the agreement gate fires.
MIN_AGREEMENT_OBSERVATIONS: int = 20


# ---------------------------------------------------------------------------
# Internal data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyGuardStatus:
    """Snapshot of the guard's current state for observability.

    Attributes:
        enabled: Whether LLM routing is currently allowed.
        p95_ms: Current P95 latency in milliseconds (None if < MIN_SAMPLES_FOR_TRIP).
        sample_count: Number of latency samples in the rolling window.
        circuit_open: True when the latency circuit breaker is open.
        circuit_open_reason: Human-readable reason why the circuit is open.
        cooldown_remaining_s: Seconds until the circuit auto-resets (0 if closed).
        agreement_rate: Current agreement rate (None if < MIN_AGREEMENT_OBSERVATIONS).
        agreement_disabled: True when disabled due to low agreement rate.
        agreement_sample_count: Number of observations in the agreement window.
    """

    enabled: bool
    p95_ms: float | None
    sample_count: int
    circuit_open: bool
    circuit_open_reason: str
    cooldown_remaining_s: float
    agreement_rate: float | None
    agreement_disabled: bool
    agreement_sample_count: int


@dataclass
class _AgreementObservation:
    """Single agreement/disagreement observation with a wall-clock timestamp."""

    timestamp: float  # time.time()
    agreed: bool


# ---------------------------------------------------------------------------
# LatencyGuard
# ---------------------------------------------------------------------------


class LatencyGuard:
    """Thread-safe in-memory circuit breaker for LLM routing.

    Two independent disable conditions:
    1. **Latency circuit breaker**: P95 of recent routing calls exceeds
       P95_SLO_MS.  Opens for COOLDOWN_SECONDS, then auto-resets.
    2. **Agreement-rate gate**: LLM vs. fuzzy-match agreement rate falls
       below AGREEMENT_RATE_THRESHOLD over a AGREEMENT_WINDOW_SECONDS rolling
       window (requires MIN_AGREEMENT_OBSERVATIONS samples).

    Both conditions independently disable LLM routing. The guard is
    re-enabled only after the cooldown expires (circuit) or the agreement
    rate recovers (gate).

    Thread safety:
        All state is protected by ``_lock`` (a reentrant lock so that
        ``is_enabled()`` can call internal helpers without deadlocking).
    """

    # Singleton — one guard per process.
    _instance: LatencyGuard | None = None
    # NOTE: _instance_lock is intentionally created at class definition time (import
    # time), which is a minor exception to the "No side-effects on import" principle
    # stated in the module docstring.  The lock *must* exist before any instance is
    # created — lazy initialisation would itself require a lock to be safe, creating
    # a chicken-and-egg problem.  A threading.Lock() has no external I/O side-effects
    # and is safe to allocate at import time.
    _instance_lock: threading.Lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> LatencyGuard:
        """Return the singleton LatencyGuard, creating it on first call."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_instance(cls) -> None:
        """Reset singleton for testing.  Not for production use."""
        with cls._instance_lock:
            cls._instance = None

    def __init__(self) -> None:
        # Reentrant so internal helpers can call is_enabled() without deadlock.
        self._lock = threading.RLock()

        # --- Latency circuit breaker state ---
        # Rolling buffer of raw latency samples (milliseconds, float).
        self._latency_samples: deque[float] = deque(maxlen=LATENCY_WINDOW_SIZE)

        # When the circuit opened (monotonic seconds); None if closed.
        self._circuit_open_at: float | None = None

        # Human-readable reason for the current open circuit.
        self._circuit_open_reason: str = ""

        # --- Agreement-rate gate state ---
        # Timestamped observations of LLM vs. fuzzy agreement.
        self._agreement_obs: deque[_AgreementObservation] = deque()

        # Whether the agreement gate is currently disabling LLM routing.
        self._agreement_disabled: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_latency(self, latency_ms: float) -> None:
        """Record one LLM routing latency sample and update circuit state.

        Args:
            latency_ms: Measured latency in milliseconds (must be >= 0).
        """
        if not isinstance(latency_ms, (int, float)):
            logger.debug(
                "LatencyGuard.record_latency: ignoring non-numeric value %r", latency_ms
            )
            return
        if latency_ms < 0:
            logger.debug(
                "LatencyGuard.record_latency: ignoring negative value %.1f", latency_ms
            )
            return
        if math.isnan(latency_ms) or math.isinf(latency_ms):
            logger.debug(
                "LatencyGuard.record_latency: ignoring non-finite value %r", latency_ms
            )
            return

        with self._lock:
            self._latency_samples.append(latency_ms)
            self._maybe_trip_circuit()

    def record_agreement(self, *, agreed: bool) -> None:
        """Record whether LLM routing agreed with fuzzy matching on this call.

        The observation is timestamped with the current wall-clock time and
        kept for AGREEMENT_WINDOW_SECONDS.

        Args:
            agreed: True if the LLM selected the same agent as fuzzy matching.
        """
        with self._lock:
            now = time.time()
            self._agreement_obs.append(
                _AgreementObservation(timestamp=now, agreed=agreed)
            )
            self._prune_agreement_window(now)
            self._update_agreement_gate()

    def is_enabled(self) -> bool:
        """Return True if LLM routing is currently allowed.

        LLM routing is disabled when:
        - The latency circuit breaker is open (P95 breached within cooldown), OR
        - The agreement gate is active (agreement rate below threshold).

        NOTE: The two disable conditions are fully independent.  When the latency
        circuit auto-resets after its cooldown expires (see below), the agreement
        gate's ``_agreement_disabled`` flag is intentionally NOT cleared.  A latency
        recovery does not imply that agreement rate has recovered — those metrics
        measure different things and reset on different timescales.  The agreement
        gate persists until ``_update_agreement_gate()`` clears it when the rate
        rises back above AGREEMENT_RATE_THRESHOLD.

        Returns:
            True → caller may proceed with LLM routing.
            False → caller should fall through to fuzzy matching.
        """
        with self._lock:
            # Auto-reset circuit if cooldown has expired.
            if self._circuit_open_at is not None:
                elapsed = time.monotonic() - self._circuit_open_at
                if elapsed >= COOLDOWN_SECONDS:
                    logger.info(
                        "LatencyGuard: circuit breaker reset after %.0fs cooldown",
                        elapsed,
                    )
                    self._circuit_open_at = None
                    self._circuit_open_reason = ""
                    # Clear samples so we start fresh — prevents immediately
                    # re-tripping on the stale P95.
                    self._latency_samples.clear()
                    # _agreement_disabled is NOT reset here: agreement-gate state
                    # is independent and persists through latency circuit resets.

            if self._circuit_open_at is not None:
                return False

            if self._agreement_disabled:
                return False

            return True

    def get_status(self) -> LatencyGuardStatus:
        """Return a frozen snapshot of the guard's current state.

        Safe to call from any thread; never raises.

        Side effect: prunes the agreement observation window (removes entries
        older than AGREEMENT_WINDOW_SECONDS) to ensure the snapshot reflects
        only fresh observations.  This mutates _agreement_obs as a necessary
        part of producing an accurate agreement_rate value.
        """
        try:
            with self._lock:
                now_mono = time.monotonic()
                now_wall = time.time()

                # Latency stats
                p95 = (
                    self._compute_p95()
                    if len(self._latency_samples) >= MIN_SAMPLES_FOR_TRIP
                    else None
                )
                circuit_open = self._circuit_open_at is not None
                cooldown_remaining = 0.0
                if circuit_open and self._circuit_open_at is not None:
                    elapsed = now_mono - self._circuit_open_at
                    cooldown_remaining = max(0.0, COOLDOWN_SECONDS - elapsed)

                # Agreement stats
                self._prune_agreement_window(now_wall)
                agreement_rate = self._compute_agreement_rate()

                # Derive enabled from state already captured in this snapshot.
                # Do NOT call self.is_enabled() here: it performs the cooldown
                # auto-reset (clears samples, resets _circuit_open_at) as a
                # side-effect, which would mutate state beyond what this read
                # is supposed to do and would produce an inconsistent snapshot
                # where circuit_open=True but enabled=True for the same instant.
                # NOTE: does not perform cooldown auto-reset; use is_enabled()
                # for authoritative check.  This snapshot may lag is_enabled()
                # by up to COOLDOWN_SECONDS if the cooldown has just elapsed.
                enabled = (not circuit_open) and (not self._agreement_disabled)

                return LatencyGuardStatus(
                    enabled=enabled,
                    p95_ms=p95,
                    sample_count=len(self._latency_samples),
                    circuit_open=circuit_open,
                    circuit_open_reason=self._circuit_open_reason,
                    cooldown_remaining_s=cooldown_remaining,
                    agreement_rate=agreement_rate,
                    agreement_disabled=self._agreement_disabled,
                    agreement_sample_count=len(self._agreement_obs),
                )
        except Exception as exc:
            logger.debug("LatencyGuard.get_status failed (non-blocking): %s", exc)
            return LatencyGuardStatus(
                enabled=True,
                p95_ms=None,
                sample_count=0,
                circuit_open=False,
                circuit_open_reason="",
                cooldown_remaining_s=0.0,
                agreement_rate=None,
                agreement_disabled=False,
                agreement_sample_count=0,
            )

    def reset(self) -> None:
        """Fully reset all state.  Intended for testing and manual recovery.

        WARNING: Do NOT call this method in production code paths.  Calling
        ``reset()`` discards all accumulated circuit-breaker state — latency
        samples, the open-circuit timestamp, and agreement-rate observations —
        which can allow a previously-tripped circuit to re-enable LLM routing
        immediately, bypassing the SLO and agreement-rate protections entirely.
        This method exists only for unit tests and one-off manual recovery
        operations performed by an operator who fully understands the implications.
        """
        with self._lock:
            self._latency_samples.clear()
            self._circuit_open_at = None
            self._circuit_open_reason = ""
            self._agreement_obs.clear()
            self._agreement_disabled = False
        logger.info("LatencyGuard: state reset")

    # ------------------------------------------------------------------
    # Internal helpers (must be called with _lock held)
    # ------------------------------------------------------------------

    def _compute_p95(self) -> float:
        """Compute the 95th-percentile of the current sample window.

        Requires that ``_latency_samples`` is non-empty.
        """
        samples = sorted(self._latency_samples)
        n = len(samples)
        # Index of the 95th percentile using the nearest-rank method.
        # math.ceil(0.95 * n) gives the 1-based rank of the P95 value;
        # subtract 1 for the 0-based list index.
        # Example: n=10 → ceil(9.5)=10 → idx=9 (correct P95, the max).
        # The previous int(0.95*n)-1 formula gave idx=8 for n=10, which
        # is the 90th percentile — one slot too low.
        idx = math.ceil(0.95 * n) - 1
        return samples[idx]

    def _maybe_trip_circuit(self) -> None:
        """Trip the circuit breaker if the P95 SLO is breached.

        No-op when the circuit is already open or when there are fewer than
        MIN_SAMPLES_FOR_TRIP samples (prevents false positives on startup).
        """
        if self._circuit_open_at is not None:
            return  # Already open; don't reset the timer.

        if len(self._latency_samples) < MIN_SAMPLES_FOR_TRIP:
            return  # Not enough data yet.

        p95 = self._compute_p95()
        if p95 > P95_SLO_MS:
            self._circuit_open_at = time.monotonic()
            self._circuit_open_reason = (
                f"P95 latency {p95:.1f}ms exceeds SLO {P95_SLO_MS:.0f}ms"
            )
            logger.warning(
                "LatencyGuard: circuit breaker OPENED — %s; "
                "LLM routing disabled for %.0fs",
                self._circuit_open_reason,
                COOLDOWN_SECONDS,
            )

    def _prune_agreement_window(self, now: float) -> None:
        """Remove observations outside the rolling window."""
        cutoff = now - AGREEMENT_WINDOW_SECONDS
        # Strict less-than: observations with timestamp == cutoff are retained
        # (i.e. "older than" is exclusive of the boundary).
        while self._agreement_obs and self._agreement_obs[0].timestamp < cutoff:
            self._agreement_obs.popleft()

    def _compute_agreement_rate(self) -> float | None:
        """Return agreement rate [0.0, 1.0] or None if not enough data."""
        n = len(self._agreement_obs)
        if n < MIN_AGREEMENT_OBSERVATIONS:
            return None
        agreed = sum(1 for obs in self._agreement_obs if obs.agreed)
        return agreed / n

    def _update_agreement_gate(self) -> None:
        """Enable or disable the agreement gate based on current rate."""
        rate = self._compute_agreement_rate()
        if rate is None:
            # Not enough data — do not change the gate state to avoid
            # spurious disables during the initial warm-up period.
            return

        if rate < AGREEMENT_RATE_THRESHOLD and not self._agreement_disabled:
            self._agreement_disabled = True
            logger.warning(
                "LatencyGuard: agreement gate DISABLED — "
                "agreement rate %.1f%% < threshold %.0f%% "
                "over %d observations (3-day window); "
                "LLM routing auto-disabled (USE_LLM_ROUTING effectively false)",
                rate * 100,
                AGREEMENT_RATE_THRESHOLD * 100,
                len(self._agreement_obs),
            )
        elif rate >= AGREEMENT_RATE_THRESHOLD and self._agreement_disabled:
            self._agreement_disabled = False
            logger.info(
                "LatencyGuard: agreement gate RE-ENABLED — "
                "rate %.1f%% recovered above threshold %.0f%%",
                rate * 100,
                AGREEMENT_RATE_THRESHOLD * 100,
            )
