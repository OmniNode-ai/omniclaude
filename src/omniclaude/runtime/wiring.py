# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Service wiring for omniclaude handlers.

This module publishes handler contracts to Kafka for discovery by the platform's
KafkaContractSource. Handler instantiation is handled by omnibase_infra's
ServiceRuntimeHostProcess.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

Event-Driven Wiring Strategy:
    1. Read handler contracts from configured source (filesystem or package)
    2. Emit ModelContractRegisteredEvent to Kafka for each handler
    3. KafkaContractSource (in omnibase_infra) caches the descriptors
    4. ServiceRuntimeHostProcess imports, instantiates, and initializes handlers

This replaces the previous filesystem-based registration approach with
platform-native event-driven discovery.

Design Principles:
    - Explicit configuration required - no magic path resolution
    - Contract errors are non-fatal (degraded mode continues)
    - Infrastructure errors are fatal by default (fail_fast=True)
    - Zero contracts is an error by default (allow_zero_contracts=False)
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml

from omniclaude.runtime.contract_models import (
    ContractError,
    ContractPublisherConfig,
    InfraError,
    PublishResult,
)
from omniclaude.runtime.exceptions import (
    ContractPublishingInfraError,
    ContractSourceNotConfiguredError,
    NoContractsFoundError,
)

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

logger = logging.getLogger(__name__)

# Valid fully qualified Python path: module.submodule.ClassName (at least 2 parts, valid Python identifiers)
HANDLER_CLASS_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)+$"
)


