"""
Retry Manager with Exponential Backoff

Implements intelligent retry logic with exponential backoff for transient failures.
Integrates with circuit breaker pattern for robust error handling.
"""

import asyncio
from typing import Any, Callable, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import random


class RetryStrategy(Enum):
    """Retry strategies for different failure types."""

    EXPONENTIAL_BACKOFF = "exponential_backoff"
    LINEAR_BACKOFF = "linear_backoff"
    FIXED_DELAY = "fixed_delay"
    NO_RETRY = "no_retry"


class TransientError(Exception):
    """Exception for transient errors that should be retried."""

    pass


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL_BACKOFF
    retry_on_exceptions: Tuple[type, ...] = (TransientError, ConnectionError, TimeoutError)
    backoff_multiplier: float = 1.0


class RetryManager:
    """
    Manages retry logic with exponential backoff and circuit breaker integration.

    Features:
    - Multiple retry strategies
    - Jitter to prevent thundering herd
    - Exception filtering
    - Circuit breaker integration
    - Performance metrics
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        """
        Initialize retry manager.

        Args:
            config: Retry configuration
        """
        self.config = config or RetryConfig()
        self._stats = {
            "total_attempts": 0,
            "total_retries": 0,
            "total_successes": 0,
            "total_failures": 0,
            "retry_distribution": {},
        }

    async def execute_with_retry(
        self, func: Callable, *args, config: Optional[RetryConfig] = None, **kwargs
    ) -> Tuple[bool, Any]:
        """
        Execute function with retry logic.

        Args:
            func: Function to execute
            *args: Function arguments
            config: Optional retry configuration override
            **kwargs: Function keyword arguments

        Returns:
            Tuple of (success, result)
        """
        retry_config = config or self.config
        last_exception = None

        for attempt in range(retry_config.max_retries + 1):
            self._stats["total_attempts"] += 1

            try:
                # Execute the function
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success
                self._stats["total_successes"] += 1
                if attempt > 0:
                    self._stats["total_retries"] += attempt
                    self._stats["retry_distribution"][str(attempt)] = (
                        self._stats["retry_distribution"].get(str(attempt), 0) + 1
                    )

                return True, result

            except Exception as e:
                last_exception = e

                # Check if this exception should be retried
                if not self._should_retry(e, retry_config):
                    self._stats["total_failures"] += 1
                    break

                # Check if we've exhausted retries
                if attempt >= retry_config.max_retries:
                    self._stats["total_failures"] += 1
                    break

                # Calculate delay and wait
                delay = self._calculate_delay(attempt, retry_config)
                await asyncio.sleep(delay)

        # All retries failed
        return False, last_exception

    def _should_retry(self, exception: Exception, config: RetryConfig) -> bool:
        """
        Check if an exception should be retried.

        Args:
            exception: Exception to check
            config: Retry configuration

        Returns:
            True if exception should be retried
        """
        # Check if exception type is in retry list
        if isinstance(exception, config.retry_on_exceptions):
            return True

        # Check for transient error patterns
        error_str = str(exception).lower()
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
            "internal server error",
            "too many requests",
        ]

        return any(pattern in error_str for pattern in transient_patterns)

    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        """
        Calculate delay for retry attempt.

        Args:
            attempt: Current attempt number (0-based)
            config: Retry configuration

        Returns:
            Delay in seconds
        """
        if config.strategy == RetryStrategy.NO_RETRY:
            return 0.0
        elif config.strategy == RetryStrategy.FIXED_DELAY:
            delay = config.base_delay
        elif config.strategy == RetryStrategy.LINEAR_BACKOFF:
            delay = config.base_delay * (attempt + 1) * config.backoff_multiplier
        else:  # EXPONENTIAL_BACKOFF
            delay = config.base_delay * (config.exponential_base**attempt) * config.backoff_multiplier

        # Apply jitter to prevent thundering herd
        if config.jitter:
            jitter_factor = random.uniform(0.5, 1.5)
            delay *= jitter_factor

        # Cap at maximum delay
        return min(delay, config.max_delay)

    async def execute_with_circuit_breaker(
        self, func: Callable, circuit_breaker_name: str, *args, config: Optional[RetryConfig] = None, **kwargs
    ) -> Tuple[bool, Any]:
        """
        Execute function with both retry logic and circuit breaker protection.

        Args:
            func: Function to execute
            circuit_breaker_name: Name of circuit breaker to use
            *args: Function arguments
            config: Optional retry configuration override
            **kwargs: Function keyword arguments

        Returns:
            Tuple of (success, result)
        """
        try:
            from .circuit_breaker import call_with_breaker, CircuitBreakerConfig

            # Create circuit breaker config for retry operations
            # Use retry config values to create circuit breaker config
            cb_config = CircuitBreakerConfig(
                failure_threshold=config.max_retries if config else 3,
                timeout_seconds=30.0,
                success_threshold=2,
                max_retries=0,  # Let retry manager handle retries
                base_delay=config.base_delay if config else 1.0,
                max_delay=config.max_delay if config else 10.0,
            )

            # Use circuit breaker with retry logic
            cb_success, cb_result = await call_with_breaker(
                circuit_breaker_name, self.execute_with_retry, func, *args, config=cb_config, **kwargs
            )

            # cb_result is a tuple (retry_success, retry_result) from execute_with_retry
            if cb_success and isinstance(cb_result, tuple) and len(cb_result) == 2:
                retry_success, retry_result = cb_result
                return retry_success, retry_result
            else:
                return cb_success, cb_result

        except ImportError:
            # Fallback to retry only if circuit breaker not available
            return await self.execute_with_retry(func, *args, config=config, **kwargs)

    def get_stats(self) -> Dict[str, Any]:
        """Get retry statistics."""
        success_rate = 0.0
        if self._stats["total_attempts"] > 0:
            success_rate = self._stats["total_successes"] / self._stats["total_attempts"]

        retry_rate = 0.0
        if self._stats["total_attempts"] > 0:
            retry_rate = self._stats["total_retries"] / self._stats["total_attempts"]

        return {
            "total_attempts": self._stats["total_attempts"],
            "total_retries": self._stats["total_retries"],
            "total_successes": self._stats["total_successes"],
            "total_failures": self._stats["total_failures"],
            "success_rate": success_rate,
            "retry_rate": retry_rate,
            "retry_distribution": self._stats["retry_distribution"],
            "config": {
                "max_retries": self.config.max_retries,
                "base_delay": self.config.base_delay,
                "max_delay": self.config.max_delay,
                "strategy": self.config.strategy.value,
                "jitter": self.config.jitter,
            },
        }

    def reset_stats(self):
        """Reset retry statistics."""
        self._stats = {
            "total_attempts": 0,
            "total_retries": 0,
            "total_successes": 0,
            "total_failures": 0,
            "retry_distribution": {},
        }


class RetryManagerManager:
    """Manages multiple retry managers for different operations."""

    def __init__(self):
        self._managers: Dict[str, RetryManager] = {}
        self._default_config = RetryConfig()

    def get_manager(self, name: str, config: Optional[RetryConfig] = None) -> RetryManager:
        """Get or create a retry manager."""
        if name not in self._managers:
            self._managers[name] = RetryManager(config or self._default_config)
        return self._managers[name]

    async def execute_with_retry(
        self, manager_name: str, func: Callable, *args, config: Optional[RetryConfig] = None, **kwargs
    ) -> Tuple[bool, Any]:
        """Execute function with named retry manager."""
        manager = self.get_manager(manager_name, config)
        return await manager.execute_with_retry(func, *args, config=config, **kwargs)

    async def execute_with_circuit_breaker(
        self,
        manager_name: str,
        func: Callable,
        circuit_breaker_name: str,
        *args,
        config: Optional[RetryConfig] = None,
        **kwargs,
    ) -> Tuple[bool, Any]:
        """Execute function with both retry and circuit breaker."""
        manager = self.get_manager(manager_name, config)
        return await manager.execute_with_circuit_breaker(func, circuit_breaker_name, *args, config=config, **kwargs)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all retry managers."""
        return {name: manager.get_stats() for name, manager in self._managers.items()}

    def reset_all_stats(self):
        """Reset statistics for all retry managers."""
        for manager in self._managers.values():
            manager.reset_stats()


