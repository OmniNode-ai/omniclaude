# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Service wiring for omniclaude handlers.

This module publishes handler contracts to Kafka for discovery by the platform's
KafkaContractSource. Handler instantiation is handled by omnibase_infra's
ServiceRuntimeHostProcess.

Ticket: OMN-1812 - Migrate wiring.py to use ServiceContractPublisher from omnibase_infra

Architecture (ARCH-002):
    Runtime owns all Kafka plumbing. This module delegates to ServiceContractPublisher
    from omnibase_infra which handles:
    - YAML parsing and validation
    - Contract hash computation
    - Kafka event emission (ModelContractRegisteredEvent)
    - Error categorization (contract vs infrastructure)

Event-Driven Wiring Strategy:
    1. Read handler contracts from configured source (filesystem or package)
    2. Emit ModelContractRegisteredEvent to Kafka for each handler
    3. KafkaContractSource (in omnibase_infra) caches the descriptors
    4. ServiceRuntimeHostProcess imports, instantiates, and initializes handlers

This replaces the previous local implementation with the standardized infra service.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from omnibase_infra.services.contract_publisher import (
    ContractSourceNotConfiguredError,
    ModelContractPublisherConfig,
    ModelPublishResult,
    ServiceContractPublisher,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

logger = logging.getLogger(__name__)


async def publish_handler_contracts(
    container: ModelONEXContainer,
    config: ModelContractPublisherConfig,
    environment: str | None = None,
) -> ModelPublishResult:
    """Publish handler contracts to Kafka for discovery.

    Emits ModelContractRegisteredEvent for each handler contract found in
    the configured source. The events are consumed by KafkaContractSource
    in omnibase_infra for handler discovery and registration.

    This function delegates to ServiceContractPublisher from omnibase_infra
    which handles all YAML parsing, validation, and Kafka emission.

    Error Handling:
        - Contract errors (YAML parse, schema validation, missing fields) are
          non-fatal: logged, added to contract_errors, processing continues.
        - Infrastructure errors (Kafka, publisher) are fatal by default:
          raises ContractPublishingInfraError immediately when fail_fast=True.
        - Zero contracts raises NoContractsFoundError when allow_zero_contracts=False
          and no contract files exist. If contracts are found but all fail validation,
          the function returns normally with contract_errors populated.

    Args:
        container: The ONEX container with event bus publisher.
        config: Configuration specifying contract source (filesystem, package, composite).
        environment: Environment prefix for Kafka topics (e.g., "dev").
            Defaults to ONEX_ENV environment variable or "dev".
            If provided, overrides the config's environment setting.

    Returns:
        ModelPublishResult with published handler IDs, contract_errors, infra_errors,
        and duration_ms.

    Raises:
        ImportError: If omnibase_infra contract publisher is not available.
        NotImplementedError: If package or composite mode is used (not yet implemented).
        NoContractsFoundError: If no contract files found (empty directory) and
            allow_zero_contracts=False. Not raised if contracts exist but all fail validation.
        ContractPublishingInfraError: If infrastructure errors occur and fail_fast=True.

    Example:
        >>> container = ModelONEXContainer(...)
        >>> config = ModelContractPublisherConfig(
        ...     mode="filesystem",
        ...     filesystem_root=Path("/app/contracts/handlers"),
        ... )
        >>> result = await publish_handler_contracts(container, config)
        >>> print(f"Published {len(result.published)} contracts in {result.duration_ms:.1f}ms")
        >>> if result.contract_errors:
        ...     print(f"Errors: {len(result.contract_errors)}")
    """
    # Resolve environment if provided (override config setting)
    if environment is not None:
        resolved_env = environment.strip() or "dev"
        config = config.model_copy(update={"environment": resolved_env})

    # Delegate to infra service
    publisher = await ServiceContractPublisher.from_container(container, config)
    return await publisher.publish_all()


async def wire_omniclaude_services(
    container: ModelONEXContainer,
    config: ModelContractPublisherConfig | None = None,
) -> None:
    """Register omniclaude handlers with the platform via event-driven discovery.

    This function publishes handler contracts to Kafka. The actual handler
    instantiation is handled by ServiceRuntimeHostProcess in omnibase_infra
    when it receives the registration events via KafkaContractSource.

    After publishing, handlers can be resolved via:
        handler = await container.get_service_async(ProtocolPatternPersistence)

    Note: Handler availability depends on KafkaContractSource caching the
    registration event. In beta, this requires a runtime restart after
    first publication.

    Args:
        container: The ONEX container with event bus publisher.
        config: Configuration specifying contract source. If None, falls back
            to OMNICLAUDE_CONTRACTS_ROOT environment variable.

    Raises:
        ContractSourceNotConfiguredError: If no config provided and
            OMNICLAUDE_CONTRACTS_ROOT environment variable is not set.

    Example:
        from omniclaude.runtime import wire_omniclaude_services
        from omnibase_infra.services.contract_publisher import ModelContractPublisherConfig
        from pathlib import Path

        # During application bootstrap with explicit config
        container = ModelONEXContainer(...)
        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=Path("/app/contracts/handlers"),
        )
        await wire_omniclaude_services(container, config)

        # Or using environment variable
        # export OMNICLAUDE_CONTRACTS_ROOT=/app/contracts/handlers
        await wire_omniclaude_services(container)
    """
    if config is None:
        # Check for env var configuration
        contracts_root = os.getenv("OMNICLAUDE_CONTRACTS_ROOT")
        if contracts_root is None:
            raise ContractSourceNotConfiguredError(
                "No contract source configured. Either pass ModelContractPublisherConfig "
                "or set OMNICLAUDE_CONTRACTS_ROOT environment variable."
            )
        config = ModelContractPublisherConfig(
            mode="filesystem",
            filesystem_root=Path(contracts_root),
        )

    await publish_handler_contracts(container, config)
