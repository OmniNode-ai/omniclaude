#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""
Agent Detector - Detect automated workflows from user prompts

Analyzes user prompts to detect if they trigger automated workflow execution.
"""

import logging
import re

logger = logging.getLogger(__name__)


class AgentDetector:
    """Detects automated workflow triggers in user prompts."""

    # Patterns that indicate automated workflow requests
    WORKFLOW_PATTERNS = [
        r"\bparallel\s+(?:execution|agents?|tasks?)\b",
        r"\bmulti[- ]?agent\b",
        r"\borchestrat(?:e|ion)\b",
        r"\bworkflow\b",
        r"\b(?:run|execute)\s+(?:all|multiple)\b",
        r"\bauto(?:mat(?:e|ic|ion)|nomous)\b",
        r"\bcoordinat(?:e|ion)\b",
        r"\bdispatch\b",
    ]

    def __init__(self, custom_patterns: list[str] | None = None):
        """
        Initialize agent detector.

        Args:
            custom_patterns: Additional regex patterns to detect workflows
        """
        self.patterns = self.WORKFLOW_PATTERNS.copy()
        if custom_patterns:
            self.patterns.extend(custom_patterns)

        # Pre-compile patterns for efficiency
        self._compiled_patterns = [re.compile(p, re.IGNORECASE) for p in self.patterns]

    def detect_automated_workflow(self, prompt: str) -> bool:
        """
        Detect if prompt indicates an automated workflow request.

        Args:
            prompt: User prompt to analyze

        Returns:
            True if automated workflow is detected, False otherwise
        """
        if not prompt:
            return False

        # Check for workflow patterns
        for pattern in self._compiled_patterns:
            if pattern.search(prompt):
                logger.debug(f"Workflow pattern matched: {pattern.pattern}")
                return True

        return False

    def get_workflow_type(self, prompt: str) -> str | None:
        """
        Identify the type of workflow requested.

        Args:
            prompt: User prompt to analyze

        Returns:
            Workflow type string or None if not detected
        """
        prompt_lower = prompt.lower()

        if "parallel" in prompt_lower:
            return "parallel_execution"
        elif "multi-agent" in prompt_lower or "multiagent" in prompt_lower:
            return "multi_agent_coordination"
        elif "orchestrat" in prompt_lower:
            return "orchestration"
        elif "workflow" in prompt_lower:
            return "workflow_automation"

        return None
