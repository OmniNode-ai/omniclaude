# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for latency_guard.py.

Tests cover:
- Rolling P95 latency tracking
- Auto-disable on SLO breach (P95 > 80ms)
- Cooldown auto-reset after 5 minutes
- Agreement rate tracking with auto-disable (< 60%)
- Agreement rate recovery (gate re-enables)
- Min-sample guards (no false positives on startup)
- Thread safety (smoke test via concurrent writes)
- get_status() snapshot accuracy
- reset() clears all state
- Singleton pattern
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Generator
from pathlib import Path

import pytest

# Plugin lib path is set by tests/conftest.py; explicit insert here as
# belt-and-suspenders for direct test invocation.
_LIB_PATH = str(
    Path(__file__).parent.parent.parent.parent.parent
    / "plugins"
    / "onex"
    / "hooks"
    / "lib"
)
if _LIB_PATH not in sys.path:
    sys.path.insert(0, _LIB_PATH)

from latency_guard import (
    AGREEMENT_RATE_THRESHOLD,
    AGREEMENT_WINDOW_SECONDS,
    COOLDOWN_SECONDS,
    MIN_AGREEMENT_OBSERVATIONS,
    MIN_SAMPLES_FOR_TRIP,
    P95_SLO_MS,
    LatencyGuard,
    LatencyGuardStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fresh_guard() -> LatencyGuard:
    """Return a new LatencyGuard instance with no shared state."""
    LatencyGuard._reset_instance()
    guard = LatencyGuard.get_instance()
    return guard


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    @pytest.mark.unit
    def test_get_instance_returns_same_object(self) -> None:
        LatencyGuard._reset_instance()
        g1 = LatencyGuard.get_instance()
        g2 = LatencyGuard.get_instance()
        assert g1 is g2

    @pytest.mark.unit
    def test_reset_instance_creates_new(self) -> None:
        LatencyGuard._reset_instance()
        g1 = LatencyGuard.get_instance()
        LatencyGuard._reset_instance()
        g2 = LatencyGuard.get_instance()
        assert g1 is not g2


# ---------------------------------------------------------------------------
# Latency P95 tracking
# ---------------------------------------------------------------------------


class TestLatencyTracking:
    @pytest.fixture(autouse=True)
    def fresh(self) -> Generator[LatencyGuard, None, None]:
        # This fixture is used for its side-effect of resetting the singleton
        # before each test.  The return value is intentionally unused by
        # individual tests — they call LatencyGuard.get_instance() directly so
        # the instance is visible without fixture injection.
        # Reset before AND after each test for clean isolation: the pre-test
        # reset ensures a clean state even if a previous test leaked state;
        # the post-test reset ensures subsequent tests start clean regardless
        # of what this test does.
        _make_fresh_guard()
        yield LatencyGuard.get_instance()
        LatencyGuard._reset_instance()

    @pytest.mark.unit
    def test_enabled_by_default(self) -> None:
        guard = LatencyGuard.get_instance()
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_no_trip_below_min_samples(self) -> None:
        """Circuit must not trip before MIN_SAMPLES_FOR_TRIP samples."""
        guard = LatencyGuard.get_instance()
        # Add samples that all breach the SLO — but count < MIN_SAMPLES_FOR_TRIP
        for _ in range(MIN_SAMPLES_FOR_TRIP - 1):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert guard.is_enabled(), (
            "Should not trip with fewer than MIN_SAMPLES_FOR_TRIP samples"
        )

    @pytest.mark.unit
    def test_trips_when_p95_exceeds_slo(self) -> None:
        """Circuit opens when P95 > P95_SLO_MS after MIN_SAMPLES_FOR_TRIP samples."""
        guard = LatencyGuard.get_instance()
        # All samples breach the SLO => P95 breaches too.
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert not guard.is_enabled()

    @pytest.mark.unit
    def test_does_not_trip_when_p95_at_slo(self) -> None:
        """Circuit must NOT open when P95 exactly equals P95_SLO_MS (strict >)."""
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS)
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_does_not_trip_when_p95_below_slo(self) -> None:
        """Mix of fast and slow, but P95 stays under SLO."""
        guard = LatencyGuard.get_instance()
        # 95 fast samples + 5 slow (P95 = fast sample)
        for _ in range(95):
            guard.record_latency(10.0)
        for _ in range(5):
            guard.record_latency(P95_SLO_MS + 50.0)
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_trips_when_majority_samples_are_slow(self) -> None:
        """P95 breaches SLO when the 95th-percentile sample is slow."""
        guard = LatencyGuard.get_instance()
        # Use MIN_SAMPLES_FOR_TRIP samples so we stay at exactly that threshold.
        # The implementation uses the nearest-rank method:
        #   idx = max(0, math.ceil(0.95 * n) - 1)
        # For MIN_SAMPLES_FOR_TRIP=10: idx = max(0, ceil(9.5) - 1) = max(0, 10-1) = 9
        # → the last element of the sorted array.
        # By making all n samples breach the SLO, every index (including 9) is
        # above the SLO, so P95 > SLO is guaranteed regardless of n.
        n = MIN_SAMPLES_FOR_TRIP
        for _ in range(n):
            guard.record_latency(P95_SLO_MS + 10.0)
        assert not guard.is_enabled()

    @pytest.mark.unit
    def test_negative_latency_ignored(self) -> None:
        """Negative latency values must be ignored without raising."""
        guard = LatencyGuard.get_instance()
        guard.record_latency(-10.0)
        assert guard.is_enabled()
        status = guard.get_status()
        assert status.sample_count == 0

    @pytest.mark.unit
    def test_zero_latency_accepted(self) -> None:
        """Zero latency is a valid (very fast) sample."""
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(0.0)
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_circuit_auto_resets_after_cooldown(self) -> None:
        """Circuit resets automatically once the cooldown has elapsed."""
        guard = LatencyGuard.get_instance()
        # Trip the circuit
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert not guard.is_enabled()

        # Fake the circuit-open time to be in the past
        with guard._lock:
            guard._circuit_open_at = time.monotonic() - (COOLDOWN_SECONDS + 1.0)

        assert guard.is_enabled(), "Circuit should have auto-reset after cooldown"

    @pytest.mark.unit
    def test_samples_cleared_on_auto_reset(self) -> None:
        """Sample buffer is wiped on auto-reset to avoid immediate re-trip."""
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        with guard._lock:
            guard._circuit_open_at = time.monotonic() - (COOLDOWN_SECONDS + 1.0)

        guard.is_enabled()  # triggers auto-reset
        status = guard.get_status()
        assert status.sample_count == 0

    @pytest.mark.unit
    def test_circuit_still_open_within_cooldown(self) -> None:
        """Circuit remains open if cooldown has not elapsed."""
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)

        with guard._lock:
            # Only 1 second into cooldown
            guard._circuit_open_at = time.monotonic() - 1.0

        assert not guard.is_enabled()


