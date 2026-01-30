# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Service wiring for omniclaude handlers.

This module publishes handler contracts to Kafka for discovery by the platform's
KafkaContractSource. Handler instantiation is handled by omnibase_infra's
ServiceRuntimeHostProcess.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

Event-Driven Wiring Strategy:
    1. Read handler contracts from contracts/handlers/**/contract.yaml
    2. Emit ModelContractRegisteredEvent to Kafka for each handler
    3. KafkaContractSource (in omnibase_infra) caches the descriptors
    4. ServiceRuntimeHostProcess imports, instantiates, and initializes handlers

This replaces the previous filesystem-based registration approach with
platform-native event-driven discovery.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import yaml

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PublishResult:
    """Result of publishing handler contracts to Kafka.

    Attributes:
        published: Handler IDs that were successfully published.
        failed: Contract paths/names that failed to publish or were skipped.
    """

    published: list[str]
    failed: list[str]


# Default contracts directory relative to repo root
DEFAULT_CONTRACTS_SUBPATH = "contracts/handlers"


async def publish_handler_contracts(
    container: ModelONEXContainer,
    contracts_root: Path | None = None,
    environment: str | None = None,
) -> PublishResult:
    """Publish handler contracts to Kafka for discovery.

    Emits ModelContractRegisteredEvent for each handler contract found in
    the contracts directory. The events are consumed by KafkaContractSource
    in omnibase_infra for handler discovery and registration.

    Contracts are skipped (added to failed list) if:
        - The contract file is not a valid YAML dict
        - The contract is missing a handler_id
        - The handler_class is present but not fully qualified (no '.')

    Args:
        container: The ONEX container with event bus publisher.
        contracts_root: Root directory containing handler contracts.
            Defaults to contracts/handlers relative to repo root.
        environment: Environment prefix for Kafka topics (e.g., "dev").
            Defaults to ONEX_ENV environment variable or "dev".

    Returns:
        PublishResult with published handler IDs and failed contract paths.

    Raises:
        ImportError: If omnibase_core event models are not available.

    Example:
        >>> container = ModelONEXContainer(...)
        >>> result = await publish_handler_contracts(container)
        >>> print(f"Published {len(result.published)} contracts")
        >>> if result.failed:
        ...     print(f"Failed: {result.failed}")
    """
    # Import here to avoid circular imports and allow graceful degradation
    try:
        from omnibase_core.models.events.contract_registration import (
            TOPIC_SUFFIX_CONTRACT_REGISTERED,
            ModelContractRegisteredEvent,
        )
        from omnibase_core.models.primitives.model_semver import ModelSemVer
    except ImportError as e:
        logger.warning(
            "Contract registration events not available (omnibase_core >= 0.9.10 required): %s",
            e,
        )
        raise

    # Resolve contracts root
    if contracts_root is None:
        # Default: repo_root/contracts/handlers
        # Path: src/omniclaude/runtime/wiring.py -> ../../../../contracts/handlers
        contracts_root = (
            Path(__file__).parent.parent.parent.parent / DEFAULT_CONTRACTS_SUBPATH
        )

    # Resolve environment
    if environment is None:
        environment = os.getenv("ONEX_ENV", "dev")

    if not contracts_root.exists():
        logger.warning(
            "Contracts directory does not exist: %s. No handlers will be published.",
            contracts_root,
        )
        return PublishResult(published=[], failed=[])

    # Discover contract files
    contract_paths: list[Path] = sorted(contracts_root.glob("**/contract.yaml"))
    if not contract_paths:
        logger.info("No handler contracts found in %s", contracts_root)
        return PublishResult(published=[], failed=[])

    logger.info(
        "Publishing %d handler contract(s) from %s",
        len(contract_paths),
        contracts_root,
    )

    # Get event bus publisher from container
    try:
        publisher = await container.get_service_async("ProtocolEventBusPublisher")
    except Exception as e:
        logger.warning(
            "Failed to get event bus publisher from container: %s",
            e,
        )
        raise

    # Build topic name
    topic = f"{environment}.{TOPIC_SUFFIX_CONTRACT_REGISTERED}"

    published: list[str] = []
    failed: list[str] = []
    for contract_path in contract_paths:
        try:
            # Read contract YAML
            contract_yaml = contract_path.read_text(encoding="utf-8")
            contract_data = yaml.safe_load(contract_yaml)

            if not isinstance(contract_data, dict):
                logger.warning(
                    "Skipping invalid contract (not a dict): %s",
                    contract_path,
                )
                failed.append(contract_path.parent.name)
                continue

            # Extract identity fields - validate handler_id to avoid empty Kafka keys
            handler_id = contract_data.get("handler_id", "")
            if not isinstance(handler_id, str) or not handler_id.strip():
                logger.warning(
                    "Skipping contract with missing or invalid handler_id: %s",
                    contract_path,
                )
                failed.append(contract_path.parent.name)
                continue
            # Use stripped version to avoid whitespace-only keys
            handler_id = handler_id.strip()

            # Validate handler_class format if present (required for KafkaContractSource)
            metadata = contract_data.get("metadata", {})
            handler_class = metadata.get("handler_class", "")
            if handler_class and "." not in handler_class:
                logger.warning(
                    "Skipping contract with invalid handler_class (must be fully qualified with '.'): %s in %s",
                    handler_class,
                    contract_path,
                )
                failed.append(contract_path.parent.name)
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

            # Compute hash for change detection
            contract_hash = hashlib.sha256(contract_yaml.encode("utf-8")).hexdigest()

            # Create registration event
            event = ModelContractRegisteredEvent(
                event_id=uuid4(),
                node_name=handler_id,
                node_version=version,
                contract_hash=contract_hash,
                contract_yaml=contract_yaml,
            )

            # Publish to Kafka
            await publisher.publish(
                topic=topic,
                key=handler_id.encode("utf-8"),
                value=event.model_dump_json().encode("utf-8"),
            )

            published.append(handler_id)
            logger.info(
                "Published handler contract: %s [%s] (v%s) to %s",
                name,
                handler_id,
                version,
                topic,
            )

        except Exception as e:
            contract_name = contract_path.parent.name
            failed.append(contract_name)
            logger.warning(
                "Failed to publish contract %s: %s",
                contract_path,
                e,
            )
            # Continue with other contracts - don't fail everything for one bad contract

    if failed:
        logger.warning(
            "Failed to publish %d contract(s): %s",
            len(failed),
            ", ".join(failed),
        )

    logger.info(
        "Successfully published %d/%d handler contract(s)",
        len(published),
        len(contract_paths),
    )

    return PublishResult(published=published, failed=failed)


async def wire_omniclaude_services(container: ModelONEXContainer) -> None:
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

    Example:
        from omniclaude.runtime import wire_omniclaude_services

        # During application bootstrap
        container = ModelONEXContainer(...)
        await wire_omniclaude_services(container)
    """
    await publish_handler_contracts(container)
