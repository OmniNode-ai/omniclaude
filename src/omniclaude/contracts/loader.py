# SPDX-License-Identifier: MIT
# Copyright (c) 2025 OmniNode Team
"""Contract Loader for OmniClaude handlers.

This module provides the ContractLoader class that discovers and validates
handler contracts from the contracts directory.

Ticket: OMN-1605 - Implement contract-driven handler registration loader

Usage:
    >>> from pathlib import Path
    >>> from omniclaude.contracts.loader import ContractLoader
    >>>
    >>> loader = ContractLoader(Path("contracts/handlers"))
    >>> contracts = loader.load_all_contracts()
    >>> for contract in contracts:
    ...     print(f"Loaded: {contract.handler_id}")
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from pydantic import ValidationError

from omniclaude.contracts.models.model_handler_contract import ModelHandlerContract

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ContractLoadError(Exception):
    """Raised when a contract fails to load or validate.

    Attributes:
        path: Path to the contract file that failed.
        cause: The underlying exception that caused the failure.
    """

    def __init__(
        self, message: str, path: Path, cause: Exception | None = None
    ) -> None:
        """Initialize the error.

        Args:
            message: Error message.
            path: Path to the contract file.
            cause: The underlying exception.
        """
        super().__init__(message)
        self.path = path
        self.cause = cause


class ContractLoader:
    """Loader for handler contracts.

    This class discovers and validates handler contracts from a contracts directory.
    It scans for `contract.yaml` files in subdirectories and validates them against
    the ModelHandlerContract schema.

    Attributes:
        contracts_root: Root directory for contract discovery.

    Example:
        >>> loader = ContractLoader(Path("contracts/handlers"))
        >>> # Discover all contract files
        >>> paths = loader.discover_contracts()
        >>> # Load and validate a single contract
        >>> contract = loader.load_contract(paths[0])
        >>> # Load all contracts at once
        >>> all_contracts = loader.load_all_contracts()
    """

    GLOB_PATTERN = "**/contract.yaml"
    """Glob pattern for discovering contract files."""

    def __init__(self, contracts_root: Path) -> None:
        """Initialize the contract loader.

        Args:
            contracts_root: Root directory containing handler contracts.
                Expected structure: contracts_root/<handler_name>/contract.yaml
        """
        self._contracts_root = contracts_root
        logger.debug("ContractLoader initialized with root: %s", contracts_root)

    @property
    def contracts_root(self) -> Path:
        """Return the contracts root directory."""
        return self._contracts_root

    def discover_contracts(self) -> list[Path]:
        """Discover all contract.yaml files in the contracts directory.

        Returns:
            List of paths to contract.yaml files, sorted alphabetically.
            Returns empty list if contracts directory does not exist.

        Example:
            >>> loader = ContractLoader(Path("contracts/handlers"))
            >>> paths = loader.discover_contracts()
            >>> print(paths)
            [PosixPath('contracts/handlers/foo/contract.yaml'),
             PosixPath('contracts/handlers/bar/contract.yaml')]
        """
        if not self._contracts_root.exists():
            logger.warning(
                "Contracts directory does not exist: %s",
                self._contracts_root,
            )
            return []

        if not self._contracts_root.is_dir():
            logger.warning(
                "Contracts path is not a directory: %s",
                self._contracts_root,
            )
            return []

        discovered = sorted(self._contracts_root.glob(self.GLOB_PATTERN))
        logger.info(
            "Discovered %d contract(s) in %s",
            len(discovered),
            self._contracts_root,
        )

        for path in discovered:
            logger.debug("  - %s", path.relative_to(self._contracts_root))

        return discovered

    def load_contract(self, path: Path) -> ModelHandlerContract:
        """Load and validate a single contract from a YAML file.

        Args:
            path: Path to the contract.yaml file.

        Returns:
            Validated ModelHandlerContract instance.

        Raises:
            ContractLoadError: If the file cannot be read or parsed.
            ContractLoadError: If the contract fails validation.

        Example:
            >>> loader = ContractLoader(Path("contracts/handlers"))
            >>> contract = loader.load_contract(
            ...     Path("contracts/handlers/foo/contract.yaml")
            ... )
            >>> print(contract.handler_id)
            'effect.foo.handler'
        """
        logger.debug("Loading contract from: %s", path)

        # Read and parse YAML
        try:
            with open(path, encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except FileNotFoundError as e:
            raise ContractLoadError(
                f"Contract file not found: {path}",
                path=path,
                cause=e,
            ) from e
        except yaml.YAMLError as e:
            raise ContractLoadError(
                f"Invalid YAML in contract file: {path}",
                path=path,
                cause=e,
            ) from e

        if raw_data is None:
            raise ContractLoadError(
                f"Contract file is empty: {path}",
                path=path,
            )

        if not isinstance(raw_data, dict):
            raise ContractLoadError(
                f"Contract must be a YAML mapping, got {type(raw_data).__name__}: {path}",
                path=path,
            )

        # Validate against Pydantic model
        try:
            contract = ModelHandlerContract.model_validate(raw_data)
        except ValidationError as e:
            # Format validation errors for clarity
            error_details = []
            for error in e.errors():
                loc = ".".join(str(x) for x in error["loc"])
                msg = error["msg"]
                error_details.append(f"  - {loc}: {msg}")

            raise ContractLoadError(
                f"Contract validation failed for {path}:\n" + "\n".join(error_details),
                path=path,
                cause=e,
            ) from e

        logger.info(
            "Loaded contract: %s (v%s) from %s",
            contract.handler_id,
            contract.contract_version,
            path.name,
        )

        return contract

    def load_all_contracts(self) -> list[ModelHandlerContract]:
        """Load and validate all contracts from the contracts directory.

        This method discovers all contract files and loads them, failing fast
        on any validation error.

        Returns:
            List of validated ModelHandlerContract instances.
            Returns empty list if no contracts are found.

        Raises:
            ContractLoadError: If any contract fails to load or validate.
                The error includes the path to the failing contract.

        Example:
            >>> loader = ContractLoader(Path("contracts/handlers"))
            >>> contracts = loader.load_all_contracts()
            >>> for c in contracts:
            ...     print(f"{c.handler_id}: {c.name}")
        """
        paths = self.discover_contracts()

        if not paths:
            logger.info("No contracts found to load")
            return []

        contracts: list[ModelHandlerContract] = []
        logger.info("Loading %d contract(s)...", len(paths))

        for path in paths:
            # Fail fast on first error
            contract = self.load_contract(path)
            contracts.append(contract)

        logger.info(
            "Successfully loaded %d contract(s)",
            len(contracts),
        )

        return contracts


__all__ = [
    "ContractLoadError",
    "ContractLoader",
]