# ---------------------------------------------------------------------------
# Agreement rate tracking
# ---------------------------------------------------------------------------


class TestAgreementRateTracking:
    @pytest.fixture(autouse=True)
    def fresh(self) -> LatencyGuard:
        # Used for its side-effect of resetting singleton state before each test.
        # The return value is intentionally unused by individual tests.
        return _make_fresh_guard()

    @pytest.mark.unit
    def test_enabled_before_min_observations(self) -> None:
        """Agreement gate must not fire before MIN_AGREEMENT_OBSERVATIONS."""
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_AGREEMENT_OBSERVATIONS - 1):
            guard.record_agreement(agreed=False)  # all disagreements
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_disables_when_agreement_rate_below_threshold(self) -> None:
        """Auto-disable when agreement rate falls below AGREEMENT_RATE_THRESHOLD."""
        guard = LatencyGuard.get_instance()
        # Record enough disagreements to trigger the gate
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        assert not guard.is_enabled()

    @pytest.mark.unit
    def test_stays_enabled_at_threshold(self) -> None:
        """Gate must NOT fire when rate equals threshold (strict <)."""
        guard = LatencyGuard.get_instance()
        n = MIN_AGREEMENT_OBSERVATIONS
        # Exactly AGREEMENT_RATE_THRESHOLD agreement
        agree_count = int(n * AGREEMENT_RATE_THRESHOLD)
        disagree_count = n - agree_count
        for _ in range(agree_count):
            guard.record_agreement(agreed=True)
        for _ in range(disagree_count):
            guard.record_agreement(agreed=False)
        # Rate == threshold: should still be enabled (strict < comparison)
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_gate_re_enables_when_rate_recovers(self) -> None:
        """Agreement gate re-enables after rate recovers above threshold."""
        guard = LatencyGuard.get_instance()
        # Disable the gate
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        assert not guard.is_enabled()

        # Add enough agreements to push rate above threshold.
        # Old disagreements are still in the window, so we add many agreements.
        required = int(MIN_AGREEMENT_OBSERVATIONS / (1 - AGREEMENT_RATE_THRESHOLD) * 2)
        for _ in range(required):
            guard.record_agreement(agreed=True)
        assert guard.is_enabled()

    @pytest.mark.unit
    def test_old_observations_pruned_outside_window(self) -> None:
        """Observations older than AGREEMENT_WINDOW_SECONDS are pruned."""
        guard = LatencyGuard.get_instance()

        # Insert observations with timestamps far in the past.
        from latency_guard import _AgreementObservation

        old_ts = time.time() - (AGREEMENT_WINDOW_SECONDS + 1.0)
        with guard._lock:
            for _ in range(MIN_AGREEMENT_OBSERVATIONS):
                guard._agreement_obs.append(
                    _AgreementObservation(timestamp=old_ts, agreed=False)
                )

        # Trigger pruning by adding one fresh observation
        guard.record_agreement(agreed=True)

        status = guard.get_status()
        # Only the single fresh observation should remain after pruning
        assert status.agreement_sample_count == 1

    @pytest.mark.unit
    def test_agreement_rate_is_none_below_min_observations(self) -> None:
        guard = LatencyGuard.get_instance()
        guard.record_agreement(agreed=True)
        status = guard.get_status()
        assert status.agreement_rate is None

    @pytest.mark.unit
    def test_agreement_rate_computed_correctly(self) -> None:
        guard = LatencyGuard.get_instance()
        n = MIN_AGREEMENT_OBSERVATIONS
        for _ in range(n):
            guard.record_agreement(agreed=True)
        status = guard.get_status()
        assert status.agreement_rate == pytest.approx(1.0, abs=1e-6)

    @pytest.mark.unit
    def test_partial_agreement_rate(self) -> None:
        guard = LatencyGuard.get_instance()
        n = MIN_AGREEMENT_OBSERVATIONS
        # 80% agree
        for _ in range(int(n * 0.8)):
            guard.record_agreement(agreed=True)
        for _ in range(n - int(n * 0.8)):
            guard.record_agreement(agreed=False)
        status = guard.get_status()
        assert status.agreement_rate is not None
        assert status.agreement_rate == pytest.approx(0.8, abs=0.01)