# Global retry manager manager
retry_manager_manager = RetryManagerManager()


# Convenience functions
async def execute_with_retry(
    func: Callable, *args, manager_name: str = "default", config: Optional[RetryConfig] = None, **kwargs
) -> Tuple[bool, Any]:
    """Execute function with retry logic."""
    return await retry_manager_manager.execute_with_retry(manager_name, func, *args, config=config, **kwargs)


async def execute_with_circuit_breaker(
    func: Callable,
    circuit_breaker_name: str,
    *args,
    manager_name: str = "default",
    config: Optional[RetryConfig] = None,
    **kwargs,
) -> Tuple[bool, Any]:
    """Execute function with both retry and circuit breaker protection."""
    return await retry_manager_manager.execute_with_circuit_breaker(
        manager_name, func, circuit_breaker_name, *args, config=config, **kwargs
    )


def get_retry_stats(manager_name: str = "default") -> Optional[Dict[str, Any]]:
    """Get statistics for a specific retry manager."""
    if manager_name in retry_manager_manager._managers:
        return retry_manager_manager._managers[manager_name].get_stats()
    return None


def get_all_retry_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all retry managers."""
    return retry_manager_manager.get_all_stats()


def reset_retry_stats(manager_name: str = "default"):
    """Reset statistics for a specific retry manager."""
    if manager_name in retry_manager_manager._managers:
        retry_manager_manager._managers[manager_name].reset_stats()


def reset_all_retry_stats():
    """Reset statistics for all retry managers."""
    retry_manager_manager.reset_all_stats()


# Predefined retry configurations for common scenarios
QUICK_RETRY_CONFIG = RetryConfig(
    max_retries=2, base_delay=0.5, max_delay=5.0, strategy=RetryStrategy.EXPONENTIAL_BACKOFF
)

STANDARD_RETRY_CONFIG = RetryConfig(
    max_retries=3, base_delay=1.0, max_delay=30.0, strategy=RetryStrategy.EXPONENTIAL_BACKOFF
)

AGGRESSIVE_RETRY_CONFIG = RetryConfig(
    max_retries=5, base_delay=2.0, max_delay=120.0, strategy=RetryStrategy.EXPONENTIAL_BACKOFF
)

DATABASE_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=10.0,
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    retry_on_exceptions=(TransientError, ConnectionError, TimeoutError),
)

API_RETRY_CONFIG = RetryConfig(
    max_retries=3,
    base_delay=1.0,
    max_delay=30.0,
    strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
    retry_on_exceptions=(TransientError, ConnectionError, TimeoutError),
)
