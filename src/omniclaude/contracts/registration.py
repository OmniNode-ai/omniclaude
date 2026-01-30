# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract-driven handler registration for OmniClaude.

This module provides automatic handler registration from contract definitions,
replacing manual wiring with a declarative approach.

The registration process:
1. Load contract YAML defining handler identity and binding
2. Dynamically import protocol and handler classes
3. Instantiate handler with container dependency
4. Register handler instance in ServiceRegistry

Manual Wiring vs Contract-Driven:
    Manual wiring (wiring.py) requires explicit imports and registration calls.
    Contract-driven registration reads YAML contracts and auto-registers handlers,
    enabling discovery-based handler loading without code changes.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

Usage:
    >>> from pathlib import Path
    >>> from omniclaude.contracts.registration import register_all_handlers
    >>>
    >>> # During application bootstrap
    >>> container = ModelONEXContainer(...)
    >>> reg_ids = await register_all_handlers(container, Path("contracts/handlers"))
    >>> print(f"Registered {len(reg_ids)} handlers")

See Also:
    - omniclaude.contracts.loader.ContractLoader: Contract discovery and loading
    - omniclaude.contracts.models.model_handler_contract.ModelHandlerContract: Contract schema
    - omniclaude.runtime.wiring: Manual wiring (will call this module in hybrid approach)
"""

from __future__ import annotations

import logging
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from omnibase_core.enums.enum_injection_scope import EnumInjectionScope

from omniclaude.contracts.loader import ContractLoader, ContractLoadError
from omniclaude.contracts.models.model_handler_contract import ModelHandlerContract

if TYPE_CHECKING:
    from omnibase_core.models.container.model_onex_container import ModelONEXContainer

logger = logging.getLogger(__name__)


class HandlerRegistrationError(Exception):
    """Raised when handler registration fails.

    This exception captures the context of a failed registration,
    including the contract that failed and the underlying cause.

    Attributes:
        message: Human-readable error description.
        contract: The contract that failed to register (if available).
        cause: The underlying exception that caused the failure.
    """

    def __init__(
        self,
        message: str,
        contract: ModelHandlerContract | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message describing what failed.
            contract: The contract that failed to register (if available).
            cause: The underlying exception that caused the failure.
        """
        super().__init__(message)
        self.contract = contract
        self.cause = cause


def _import_class(fully_qualified_name: str) -> type:
    """Dynamically import a class from its fully qualified name.

    Args:
        fully_qualified_name: Full Python path to the class.
            Format: "package.module.ClassName"

    Returns:
        The imported class.

    Raises:
        HandlerRegistrationError: If the module or class cannot be imported.

    Example:
        >>> cls = _import_class("omniclaude.handlers.my_handler.MyHandler")
        >>> instance = cls(container)
    """
    if not fully_qualified_name or "." not in fully_qualified_name:
        raise HandlerRegistrationError(
            f"Invalid fully qualified class name: '{fully_qualified_name}'. "
            f"Expected format: 'package.module.ClassName'"
        )

    # Split into module path and class name
    parts = fully_qualified_name.rsplit(".", 1)
    if len(parts) != 2:
        raise HandlerRegistrationError(
            f"Cannot parse class name from: '{fully_qualified_name}'. "
            f"Expected format: 'package.module.ClassName'"
        )

    module_path, class_name = parts

    # Import the module
    try:
        module = import_module(module_path)
    except ImportError as e:
        raise HandlerRegistrationError(
            f"Failed to import module '{module_path}': {e}. "
            f"Check that the module exists and all dependencies are installed.",
            cause=e,
        ) from e
    except Exception as e:
        raise HandlerRegistrationError(
            f"Unexpected error importing module '{module_path}': {e}",
            cause=e,
        ) from e

    # Get the class from the module
    try:
        cls = getattr(module, class_name)
    except AttributeError as e:
        available_attrs = [a for a in dir(module) if not a.startswith("_")]
        raise HandlerRegistrationError(
            f"Class '{class_name}' not found in module '{module_path}'. "
            f"Available names: {', '.join(available_attrs[:10])}{'...' if len(available_attrs) > 10 else ''}",
            cause=e,
        ) from e

    # Verify it's actually a class (or at least callable)
    if not isinstance(cls, type):
        logger.warning(
            "Imported '%s' is not a class (type: %s). "
            "Proceeding anyway as it may be a Protocol or typing construct.",
            fully_qualified_name,
            type(cls).__name__,
        )

    return cls