# ---------------------------------------------------------------------------
# Combined: both circuit and agreement gate
# ---------------------------------------------------------------------------


class TestCombinedGates:
    @pytest.fixture(autouse=True)
    def fresh(self) -> LatencyGuard:
        # Used for its side-effect of resetting singleton state before each test.
        # The return value is intentionally unused by individual tests.
        return _make_fresh_guard()

    @pytest.mark.unit
    def test_latency_circuit_takes_priority(self) -> None:
        """If circuit is open, is_enabled() returns False regardless of agreement."""
        guard = LatencyGuard.get_instance()
        # Healthy agreement
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=True)
        assert guard.is_enabled()

        # Trip the circuit
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert not guard.is_enabled()

    @pytest.mark.unit
    def test_agreement_gate_takes_priority(self) -> None:
        """If agreement gate is active, is_enabled() returns False regardless of latency."""
        guard = LatencyGuard.get_instance()
        # Good latency
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(1.0)
        assert guard.is_enabled()

        # Trigger agreement gate
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        assert not guard.is_enabled()

    @pytest.mark.unit
    def test_agreement_gate_persists_after_latency_circuit_resets(self) -> None:
        """Agreement gate must remain active when the latency circuit auto-resets.

        Both gates are independent: a latency-circuit recovery (cooldown expiry)
        must NOT implicitly clear the agreement gate.  This verifies the note in
        is_enabled() about gate independence.

        Scenario:
          1. Trip both the latency circuit and the agreement gate.
          2. Fast-forward the circuit's open-at timestamp past the cooldown.
          3. Call is_enabled() — the latency circuit should auto-reset.
          4. Guard must still return False because the agreement gate is still active.
        """
        guard = LatencyGuard.get_instance()

        # Trip the latency circuit breaker.
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert not guard.is_enabled(), "Latency circuit should be open"

        # Trip the agreement gate.
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        assert not guard.is_enabled(), "Both gates should be active"

        # Fast-forward the circuit open-at timestamp so the cooldown has elapsed.
        with guard._lock:
            guard._circuit_open_at = time.monotonic() - (COOLDOWN_SECONDS + 1.0)

        # After this call the latency circuit auto-resets, but the agreement gate
        # must persist — the guard should still be disabled.
        result = guard.is_enabled()
        assert result is False, (
            "Guard must remain disabled: latency circuit recovered but "
            "agreement gate is still active"
        )

        # Confirm the latency circuit did actually reset (samples cleared).
        status = guard.get_status()
        assert not status.circuit_open, "Latency circuit should have auto-reset"
        assert status.agreement_disabled, "Agreement gate must still be active"
        assert status.sample_count == 0, "Samples should have been cleared on reset"


