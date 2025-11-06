#!/usr/bin/env python3
"""
Migration Utility: Correlation Manager → Memory Client

Migrates existing correlation manager state to the new memory client.

Migration Strategy:
1. Read correlation state files from ~/.claude/hooks/.state/
2. Convert to memory client format
3. Store in appropriate categories
4. Validate migration
5. Create backup of original data

Usage:
    python migrate_to_memory.py [--dry-run] [--backup] [--verbose]

Options:
    --dry-run: Preview migration without making changes
    --backup: Create backup before migration (default: True)
    --verbose: Detailed logging
"""

import argparse
import asyncio
import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_client import get_memory_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CorrelationMigrator:
    """Migrates correlation manager data to memory client"""

    def __init__(self, dry_run: bool = False, create_backup: bool = True):
        """
        Initialize migrator

        Args:
            dry_run: Preview migration without making changes
            create_backup: Create backup before migration
        """
        self.dry_run = dry_run
        self.create_backup = create_backup

        self.state_dir = Path.home() / ".claude" / "hooks" / ".state"
        self.backup_dir = Path.home() / ".claude" / "hooks" / ".state_backup"

        self.migration_stats = {
            "files_found": 0,
            "files_migrated": 0,
            "files_skipped": 0,
            "files_failed": 0,
            "memories_created": 0
        }

    async def migrate(self) -> Dict[str, Any]:
        """
        Run migration

        Returns:
            Migration statistics
        """
        logger.info("=" * 70)
        logger.info("Correlation Manager → Memory Client Migration")
        logger.info("=" * 70)
        logger.info(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        logger.info(f"Backup: {'Enabled' if self.create_backup else 'Disabled'}")
        logger.info("")

        # Check if state directory exists
        if not self.state_dir.exists():
            logger.warning(f"State directory not found: {self.state_dir}")
            logger.info("No migration needed - correlation manager not in use")
            return self.migration_stats

        # Create backup
        if self.create_backup and not self.dry_run:
            await self._create_backup()

        # Find all state files
        state_files = list(self.state_dir.glob("*.json"))
        self.migration_stats["files_found"] = len(state_files)

        logger.info(f"Found {len(state_files)} state files to migrate")
        logger.info("")

        # Migrate each file
        for state_file in state_files:
            await self._migrate_file(state_file)

        # Print summary
        self._print_summary()

        return self.migration_stats

    async def _create_backup(self) -> None:
        """Create backup of state directory"""
        try:
            if self.backup_dir.exists():
                shutil.rmtree(self.backup_dir)

            shutil.copytree(self.state_dir, self.backup_dir)
            logger.info(f"✅ Created backup: {self.backup_dir}")
            logger.info("")

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            raise

    async def _migrate_file(self, file_path: Path) -> None:
        """Migrate a single state file"""
        try:
            # Read state file
            with open(file_path, 'r') as f:
                state_data = json.load(f)

            logger.info(f"Migrating: {file_path.name}")

            # Determine how to migrate based on file type
            if file_path.name == "correlation_id.json":
                await self._migrate_correlation_context(state_data)
            elif file_path.name.startswith("agent_"):
                await self._migrate_agent_state(file_path.name, state_data)
            else:
                await self._migrate_generic_state(file_path.name, state_data)

            self.migration_stats["files_migrated"] += 1
            logger.info(f"  ✅ Migrated successfully")

        except Exception as e:
            logger.error(f"  ❌ Failed to migrate {file_path.name}: {e}")
            self.migration_stats["files_failed"] += 1

    async def _migrate_correlation_context(self, data: Dict[str, Any]) -> None:
        """Migrate correlation context to memory"""
        memory = get_memory_client()

        # Extract correlation data
        correlation_id = data.get("correlation_id")
        agent_name = data.get("agent_name")
        agent_domain = data.get("agent_domain")
        prompt_preview = data.get("prompt_preview")
        created_at = data.get("created_at")

        if not correlation_id:
            logger.warning("  ⚠️  No correlation_id found, skipping")
            self.migration_stats["files_skipped"] += 1
            return

        # Create memory entry
        correlation_memory = {
            "correlation_id": correlation_id,
            "agent_name": agent_name,
            "agent_domain": agent_domain,
            "prompt_preview": prompt_preview,
            "created_at": created_at,
            "migrated_at": datetime.utcnow().isoformat(),
            "source": "correlation_manager"
        }

        if not self.dry_run:
            await memory.store_memory(
                key=f"correlation_{correlation_id}",
                value=correlation_memory,
                category="routing",
                metadata={"migrated_from": "correlation_manager"}
            )
            self.migration_stats["memories_created"] += 1

        logger.info(f"  → Stored as: routing/correlation_{correlation_id[:8]}...")

    async def _migrate_agent_state(self, filename: str, data: Dict[str, Any]) -> None:
        """Migrate agent state to memory"""
        memory = get_memory_client()

        # Extract agent name from filename
        agent_name = filename.replace("agent_", "").replace(".json", "")

        if not self.dry_run:
            await memory.store_memory(
                key=f"agent_state_{agent_name}",
                value=data,
                category="routing",
                metadata={"migrated_from": "correlation_manager", "agent": agent_name}
            )
            self.migration_stats["memories_created"] += 1

        logger.info(f"  → Stored as: routing/agent_state_{agent_name}")

    async def _migrate_generic_state(self, filename: str, data: Dict[str, Any]) -> None:
        """Migrate generic state file to memory"""
        memory = get_memory_client()

        # Use filename (without extension) as key
        key = filename.replace(".json", "")

        if not self.dry_run:
            await memory.store_memory(
                key=f"legacy_{key}",
                value=data,
                category="workspace",
                metadata={"migrated_from": "correlation_manager", "original_file": filename}
            )
            self.migration_stats["memories_created"] += 1

        logger.info(f"  → Stored as: workspace/legacy_{key}")

    def _print_summary(self) -> None:
        """Print migration summary"""
        logger.info("")
        logger.info("=" * 70)
        logger.info("Migration Summary")
        logger.info("=" * 70)
        logger.info(f"Files found:     {self.migration_stats['files_found']}")
        logger.info(f"Files migrated:  {self.migration_stats['files_migrated']}")
        logger.info(f"Files skipped:   {self.migration_stats['files_skipped']}")
        logger.info(f"Files failed:    {self.migration_stats['files_failed']}")
        logger.info(f"Memories created: {self.migration_stats['memories_created']}")
        logger.info("=" * 70)

        if self.dry_run:
            logger.info("DRY RUN COMPLETE - No changes were made")
            logger.info("Run without --dry-run to perform actual migration")
        else:
            logger.info("MIGRATION COMPLETE")

            if self.create_backup:
                logger.info(f"Backup saved to: {self.backup_dir}")

        logger.info("=" * 70)


async def validate_migration() -> bool:
    """
    Validate migration by comparing counts

    Returns:
        True if validation passes
    """
    logger.info("\nValidating migration...")

    memory = get_memory_client()
    state_dir = Path.home() / ".claude" / "hooks" / ".state"

    # Count original files
    original_count = len(list(state_dir.glob("*.json"))) if state_dir.exists() else 0

    # Count migrated memories
    categories = await memory.list_categories()
    migrated_count = 0

    for category in categories:
        keys = await memory.list_memory(category)
        migrated_memories = [k for k in keys if "migrated_from" in k or k.startswith("correlation_") or k.startswith("legacy_")]
        migrated_count += len(migrated_memories)

    logger.info(f"Original files: {original_count}")
    logger.info(f"Migrated memories: {migrated_count}")

    if migrated_count >= original_count:
        logger.info("✅ Validation passed")
        return True
    else:
        logger.warning("⚠️  Migration count mismatch - please review")
        return False


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Migrate correlation manager data to memory client"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without making changes"
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup creation"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate migration after completion"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Run migration
    migrator = CorrelationMigrator(
        dry_run=args.dry_run,
        create_backup=not args.no_backup
    )

    stats = await migrator.migrate()

    # Validate if requested
    if args.validate and not args.dry_run:
        await validate_migration()

    return stats


if __name__ == "__main__":
    asyncio.run(main())