async def register_handler_from_contract(
    container: ModelONEXContainer,
    contract: ModelHandlerContract,
) -> UUID:
    """Register a single handler from its contract definition.

    This function performs contract-driven handler registration:
    1. Dynamically imports the protocol interface from contract.protocol
    2. Dynamically imports the handler class from contract.handler_class
    3. Instantiates the handler with container as sole argument
    4. Registers the instance in ServiceRegistry against the protocol

    Constructor Signature:
        All handlers must accept `container` as their sole constructor argument:
            def __init__(self, container: ModelONEXContainer) -> None: ...

    Lazy Loading:
        If contract.lazy_load is True, a warning is logged. Lazy loading is
        not yet implemented (OMN-1716). The handler is registered eagerly.

    Args:
        container: The ONEX container with ServiceRegistry for DI bindings.
        contract: The handler contract defining binding information.

    Returns:
        UUID of the registration in ServiceRegistry.

    Raises:
        HandlerRegistrationError: If protocol or handler import fails.
        HandlerRegistrationError: If handler instantiation fails.
        HandlerRegistrationError: If registration fails.

    Example:
        >>> contract = ModelHandlerContract(
        ...     handler_id="effect.pattern.storage.postgres",
        ...     handler_class="omniclaude.handlers.HandlerPatternStorage",
        ...     protocol="omniclaude.protocols.ProtocolPatternPersistence",
        ...     handler_key="postgresql",
        ...     ...
        ... )
        >>> reg_id = await register_handler_from_contract(container, contract)
        >>> print(f"Registered with ID: {reg_id}")
    """
    handler_id = contract.handler_id
    handler_key = contract.handler_key
    version = str(contract.contract_version)

    logger.info(
        "Registering handler from contract: %s (key=%s, version=%s)",
        handler_id,
        handler_key,
        version,
    )

    # Check for lazy loading (not yet implemented)
    if contract.lazy_load:
        logger.warning(
            "Lazy loading not yet supported, using eager loading. "
            "Handler: %s. See OMN-1716 for lazy loading implementation.",
            handler_id,
        )

    # 1. Import the protocol interface
    logger.debug("Importing protocol: %s", contract.protocol)
    try:
        protocol_class = _import_class(contract.protocol)
    except HandlerRegistrationError as e:
        raise HandlerRegistrationError(
            f"Failed to import protocol for handler '{handler_id}': {e}",
            contract=contract,
            cause=e.cause,
        ) from e

    # 2. Import the handler class
    logger.debug("Importing handler class: %s", contract.handler_class)
    try:
        handler_class = _import_class(contract.handler_class)
    except HandlerRegistrationError as e:
        raise HandlerRegistrationError(
            f"Failed to import handler class for '{handler_id}': {e}",
            contract=contract,
            cause=e.cause,
        ) from e

    # 3. Instantiate the handler with container
    logger.debug("Instantiating handler: %s", contract.handler_class)
    try:
        handler_instance = handler_class(container)
    except TypeError as e:
        raise HandlerRegistrationError(
            f"Handler '{contract.handler_class}' constructor failed. "
            f"Expected signature: __init__(self, container: ModelONEXContainer). "
            f"Error: {e}",
            contract=contract,
            cause=e,
        ) from e
    except Exception as e:
        raise HandlerRegistrationError(
            f"Failed to instantiate handler '{contract.handler_class}': {e}",
            contract=contract,
            cause=e,
        ) from e

    # 4. Register with ServiceRegistry
    protocol_name = (
        protocol_class.__name__
        if hasattr(protocol_class, "__name__")
        else contract.protocol
    )
    logger.debug(
        "Registering handler instance: %s -> %s",
        protocol_name,
        type(handler_instance).__name__,
    )
    try:
        registration_id = await container.service_registry.register_instance(
            interface=protocol_class,  # type: ignore[type-abstract]
            instance=handler_instance,
            scope=EnumInjectionScope.GLOBAL,
            metadata={
                "handler_key": handler_key,
                "handler_id": handler_id,
                "version": version,
                "contract_name": contract.name,
            },
        )
    except Exception as e:
        raise HandlerRegistrationError(
            f"Failed to register handler '{handler_id}' in ServiceRegistry: {e}",
            contract=contract,
            cause=e,
        ) from e

    logger.info(
        "Handler registered successfully: %s (registration_id=%s)",
        handler_id,
        registration_id,
    )

    return registration_id


async def register_all_handlers(
    container: ModelONEXContainer,
    contracts_root: Path | None = None,
) -> list[UUID]:
    """Register all handlers from contracts directory.

    This function discovers and loads all handler contracts, then registers
    each handler in the container's ServiceRegistry.

    Contract Discovery:
        Contracts are discovered from the contracts_root directory using
        ContractLoader. Each subdirectory should contain a contract.yaml file.

    Default Contracts Root:
        If contracts_root is None, defaults to "contracts/handlers" relative
        to the current working directory.

    Fail-Fast Behavior:
        If any contract fails to load or any handler fails to register,
        the function raises immediately. Partial registration state may exist.

    Args:
        container: The ONEX container with ServiceRegistry for DI bindings.
        contracts_root: Root directory containing handler contracts.
            Defaults to "contracts/handlers" relative to current directory.

    Returns:
        List of registration UUIDs for all registered handlers.

    Raises:
        ContractLoadError: If any contract fails to load or validate.
        HandlerRegistrationError: If any handler fails to register.

    Example:
        >>> container = await create_model_onex_container()
        >>> reg_ids = await register_all_handlers(container)
        >>> print(f"Registered {len(reg_ids)} handlers")

        # With custom contracts directory
        >>> reg_ids = await register_all_handlers(
        ...     container,
        ...     contracts_root=Path("/custom/contracts/handlers"),
        ... )
    """
    # Determine contracts root
    if contracts_root is None:
        # Default to contracts/handlers relative to current directory
        contracts_root = Path("contracts/handlers")

    logger.info("Loading handler contracts from: %s", contracts_root)

    # Load all contracts using ContractLoader
    loader = ContractLoader(contracts_root)

    try:
        contracts = loader.load_all_contracts()
    except ContractLoadError:
        # Re-raise contract load errors as-is
        raise

    if not contracts:
        logger.info("No handler contracts found to register")
        return []

    logger.info("Registering %d handler(s) from contracts", len(contracts))

    # Register each handler
    registration_ids: list[UUID] = []

    for contract in contracts:
        reg_id = await register_handler_from_contract(container, contract)
        registration_ids.append(reg_id)

    logger.info(
        "Successfully registered %d handler(s) from contracts",
        len(registration_ids),
    )

    return registration_ids


__all__ = [
    "HandlerRegistrationError",
    "register_all_handlers",
    "register_handler_from_contract",
]
