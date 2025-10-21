#!/usr/bin/env python3
"""
Enhanced Metadata Extractor - Rich context capture for user prompts
Performance target: <15ms overhead
"""

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class MetadataExtractor:
    """Extract rich metadata from user prompts and environment."""

    # Workflow stage keywords
    WORKFLOW_KEYWORDS = {
        "debugging": [
            "debug",
            "error",
            "fix",
            "bug",
            "issue",
            "problem",
            "crash",
            "fail",
        ],
        "feature_development": [
            "implement",
            "add",
            "create",
            "new",
            "build",
            "develop",
        ],
        "refactoring": [
            "refactor",
            "improve",
            "optimize",
            "clean",
            "restructure",
            "reorganize",
        ],
        "testing": ["test", "verify", "check", "validate", "coverage", "unit test"],
        "documentation": ["document", "docs", "readme", "comment", "explain"],
        "review": ["review", "analyze", "inspect", "evaluate", "assess"],
    }

    # Command words indicating action
    COMMAND_WORDS = [
        "implement",
        "add",
        "create",
        "build",
        "develop",
        "fix",
        "debug",
        "resolve",
        "solve",
        "refactor",
        "improve",
        "optimize",
        "clean",
        "test",
        "verify",
        "validate",
        "check",
        "document",
        "explain",
        "describe",
        "update",
        "modify",
        "change",
        "edit",
        "remove",
        "delete",
        "drop",
        "deploy",
        "release",
        "ship",
    ]

    # File type classifications
    FILE_TYPE_MAP = {
        "source": [
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".java",
            ".cpp",
            ".c",
            ".go",
            ".rs",
            ".rb",
        ],
        "test": ["_test.py", "_test.js", ".test.ts", ".spec.js", ".test.tsx", "test_"],
        "config": [".yaml", ".yml", ".json", ".toml", ".ini", ".conf", ".cfg"],
        "doc": [".md", ".rst", ".txt", ".adoc"],
        "build": ["Dockerfile", "Makefile", ".sh", ".bash"],
    }

    def __init__(self, working_dir: Optional[Path] = None):
        """Initialize metadata extractor.

        Args:
            working_dir: Current working directory (default: CWD)
        """
        self.working_dir = Path(working_dir or os.getcwd())

    def extract_all(
        self,
        prompt: str,
        agent_name: Optional[str] = None,
        correlation_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Extract all metadata from prompt and environment.

        Args:
            prompt: User prompt text
            agent_name: Detected agent name (if any)
            correlation_context: Session context from correlation manager

        Returns:
            Complete metadata dictionary
        """
        start_time = time.perf_counter()

        metadata = {
            "trigger_source": self._detect_trigger_source(prompt, agent_name),
            "workflow_stage": self._classify_workflow_stage(prompt, agent_name),
            "editor_context": self._extract_editor_context(),
            "session_context": self._extract_session_context(correlation_context),
            "prompt_characteristics": self._extract_prompt_characteristics(prompt),
            "extraction_time_ms": 0,  # Will be updated at end
        }

        # Calculate extraction time
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        metadata["extraction_time_ms"] = round(elapsed_ms, 2)

        return metadata

    def _detect_trigger_source(self, prompt: str, agent_name: Optional[str]) -> str:
        """Detect if prompt was manual or automatic.

        For now, all are manual. Future: detect from hook metadata.

        Args:
            prompt: User prompt text
            agent_name: Detected agent name

        Returns:
            "manual" or "automatic"
        """
        # Simple heuristic: explicit agent invocation = manual
        # Everything is manual for now (Phase 1)
        return "manual"

    def _classify_workflow_stage(self, prompt: str, agent_name: Optional[str]) -> str:
        """Classify workflow stage using keyword heuristics.

        Args:
            prompt: User prompt text
            agent_name: Detected agent name

        Returns:
            Workflow stage classification
        """
        prompt_lower = prompt.lower()

        # Score each workflow stage
        scores: Dict[str, int] = {}
        for stage, keywords in self.WORKFLOW_KEYWORDS.items():
            score = sum(1 for keyword in keywords if keyword in prompt_lower)
            if score > 0:
                scores[stage] = score

        # Return highest scoring stage
        if scores:
            return max(scores, key=scores.get)

        # Default: exploratory if no clear match
        return "exploratory"

    def _extract_editor_context(self) -> Dict[str, Any]:
        """Extract context about current editor state.

        Returns:
            Editor context (active file, language, file type)
        """
        context: Dict[str, Any] = {
            "working_directory": str(self.working_dir),
            "active_file": None,
            "language": None,
            "file_type": None,
        }

        # Try to detect most recently modified file
        try:
            # Look for recently modified files in current directory
            recent_files = sorted(
                [f for f in self.working_dir.rglob("*") if f.is_file()],
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[
                :5
            ]  # Top 5 most recent

            if recent_files:
                # Use most recent file
                active_file = recent_files[0]
                context["active_file"] = str(active_file.relative_to(self.working_dir))
                context["language"] = self._detect_language(active_file)
                context["file_type"] = self._classify_file_type(active_file)

        except Exception:
            # Graceful degradation: leave as None
            pass

        return context

    def _detect_language(self, file_path: Path) -> Optional[str]:
        """Detect programming language from file extension.

        Args:
            file_path: Path to file

        Returns:
            Language name or None
        """
        ext_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".sh": "bash",
            ".bash": "bash",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".json": "json",
            ".md": "markdown",
        }

        suffix = file_path.suffix.lower()
        return ext_map.get(suffix)

    def _classify_file_type(self, file_path: Path) -> str:
        """Classify file type (source, test, config, doc, build).

        Args:
            file_path: Path to file

        Returns:
            File type classification
        """
        file_name = file_path.name.lower()
        suffix = file_path.suffix.lower()

        # Check each type
        for file_type, patterns in self.FILE_TYPE_MAP.items():
            for pattern in patterns:
                if pattern.startswith("."):
                    # Extension match
                    if suffix == pattern:
                        return file_type
                else:
                    # Name pattern match
                    if pattern in file_name:
                        return file_type

        return "other"

    def _extract_session_context(
        self, correlation_context: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Extract session-level context.

        Args:
            correlation_context: Context from correlation manager

        Returns:
            Session context
        """
        context = {
            "prompts_in_session": 1,
            "time_since_last_prompt_seconds": None,
        }  # Default: first prompt

        if correlation_context:
            # Get prompt count from correlation context
            context["prompts_in_session"] = correlation_context.get("prompt_count", 1)

            # Calculate time since last prompt
            if "last_accessed" in correlation_context:
                try:
                    last_accessed = datetime.fromisoformat(
                        correlation_context["last_accessed"]
                    )
                    now = datetime.now(last_accessed.tzinfo)
                    delta = (now - last_accessed).total_seconds()
                    context["time_since_last_prompt_seconds"] = round(delta, 1)
                except Exception:
                    pass

        return context

    def _extract_prompt_characteristics(self, prompt: str) -> Dict[str, Any]:
        """Extract characteristics of the prompt text.

        Args:
            prompt: User prompt text

        Returns:
            Prompt characteristics
        """
        characteristics = {
            "length_chars": len(prompt),
            "has_code_block": self._has_code_block(prompt),
            "question_count": self._count_questions(prompt),
            "command_words": self._extract_command_words(prompt),
        }

        return characteristics

    def _has_code_block(self, prompt: str) -> bool:
        """Check if prompt contains code blocks.

        Args:
            prompt: User prompt text

        Returns:
            True if code blocks present
        """
        # Look for markdown code blocks
        return "```" in prompt or "`" in prompt

    def _count_questions(self, prompt: str) -> int:
        """Count question marks in prompt.

        Args:
            prompt: User prompt text

        Returns:
            Number of questions
        """
        return prompt.count("?")

    def _extract_command_words(self, prompt: str) -> List[str]:
        """Extract command/action words from prompt.

        Args:
            prompt: User prompt text

        Returns:
            List of command words found
        """
        prompt_lower = prompt.lower()
        found_commands = []

        for command in self.COMMAND_WORDS:
            if command in prompt_lower:
                found_commands.append(command)

        return found_commands


# Convenience function for CLI usage
def extract_metadata(
    prompt: str, agent_name: Optional[str] = None, working_dir: Optional[str] = None
) -> Dict[str, Any]:
    """Extract metadata from prompt.

    Args:
        prompt: User prompt text
        agent_name: Detected agent name
        working_dir: Working directory path

    Returns:
        Complete metadata dictionary
    """
    extractor = MetadataExtractor(working_dir=working_dir)
    return extractor.extract_all(prompt, agent_name=agent_name)


if __name__ == "__main__":
    import json
    import sys

    # Test metadata extraction
    if len(sys.argv) < 2:
        print("Usage: metadata_extractor.py <prompt> [agent_name]", file=sys.stderr)
        sys.exit(1)

    prompt = " ".join(sys.argv[1:])
    agent_name = sys.argv[2] if len(sys.argv) > 2 else None

    metadata = extract_metadata(prompt, agent_name=agent_name)
    print(json.dumps(metadata, indent=2))
