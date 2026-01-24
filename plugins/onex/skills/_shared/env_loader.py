"""
Shared environment loader for agent-tracking skills.

Provides a robust way to load .env files from the project root,
with marker-file-based project root detection.
"""

import os
from pathlib import Path


def find_project_root(start_path: Path | None = None) -> Path | None:
    """
    Find the project root by looking for marker files.

    Searches upward from start_path for common project root markers:
    - pyproject.toml
    - .git directory
    - .env file

    Args:
        start_path: Starting directory for search. Defaults to current file's directory.

    Returns:
        Path to project root, or None if not found.
    """
    if start_path is None:
        start_path = Path(__file__).resolve().parent

    current = start_path
    markers = ["pyproject.toml", ".git", ".env"]

    # Search up to 10 levels to prevent infinite loops
    for _ in range(10):
        for marker in markers:
            marker_path = current / marker
            if marker_path.exists():
                return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent

    return None


def load_env_file(project_root: Path | None = None) -> bool:
    """
    Load environment variables from project .env file.

    Searches for .env files in the following order:
    1. Provided project_root (if specified)
    2. Auto-detected project root (via marker files)
    3. Fallback to ~/Code/omniclaude/.env

    Args:
        project_root: Optional explicit project root path.

    Returns:
        True if an .env file was loaded, False otherwise.
    """
    env_paths: list[Path] = []

    # Add explicitly provided project root
    if project_root is not None:
        env_paths.append(Path(project_root) / ".env")

    # Auto-detect project root
    detected_root = find_project_root()
    if detected_root is not None:
        env_paths.append(detected_root / ".env")

    # Add fallback paths
    env_paths.extend(
        [
            Path.home() / "Code" / "omniclaude" / ".env",
            Path.home() / "Code" / "omniclaude2" / ".env",
        ]
    )

    for env_path in env_paths:
        if env_path.exists():
            _parse_env_file(env_path)
            return True

    return False


def _parse_env_file(env_path: Path) -> None:
    """
    Parse an .env file and set environment variables.

    Only sets variables that are not already in the environment.

    Args:
        env_path: Path to the .env file.
    """
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue
            # Must have an equals sign
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            # Remove surrounding quotes if present
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]

            # Only set if not already in environment
            if key not in os.environ:
                os.environ[key] = value
