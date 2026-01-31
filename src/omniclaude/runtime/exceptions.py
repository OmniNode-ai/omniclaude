# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Exception types for contract publishing errors.

This module defines a hierarchy of exceptions for contract publishing:

- ContractPublisherError: Base exception for all publishing errors
- ContractSourceNotConfiguredError: Fatal config error (no source configured)
- ContractPublishingInfraError: Infrastructure failures (Kafka, network, etc.)
- NoContractsFoundError: No contracts found when expected

These exceptions enable fail-fast behavior for infrastructure errors while
allowing degraded mode for configuration errors.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from omniclaude.runtime.contract_models import InfraError

__all__ = [
    "ContractPublisherError",
    "ContractSourceNotConfiguredError",
    "ContractPublishingInfraError",
    "NoContractsFoundError",
]


class ContractPublisherError(Exception):
    """Base exception for contract publishing errors."""

    pass


class ContractSourceNotConfiguredError(ContractPublisherError):
    """Raised when no contract source is configured.

    This is a fatal startup error - the publisher refuses to guess paths.
    The caller must explicitly configure either:
    - A directory path containing contract YAML files
    - A callable that returns contracts

    Example:
        >>> raise ContractSourceNotConfiguredError()
        ContractSourceNotConfiguredError: No contract source configured...
    """

    def __init__(self, message: str | None = None):
        if message is None:
            message = (
                "No contract source configured. "
                "Provide either 'contract_dir' or 'contract_source' parameter."
            )
        super().__init__(message)


class ContractPublishingInfraError(ContractPublisherError):
    """Raised when infrastructure fails during contract publishing.

    Only raised when fail_fast=True (default). Contains the list of
    infrastructure errors that caused the failure.

    Attributes:
        infra_errors: List of InfraError instances describing what failed.

    Example:
        >>> from omniclaude.runtime.contract_models import InfraError
        >>> errors = [InfraError(error_type="kafka_unavailable", ...)]
        >>> raise ContractPublishingInfraError(errors)
        ContractPublishingInfraError: Contract publishing failed...
    """

    def __init__(
        self, infra_errors: list[InfraError], message: str | None = None
    ) -> None:
        self.infra_errors = infra_errors
        if message is None:
            error_types = [e.error_type for e in infra_errors]
            message = f"Contract publishing failed due to infrastructure errors: {error_types}"
        super().__init__(message)


class NoContractsFoundError(ContractPublisherError):
    """Raised when no contracts are found and allow_zero_contracts=False.

    This catches configuration mistakes where the source path is wrong
    or contracts are missing from the expected location.

    Attributes:
        source_description: Human-readable description of where contracts
            were expected (e.g., directory path or source name).

    Example:
        >>> raise NoContractsFoundError("/path/to/contracts")
        NoContractsFoundError: No contracts found from /path/to/contracts...
    """

    def __init__(self, source_description: str) -> None:
        self.source_description = source_description
        super().__init__(
            f"No contracts found from {source_description}. "
            "Set allow_zero_contracts=True to allow empty publishing."
        )
