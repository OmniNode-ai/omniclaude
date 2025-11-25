"""
File Utilities - Common file operations

Responsible for:
- Directory creation and management
- File writing with proper encoding
- Path handling and validation
- Backup and cleanup operations
"""

import json
import logging
import os
import shutil
import time
from typing import Any, Dict, List, Optional


# Configure logger for this module
logger = logging.getLogger(__name__)


class FileUtils:
    """Utility class for file system operations."""

    def __init__(self, base_path: Optional[str] = None):
        """Initialize FileUtils with optional base path."""
        self.base_path = base_path or os.getcwd()
        self.backup_dir = os.path.join(self.base_path, ".backups")

    def ensure_directory(self, directory_path: str) -> str:
        """Ensure directory exists, create if necessary."""
        full_path = self._resolve_path(directory_path)

        try:
            os.makedirs(full_path, exist_ok=True)
            return full_path
        except OSError as e:
            raise OSError(f"Failed to create directory {full_path}: {e}")

    def write_file(self, file_path: str, content: str, encoding: str = "utf-8") -> None:
        """Write content to file with proper encoding."""
        full_path = self._resolve_path(file_path)

        # Ensure parent directory exists
        parent_dir = os.path.dirname(full_path)
        if parent_dir:
            self.ensure_directory(parent_dir)

        try:
            with open(full_path, "w", encoding=encoding) as f:
                f.write(content)
        except OSError as e:
            raise OSError(f"Failed to write file {full_path}: {e}")

    def write_json(self, file_path: str, data: Dict[str, Any], indent: int = 2) -> None:
        """Write JSON data to file with proper formatting."""
        try:
            json_content = json.dumps(data, indent=indent, ensure_ascii=False)
            self.write_file(file_path, json_content)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize data to JSON for {file_path}: {e}")

    def read_file(self, file_path: str, encoding: str = "utf-8") -> str:
        """Read content from file."""
        full_path = self._resolve_path(file_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        try:
            with open(full_path, "r", encoding=encoding) as f:
                return f.read()
        except OSError as e:
            raise OSError(f"Failed to read file {full_path}: {e}")

    def read_json(self, file_path: str) -> Dict[str, Any]:
        """Read JSON data from file."""
        try:
            content = self.read_file(file_path)
            return json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in file {file_path}: {e}")

    def file_exists(self, file_path: str) -> bool:
        """Check if file exists."""
        full_path = self._resolve_path(file_path)
        return os.path.exists(full_path)

    def delete_file(self, file_path: str) -> bool:
        """Delete file if it exists."""
        full_path = self._resolve_path(file_path)

        if not os.path.exists(full_path):
            return False

        try:
            os.remove(full_path)
            return True
        except OSError as e:
            raise OSError(f"Failed to delete file {full_path}: {e}")

    def copy_file(self, source_path: str, destination_path: str) -> None:
        """Copy file from source to destination."""
        src_full = self._resolve_path(source_path)
        dst_full = self._resolve_path(destination_path)

        # Ensure destination directory exists
        dst_dir = os.path.dirname(dst_full)
        if dst_dir:
            self.ensure_directory(dst_dir)

        try:
            shutil.copy2(src_full, dst_full)
        except OSError as e:
            raise OSError(f"Failed to copy file from {src_full} to {dst_full}: {e}")

    def move_file(self, source_path: str, destination_path: str) -> None:
        """Move file from source to destination."""
        src_full = self._resolve_path(source_path)
        dst_full = self._resolve_path(destination_path)

        # Ensure destination directory exists
        dst_dir = os.path.dirname(dst_full)
        if dst_dir:
            self.ensure_directory(dst_dir)

        try:
            shutil.move(src_full, dst_full)
        except OSError as e:
            raise OSError(f"Failed to move file from {src_full} to {dst_full}: {e}")

    def create_backup(self, file_path: str, backup_dir: Optional[str] = None) -> str:
        """Create backup of file."""
        if not self.file_exists(file_path):
            raise FileNotFoundError(f"Cannot backup non-existent file: {file_path}")

        if backup_dir is None:
            backup_dir = self.backup_dir

        self.ensure_directory(backup_dir)

        # Generate backup filename with timestamp
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_basename = os.path.basename(file_path)
        backup_filename = f"{file_basename}.{timestamp}.bak"
        backup_path = os.path.join(backup_dir, backup_filename)

        self.copy_file(file_path, backup_path)
        return backup_path

    def list_files(
        self, directory_path: str, pattern: str = "*", recursive: bool = False
    ) -> List[str]:
        """List files in directory matching pattern."""
        full_path = self._resolve_path(directory_path)

        if not os.path.exists(full_path):
            return []

        files = []

        if recursive:
            for root, dirs, filenames in os.walk(full_path):
                for filename in filenames:
                    if self._matches_pattern(filename, pattern):
                        rel_path = os.path.relpath(
                            os.path.join(root, filename), self.base_path
                        )
                        files.append(rel_path)
        else:
            try:
                for filename in os.listdir(full_path):
                    file_full_path = os.path.join(full_path, filename)
                    if os.path.isfile(file_full_path) and self._matches_pattern(
                        filename, pattern
                    ):
                        rel_path = os.path.relpath(file_full_path, self.base_path)
                        files.append(rel_path)
            except OSError as e:
                # Directory may not be readable - log warning but continue
                logger.warning(
                    f"Failed to list directory contents: {e} (path: {full_path})"
                )
                # Don't re-raise - return empty list for this directory

        return sorted(files)

    def get_file_size(self, file_path: str) -> int:
        """Get file size in bytes."""
        full_path = self._resolve_path(file_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        return os.path.getsize(full_path)

    def get_file_info(self, file_path: str) -> Dict[str, Any]:
        """Get comprehensive file information."""
        full_path = self._resolve_path(file_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File not found: {full_path}")

        stat_info = os.stat(full_path)

        return {
            "path": full_path,
            "size": stat_info.st_size,
            "modified": stat_info.st_mtime,
            "created": stat_info.st_ctime,
            "is_file": os.path.isfile(full_path),
            "is_directory": os.path.isdir(full_path),
            "is_symlink": os.path.islink(full_path),
            "permissions": oct(stat_info.st_mode)[-3:],
            "extension": os.path.splitext(full_path)[1].lower(),
            "basename": os.path.basename(full_path),
            "dirname": os.path.dirname(full_path),
        }

    def clean_directory(self, directory_path: str, keep_pattern: str = None) -> int:
        """Clean directory, optionally keeping files matching pattern."""
        full_path = self._resolve_path(directory_path)

        if not os.path.exists(full_path):
            return 0

        deleted_count = 0

        try:
            for item in os.listdir(full_path):
                item_path = os.path.join(full_path, item)

                if os.path.isfile(item_path):
                    # Check if file should be kept
                    if keep_pattern and self._matches_pattern(item, keep_pattern):
                        continue

                    os.remove(item_path)
                    deleted_count += 1
                elif os.path.isdir(item_path):
                    # Recursively clean subdirectories
                    deleted_count += self.clean_directory(item_path, keep_pattern)

                    # Try to remove empty directory
                    try:
                        os.rmdir(item_path)
                    except OSError as e:
                        # Directory not empty or not removable - log at debug level
                        logger.debug(
                            f"Could not remove directory (likely not empty): {e} (path: {item_path})"
                        )
                        # Don't re-raise - this is expected for non-empty directories
        except OSError as e:
            # Directory may not be readable - log warning
            logger.warning(f"Failed to clean directory: {e} (path: {full_path})")
            # Don't re-raise - return count of deleted files so far

        return deleted_count

    def archive_directory(
        self, directory_path: str, archive_path: str, format: str = "zip"
    ) -> str:
        """Archive directory into specified format."""
        full_path = self._resolve_path(directory_path)
        archive_full_path = self._resolve_path(archive_path)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"Directory not found: {full_path}")

        # Ensure archive directory exists
        archive_dir = os.path.dirname(archive_full_path)
        self.ensure_directory(archive_dir)

        if format.lower() == "zip":
            try:
                import zipfile

                with zipfile.ZipFile(
                    archive_full_path, "w", zipfile.ZIP_DEFLATED
                ) as zipf:
                    for root, dirs, files in os.walk(full_path):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arc_path = os.path.relpath(file_path, full_path)
                            zipf.write(file_path, arc_path)
            except ImportError:
                raise ImportError("zipfile module not available")
        else:
            raise ValueError(f"Unsupported archive format: {format}")

        return archive_full_path

    def extract_archive(
        self, archive_path: str, extract_path: str, format: str = "zip"
    ) -> None:
        """Extract archive into specified directory."""
        archive_full_path = self._resolve_path(archive_path)
        extract_full_path = self._resolve_path(extract_path)

        if not os.path.exists(archive_full_path):
            raise FileNotFoundError(f"Archive not found: {archive_full_path}")

        self.ensure_directory(extract_full_path)

        if format.lower() == "zip":
            try:
                import zipfile

                with zipfile.ZipFile(archive_full_path, "r") as zipf:
                    zipf.extractall(extract_full_path)
            except ImportError:
                raise ImportError("zipfile module not available")
        else:
            raise ValueError(f"Unsupported archive format: {format}")

    def _resolve_path(self, path: str) -> str:
        """Resolve path relative to base path."""
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_path, path)

    def _matches_pattern(self, filename: str, pattern: str) -> bool:
        """Check if filename matches pattern (supports * and ? wildcards)."""
        import fnmatch

        return fnmatch.fnmatch(filename, pattern)


class BackupManager:
    """Manages file backups with rotation and cleanup."""

    def __init__(self, backup_dir: str = ".backups", max_backups: int = 10):
        self.backup_dir = backup_dir
        self.max_backups = max_backups
        self.file_utils = FileUtils(backup_dir)

    def backup_file(self, file_path: str, description: str = "") -> str:
        """Create backup of file with metadata."""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Cannot backup non-existent file: {file_path}")

        # Ensure backup directory exists
        self.file_utils.ensure_directory(self.backup_dir)

        # Create backup metadata
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_basename = os.path.basename(file_path)
        backup_filename = f"{file_basename}.{timestamp}.bak"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        # Copy file to backup location
        self.file_utils.copy_file(file_path, backup_path)

        # Create backup metadata file
        metadata = {
            "original_path": file_path,
            "backup_path": backup_path,
            "timestamp": timestamp,
            "description": description,
            "file_size": self.file_utils.get_file_size(file_path),
            "created_at": time.time(),
        }

        metadata_filename = f"{backup_filename}.meta"
        metadata_path = os.path.join(self.backup_dir, metadata_filename)
        self.file_utils.write_json(metadata_path, metadata)

        # Rotate backups if needed
        self._rotate_backups(file_basename)

        return backup_path

    def _rotate_backups(self, file_basename: str) -> None:
        """Rotate backups to maintain maximum count."""
        backup_files = self.file_utils.list_files(
            self.backup_dir, pattern=f"{file_basename}.*.bak"
        )

        if len(backup_files) > self.max_backups:
            # Sort by timestamp (oldest first)
            backup_files.sort()

            # Remove oldest backups
            excess_count = len(backup_files) - self.max_backups
            for i in range(excess_count):
                backup_to_remove = backup_files[i]
                backup_path = self.file_utils._resolve_path(backup_to_remove)

                # Remove backup file and metadata
                try:
                    os.remove(backup_path)
                    metadata_path = backup_path + ".meta"
                    if os.path.exists(metadata_path):
                        os.remove(metadata_path)
                except OSError as e:
                    # Backup cleanup failed - log warning but continue rotation
                    logger.warning(
                        f"Failed to remove old backup file: {e} (path: {backup_path})"
                    )
                    # Don't re-raise - continue with remaining backups

    def list_backups(self, file_basename: Optional[str] = None) -> List[Dict[str, Any]]:
        """List available backups with metadata."""
        backup_files = self.file_utils.list_files(
            self.backup_dir, pattern=f"{file_basename or '*'}.*.bak"
        )

        backups = []
        for backup_file in backup_files:
            backup_path = self.file_utils._resolve_path(backup_file)
            metadata_path = backup_path + ".meta"

            metadata = {}
            if os.path.exists(metadata_path):
                try:
                    metadata = self.file_utils.read_json(metadata_path)
                except (json.JSONDecodeError, FileNotFoundError):
                    pass  # nosec B110 - metadata is optional, defaults to empty dict

            backup_info = self.file_utils.get_file_info(backup_path)
            backup_info.update(metadata)
            backups.append(backup_info)

        # Sort by timestamp (newest first)
        backups.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

        return backups

    def restore_backup(
        self, backup_path: str, target_path: Optional[str] = None
    ) -> str:
        """Restore file from backup."""
        backup_full_path = self.file_utils._resolve_path(backup_path)

        if not os.path.exists(backup_full_path):
            raise FileNotFoundError(f"Backup not found: {backup_full_path}")

        if target_path is None:
            # Try to restore to original location from metadata
            metadata_path = backup_full_path + ".meta"
            if os.path.exists(metadata_path):
                metadata = self.file_utils.read_json(metadata_path)
                target_path = metadata.get("original_path")

            if target_path is None:
                raise ValueError("Cannot determine restore target path")

        target_full_path = self.file_utils._resolve_path(target_path)

        # Copy backup to target location
        self.file_utils.copy_file(backup_full_path, target_full_path)

        return target_full_path

    def cleanup_old_backups(self, days_old: int = 30) -> int:
        """Remove backups older than specified days."""
        cutoff_time = time.time() - (days_old * 24 * 60 * 60)
        removed_count = 0

        backup_files = self.file_utils.list_files(self.backup_dir, "*.bak")

        for backup_file in backup_files:
            backup_path = self.file_utils._resolve_path(backup_file)

            # Check file modification time
            try:
                if os.path.getmtime(backup_path) < cutoff_time:
                    os.remove(backup_path)

                    # Also remove metadata file if it exists
                    metadata_path = backup_path + ".meta"
                    if os.path.exists(metadata_path):
                        os.remove(metadata_path)

                    removed_count += 1
            except OSError as e:
                # Backup removal failed - log warning but continue cleanup
                logger.warning(
                    f"Failed to remove old backup by age: {e} (path: {backup_path})"
                )
                # Don't re-raise - continue with remaining backups

        return removed_count