# ---------------------------------------------------------------------------
# get_status() snapshot
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.fixture(autouse=True)
    def fresh(self) -> LatencyGuard:
        # Used for its side-effect of resetting singleton state before each test.
        # The return value is intentionally unused by individual tests.
        return _make_fresh_guard()

    @pytest.mark.unit
    def test_status_enabled_by_default(self) -> None:
        guard = LatencyGuard.get_instance()
        status = guard.get_status()
        assert isinstance(status, LatencyGuardStatus)
        assert status.enabled
        assert not status.circuit_open
        assert not status.agreement_disabled
        assert status.p95_ms is None  # not enough samples
        assert status.agreement_rate is None  # not enough observations
        assert status.cooldown_remaining_s == 0.0

    @pytest.mark.unit
    def test_status_reflects_open_circuit(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        status = guard.get_status()
        assert not status.enabled
        assert status.circuit_open
        assert status.cooldown_remaining_s > 0

    @pytest.mark.unit
    def test_status_reflects_agreement_disabled(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        status = guard.get_status()
        assert not status.enabled
        assert status.agreement_disabled

    @pytest.mark.unit
    def test_status_p95_present_after_min_samples(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(50.0)
        status = guard.get_status()
        assert status.p95_ms is not None
        assert status.p95_ms == pytest.approx(50.0, abs=1.0)

    @pytest.mark.unit
    def test_status_circuit_open_reason_set(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 10.0)
        status = guard.get_status()
        assert (
            "P95" in status.circuit_open_reason
            or "latency" in status.circuit_open_reason.lower()
        )


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestReset:
    @pytest.fixture(autouse=True)
    def fresh(self) -> LatencyGuard:
        # Used for its side-effect of resetting singleton state before each test.
        # The return value is intentionally unused by individual tests.
        return _make_fresh_guard()

    @pytest.mark.unit
    def test_reset_clears_latency_samples(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        assert not guard.is_enabled()
        guard.reset()
        assert guard.is_enabled()
        assert guard.get_status().sample_count == 0

    @pytest.mark.unit
    def test_reset_clears_agreement_observations(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        assert not guard.is_enabled()
        guard.reset()
        assert guard.is_enabled()
        assert guard.get_status().agreement_sample_count == 0

    @pytest.mark.unit
    def test_reset_clears_both(self) -> None:
        guard = LatencyGuard.get_instance()
        for _ in range(MIN_SAMPLES_FOR_TRIP):
            guard.record_latency(P95_SLO_MS + 1.0)
        for _ in range(MIN_AGREEMENT_OBSERVATIONS):
            guard.record_agreement(agreed=False)
        guard.reset()
        status = guard.get_status()
        assert status.enabled
        assert not status.circuit_open
        assert not status.agreement_disabled
        assert status.sample_count == 0
        assert status.agreement_sample_count == 0


# ---------------------------------------------------------------------------
# Thread safety (smoke test)
# ---------------------------------------------------------------------------


class TestThreadSafety:
    @pytest.fixture(autouse=True)
    def fresh(self) -> LatencyGuard:
        # Used for its side-effect of resetting singleton state before each test.
        # The return value is intentionally unused by individual tests.
        return _make_fresh_guard()

    @pytest.mark.unit
    def test_concurrent_record_latency(self) -> None:
        """Concurrent record_latency calls must not raise."""
        guard = LatencyGuard.get_instance()
        errors: list[Exception] = []

        def writer() -> None:
            try:
                for _ in range(50):
                    guard.record_latency(20.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Thread errors: {errors}"

    @pytest.mark.unit
    def test_concurrent_mixed_operations(self) -> None:
        """Mix of reads and writes from many threads must not raise."""
        guard = LatencyGuard.get_instance()
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for i in range(20):
                    guard.record_latency(float(i))
                    guard.record_agreement(agreed=(i % 2 == 0))
                    guard.is_enabled()
                    guard.get_status()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Thread errors: {errors}"
