"""
Log Rotation and Retention Configuration

Provides configurable log rotation and retention for structured logging.
Supports size-based and time-based rotation with automatic cleanup of old logs.

Features:
- Size-based rotation (default: 100MB per file)
- Time-based rotation (daily rotation option)
- Automatic log retention (default: 30 days)
- Compression support for archived logs
- Directory-based organization
- Environment-specific configurations

Usage:
    # Configure rotation for a logger
    from lib.log_rotation import configure_file_rotation
    from lib.structured_logger import get_logger

    logger = get_logger(__name__, component="agent-researcher")
    configure_file_rotation(
        logger,
        log_dir="/var/log/agents",
        max_bytes=100 * 1024 * 1024,  # 100MB
        backup_count=30  # Keep 30 files
    )
"""

import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Literal

from .structured_logger import JSONFormatter, StructuredLogger

LogRotationType = Literal["size", "time"]


class LogRotationConfig:
    """
    Log rotation configuration with sensible defaults.

    Attributes:
        log_dir: Directory for log files (default: ./logs)
        rotation_type: "size" or "time" based rotation
        max_bytes: Maximum file size before rotation (size-based, default: 100MB)
        backup_count: Number of backup files to keep (default: 30)
        when: Time-based rotation interval (time-based, default: "midnight")
        interval: Rotation interval multiplier (time-based, default: 1)
        encoding: Log file encoding (default: "utf-8")
        compression: Whether to compress archived logs (default: False)
    """

    def __init__(
        self,
        log_dir: str = "./logs",
        rotation_type: LogRotationType = "size",
        max_bytes: int = 100 * 1024 * 1024,  # 100MB
        backup_count: int = 30,
        when: str = "midnight",
        interval: int = 1,
        encoding: str = "utf-8",
        compression: bool = False,
    ):
        self.log_dir = log_dir
        self.rotation_type = rotation_type
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.when = when
        self.interval = interval
        self.encoding = encoding
        self.compression = compression

    @classmethod
    def development(cls) -> "LogRotationConfig":
        """Development environment configuration (smaller files, shorter retention)"""
        return cls(
            log_dir="./logs/dev",
            rotation_type="size",
            max_bytes=10 * 1024 * 1024,  # 10MB
            backup_count=5,
            compression=False,
        )

    @classmethod
    def production(cls) -> "LogRotationConfig":
        """Production environment configuration (larger files, longer retention)"""
        return cls(
            log_dir="/var/log/agents",
            rotation_type="size",
            max_bytes=100 * 1024 * 1024,  # 100MB
            backup_count=30,
            compression=True,
        )

    @classmethod
    def daily_rotation(
        cls, log_dir: str = "./logs", retention_days: int = 30
    ) -> "LogRotationConfig":
        """Daily rotation configuration"""
        return cls(
            log_dir=log_dir,
            rotation_type="time",
            when="midnight",
            interval=1,
            backup_count=retention_days,
            compression=True,
        )


def configure_file_rotation(
    logger: StructuredLogger,
    config: LogRotationConfig | None = None,
    log_dir: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
    filename: str | None = None,
):
    """
    Configure file rotation for a structured logger.

    Args:
        logger: StructuredLogger instance to configure
        config: LogRotationConfig instance (if provided, overrides other params)
        log_dir: Directory for log files (default: ./logs)
        max_bytes: Maximum file size before rotation (default: 100MB)
        backup_count: Number of backup files to keep (default: 30)
        filename: Log file name (default: <logger_name>.log)

    Example:
        logger = get_logger(__name__, component="agent-researcher")
        configure_file_rotation(
            logger,
            log_dir="/var/log/agents",
            max_bytes=100 * 1024 * 1024,
            backup_count=30
        )
    """
    # Use config if provided, otherwise create from parameters
    if config is None:
        config = LogRotationConfig(
            log_dir=log_dir or "./logs",
            max_bytes=max_bytes or 100 * 1024 * 1024,
            backup_count=backup_count or 30,
        )

    # Create log directory if it doesn't exist
    log_path = Path(config.log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Determine log filename
    if filename is None:
        filename = f"{logger.logger.name}.log"
    log_file = log_path / filename

    # Create appropriate handler based on rotation type
    handler: RotatingFileHandler | TimedRotatingFileHandler
    if config.rotation_type == "size":
        handler = RotatingFileHandler(
            filename=str(log_file),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding=config.encoding,
        )
    else:  # time-based rotation
        handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when=config.when,
            interval=config.interval,
            backupCount=config.backup_count,
            encoding=config.encoding,
        )

    # Set JSON formatter
    handler.setFormatter(JSONFormatter())

    # Add handler to logger
    logger.logger.addHandler(handler)


