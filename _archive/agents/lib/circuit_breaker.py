"""
Circuit Breaker Pattern Implementation

Prevents cascade failures by monitoring external service calls and
automatically opening the circuit when failure rates exceed thresholds.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"  # Circuit is open, calls fail fast
    HALF_OPEN = "HALF_OPEN"  # Testing if service is back


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5  # Number of failures before opening
    timeout_seconds: float = 60.0  # Time to wait before trying again
    success_threshold: int = 3  # Successes needed to close from half-open
    max_retries: int = 3  # Max retries for transient errors
    base_delay: float = 1.0  # Base delay for exponential backoff
    max_delay: float = 60.0  # Maximum delay between retries


class CircuitBreaker:
    """
    Circuit breaker implementation for external service calls.

    Features:
    - Automatic failure detection
    - Exponential backoff retry
    - Configurable thresholds
    - State monitoring
    - Graceful degradation
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        """
        Initialize circuit breaker.

        Args:
            name: Unique name for this circuit breaker
            config: Configuration options
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()

        # State tracking
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: float | None = None
        self.last_success_time: float | None = None

        # Statistics
        self.total_calls = 0
        self.total_failures = 0
        self.total_successes = 0
        self.circuit_opens = 0

        # Lock for thread safety
        self._lock = asyncio.Lock()

    async def call(self, func: Callable, *args, **kwargs) -> tuple[bool, Any]:
        """
        Execute a function with circuit breaker protection.

        Args:
            func: Function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments

        Returns:
            Tuple of (success, result)
        """
        async with self._lock:
            self.total_calls += 1
            just_transitioned_to_half_open = False

            # Check if circuit should be opened
            if self.state == CircuitState.CLOSED and self._should_open_circuit():
                self._open_circuit()

            # Check if circuit should be closed
            elif self.state == CircuitState.HALF_OPEN and self._should_close_circuit():
                self._close_circuit()

            # Handle different circuit states
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._half_open_circuit()
                    just_transitioned_to_half_open = True
                else:
                    return False, CircuitBreakerError(f"Circuit {self.name} is OPEN")

            # Execute the function with retry logic
            return await self._execute_with_retry(
                func, just_transitioned_to_half_open, *args, **kwargs
            )

    def _should_open_circuit(self) -> bool:
        """Check if circuit should be opened."""
        return self.failure_count >= self.config.failure_threshold

    def _should_close_circuit(self) -> bool:
        """Check if circuit should be closed from half-open."""
        return self.success_count >= self.config.success_threshold

    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit."""
        if self.last_failure_time is None:
            return True

        time_since_failure = time.time() - self.last_failure_time
        return time_since_failure >= self.config.timeout_seconds

    def _open_circuit(self):
        """Open the circuit."""
        self.state = CircuitState.OPEN
        self.circuit_opens += 1
        self.failure_count = 0
        self.success_count = 0
        print(f"[CircuitBreaker] {self.name} circuit OPENED")

    def _close_circuit(self):
        """Close the circuit."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        print(f"[CircuitBreaker] {self.name} circuit CLOSED")

    def _half_open_circuit(self):
        """Set circuit to half-open state."""
        self.state = CircuitState.HALF_OPEN
        self.failure_count = 0
        self.success_count = 0
        print(f"[CircuitBreaker] {self.name} circuit HALF-OPEN")

    async def _execute_with_retry(
        self, func: Callable, just_transitioned: bool, *args, **kwargs
    ) -> tuple[bool, Any]:
        """Execute function with retry logic."""
        last_exception = None

        for attempt in range(self.config.max_retries + 1):
            try:
                # Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success - update circuit state
                self._record_success(just_transitioned)
                return True, result

            except Exception as e:
                last_exception = e

                # Check if this is a transient error that should be retried
                if (
                    not self._is_transient_error(e)
                    or attempt == self.config.max_retries
                ):
                    self._record_failure()
                    break

                # Wait before retry with exponential backoff
                delay = min(
                    self.config.base_delay * (2**attempt), self.config.max_delay
                )
                await asyncio.sleep(delay)

        # All retries failed
        return False, last_exception

    def _is_transient_error(self, error: Exception) -> bool:
        """
        Check if an error is transient and should be retried.

        Args:
            error: Exception to check

        Returns:
            True if error is transient
        """
        # Common transient error patterns
        transient_patterns = [
            "timeout",
            "connection",
            "network",
            "temporary",
            "rate limit",
            "throttle",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
        ]

        error_str = str(error).lower()
        return any(pattern in error_str for pattern in transient_patterns)

    def _record_success(self, just_transitioned: bool = False):
        """Record a successful call."""
        self.total_successes += 1
        self.last_success_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            # Don't close circuit on the same call that transitioned to HALF_OPEN
            if not just_transitioned and self._should_close_circuit():
                self._close_circuit()
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0  # Reset failure count on success

    def _record_failure(self):
        """Record a failed call."""
        self.total_failures += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.CLOSED:
            self.failure_count += 1
            # Check if we should open circuit after recording failure
            if self._should_open_circuit():
                self._open_circuit()
        elif self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open state opens the circuit
            self._open_circuit()

    def get_stats(self) -> dict[str, Any]:
        """Get circuit breaker statistics."""
        success_rate = 0.0
        if self.total_calls > 0:
            success_rate = self.total_successes / self.total_calls

        return {
            "name": self.name,
            "state": self.state.value,
            "total_calls": self.total_calls,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": success_rate,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "circuit_opens": self.circuit_opens,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "config": {
                "failure_threshold": self.config.failure_threshold,
                "timeout_seconds": self.config.timeout_seconds,
                "success_threshold": self.config.success_threshold,
                "max_retries": self.config.max_retries,
            },
        }

    def reset(self):
        """Reset circuit breaker to initial state."""

        async def _reset():
            async with self._lock:
                self.state = CircuitState.CLOSED
                self.failure_count = 0
                self.success_count = 0
                self.last_failure_time = None
                self.last_success_time = None
                print(f"[CircuitBreaker] {self.name} circuit RESET")

        return asyncio.create_task(_reset())


class CircuitBreakerError(Exception):
    """Exception raised when circuit breaker is open."""

    pass


class CircuitBreakerManager:
    """Manages multiple circuit breakers."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get_breaker(
        self, name: str, config: CircuitBreakerConfig | None = None
    ) -> CircuitBreaker:
        """Get or create a circuit breaker."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, config)
        return self._breakers[name]

    async def call_with_breaker(
        self,
        breaker_name: str,
        func: Callable,
        *args,
        config: CircuitBreakerConfig | None = None,
        **kwargs,
    ) -> tuple[bool, Any]:
        """Execute function with circuit breaker protection."""
        breaker = self.get_breaker(breaker_name, config)
        return await breaker.call(func, *args, **kwargs)

    def get_all_stats(self) -> dict[str, dict[str, Any]]:
        """Get statistics for all circuit breakers."""
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self):
        """Reset all circuit breakers."""
        for breaker in self._breakers.values():
            breaker.reset()


# Global circuit breaker manager
circuit_breaker_manager = CircuitBreakerManager()


# Convenience functions
async def call_with_breaker(
    breaker_name: str,
    func: Callable,
    *args,
    config: CircuitBreakerConfig | None = None,
    **kwargs,
) -> tuple[bool, Any]:
    """Execute function with circuit breaker protection.

    Returns:
        Tuple[bool, Any]: (success, result) where success is True if the call
        succeeded, and result is the return value or exception.
    """
    return await circuit_breaker_manager.call_with_breaker(
        breaker_name, func, *args, config=config, **kwargs
    )


def get_breaker_stats(breaker_name: str) -> dict[str, Any] | None:
    """Get statistics for a specific circuit breaker."""
    if breaker_name in circuit_breaker_manager._breakers:
        return circuit_breaker_manager._breakers[breaker_name].get_stats()
    return None


def get_all_breaker_stats() -> dict[str, dict[str, Any]]:
    """Get statistics for all circuit breakers."""
    return circuit_breaker_manager.get_all_stats()


def reset_breaker(breaker_name: str):
    """Reset a specific circuit breaker."""
    if breaker_name in circuit_breaker_manager._breakers:
        circuit_breaker_manager._breakers[breaker_name].reset()


def reset_all_breakers():
    """Reset all circuit breakers."""
    circuit_breaker_manager.reset_all()
