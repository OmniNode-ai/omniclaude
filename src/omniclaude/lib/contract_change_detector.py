# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# Copyright (c) 2025 OmniNode Team
"""Contract change detection for PR diffs (OMN-3138).

Detects contract.yaml file changes in a git diff range and extracts
``declared_topics`` from each changed contract. Used by the pr-queue-pipeline
to emit ``ModelPRChangeSet`` events for downstream Delta Intelligence nodes.

Usage:
    from omniclaude.lib.contract_change_detector import detect_contract_changes

    changes = detect_contract_changes(
        repo_path="/path/to/repo",
        base_sha="abc1234",
        head_sha="def5678",
    )
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Literal

import yaml

from omniclaude.nodes.shared.models.model_pr_changeset import ModelContractChange

logger = logging.getLogger(__name__)

# Pattern matching contract files in the diff output.
CONTRACT_FILE_PATTERN = "contract.yaml"


def detect_contract_changes(
    repo_path: str | Path,
    base_sha: str,
    head_sha: str,
) -> list[ModelContractChange]:
    """Detect contract.yaml changes between two commits.

    Runs ``git diff --name-status <base_sha>..<head_sha>`` and filters for
    files matching ``contract.yaml``. For each changed contract, attempts to
    extract ``declared_topics`` from the contract YAML at ``head_sha``.

    Args:
        repo_path: Path to the git repository.
        base_sha: Base commit SHA.
        head_sha: Head commit SHA.

    Returns:
        List of ModelContractChange instances for each contract.yaml changed.
        Returns empty list if git diff fails or no contracts changed.
    """
    repo_path = Path(repo_path)
    changed_files = _git_diff_name_status(repo_path, base_sha, head_sha)
    if not changed_files:
        return []

    changes: list[ModelContractChange] = []
    for status, file_path in changed_files:
        if not file_path.endswith(CONTRACT_FILE_PATTERN):
            continue

        change_type = _map_git_status(status)
        declared_topics: list[str] = []

        if change_type != "deleted":
            declared_topics = _extract_declared_topics(repo_path, head_sha, file_path)

        changes.append(
            ModelContractChange(
                file_path=file_path,
                change_type=change_type,
                declared_topics=declared_topics,
            )
        )

    return changes


def _git_diff_name_status(
    repo_path: Path, base_sha: str, head_sha: str
) -> list[tuple[str, str]]:
    """Run git diff --name-status and return (status, path) pairs.

    Returns:
        List of (status_letter, file_path) tuples. Empty list on error.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "diff",
                "--name-status",
                f"{base_sha}..{head_sha}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            logger.warning(
                "git diff failed (rc=%d): %s", result.returncode, result.stderr.strip()
            )
            return []

        pairs: list[tuple[str, str]] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("\t", maxsplit=1)
            if len(parts) == 2:
                pairs.append((parts[0].strip(), parts[1].strip()))
        return pairs

    except subprocess.TimeoutExpired:
        logger.warning("git diff timed out after 30s")
        return []
    except FileNotFoundError:
        logger.warning("git binary not found")
        return []


def _map_git_status(status: str) -> Literal["added", "modified", "deleted"]:
    """Map a git diff --name-status letter to a change type.

    Args:
        status: Single-character git status (A, M, D, R, C, etc.).

    Returns:
        One of "added", "modified", or "deleted".
    """
    first_char = status[0].upper() if status else "M"
    if first_char == "A":
        return "added"
    if first_char == "D":
        return "deleted"
    # M, R (rename), C (copy), T (type change) all map to "modified"
    return "modified"


def _extract_declared_topics(repo_path: Path, sha: str, file_path: str) -> list[str]:
    """Extract declared_topics from a contract.yaml at a specific commit.

    Uses ``git show <sha>:<path>`` to read the file content without checking
    out the commit.

    Args:
        repo_path: Path to the git repository.
        sha: Commit SHA to read from.
        file_path: Relative path to the contract.yaml.

    Returns:
        List of topic strings from the ``declared_topics`` field.
        Empty list if parsing fails or field is missing.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "show", f"{sha}:{file_path}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            logger.debug(
                "git show %s:%s failed: %s", sha[:8], file_path, result.stderr.strip()
            )
            return []

        data = yaml.safe_load(result.stdout)
        if not isinstance(data, dict):
            return []

        topics = data.get("declared_topics")
        if isinstance(topics, list) and topics:
            return [str(t) for t in topics if t]

        # Fallback: single topic_base string
        topic_base = data.get("topic_base")
        if isinstance(topic_base, str) and topic_base:
            return [topic_base]

        return []

    except (subprocess.TimeoutExpired, yaml.YAMLError) as exc:
        logger.debug("Failed to extract topics from %s:%s: %s", sha[:8], file_path, exc)
        return []
    except FileNotFoundError:
        logger.debug("git binary not found")
        return []


def count_total_files_changed(
    repo_path: str | Path, base_sha: str, head_sha: str
) -> int:
    """Count total files changed between two commits.

    Args:
        repo_path: Path to the git repository.
        base_sha: Base commit SHA.
        head_sha: Head commit SHA.

    Returns:
        Number of files changed. Returns 0 on error.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "diff",
                "--name-only",
                f"{base_sha}..{head_sha}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return 0
        return len(
            [line for line in result.stdout.strip().splitlines() if line.strip()]
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 0


__all__ = [
    "count_total_files_changed",
    "detect_contract_changes",
]