def _compute_contract_hash(content: str) -> str:
    """Compute SHA-256 hash of contract content for change detection."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def publish_handler_contracts(
    container: ModelONEXContainer,
    config: ContractPublisherConfig,
    environment: str | None = None,
) -> PublishResult:
    """Publish handler contracts to Kafka for discovery.

    Emits ModelContractRegisteredEvent for each handler contract found in
    the configured source. The events are consumed by KafkaContractSource
    in omnibase_infra for handler discovery and registration.

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

    Returns:
        PublishResult with published handler IDs, contract_errors, infra_errors,
        and duration_ms.

    Raises:
        ImportError: If omnibase_core event models are not available.
        NotImplementedError: If package or composite mode is used (not yet implemented).
        NoContractsFoundError: If no contract files found (empty directory) and
            allow_zero_contracts=False. Not raised if contracts exist but all fail validation.
        ContractPublishingInfraError: If infrastructure errors occur and fail_fast=True.

    Example:
        >>> container = ModelONEXContainer(...)
        >>> config = ContractPublisherConfig(
        ...     mode="filesystem",
        ...     filesystem_root=Path("/app/contracts/handlers"),
        ... )
        >>> result = await publish_handler_contracts(container, config)
        >>> print(f"Published {len(result.published)} contracts in {result.duration_ms:.1f}ms")
        >>> if result.contract_errors:
        ...     print(f"Errors: {len(result.contract_errors)}")
    """
    start_time = time.monotonic()

    # Import here to avoid circular imports and allow graceful degradation
    try:
        from omnibase_core.models.events.contract_registration import (
            CONTRACT_REGISTERED_EVENT,
            ModelContractRegisteredEvent,
        )
        from omnibase_core.models.primitives.model_semver import ModelSemVer
        from omnibase_spi.protocols.protocol_event_bus_publisher import (
            ProtocolEventBusPublisher,
        )
    except ImportError as e:
        logger.warning(
            "Contract registration events not available (omnibase_core >= 0.9.11 required): %s",
            e,
        )
        raise

    # Resolve contract paths based on mode - NO MAGIC PATHS
    source_description = "unknown"  # Initialize to ensure variable is always bound
    contracts_root: Path | None = None  # Initialize to prevent unbound variable risk
    match config.mode:
        case "filesystem":
            contracts_root = config.filesystem_root
            source_description = f"filesystem: {contracts_root}"
        case "package":
            # For now, package mode not implemented - raise clear error
            raise NotImplementedError(
                "package mode not yet implemented. Use filesystem mode with explicit path."
            )
        case "composite":
            # Try filesystem if configured
            if config.filesystem_root and config.filesystem_root.exists():
                contracts_root = config.filesystem_root
                source_description = f"composite (filesystem): {contracts_root}"
            else:
                raise NotImplementedError(
                    "composite mode with package fallback not yet implemented."
                )

    # Resolve environment - handle empty string and None cases
    if environment is None:
        environment = os.getenv("ONEX_ENV", "") or "dev"
    environment = environment.strip() or "dev"

    # Initialize error tracking
    contract_errors: list[ContractError] = []
    infra_errors: list[InfraError] = []
    published: list[str] = []

    # Check if contracts directory exists
    if contracts_root is None or not contracts_root.exists():
        logger.warning(
            "Contracts directory does not exist: %s",
            contracts_root,
        )
        duration_ms = (time.monotonic() - start_time) * 1000
        if not config.allow_zero_contracts:
            raise NoContractsFoundError(source_description)
        return PublishResult(
            published=[],
            contract_errors=[],
            infra_errors=[],
            duration_ms=duration_ms,
        )

    # Discover contract files
    contract_paths: list[Path] = sorted(contracts_root.glob("**/contract.yaml"))
    if not contract_paths:
        logger.info("No handler contracts found in %s", contracts_root)
        duration_ms = (time.monotonic() - start_time) * 1000
        if not config.allow_zero_contracts:
            raise NoContractsFoundError(source_description)
        return PublishResult(
            published=[],
            contract_errors=[],
            infra_errors=[],
            duration_ms=duration_ms,
        )

    logger.info(
        "Publishing %d handler contract(s) from %s",
        len(contract_paths),
        contracts_root,
    )

    # Get event bus publisher from container
    try:
        publisher: ProtocolEventBusPublisher = await container.get_service_async(
            ProtocolEventBusPublisher
        )
    except Exception as e:
        error = InfraError(
            error_type="publisher_unavailable",
            message=f"Failed to get event bus publisher from container: {e}",
            retriable=False,
        )
        infra_errors.append(error)
        logger.warning(error.message)
        if config.fail_fast:
            raise ContractPublishingInfraError(infra_errors)
        duration_ms = (time.monotonic() - start_time) * 1000
        return PublishResult(
            published=[],
            contract_errors=[],
            infra_errors=infra_errors,
            duration_ms=duration_ms,
        )

    # Build topic name
    topic = f"{environment}.{CONTRACT_REGISTERED_EVENT}"

    for contract_path in contract_paths:
        try:
            # Read contract YAML
            contract_yaml = contract_path.read_text(encoding="utf-8")
            try:
                contract_data = yaml.safe_load(contract_yaml)
            except yaml.YAMLError as e:
                error = ContractError(
                    contract_path=str(contract_path),
                    error_type="yaml_parse",
                    message=f"Invalid YAML: {e}",
                )
                contract_errors.append(error)
                logger.warning(
                    "Skipping contract with YAML parse error: %s - %s",
                    contract_path,
                    e,
                )
                continue

            if not isinstance(contract_data, dict):
                error = ContractError(
                    contract_path=str(contract_path),
                    error_type="schema_validation",
                    message="Contract is not a dict",
                )
                contract_errors.append(error)
                logger.warning(
                    "Skipping invalid contract (not a dict): %s",
                    contract_path,
                )
                continue

            # Extract identity fields - validate handler_id to avoid empty Kafka keys
            handler_id = contract_data.get("handler_id", "")
            if not isinstance(handler_id, str) or not handler_id.strip():
                error = ContractError(
                    contract_path=str(contract_path),
                    error_type="missing_field",
                    message="Contract missing required field: handler_id",
                )
                contract_errors.append(error)
                logger.warning(
                    "Skipping contract with missing or invalid handler_id: %s",
                    contract_path,
                )
                continue
            # Use stripped version to avoid whitespace-only keys
            handler_id = handler_id.strip()

            # Validate handler_class format if present (required for KafkaContractSource)
            metadata = contract_data.get("metadata", {})
            handler_class = metadata.get("handler_class", "")
            if handler_class and not HANDLER_CLASS_PATTERN.match(handler_class):
                error = ContractError(
                    contract_path=str(contract_path),
                    error_type="invalid_handler_class",
                    message=f"handler_class must be a valid fully qualified Python path (e.g., 'module.submodule.ClassName'): {handler_class}",
                )
                contract_errors.append(error)
                logger.warning(
                    "Skipping contract with invalid handler_class (must be a valid fully qualified Python path): %s in %s",
                    handler_class,
                    contract_path,
                )
                continue

            name = contract_data.get("name", handler_id)

            # Parse version
            version_data = contract_data.get("contract_version", {})
            if isinstance(version_data, dict):
                version = ModelSemVer(
                    major=version_data.get("major", 0),
                    minor=version_data.get("minor", 0),
                    patch=version_data.get("patch", 0),
                )
            else:
                version = ModelSemVer(major=0, minor=0, patch=0)

            # Compute SHA-256 hash for change detection.
            # This enables consumers (e.g., KafkaContractSource) to detect contract changes:
            # - Compare stored hash with incoming hash
            # - Skip re-processing if hash unchanged (idempotent republishing)
            # - Trigger re-registration only when contract content changes
            contract_hash = _compute_contract_hash(contract_yaml)

            # Create registration event
            event = ModelContractRegisteredEvent(
                event_id=uuid4(),
                node_name=handler_id,
                node_version=version,
                contract_hash=contract_hash,
                contract_yaml=contract_yaml,
            )

            # Publish to Kafka
            try:
                await publisher.publish(
                    topic=topic,
                    key=handler_id.encode("utf-8"),
                    value=event.model_dump_json().encode("utf-8"),
                )
            except Exception as e:
                error = InfraError(
                    error_type="publish_failed",
                    message=f"Failed to publish contract {handler_id}: {e}",
                    retriable=True,
                )
                infra_errors.append(error)
                logger.warning(error.message)
                if config.fail_fast:
                    raise ContractPublishingInfraError(infra_errors)
                continue

            published.append(handler_id)
            logger.info(
                "Published handler contract: %s [%s] (v%s) to %s",
                name,
                handler_id,
                version,
                topic,
            )

        except ContractPublishingInfraError:
            # Re-raise infra errors immediately
            raise
        except Exception as e:
            # Catch-all for unexpected contract-level errors
            error = ContractError(
                contract_path=str(contract_path),
                error_type="schema_validation",
                message=f"Unexpected error processing contract: {e}",
            )
            contract_errors.append(error)
            logger.warning(
                "Failed to process contract %s: %s",
                contract_path,
                e,
            )
            # Continue with other contracts - don't fail everything for one bad contract

    # Log summary
    if contract_errors:
        logger.warning(
            "Contract errors (%d): %s",
            len(contract_errors),
            ", ".join(e.contract_path for e in contract_errors),
        )

    if infra_errors:
        logger.warning(
            "Infrastructure errors (%d): %s",
            len(infra_errors),
            ", ".join(e.error_type for e in infra_errors),
        )

    duration_ms = (time.monotonic() - start_time) * 1000

    logger.info(
        "Successfully published %d/%d handler contract(s) in %.1fms",
        len(published),
        len(contract_paths),
        duration_ms,
    )

    # Zero-contracts guard - only raise if truly no contracts found.
    # If contract_errors is non-empty, we DID find contracts - they just all failed validation.
    if not published and not contract_errors and not config.allow_zero_contracts:
        raise NoContractsFoundError(source_description)

    # Log when all contracts failed validation (distinct from "not found")
    if not published and contract_errors:
        logger.warning(
            "All %d contract(s) failed validation - none published",
            len(contract_errors),
        )

    # Fail-fast check for accumulated infra errors (when fail_fast=True but we got here)
    if infra_errors and config.fail_fast:
        raise ContractPublishingInfraError(infra_errors)

    return PublishResult(
        published=published,
        contract_errors=contract_errors,
        infra_errors=infra_errors,
        duration_ms=duration_ms,
    )


async def wire_omniclaude_services(
    container: ModelONEXContainer,
    config: ContractPublisherConfig | None = None,
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
        from omniclaude.runtime.contract_models import ContractPublisherConfig
        from pathlib import Path

        # During application bootstrap with explicit config
        container = ModelONEXContainer(...)
        config = ContractPublisherConfig(
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
                "No contract source configured. Either pass ContractPublisherConfig "
                "or set OMNICLAUDE_CONTRACTS_ROOT environment variable."
            )
        config = ContractPublisherConfig(
            mode="filesystem",
            filesystem_root=Path(contracts_root),
        )

    await publish_handler_contracts(container, config)