def configure_global_rotation(
    config: LogRotationConfig | None = None,
    environment: Literal["development", "production"] = "development",
):
    """
    Configure rotation for all loggers globally.

    Args:
        config: LogRotationConfig instance (if not provided, uses environment default)
        environment: Environment type for default config ("development" or "production")

    Example:
        # Development environment
        configure_global_rotation(environment="development")

        # Production environment
        configure_global_rotation(environment="production")

        # Custom configuration
        config = LogRotationConfig(
            log_dir="/var/log/agents",
            max_bytes=50 * 1024 * 1024,
            backup_count=60
        )
        configure_global_rotation(config=config)
    """
    # Use environment-specific config if none provided
    if config is None:
        if environment == "production":
            config = LogRotationConfig.production()
        else:
            config = LogRotationConfig.development()

    # Create log directory
    log_path = Path(config.log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Configure root logger
    root_logger = logging.getLogger()

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create appropriate handler
    if config.rotation_type == "size":
        handler = RotatingFileHandler(
            filename=str(log_path / "agent_framework.log"),
            maxBytes=config.max_bytes,
            backupCount=config.backup_count,
            encoding=config.encoding,
        )
    else:  # time-based rotation
        handler = TimedRotatingFileHandler(
            filename=str(log_path / "agent_framework.log"),
            when=config.when,
            interval=config.interval,
            backupCount=config.backup_count,
            encoding=config.encoding,
        )

    # Set JSON formatter
    handler.setFormatter(JSONFormatter())

    # Add handler to root logger
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


def cleanup_old_logs(log_dir: str, retention_days: int = 30):
    """
    Clean up log files older than retention period.

    Args:
        log_dir: Directory containing log files
        retention_days: Number of days to retain logs (default: 30)

    Example:
        cleanup_old_logs("/var/log/agents", retention_days=30)
    """
    import time
    from pathlib import Path

    log_path = Path(log_dir)
    if not log_path.exists():
        return

    # Calculate cutoff time
    cutoff_time = time.time() - (retention_days * 24 * 60 * 60)

    # Iterate through log files
    for log_file in log_path.glob("*.log*"):
        if log_file.is_file():
            file_mtime = log_file.stat().st_mtime
            if file_mtime < cutoff_time:
                log_file.unlink()


def get_log_stats(log_dir: str) -> dict:
    """
    Get statistics about log files in directory.

    Args:
        log_dir: Directory containing log files

    Returns:
        Dictionary with log statistics

    Example:
        stats = get_log_stats("/var/log/agents")
        print(f"Total size: {stats['total_size_mb']:.2f}MB")
        print(f"File count: {stats['file_count']}")
    """
    from pathlib import Path

    log_path = Path(log_dir)
    if not log_path.exists():
        return {
            "file_count": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "oldest_file": None,
            "newest_file": None,
        }

    log_files = list(log_path.glob("*.log*"))
    if not log_files:
        return {
            "file_count": 0,
            "total_size_bytes": 0,
            "total_size_mb": 0.0,
            "oldest_file": None,
            "newest_file": None,
        }

    total_size = sum(f.stat().st_size for f in log_files)
    oldest_file = min(log_files, key=lambda f: f.stat().st_mtime)
    newest_file = max(log_files, key=lambda f: f.stat().st_mtime)

    return {
        "file_count": len(log_files),
        "total_size_bytes": total_size,
        "total_size_mb": total_size / (1024 * 1024),
        "oldest_file": str(oldest_file),
        "newest_file": str(newest_file),
    }
