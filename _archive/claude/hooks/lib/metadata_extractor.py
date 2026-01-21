#!/usr/bin/env python3
"""
Metadata Extractor - Extract contextual metadata from prompts

Extracts metadata from user prompts including:
- Git branch/repo information
- Project context
- File references
- Intent classification
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """Extract contextual metadata from prompts and environment."""

    def __init__(self, working_dir: str | None = None):
        """
        Initialize metadata extractor.

        Args:
            working_dir: Working directory for git operations
        """
        self.working_dir = working_dir or os.getcwd()

    def extract_all(
        self,
        prompt: str,
        agent_name: str | None = None,
        correlation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Extract all available metadata.

        Args:
            prompt: User prompt
            agent_name: Detected agent name
            correlation_context: Correlation context from previous hooks

        Returns:
            Dictionary containing all extracted metadata
        """
        metadata: dict[str, Any] = {}

        # Extract git info
        git_info = self._extract_git_info()
        if git_info:
            metadata["git"] = git_info

        # Extract file references from prompt
        file_refs = self._extract_file_references(prompt)
        if file_refs:
            metadata["file_references"] = file_refs

        # Extract intent signals
        intent = self._extract_intent(prompt)
        if intent:
            metadata["intent"] = intent

        # Include agent info
        if agent_name:
            metadata["agent_name"] = agent_name

        # Include correlation context
        if correlation_context:
            metadata["correlation"] = correlation_context

        # Project info
        metadata["project"] = {
            "working_dir": self.working_dir,
            "project_name": Path(self.working_dir).name,
        }

        return metadata

    def _extract_git_info(self) -> dict[str, str] | None:
        """Extract git repository information."""
        try:
            # Get current branch
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=2,
            )

            # Get repo root
            repo_root = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=2,
            )

            if branch.returncode == 0:
                return {
                    "branch": branch.stdout.strip(),
                    "repo_root": (
                        repo_root.stdout.strip() if repo_root.returncode == 0 else ""
                    ),
                }
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return None

    def _extract_file_references(self, prompt: str) -> list[str]:
        """Extract file paths mentioned in the prompt."""
        # Match common file path patterns
        patterns = [
            r"[\w./\\-]+\.(?:py|js|ts|tsx|jsx|md|yaml|yml|json|sh|sql)\b",
            r"/[\w./\\-]+",  # Unix absolute paths
            r"\.\/[\w./\\-]+",  # Relative paths
        ]

        file_refs = set()
        for pattern in patterns:
            matches = re.findall(pattern, prompt)
            file_refs.update(matches)

        return list(file_refs)[:10]  # Limit to 10 references

    def _extract_intent(self, prompt: str) -> dict[str, Any]:
        """Extract intent classification from prompt."""
        prompt_lower = prompt.lower()

        # Intent categories
        intent = {
            "type": "unknown",
            "signals": [],
        }

        # Check for common intent patterns
        if any(
            word in prompt_lower for word in ["fix", "bug", "error", "issue", "broken"]
        ):
            intent["type"] = "bug_fix"
            intent["signals"].append("contains_fix_keywords")

        elif any(
            word in prompt_lower
            for word in ["add", "create", "implement", "new", "feature"]
        ):
            intent["type"] = "feature"
            intent["signals"].append("contains_feature_keywords")

        elif any(
            word in prompt_lower
            for word in ["refactor", "improve", "optimize", "clean"]
        ):
            intent["type"] = "refactor"
            intent["signals"].append("contains_refactor_keywords")

        elif any(word in prompt_lower for word in ["test", "testing", "spec", "unit"]):
            intent["type"] = "testing"
            intent["signals"].append("contains_test_keywords")

        elif any(
            word in prompt_lower for word in ["document", "docs", "readme", "explain"]
        ):
            intent["type"] = "documentation"
            intent["signals"].append("contains_doc_keywords")

        return intent
