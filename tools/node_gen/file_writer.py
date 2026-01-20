#!/usr/bin/env python3
"""
FileWriter component for atomic file operations with rollback.

Provides transactional file writing with automatic cleanup on failure.
Supports ONEX directory structure generation for node files.
"""

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from omnibase_core.enums.enum_core_error_code import EnumCoreErrorCode
from omnibase_core.models.errors.model_onex_error import ModelOnexError

from .models.file_write_result import FileWriteResult

logger = logging.getLogger(__name__)


class FileWriter:
    """Atomic file writer with rollback support.

    Writes node files atomically with automatic cleanup on failure.
    Tracks all created paths for rollback operations.

    Features:
    - Atomic writes using temporary files
    - Automatic rollback on exception
    - Directory structure creation
    - Write verification
    - Collision detection

    Example:
        ```python
        writer = FileWriter(enable_rollback=True)

        with writer.atomic_write_context():
            result = writer.write_node_files(
                output_directory="/path/to/output",
                node_name="DatabaseWriter",
                node_type="EFFECT",
                domain="data_services",
                files={
                    "v1_0_0/node.py": "...",
                    "v1_0_0/config.py": "...",
                }
            )
        # Automatic rollback on exception
        ```

    Attributes:
        enable_rollback: Whether to enable automatic rollback on errors
        _created_paths: List of paths created during write operation
    """

    def __init__(self, enable_rollback: bool = True) -> None:
        """Initialize FileWriter.

        Args:
            enable_rollback: Enable automatic rollback on errors (default: True)
        """
        self.enable_rollback = enable_rollback
        self._created_paths: list[Path] = []
        self._logger = logger

    @contextmanager
    def atomic_write_context(self) -> Generator["FileWriter", None, None]:
        """Context manager for atomic writes with rollback.

        Automatically rolls back all file operations if an exception occurs.

        Yields:
            Self reference for chaining operations

        Example:
            ```python
            with writer.atomic_write_context():
                result = writer.write_node_files(...)
            # Rollback on exception
            ```
        """
        try:
            yield self
        except Exception as e:
            if self.enable_rollback:
                self._logger.warning(f"Exception during write operation, rolling back: {e}")
                self.rollback()
            raise
        finally:
            # Always clear tracking list
            self._created_paths.clear()

    def write_node_files(
        self,
        output_directory: str,
        node_name: str,
        node_type: str,
        domain: str,
        files: dict[str, str],
        allow_overwrite: bool = False,
    ) -> FileWriteResult:
        """Write node files atomically with rollback support.

        Creates ONEX-compliant directory structure and writes all node files.
        Validates directory permissions, detects collisions, and verifies writes.

        Args:
            output_directory: Base output directory path
            node_name: Node name (e.g., "DatabaseWriter")
            node_type: Node type suffix (e.g., "EFFECT")
            domain: Domain classification (e.g., "data_services")
            files: Dictionary mapping relative paths to file contents
            allow_overwrite: Allow overwriting existing files (default: False)

        Returns:
            FileWriteResult with operation details and written paths

        Raises:
            ModelOnexError: If validation fails or write operation errors

        Example:
            ```python
            result = writer.write_node_files(
                output_directory="/output",
                node_name="PostgresWriter",
                node_type="EFFECT",
                domain="infrastructure",
                files={
                    "v1_0_0/node.py": "class Node...",
                    "v1_0_0/models/model_input.py": "class Model...",
                }
            )
            ```
        """
        try:
            # Validate inputs
            if not files:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.VALIDATION_FAILED,
                    message="No files provided for writing",
                    context={
                        "node_name": node_name,
                        "node_type": node_type,
                        "domain": domain,
                    },
                )

            # Create node directory name following ONEX convention
            node_dir_name = self._create_node_directory_name(
                domain=domain, node_name=node_name, node_type=node_type
            )

            # Prepare paths
            output_path = Path(output_directory).resolve()
            node_path = output_path / node_dir_name

            # Validate output directory
            self._validate_output_directory(output_path)

            # Prepare full paths for collision detection
            file_paths = [node_path / relative_path for relative_path in files]

            # Check for file collisions
            if not allow_overwrite:
                self._check_file_collisions(file_paths)

            # Track created directories and files
            directories_created: list[str] = []
            files_written: list[str] = []
            total_bytes = 0

            # Create node directory
            if not node_path.exists():
                node_path.mkdir(parents=True, exist_ok=True)
                self._created_paths.append(node_path)
                directories_created.append(str(node_path.relative_to(output_path)))
                self._logger.debug(f"Created node directory: {node_path}")

            # Write all files
            for relative_path, content in files.items():
                full_path = node_path / relative_path

                # Create parent directories
                parent_dir = full_path.parent
                if not parent_dir.exists():
                    parent_dir.mkdir(parents=True, exist_ok=True)
                    self._created_paths.append(parent_dir)
                    rel_dir = str(parent_dir.relative_to(output_path))
                    if rel_dir not in directories_created:
                        directories_created.append(rel_dir)
                    self._logger.debug(f"Created directory: {parent_dir}")

                # Write file atomically
                self._write_file(full_path, content)
                self._created_paths.append(full_path)

                # Verify write
                if not self._verify_write(full_path, content):
                    raise ModelOnexError(
                        error_code=EnumCoreErrorCode.OPERATION_FAILED,
                        message=f"Write verification failed for {relative_path}",
                        context={"file_path": str(full_path)},
                    )

                # Track written file
                files_written.append(relative_path)
                total_bytes += len(content.encode("utf-8"))
                self._logger.debug(
                    f"Wrote file: {full_path} ({len(content.encode('utf-8'))} bytes)"
                )

            # Return success result
            return FileWriteResult(
                success=True,
                output_path=str(node_path),
                files_written=files_written,
                directories_created=directories_created,
                total_bytes=total_bytes,
                error=None,
            )

        except ModelOnexError:
            raise
        except Exception as e:
            self._logger.error(f"Unexpected error writing node files: {e}")
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to write node files: {str(e)}",
                context={
                    "node_name": node_name,
                    "node_type": node_type,
                    "domain": domain,
                    "file_count": len(files),
                },
            ) from e

    def rollback(self) -> None:
        """Delete all created files and directories.

        Rolls back file operations by deleting all tracked paths in reverse order.
        Handles errors gracefully by logging warnings without raising exceptions.

        Files are deleted before directories to ensure clean removal.
        """
        if not self._created_paths:
            self._logger.debug("No paths to rollback")
            return

        self._logger.info(f"Rolling back {len(self._created_paths)} paths")

        # Reverse order: delete files before directories
        for path in reversed(self._created_paths):
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                        self._logger.debug(f"Deleted file: {path}")
                    elif path.is_dir():
                        # Only delete if empty
                        if not any(path.iterdir()):
                            path.rmdir()
                            self._logger.debug(f"Deleted empty directory: {path}")
                        else:
                            self._logger.warning(f"Directory not empty, skipping: {path}")
            except Exception as e:
                # Log but don't raise during rollback
                self._logger.warning(f"Failed to delete {path} during rollback: {e}")

        self._logger.info("Rollback complete")

    def _create_node_directory_name(self, domain: str, node_name: str, node_type: str) -> str:
        """Create ONEX-compliant node directory name.

        Follows pattern: node_{domain}_{name}_{type}

        Args:
            domain: Domain classification
            node_name: Node name in PascalCase
            node_type: Node type suffix (EFFECT, COMPUTE, etc.)

        Returns:
            Directory name in snake_case
        """
        # Convert PascalCase to snake_case
        import re

        name_snake = re.sub(r"(?<!^)(?=[A-Z])", "_", node_name).lower()
        return f"node_{domain}_{name_snake}_{node_type.lower()}"

    def _validate_output_directory(self, path: Path) -> None:
        """Ensure output directory is writable.

        Args:
            path: Output directory path

        Raises:
            ModelOnexError: If directory doesn't exist or isn't writable
        """
        if not path.exists():
            # Try to create it
            try:
                path.mkdir(parents=True, exist_ok=True)
                self._logger.debug(f"Created output directory: {path}")
            except Exception as e:
                raise ModelOnexError(
                    error_code=EnumCoreErrorCode.INVALID_INPUT,
                    message=f"Cannot create output directory: {path}",
                    context={"path": str(path), "error": str(e)},
                ) from e

        if not path.is_dir():
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.INVALID_INPUT,
                message=f"Output path is not a directory: {path}",
                context={"path": str(path)},
            )

        if not os.access(path, os.W_OK):
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.INVALID_INPUT,
                message=f"Output directory is not writable: {path}",
                context={"path": str(path)},
            )

    def _check_file_collisions(self, paths: list[Path]) -> None:
        """Ensure no files will be overwritten.

        Args:
            paths: List of file paths to check

        Raises:
            ModelOnexError: If any files already exist
        """
        existing_files = [str(p) for p in paths if p.exists()]

        if existing_files:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.INVALID_INPUT,
                message=f"File collision detected: {len(existing_files)} files already exist",
                context={
                    "existing_files": existing_files[:10],  # Limit to first 10
                    "total_collisions": len(existing_files),
                },
            )

    def _write_file(self, path: Path, content: str) -> None:
        """Write single file with tracking.

        Uses atomic write with temporary file and rename.

        Args:
            path: File path to write
            content: File content

        Raises:
            ModelOnexError: If write fails
        """
        try:
            # Write to temporary file first
            temp_path = path.with_suffix(path.suffix + ".tmp")

            # Write content
            temp_path.write_text(content, encoding="utf-8")

            # Atomic rename (on Unix-like systems)
            temp_path.replace(path)

        except Exception as e:
            raise ModelOnexError(
                error_code=EnumCoreErrorCode.OPERATION_FAILED,
                message=f"Failed to write file: {path}",
                context={"path": str(path), "error": str(e)},
            ) from e

    def _verify_write(self, path: Path, expected_content: str) -> bool:
        """Verify file was written correctly.

        Args:
            path: File path to verify
            expected_content: Expected file content

        Returns:
            True if file exists and content matches
        """
        try:
            if not path.exists():
                self._logger.error(f"File does not exist after write: {path}")
                return False

            actual_content = path.read_text(encoding="utf-8")

            if actual_content != expected_content:
                self._logger.error(
                    f"Content mismatch for {path}: "
                    f"expected {len(expected_content)} bytes, "
                    f"got {len(actual_content)} bytes"
                )
                return False

            return True

        except Exception as e:
            self._logger.error(f"Failed to verify write for {path}: {e}")
            return False
