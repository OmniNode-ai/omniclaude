#!/usr/bin/env python3
"""Automated import migration from omnibase_3 to omniclaude/omnibase_core."""

import re
from pathlib import Path

# Import migration mapping
IMPORT_MIGRATIONS: dict[str, str] = {
    # Base classes
    "from omnibase.core.node_base import NodeBase": "from omnibase_core.core.infrastructure_service_bases import NodeCoreBase",
    "from omnibase.protocol.protocol_ast_builder import ProtocolASTBuilder": "# Removed: ProtocolASTBuilder not needed",
    # Container
    "from omnibase.core.onex_container import ONEXContainer": "from omnibase_core.models.container.model_onex_container import ModelONEXContainer",
    # Errors
    "from omnibase.exceptions import OnexError": "from omnibase_core.errors.model_onex_error import ModelOnexError",
    "from omnibase.core.core_error_codes import CoreErrorCode": "from omnibase_core.errors.error_codes import EnumCoreErrorCode",
    # Models
    "from omnibase.model.core.model_schema import ModelSchema": "from omnibase_core.models.contracts.model_contract_base import ModelContractBase",
    "from omnibase.model.core.model_semver import ModelSemVer": "from omnibase_core.primitives.model_semver import ModelSemVer",
    # Logging
    "from omnibase.core.core_structured_logging import emit_log_event_sync as emit_log_event": "import logging",
    "from omnibase.core.core_structured_logging import emit_log_event_sync": "import logging",
    "from omnibase.enums.enum_log_level import LogLevelEnum": "# Removed: Using standard logging levels",
}

# Class name migrations
CLASS_MIGRATIONS: dict[str, str] = {
    "OnexError": "ModelOnexError",
    "CoreErrorCode": "EnumCoreErrorCode",
    "ONEXContainer": "ModelONEXContainer",
    "ModelSchema": "ModelContractBase",
}


def migrate_file(file_path: Path, dry_run: bool = False) -> None:
    """Migrate imports in a single file.

    Args:
        file_path: Path to file to migrate
        dry_run: If True, only show changes without writing
    """
    content = file_path.read_text(encoding="utf-8")
    original_content = content

    # Migrate imports
    for old_import, new_import in IMPORT_MIGRATIONS.items():
        content = content.replace(old_import, new_import)

    # Migrate class names (in code, not imports)
    for old_class, new_class in CLASS_MIGRATIONS.items():
        # Only replace in code, not in import statements
        content = re.sub(
            rf"\b{old_class}\b(?!.*import)",
            new_class,
            content,
        )

    # Remove "Utility" prefix from class names
    content = re.sub(
        r"class\s+Utility([A-Z]\w+)",
        r"class \1",
        content,
    )

    # Update emit_log_event to logger
    content = content.replace(
        "emit_log_event_sync(",
        "logger.info(",
    )
    content = content.replace(
        "emit_log_event(",
        "logger.info(",
    )

    # Replace LogLevelEnum usage
    content = re.sub(
        r"LogLevelEnum\.(\w+)",
        lambda m: f"logging.{m.group(1)}",
        content,
    )

    if content != original_content:
        if dry_run:
            print(f"Would migrate: {file_path}")
            # Show diff
            import difflib

            diff = difflib.unified_diff(
                original_content.splitlines(),
                content.splitlines(),
                fromfile=str(file_path),
                tofile=f"{file_path} (migrated)",
                lineterm="",
            )
            print("\n".join(diff))
        else:
            file_path.write_text(content)
            print(f"Migrated: {file_path}")
    else:
        print(f"No changes: {file_path}")


def migrate_directory(directory: Path, dry_run: bool = False) -> None:
    """Migrate all Python files in directory.

    Args:
        directory: Directory containing files to migrate
        dry_run: If True, only show changes without writing
    """
    for file_path in directory.glob("*.py"):
        if file_path.name != "__init__.py":
            migrate_file(file_path, dry_run=dry_run)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Migrate omnibase_3 imports")
    parser.add_argument("path", type=Path, help="File or directory to migrate")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show changes without writing"
    )

    args = parser.parse_args()

    if args.path.is_file():
        migrate_file(args.path, dry_run=args.dry_run)
    elif args.path.is_dir():
        migrate_directory(args.path, dry_run=args.dry_run)
    else:
        print(f"Error: {args.path} is not a file or directory")
