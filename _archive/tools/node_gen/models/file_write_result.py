#!/usr/bin/env python3
"""
File write result models for node generation pipeline.

Models for tracking file write operations with rollback support.
"""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FileWriteResult(BaseModel):
    """Result of file writing operation.

    Tracks all files written, directories created, and any errors encountered.
    Used for validation and rollback operations.

    Attributes:
        success: Whether the write operation succeeded
        output_path: Base output directory for the node
        files_written: List of file paths written (relative to output_path)
        directories_created: List of directory paths created
        total_bytes: Total bytes written across all files
        error: Error message if operation failed
    """

    success: bool = Field(
        ...,
        description="Whether the file write operation succeeded",
    )

    output_path: str = Field(
        ...,
        description="Base output directory path for the generated node",
    )

    files_written: list[str] = Field(
        default_factory=list,
        description="List of file paths written (relative to output_path)",
    )

    directories_created: list[str] = Field(
        default_factory=list,
        description="List of directory paths created",
    )

    total_bytes: int = Field(
        default=0,
        description="Total bytes written across all files",
        ge=0,
    )

    error: str | None = Field(
        default=None,
        description="Error message if operation failed",
    )

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, v: str) -> str:
        """Validate output path is not empty."""
        if not v or not v.strip():
            raise ValueError("output_path cannot be empty")
        return v

    @field_validator("files_written", "directories_created")
    @classmethod
    def validate_paths(cls, v: list[str]) -> list[str]:
        """Validate paths are not empty strings."""
        if any(not path or not path.strip() for path in v):
            raise ValueError("Path list cannot contain empty strings")
        return v

    @property
    def file_count(self) -> int:
        """Number of files written."""
        return len(self.files_written)

    @property
    def directory_count(self) -> int:
        """Number of directories created."""
        return len(self.directories_created)

    def get_absolute_paths(self) -> list[Path]:
        """Get absolute paths for all written files.

        Returns:
            List of absolute Path objects for all written files
        """
        base = Path(self.output_path)
        return [base / file_path for file_path in self.files_written]

    model_config = ConfigDict(
        validate_assignment=True,
        extra="forbid",
        json_schema_extra={
            "example": {
                "success": True,
                "output_path": "/path/to/node_infrastructure_postgres_writer_effect",
                "files_written": [
                    "v1_0_0/node.py",
                    "v1_0_0/config.py",
                    "v1_0_0/models/model_postgres_writer_input.py",
                ],
                "directories_created": [
                    "v1_0_0",
                    "v1_0_0/models",
                    "v1_0_0/enums",
                ],
                "total_bytes": 45678,
                "error": None,
            }
        },
    )
