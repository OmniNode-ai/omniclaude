#!/usr/bin/env python3
"""
PR Issue Collator - Python implementation with Pydantic models.

This module collates and categorizes PR review issues using type-safe
Pydantic models. It integrates with GitHub's GraphQL API to detect
resolved review threads and supports filtering by resolution status.

Features:
- Type-safe Pydantic models (PRIssue, CollatedIssues)
- Resolution detection via GitHub review threads
- Outdated detection (file changed after comment)
- --hide-resolved flag to filter resolved issues
- --show-status flag to display resolution indicators
- Compatible with existing bash collate-issues output format

Usage:
    # As CLI
    python collate_issues.py 33 --hide-resolved
    python collate_issues.py 33 --show-status --json

    # As module
    from collate_issues import collate_pr_issues
    issues = collate_pr_issues(33, hide_resolved=True)
    print(issues.get_summary())
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, TypedDict


SCRIPT_DIR = Path(__file__).parent

try:
    from models import (
        BotType,
        CollatedIssues,
        CommentSeverity,
        CommentStatus,
        PRComment,
        PRCommentSource,
        PRIssue,
        detect_bot_type,
    )
except ImportError:
    # Fallback for standalone execution
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))
    from models import (
        BotType,
        CollatedIssues,
        CommentSeverity,
        CommentStatus,
        PRComment,
        PRCommentSource,
        PRIssue,
        detect_bot_type,
    )


# =============================================================================
# ONEX-Compliant Error Handling
# =============================================================================


class OnexError(Exception):
    """ONEX-compliant error for PR review operations.

    Provides structured error handling with error codes and context.

    Args:
        message: Human-readable error message.
        code: Error code string (e.g., "FETCH_FAILED", "PARSE_ERROR").
        context: Optional dict with additional error context.

    Example:
        >>> raise OnexError("Failed to fetch PR", code="FETCH_FAILED", context={"pr": 40})
    """

    def __init__(
        self, message: str, code: str = "GENERAL_ERROR", context: dict | None = None
    ):
        super().__init__(message)
        self.code = code
        self.context = context or {}
        self.message = message

    def __str__(self) -> str:
        if self.context:
            return f"[{self.code}] {self.message} (context: {self.context})"
        return f"[{self.code}] {self.message}"


# =============================================================================
# Constants
# =============================================================================

# Maximum characters for issue description truncation
MAX_DESCRIPTION_LENGTH = 200


# =============================================================================
# Type Definitions
# =============================================================================


class ExtractedIssue(TypedDict):
    """Type-safe structure for issues extracted from comment bodies."""

    severity: CommentSeverity
    location: str
    summary: str


# =============================================================================
# Severity Detection Patterns
# =============================================================================

CRITICAL_PATTERNS = [
    r"## 🔴",
    r"### 🔴",
    r"### CRITICAL:",
    r"### Must Fix",
    r"## Must Fix",
    r"\*\*Must Fix\*\*",
    r"critical",
    r"security",
    r"vulnerability",
    r"data.?loss",
    r"crash",
    r"breaking.?change",
    r"blocker",
]

MAJOR_PATTERNS = [
    r"## ⚠️ Moderate",
    r"### ⚠️",
    r"### MAJOR:",
    r"### Should Fix",
    r"## Should Fix",
    r"\*\*Should Fix\*\*",
    r"## 🐛",
    r"## Issues & Concerns",
    r"## Areas for Improvement",
    r"major",
    r"bug",
    r"error",
    r"incorrect",
    r"performance",
    r"inconsistent",
    r"missing.*(test|validation|error.?handling)",
]

MINOR_PATTERNS = [
    r"## 💡 Suggestion",
    r"### 💡",
    r"### MINOR:",
    r"minor",
    r"suggestion",
    r"consider",
    r"could",
    r"might",
    r"nice.?to.?have",
    r"documentation",
    r"docstring",
]

NITPICK_PATTERNS = [
    r"nitpick",
    r"nit:",
    r"style",
    r"formatting",
    r"naming",
    r"cosmetic",
    r"optional",
]


def classify_severity(body: str) -> CommentSeverity:
    """
    Classify comment severity based on body content.

    Analyzes the comment body for severity indicator patterns (critical,
    major, minor, nitpick) and returns the appropriate severity level.

    Args:
        body: The comment body text to analyze for severity patterns.

    Returns:
        CommentSeverity enum value based on detected patterns.
        Returns UNCLASSIFIED if no patterns match.

    Example:
        >>> classify_severity("This is a critical security issue")
        CommentSeverity.CRITICAL
        >>> classify_severity("nit: rename this variable")
        CommentSeverity.NITPICK
    """
    if not body:
        return CommentSeverity.UNCLASSIFIED

    # Check patterns in priority order (using re.IGNORECASE for case-insensitive matching)
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.CRITICAL

    for pattern in MAJOR_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.MAJOR

    for pattern in MINOR_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.MINOR

    for pattern in NITPICK_PATTERNS:
        if re.search(pattern, body, re.IGNORECASE):
            return CommentSeverity.NITPICK

    return CommentSeverity.UNCLASSIFIED


# =============================================================================
# Noise Filtering
# =============================================================================

# Patterns that indicate a line is NOT an actionable issue (praise, metadata, etc.)
NOISE_PATTERNS = [
    # Praise and approval indicators
    r"^\s*\*?APPROVE\*?\*?\s*[✅🟢]?",
    r"^\s*[✅✔🟢🎉👍👏💯🌟⭐]",
    r"[✅✔🟢🎉👍👏💯🌟⭐]\s*$",  # Trailing positive emojis
    r"^\s*great\s*(job|work)?",
    r"^\s*excellent",
    r"^\s*well\s*done",
    r"^\s*looks?\s*good",
    r"^\s*nice\s*(work|job)?",
    r"^\s*perfect",
    r"^\s*impressive",
    r"^\s*thorough",
    r"^\s*comprehensive",
    r"^\s*solid",
    r"^\s*clean\s*(code|implementation)?",
    r"\blgtm\b",
    r"\bapproved?\b",
    r"^\s*no\s*(issues?|concerns?|problems?)",
    r"^\s*ship\s*it",
    r"^\s*ready\s*(to\s*)?(merge|ship)",
    r"^\s*good\s*to\s*(go|merge)",
    # Praise phrases anywhere in text
    r"\bwell[\s-]*(written|designed|thought[\s-]*out|implemented|tested)\b",
    r"\b(nicely|properly|correctly)\s*(handled|implemented|done)\b",
    r"\bgood\s*(use|example|practice|pattern|approach)\b",
    r"\bclean\s*(implementation|design|code|approach)\b",
    r"\bsolid\s*(implementation|approach|foundation|work)\b",
    # Review metadata
    r"^\s*\*?\*?Review\s*(Date|completed|by|status)",
    r"^\s*Reviewed\s*(by|on|at)",
    r"^\s*Time\s*spent:",
    r"^\s*Files\s*analyzed:",
    r"^\s*lines?\s*of\s*(code|tests?)",
    r"\+\d+\s*/\s*-\d+\s*lines?",
    r"\d+\s*well-organized\s*tests?",
    r"\d+%\s*(test\s*)?coverage",
    r"\d+\s*additions?,?\s*\d+\s*deletions?",
    r"^\s*Commit:\s*[a-f0-9]+",
    r"^\s*Branch:\s*\S+",
    r"^\s*Author:\s*\S+",
    r"^\s*Date:\s*\d",
    # Statistics and metrics (not actionable)
    r"^\s*\d+\s*tests?\s*:",
    r"^\s*providing\s*(excellent|good|comprehensive)",
    r"^\s*total:\s*\d+",
    r"^\s*\d+\s*files?\s*(changed|modified|added|deleted)",
    r"^\s*\d+\s*insertions?",
    r"^\s*\d+\s*functions?\s*(added|modified)",
    # Checklist/test plan markers (these are tasks, not review issues)
    r"^(UNCHECKED|CHECKED):",
    r"^-\s*\[\s*[x ]?\s*\]",
    r"^\s*\[\s*[x ]?\s*\]",
    r"^TODO\s*:",
    r"^TEST\s*PLAN",
    # Section headers without content (just formatting)
    r"^#{1,6}\s*$",  # Empty headers
    r"^#{1,6}\s+[A-Za-z\s]+\s*$",  # Simple section headers like "### Summary"
    r"^#{1,4}\s*\d+\.\s*\*\*[^*]+:\s*[^*]*\*\*\s*$",
    r"^---+$",  # Horizontal rules
    r"^===+$",
    r"^\*\*\*+$",
    # Positive summary sections
    r"test\s*coverage.*\d+%",
    r"excellent\s*type\s*safety",
    r"good\s*architecture",
    r"well[\s-]*structured",
    r"well[\s-]*organized",
    r"well[\s-]*documented",
    # Generic section headers that aren't specific issues
    r"^(issues?|improvements?|suggestions?|recommendations?)\s*\(\d+\)\s*$",
    r"^\s*(non-blocking|optional|nice[\s-]*to[\s-]*have)\s*$",
    r"^\s*(summary|overview|conclusion|verdict|assessment)\s*:?\s*$",
    r"^\s*(strengths?|positives?|pros?|what.s\s*good)\s*:?\s*$",
    r"^\s*(weaknesses?|negatives?|cons?|areas?\s*for\s*improvement)\s*:?\s*$",
    # Section headers with parentheticals like "Improvements (Non-Blocking)"
    r"^(improvements?|suggestions?|issues?|concerns?)\s*\([^)]+\)\s*$",
    # Very short labels/headers (less than 15 chars with no action words)
    r"^[A-Za-z\s]{1,15}$",
    # Bot-specific noise
    r"walkthrough",
    r"sequence\s*diagram",
    r"^\s*<details>",
    r"^\s*</details>",
    r"^\s*<summary>",
    r"^\s*</summary>",
    # Merge status indicators
    r"^\s*mergeable\s*:\s*(true|false|yes|no)",
    r"^\s*conflicts?\s*:\s*(none|0)",
    r"^\s*ci\s*(status|checks?)\s*:\s*(passing|green|success)",
]

# Words/phrases that indicate something IS an actionable issue
ACTIONABLE_INDICATORS = [
    r"\bshould\b",
    r"\bmust\b",
    r"\bneed\s*to\b",
    r"\bfix\b",
    r"\bbug\b",
    r"\berror\b",
    r"\bmissing\b",
    r"\bincorrect\b",
    r"\bwrong\b",
    r"\bfail",
    r"\bbreak",
    r"\bissue\b",
    r"\bproblem\b",
    r"\bvulnerab",
    r"\bsecurity\b",
    r"\bconsider\b",
    r"\brefactor\b",
    r"\bimprove\b",
    r"\boptimize\b",
    r"\badd\s+(a\s+)?test",
    r"\btest\s+coverage\b(?!\s*\d)",  # "test coverage" not followed by percentage
    r"\bhandle\b",
    r"\bvalidat",
    r"\bcheck\b",
    r"\bensure\b",
    r"\brename\b",
    r"\bremove\b",
    r"\bdelete\b",
    r"\breplace\b",
    r"\bupdate\b.*\bto\b",
    r"\bchange\b.*\bto\b",
]


def is_noise(text: str) -> bool:
    """
    Check if text is noise (praise, metadata, statistics) rather than an actionable issue.

    Args:
        text: The text to check.

    Returns:
        True if the text appears to be noise, False if it might be actionable.
    """
    if not text or not text.strip():
        return True

    text_clean = text.strip()
    text_lower = text_clean.lower()

    # Strip markdown formatting for analysis
    # Remove leading markdown headers (###, ##, #)
    text_for_check = re.sub(r"^#{1,6}\s*", "", text_clean)
    # Remove bold markers
    text_for_check = re.sub(r"\*\*([^*]+)\*\*", r"\1", text_for_check)
    # Remove italic markers
    text_for_check = re.sub(r"\*([^*]+)\*", r"\1", text_for_check)
    text_for_check = text_for_check.strip()

    # Empty after stripping formatting
    if not text_for_check:
        return True

    # Very short text (less than 10 chars) is likely a label/header
    if len(text_for_check) < 10:
        return True

    # Pure header patterns (just a category name like "Summary", "Overview")
    if re.match(r"^[A-Za-z\s]{1,25}:?\s*$", text_for_check):
        return True

    # Check against noise patterns
    for pattern in NOISE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True

    # Additional context-aware noise detection
    # Lines that are mostly positive emoji
    emoji_count = len(re.findall(r"[✅✔🟢🎉👍👏💯🌟⭐🚀💪✨🏆]", text_clean))
    if emoji_count > 0 and len(text_for_check) < 50:
        # Short text with positive emojis is likely praise
        return True

    # Lines that start with numbers followed by a noun (statistics)
    if re.match(
        r"^\d+\s+(tests?|files?|functions?|classes?|methods?|lines?)\b", text_lower
    ):
        return True

    return False


def is_actionable_issue(text: str) -> bool:
    """
    Check if text describes an actionable issue that needs to be addressed.

    An actionable issue typically:
    - Contains problem-indicating words (should, must, fix, bug, etc.)
    - Describes something that needs to be changed or addressed
    - Is NOT praise, metadata, or statistics

    Args:
        text: The text to check.

    Returns:
        True if the text appears to be an actionable issue.
    """
    if not text or not text.strip():
        return False

    # First check if it's noise
    if is_noise(text):
        return False

    text_lower = text.lower()

    # Check for actionable indicators
    for pattern in ACTIONABLE_INDICATORS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True

    # If no actionable indicators found, it's likely not an issue
    # (e.g., just a section header or description)
    return False


# =============================================================================
# Issue Extraction
# =============================================================================


def extract_issues_from_body(body: str, source: str = "") -> list[ExtractedIssue]:
    """
    Extract individual issues from a structured comment body.

    Looks for patterns like:
    - ### 1. **Title** (only if it describes an actionable issue)
    - **N. Title (PRIORITY)**
    - ### CRITICAL: description
    - CodeRabbit format: `line-range`: **Title** in <details> blocks
    - CodeRabbit inline format: _⚠️ Potential issue_ | _🔴 Critical_ followed by **Title**

    Filters out:
    - Praise and approval text
    - Review metadata (dates, statistics)
    - Checklist items from PR description
    - Section headers without actionable content

    Args:
        body: Comment body text.
        source: Location string like "[path:line]".

    Returns:
        List of ExtractedIssue dicts with {severity, location, summary}.
        Deduplicated by normalized summary text.
    """
    issues: list[ExtractedIssue] = []
    # Track seen summaries to prevent duplicate issues from multiple patterns
    seen_summaries: set[str] = set()

    def add_issue(
        severity: CommentSeverity,
        summary: str,
        location: str = "",
        from_structured_pattern: bool = False,
    ) -> None:
        """Add issue if not already seen and if it's actionable.

        Args:
            severity: The severity level of the issue.
            summary: The issue summary text.
            location: Optional location override (e.g., file path from CodeRabbit).
            from_structured_pattern: If True, the issue was extracted from a recognized
                structured pattern (like ### N. **Title** or **N. Title (Priority)**).
                These patterns indicate the text is an issue, so we skip aggressive
                noise filtering that would reject valid issue titles.
        """
        summary = summary.strip()
        normalized = summary.lower()

        # Skip if empty or already seen
        if not normalized:
            return
        if normalized in seen_summaries:
            return

        # For items from structured patterns, trust the pattern - only apply minimal checks
        if from_structured_pattern:
            # Still skip truly empty or single-word items
            if len(summary.split()) < 2:
                return
        else:
            # Apply full noise filtering for unstructured content
            if is_noise(summary):
                return

            # For items that don't have explicit severity markers, require actionable content
            if (
                severity == CommentSeverity.UNCLASSIFIED
                or severity == CommentSeverity.MAJOR
            ):
                if not is_actionable_issue(summary):
                    return

        seen_summaries.add(normalized)
        # Use provided location override if given, otherwise use source
        issue_location = location if location else source
        issues.append(
            ExtractedIssue(severity=severity, location=issue_location, summary=summary)
        )

    if not body:
        return issues

    # ==========================================================================
    # CodeRabbit Inline Comment Format (from pulls/{pr}/comments endpoint)
    # ==========================================================================
    # CodeRabbit inline comments use format:
    #   _⚠️ Potential issue_ | _🔴 Critical_
    #   <details>...analysis...</details>
    #   **Issue title/description**
    #
    # Or:
    #   _🛠️ Refactor suggestion_ | _🟠 Major_
    #   <details>...</details>
    #   **Suggestion title**

    # Pattern to detect CodeRabbit inline severity indicators
    # Format: _emoji Type_ | _emoji Severity_
    # Note: Emojis can be multi-byte, so we use a more flexible pattern
    # Examples:
    #   _⚠️ Potential issue_ | _🔴 Critical_
    #   _🛠️ Refactor suggestion_ | _🟠 Major_
    coderabbit_inline_pattern = r"_[^\s_]+\s*(?:Potential\s+issue|Refactor\s+suggestion|Suggestion|Note|Tip|Warning)_\s*\|\s*_([^\s_]+)\s*(Critical|Major|Minor|Low|Nitpick|Info)_"
    inline_match = re.search(coderabbit_inline_pattern, body, re.IGNORECASE)

    if inline_match:
        # This is a CodeRabbit inline comment - extract severity and title
        severity_emoji = inline_match.group(1) if inline_match.group(1) else ""
        severity_text = inline_match.group(2).lower() if inline_match.group(2) else ""

        # Map CodeRabbit severity to our severity
        if "🔴" in severity_emoji or severity_text == "critical":
            cr_severity = CommentSeverity.CRITICAL
        elif "🟠" in severity_emoji or severity_text == "major":
            cr_severity = CommentSeverity.MAJOR
        elif "🟡" in severity_emoji or severity_text in ("minor", "low"):
            cr_severity = CommentSeverity.MINOR
        else:
            cr_severity = CommentSeverity.NITPICK

        # Find the issue title - there are two CodeRabbit formats:
        # Format A (with analysis): _severity_ ... <details>analysis</details> **Title**
        # Format B (direct):        _severity_ ... **Title** ... <details>AI prompt</details>
        #
        # Key insight: In Format A, the <details> block appears RIGHT AFTER the severity line
        # In Format B, **Title** appears directly after severity, with <details> at the end

        after_severity = body[inline_match.end() :]

        # Check if there's a <details> block immediately after the severity line (within first 50 chars)
        # This indicates Format A (analysis chain format)
        details_start_near = after_severity[:100].find("<details>")

        if details_start_near >= 0 and details_start_near < 50:
            # Format A: Look for title AFTER the first </details>
            first_details_end = after_severity.find("</details>")
            if first_details_end > 0:
                after_first_details = after_severity[first_details_end + 10 :]
                bold_match = re.search(
                    r"^\s*\*\*([^*]+)\*\*", after_first_details, re.MULTILINE
                )
                if bold_match:
                    title = bold_match.group(1).strip()
                    title = re.sub(r"\s+", " ", title)  # Normalize whitespace
                    if len(title) > 10 and not title.startswith(
                        "🤖"
                    ):  # Skip AI prompt markers
                        add_issue(
                            cr_severity,
                            title,
                            location=source,
                            from_structured_pattern=True,
                        )
        else:
            # Format B: Look for first bold text directly after severity line
            bold_match = re.search(r"\*\*([^*]+)\*\*", after_severity)
            if bold_match:
                title = bold_match.group(1).strip()
                title = re.sub(r"\s+", " ", title)
                if len(title) > 10 and not title.startswith("🤖"):
                    add_issue(
                        cr_severity,
                        title,
                        location=source,
                        from_structured_pattern=True,
                    )

    # ==========================================================================
    # CodeRabbit HTML Format Extraction
    # ==========================================================================
    # CodeRabbit uses HTML structure like:
    # <summary>Nitpick comments (N)</summary><blockquote>
    # <details><summary>file.py (M)</summary><blockquote>
    # `line-range`: **Title**
    # Description text...
    #
    # IMPORTANT: CodeRabbit has multiple section types:
    # - "Nitpick comments" - Actual issues to address
    # - "Actionable comments" - Issues that need action
    # - "Additional comments" - Positive acknowledgments (NOT issues, skip these!)

    # Find the positions of each section type in the body
    # We'll use these positions to determine which section a file comment belongs to
    nitpick_section_start = -1
    actionable_section_start = -1
    additional_section_start = -1

    nitpick_header = re.search(r"<summary>[^<]*[Nn]itpick[^<]*\(\d+\)</summary>", body)
    if nitpick_header:
        nitpick_section_start = nitpick_header.start()

    actionable_header = re.search(
        r"<summary>[^<]*[Aa]ctionable\s+comments[^<]*\(\d+\)</summary>", body
    )
    if actionable_header:
        actionable_section_start = actionable_header.start()

    additional_header = re.search(
        r"<summary>[^<]*[Aa]dditional\s+comments[^<]*\(\d+\)</summary>", body
    )
    if additional_header:
        additional_section_start = additional_header.start()

    # Extract file-level sections from CodeRabbit format
    # Pattern: <summary>path/to/file.ext (N)</summary> OR <summary>path/to/file (N)</summary>
    # Note: Some files don't have extensions (e.g., shell scripts like "ci-quick-review")
    # The pattern matches: filename with optional extension, space, (number)
    file_section_pattern = (
        r"<summary>([a-zA-Z0-9_./-]+(?:\.[a-zA-Z0-9]+)?)\s*\(\d+\)</summary>"
    )
    file_sections = re.finditer(file_section_pattern, body)

    for file_match in file_sections:
        file_path = file_match.group(1).strip()
        file_pos = file_match.start()

        # Determine which section this file belongs to based on position
        # A file belongs to the section whose header appears BEFORE it and is closest
        section_type = None

        # Check if in Additional comments section - SKIP these (they're positive acknowledgments)
        if additional_section_start >= 0 and file_pos > additional_section_start:
            # Check if there's no other section header between additional and file
            if (
                nitpick_section_start < 0
                or nitpick_section_start < additional_section_start
                or nitpick_section_start > file_pos
            ) and (
                actionable_section_start < 0
                or actionable_section_start < additional_section_start
                or actionable_section_start > file_pos
            ):
                # This file is in the Additional comments section - SKIP IT
                continue

        # Check if in Nitpick section
        if nitpick_section_start >= 0 and file_pos > nitpick_section_start:
            if (
                actionable_section_start < 0
                or actionable_section_start > file_pos
                or actionable_section_start < nitpick_section_start
            ) and (
                additional_section_start < 0
                or additional_section_start > file_pos
                or additional_section_start < nitpick_section_start
            ):
                section_type = "nitpick"

        # Check if in Actionable section
        if actionable_section_start >= 0 and file_pos > actionable_section_start:
            if (
                nitpick_section_start < 0
                or nitpick_section_start > file_pos
                or nitpick_section_start < actionable_section_start
            ) and (
                additional_section_start < 0
                or additional_section_start > file_pos
                or additional_section_start < actionable_section_start
            ):
                section_type = "actionable"

        if section_type is None:
            # File not in a recognized issue section - skip
            continue

        # Set default severity based on section
        default_severity = (
            CommentSeverity.NITPICK
            if section_type == "nitpick"
            else CommentSeverity.MAJOR
        )

        # Find the content after this file section up to the next </blockquote></details>
        start_pos = file_match.end()
        # Find the closing tags for this section
        end_match = re.search(r"</blockquote>\s*</details>", body[start_pos:])
        if end_match:
            section_content = body[start_pos : start_pos + end_match.start()]
        else:
            # Take remaining content
            section_content = body[start_pos:]

        # Extract CodeRabbit line reference format: `line-range`: **Title**
        # e.g., `305-312`: **Robust Pydantic violation logging; consider optional dict fallback**
        line_ref_pattern = r"`(\d+(?:-\d+)?)`:?\s*\*\*([^*]+)\*\*"
        line_matches = re.finditer(line_ref_pattern, section_content)

        for line_match in line_matches:
            line_range = line_match.group(1)
            title = line_match.group(2).strip()

            # Build location from file path and line range
            location = f"[{file_path}:{line_range}]"

            # Determine severity - CodeRabbit section classification takes precedence
            # Only override if title contains STRONGER severity keywords (critical/major)
            severity = default_severity
            title_severity = classify_severity(title)
            # Only upgrade severity if the title indicates something more serious
            # (e.g., a "nitpick" section item that mentions "security" should become critical)
            if title_severity in (CommentSeverity.CRITICAL, CommentSeverity.MAJOR):
                if title_severity.priority_order < severity.priority_order:
                    severity = title_severity

            add_issue(severity, title, location=location, from_structured_pattern=True)

    # ==========================================================================
    # Standard Markdown Format Extraction (Claude, generic)
    # ==========================================================================

    # IMPORTANT: Section-aware extraction MUST run FIRST to capture correct severity
    # from context (Critical Issues, High Priority Issues, etc.)

    # Pattern: Claude Code section headers with issues
    # Claude uses: ### **Critical Issues** / ### **High Priority Issues** / ### **Medium Priority Issues**
    # Items under these sections follow format: #### N. **Title** (BLOCKING) or just #### N. **Title**
    claude_sections = [
        (r"###\s*\*\*Critical\s*Issues?\*\*", CommentSeverity.CRITICAL),
        (r"###\s*\*\*High\s*Priority\s*Issues?\*\*", CommentSeverity.MAJOR),
        (r"###\s*\*\*Medium\s*Priority\s*Issues?\*\*", CommentSeverity.MINOR),
        (r"###\s*\*\*Low\s*Priority\s*Issues?\*\*", CommentSeverity.NITPICK),
    ]
    for section_pattern, section_severity in claude_sections:
        section_match = re.search(section_pattern, body, re.IGNORECASE)
        if section_match:
            # Find content between this section and the next ### header
            section_start = section_match.end()
            next_section = re.search(r"\n###\s", body[section_start:])
            if next_section:
                section_content = body[
                    section_start : section_start + next_section.start()
                ]
            else:
                section_content = body[section_start:]

            # Extract #### N. **Title** patterns within this section
            section_items = re.findall(
                r"####\s*\d+\.\s*\*\*([^*]+)\*\*", section_content
            )
            for item_title in section_items:
                item_title = item_title.strip()
                # Check for BLOCKING indicator to upgrade severity
                effective_severity = section_severity
                if (
                    "(BLOCKING)" in item_title.upper()
                    or "(REQUIRED)" in item_title.upper()
                ):
                    effective_severity = CommentSeverity.CRITICAL
                # Clean up the title
                item_title = re.sub(
                    r"\s*\(BLOCKING\)\s*", "", item_title, flags=re.IGNORECASE
                )
                item_title = re.sub(
                    r"\s*\(REQUIRED\)\s*", "", item_title, flags=re.IGNORECASE
                )
                add_issue(
                    effective_severity, item_title.strip(), from_structured_pattern=True
                )

    # Pattern: Section-aware extraction for "Suggestions" and "Observations"
    # Claude uses sections like:
    #   ## Suggestions for Improvement
    #   ### 1. Title
    #   ### 2. Another Title
    # Or:
    #   ### 💡 Observations & Suggestions
    #   #### 1. **Title**
    #   #### 2. **Another**
    suggestion_sections = [
        (r"##\s*Suggestions?\s+for\s+Improvement", CommentSeverity.MINOR),
        (r"###\s*💡?\s*Observations?\s*&?\s*Suggestions?", CommentSeverity.MINOR),
        (r"##\s*Potential\s+Issues?", CommentSeverity.MAJOR),
        (r"###\s*Potential\s+Issues?", CommentSeverity.MAJOR),
        # Claude "Areas for Improvement" section - items have inline severity hints
        (r"###?\s*🔍?\s*Areas?\s+for\s+Improvement", CommentSeverity.MINOR),
        # Claude "Minor Suggestions" / "Future Optimization" sections
        (r"###?\s*📝?\s*Minor\s+Suggestions?(?:\s*\([^)]+\))?", CommentSeverity.MINOR),
        (
            r"###?\s*💡?\s*Future\s+Optimizations?(?:\s*\([^)]+\))?",
            CommentSeverity.NITPICK,
        ),
        (r"###?\s*💡?\s*Recommendations?", CommentSeverity.MINOR),
        (r"###?\s*📋?\s*Follow[- ]?ups?(?:\s*\([^)]+\))?", CommentSeverity.MINOR),
    ]

    for section_pattern, section_severity in suggestion_sections:
        section_match = re.search(section_pattern, body, re.IGNORECASE)
        if section_match:
            # Find content between this section and next ## header
            section_start = section_match.end()
            next_section = re.search(r"\n##\s", body[section_start:])
            if next_section:
                section_content = body[
                    section_start : section_start + next_section.start()
                ]
            else:
                section_content = body[section_start:]

            # Extract numbered items within this section
            # Pattern matches multiple formats:
            #   ### 1. Plain title (markdown header)
            #   #### 1. **Bold title** (markdown header with bold)
            #   1. Plain numbered item (simple list)
            #   - Bullet item (simple list)
            # First try markdown headers
            section_items_plain = re.findall(
                r"#{3,4}\s*\d+\.\s*([^\n]+)", section_content
            )

            # Also capture plain numbered lists (1. Item, 2. Item, etc.)
            plain_numbered = re.findall(
                r"^\s*\d+\.\s+([^\n]+)", section_content, re.MULTILINE
            )
            section_items_plain.extend(plain_numbered)

            # Also capture bullet items (- Item)
            bullet_items = re.findall(
                r"^\s*[-*]\s+([^\n]+)", section_content, re.MULTILINE
            )
            section_items_plain.extend(bullet_items)
            for item_title in section_items_plain:
                item_title = item_title.strip()

                # Skip if it's a bold pattern (will be caught by next pattern)
                if item_title.startswith("**") and "**" in item_title[2:]:
                    continue

                # Remove emoji and clean up
                emojis_to_remove = [
                    "⭐",
                    "📚",
                    "🧪",
                    "⚠️",
                    "✅",
                    "🔍",
                    "❌",
                    "⚡",
                    "📝",
                    "💡",
                ]
                for emoji in emojis_to_remove:
                    item_title = item_title.replace(emoji, "")

                item_title = item_title.strip()

                # Skip if title is too short or looks like section header
                if len(item_title.split()) < 3:
                    continue

                # Determine severity from content - check for inline severity hints first
                # Format: **Title** (Minor) or **Title** (Critical) or **Title** (Very Minor)
                title_lower = item_title.lower()
                effective_severity = section_severity

                # Check for parenthesized severity hints (common in "Areas for Improvement")
                severity_hint_match = re.search(
                    r"\((Critical|Major|Minor|Very\s+Minor|Nitpick|Bug|Security|Potential\s+Bug|Security\s+Best\s+Practice)\)",
                    item_title,
                    re.IGNORECASE,
                )
                if severity_hint_match:
                    hint = severity_hint_match.group(1).lower()
                    if "critical" in hint or "security" in hint:
                        effective_severity = CommentSeverity.CRITICAL
                    elif "major" in hint or "bug" in hint:
                        effective_severity = CommentSeverity.MAJOR
                    elif "minor" in hint:
                        effective_severity = CommentSeverity.MINOR
                    elif "nitpick" in hint:
                        effective_severity = CommentSeverity.NITPICK
                    # Clean up the title by removing the severity hint
                    item_title = re.sub(r"\s*\([^)]*\)\s*$", "", item_title).strip()
                elif (
                    "critical" in title_lower
                    or "must" in title_lower
                    or "required" in title_lower
                ):
                    effective_severity = CommentSeverity.CRITICAL
                elif "should" in title_lower or "important" in title_lower:
                    effective_severity = CommentSeverity.MAJOR
                elif (
                    "consider" in title_lower
                    or "potential" in title_lower
                    or "enhancement" in title_lower
                ):
                    effective_severity = CommentSeverity.MINOR

                add_issue(effective_severity, item_title, from_structured_pattern=True)

    # Pattern: ### N. **Title** or #### N. **Title** (CodeRabbit/Claude structured format)
    # Claude Code uses #### for numbered issues under section headers like "### **Critical Issues**"
    # Claude also uses format: ### N. **Title** ⚠️ (Non-Blocking) or ### N. **Title** ✅ (Safe)
    # NOTE: This runs AFTER section-aware extraction, so items already found will be skipped
    #
    # Need to capture both the title AND any indicators that follow (emoji + status label)
    # Pattern: ### N. **Title** [optional emoji] [optional (Status)]
    numbered_bold_matches = re.findall(
        r"#{3,4} \d+\.\s*\*\*([^*]+)\*\*\s*([^\n]*)", body
    )
    for title, indicators in numbered_bold_matches:
        title = title.strip()
        indicators = indicators.strip()

        # Extract and handle Claude bot status indicators (emoji + status label)
        # Common patterns: ⚠️ (Non-Blocking), ✅ (Safe), 🔍 (Review), ❌ (BLOCKING), etc.
        effective_severity = None

        # Combine title and indicators for checking (indicators may contain emoji/status)
        full_text = f"{title} {indicators}"

        # Check for status labels and map to severity (check indicators first, then title)
        # Also check for inline severity hints like (Minor), (Major), (Critical), (Very Minor)
        if (
            re.search(r"\(BLOCKING\)", full_text, re.IGNORECASE)
            or re.search(r"\(CRITICAL\)", full_text, re.IGNORECASE)
            or re.search(r"\(REQUIRED\)", full_text, re.IGNORECASE)
        ):
            effective_severity = CommentSeverity.CRITICAL
        elif re.search(
            r"\(Security|Security\s+Best\s+Practice|Potential\s+Bug\)",
            full_text,
            re.IGNORECASE,
        ):
            effective_severity = CommentSeverity.CRITICAL
        elif re.search(r"\(Major\)", full_text, re.IGNORECASE) or re.search(
            r"\(Bug\)", full_text, re.IGNORECASE
        ):
            effective_severity = CommentSeverity.MAJOR
        elif (
            re.search(r"\(NON-BLOCKING\)", full_text, re.IGNORECASE) or "⚠️" in full_text
        ):
            effective_severity = CommentSeverity.MAJOR
        elif re.search(r"\(Minor\)", full_text, re.IGNORECASE) or re.search(
            r"\(Very\s+Minor\)", full_text, re.IGNORECASE
        ):
            effective_severity = CommentSeverity.MINOR
        elif re.search(r"\(SAFE\)", full_text, re.IGNORECASE) or "✅" in full_text:
            effective_severity = CommentSeverity.MINOR
        elif "🔍" in full_text or re.search(r"\(REVIEW\)", full_text, re.IGNORECASE):
            effective_severity = CommentSeverity.MINOR
        elif re.search(r"\(Nitpick\)", full_text, re.IGNORECASE):
            effective_severity = CommentSeverity.NITPICK
        elif "❌" in full_text:
            effective_severity = CommentSeverity.CRITICAL
        elif "⚡" in full_text:
            effective_severity = CommentSeverity.MAJOR
        elif "📝" in full_text:
            effective_severity = CommentSeverity.MINOR

        # Strip all emoji indicators (common ones from Claude bot reviews)
        emojis_to_remove = [
            "⚠️",
            "✅",
            "🔍",
            "❌",
            "⚡",
            "📝",
            "🔴",
            "🟡",
            "🟢",
            "⚫",
            "🔵",
            "🟣",
            "🟠",
        ]
        for emoji in emojis_to_remove:
            title = title.replace(emoji, "")

        # Strip status labels and severity hints in parentheses
        title = re.sub(
            r"\s*\((BLOCKING|NON-BLOCKING|CRITICAL|SAFE|REQUIRED|REVIEW|Minor|Major|Very\s+Minor|Nitpick|Bug|Security|Potential\s+Bug|Security\s+Best\s+Practice)\)\s*",
            "",
            title,
            flags=re.IGNORECASE,
        )

        # Clean up extra whitespace
        title = title.strip()

        # Skip section headers that are just categories (e.g., "Documentation: Usage Examples")
        if re.match(r"^[A-Za-z]+:\s*[A-Za-z\s]+$", title):
            # Check if the following content has actionable items
            continue

        # Use effective severity if determined from indicators, otherwise classify from title
        if effective_severity is None:
            effective_severity = classify_severity(title)

        add_issue(effective_severity, title, from_structured_pattern=True)

    # Pattern: - [ ] unchecked items (uncompleted checklist items from reviews)
    # These indicate pending items that need attention
    unchecked_items = re.findall(r"-\s*\[\s*\]\s*([^\n]+)", body)
    for item in unchecked_items:
        item = item.strip()
        if item:
            severity = classify_severity(item)
            add_issue(severity, item, from_structured_pattern=True)

    # Pattern: **N. Title (Priority)**
    priority_items = re.findall(r"\*\*\d+\.\s*([^(]+)\s*\(([^)]+)\)\*\*", body)
    for title, priority in priority_items:
        title = title.strip()
        if "high" in priority.lower() or "critical" in priority.lower():
            severity = CommentSeverity.CRITICAL
        elif "medium" in priority.lower():
            severity = CommentSeverity.MAJOR
        elif "low" in priority.lower():
            severity = CommentSeverity.MINOR
        else:
            severity = CommentSeverity.MAJOR
        add_issue(severity, title, from_structured_pattern=True)

    # Pattern: ### CRITICAL/MAJOR/MINOR: description
    for level, sev in [
        ("CRITICAL", CommentSeverity.CRITICAL),
        ("MAJOR", CommentSeverity.MAJOR),
        ("MINOR", CommentSeverity.MINOR),
    ]:
        matches = re.findall(rf"### {level}[:\s]+([^\n]+)", body, re.IGNORECASE)
        for desc in matches:
            add_issue(sev, desc, from_structured_pattern=True)

    # Pattern: Risk items (High Risk: / Medium Risk: / Low Risk:)
    risk_patterns = [
        (r"High Risk[:\s]+([^\n]+)", CommentSeverity.MAJOR),
        (r"Medium Risk[:\s]+([^\n]+)", CommentSeverity.MINOR),
        (r"Low Risk[:\s]+([^\n]+)", CommentSeverity.NITPICK),
    ]
    for pattern, sev in risk_patterns:
        matches = re.findall(pattern, body)
        for desc in matches:
            add_issue(sev, desc, from_structured_pattern=True)

    return issues


def is_claude_bot(author: str) -> bool:
    """Check if author is Claude Code bot.

    Uses detect_bot_type from models for consistent bot detection.

    Args:
        author: GitHub username to check.

    Returns:
        True if the author is identified as Claude Code bot.

    Example:
        >>> is_claude_bot("claude[bot]")
        True
        >>> is_claude_bot("octocat")
        False
    """
    return detect_bot_type(author) == BotType.CLAUDE_CODE


def is_coderabbit(author: str) -> bool:
    """Check if author is CodeRabbit bot.

    Uses detect_bot_type from models for consistent bot detection.

    Args:
        author: GitHub username to check.

    Returns:
        True if the author is identified as CodeRabbit bot.

    Example:
        >>> is_coderabbit("coderabbitai[bot]")
        True
        >>> is_coderabbit("github-actions[bot]")
        False
    """
    return detect_bot_type(author) == BotType.CODERABBIT


# =============================================================================
# Resolution Detection
# =============================================================================


def build_resolution_map(
    resolved_threads: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """
    Build a map of comment_id -> resolution info from resolved_threads.

    Args:
        resolved_threads: List of thread data from GraphQL API.

    Returns:
        Dict mapping comment database IDs to resolution info.
    """
    resolution_map: dict[int, dict[str, Any]] = {}

    for thread in resolved_threads:
        is_resolved = thread.get("is_resolved", False)
        is_outdated = thread.get("is_outdated", False)
        resolved_by = thread.get("resolved_by")

        # Map each comment in the thread
        comment_ids = thread.get("comment_ids", [])
        for cid in comment_ids:
            if cid:
                resolution_map[cid] = {
                    "is_resolved": is_resolved,
                    "is_outdated": is_outdated,
                    "resolved_by": resolved_by,
                    "path": thread.get("path"),
                    "line": thread.get("line"),
                }

    return resolution_map


def determine_comment_status(
    comment_id: Optional[int],
    resolution_map: dict[int, dict[str, Any]],
) -> tuple[CommentStatus, bool, Optional[str]]:
    """
    Determine comment resolution status from resolution map.

    Args:
        comment_id: GitHub comment database ID.
        resolution_map: Map from build_resolution_map().

    Returns:
        Tuple of (status, is_outdated, resolved_by).
    """
    if comment_id is None or comment_id not in resolution_map:
        return CommentStatus.UNADDRESSED, False, None

    info = resolution_map[comment_id]
    is_resolved = info.get("is_resolved", False)
    is_outdated = info.get("is_outdated", False)
    resolved_by = info.get("resolved_by")

    if is_outdated:
        return CommentStatus.OUTDATED, True, resolved_by
    if is_resolved:
        return CommentStatus.RESOLVED, False, resolved_by

    return CommentStatus.UNADDRESSED, False, None


# =============================================================================
# Main Collation Logic
# =============================================================================


def fetch_pr_data(pr_input: str | int) -> dict[str, Any]:
    """
    Fetch PR data using the fetch-pr-data script.

    Args:
        pr_input: PR number (int or str) or full GitHub URL.
            URLs preserve repository context for cross-repo fetching.

    Returns:
        Parsed JSON data from fetch-pr-data.

    Raises:
        OnexError: If fetch fails, with appropriate error code.
    """
    fetch_script = SCRIPT_DIR / "fetch-pr-data"

    try:
        result = subprocess.run(
            [str(fetch_script), str(pr_input)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            raise OnexError(
                f"fetch-pr-data failed: {result.stderr}",
                code="FETCH_FAILED",
                context={"pr_input": str(pr_input)},
            )

        if not result.stdout.strip():
            raise OnexError(
                "fetch-pr-data returned empty output",
                code="EMPTY_OUTPUT",
                context={"pr_input": str(pr_input)},
            )

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise OnexError(
            "fetch-pr-data timed out",
            code="TIMEOUT",
            context={"pr_input": str(pr_input)},
        )
    except json.JSONDecodeError as e:
        raise OnexError(
            f"Failed to parse fetch-pr-data output: {e}",
            code="PARSE_ERROR",
            context={"pr_input": str(pr_input)},
        )


def get_repo_name() -> str:
    """Get repository name from git.

    Uses the GitHub CLI to retrieve the current repository's name with owner.

    Returns:
        Repository name in format "owner/repo", or empty string on failure.

    Example:
        >>> get_repo_name()  # In OmniNode-ai/omniclaude repo
        'OmniNode-ai/omniclaude'
    """
    try:
        result = subprocess.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError, ValueError):
        pass
    return ""


def collate_pr_issues(
    pr_input: str | int,
    hide_resolved: bool = False,
    show_resolved_only: bool = False,
    include_nitpicks: bool = False,
) -> CollatedIssues:
    """
    Collate PR review issues with resolution detection.

    Args:
        pr_input: PR number (int or str) or full GitHub URL.
            URLs preserve repository context for cross-repo fetching.
        hide_resolved: If True, exclude resolved issues.
        show_resolved_only: If True, only include resolved issues.
        include_nitpicks: If True, include nitpick issues (otherwise filtered).

    Returns:
        CollatedIssues instance with categorized issues.

    Raises:
        OnexError: If PR data fetch fails or invalid options provided.
    """
    if hide_resolved and show_resolved_only:
        raise OnexError(
            "Cannot use both hide_resolved and show_resolved_only",
            code="INVALID_OPTIONS",
        )

    # Fetch PR data
    pr_data = fetch_pr_data(pr_input)

    # Build resolution map from resolved_threads
    resolved_threads = pr_data.get("resolved_threads", [])
    resolution_map = build_resolution_map(resolved_threads)

    # Collect all issues
    all_issues: list[PRIssue] = []

    # Process each comment source
    comment_sources = [
        ("reviews", "body"),
        ("inline_comments", "body"),
        ("pr_comments", "body"),
        ("issue_comments", "body"),
    ]

    for source_key, body_key in comment_sources:
        comments = pr_data.get(source_key, [])
        if not isinstance(comments, list):
            continue

        for comment in comments:
            if not isinstance(comment, dict):
                continue

            body = comment.get(body_key, "")
            if not body:
                continue

            # Skip addressed comments
            if body.strip().startswith("Addressed"):
                continue

            author = comment.get("author", "")
            comment_id = comment.get("id")
            path = comment.get("path", "")
            line = comment.get("line")

            # CRITICAL: Claude bot and CodeRabbit comments must NEVER be filtered as noise
            # Check author type BEFORE applying noise filtering
            is_ai_reviewer = is_claude_bot(author) or is_coderabbit(author)

            # Skip comments that are entirely noise (praise, metadata, etc.)
            # BUT NEVER skip AI reviewer comments - they have structured content
            if not is_ai_reviewer:
                # Get first non-empty line to check
                first_line = ""
                for line_text in body.strip().split("\n"):
                    line_text = line_text.strip()
                    if (
                        line_text
                        and not line_text.startswith("#")
                        and not line_text.startswith("<!--")
                    ):
                        first_line = line_text
                        break

                if is_noise(first_line) or is_noise(body[:200]):
                    continue

            # Determine location string
            location = ""
            if path:
                if line:
                    location = f"[{path}:{line}]"
                else:
                    location = f"[{path}]"

            # Get resolution status
            status, is_outdated, resolved_by = determine_comment_status(
                comment_id, resolution_map
            )

            # Check if this is a structured bot comment
            if is_ai_reviewer:
                # Extract structured issues from bot comments
                extracted = extract_issues_from_body(body, location)
                for item in extracted:
                    # Convert comment_id to int only if it's a pure numeric string
                    # GraphQL node IDs like "IC_kwDOABC123" cannot be stored as int
                    safe_comment_id = None
                    if comment_id is not None:
                        comment_id_str = str(comment_id)
                        if comment_id_str.isdigit():
                            safe_comment_id = int(comment_id_str)

                    issue = PRIssue(
                        file_path=path,
                        line_number=(
                            int(line)
                            if isinstance(line, (int, str)) and str(line).isdigit()
                            else None
                        ),
                        severity=item["severity"],
                        description=item["summary"],
                        status=status,
                        comment_id=safe_comment_id,
                        is_outdated=is_outdated,
                        resolved_by=resolved_by,
                    )
                    all_issues.append(issue)
            else:
                # Single issue from human comment
                severity = classify_severity(body)

                # Extract first meaningful line as summary
                lines = body.strip().split("\n")
                summary = ""
                for line_text in lines:
                    line_text = line_text.strip()
                    if (
                        line_text
                        and not line_text.startswith("#")
                        and not line_text.startswith("<!--")
                    ):
                        summary = line_text[:MAX_DESCRIPTION_LENGTH]
                        break

                if not summary or len(summary) < 10:
                    continue

                # Skip HTML comments
                if summary.startswith("<!--") and summary.endswith("-->"):
                    continue

                # Skip noise (praise, metadata, statistics)
                if is_noise(summary):
                    continue

                # For human comments, also check if it's actionable
                # (unless it's clearly a critical/minor severity from classify_severity)
                if severity in (CommentSeverity.UNCLASSIFIED, CommentSeverity.MAJOR):
                    if not is_actionable_issue(summary):
                        continue

                # Convert comment_id to int only if it's a pure numeric string
                # GraphQL node IDs like "IC_kwDOABC123" cannot be stored as int
                safe_comment_id = None
                if comment_id is not None:
                    comment_id_str = str(comment_id)
                    if comment_id_str.isdigit():
                        safe_comment_id = int(comment_id_str)

                issue = PRIssue(
                    file_path=path,
                    line_number=(
                        int(line)
                        if isinstance(line, (int, str)) and str(line).isdigit()
                        else None
                    ),
                    severity=severity,
                    description=summary,
                    status=status,
                    comment_id=safe_comment_id,
                    is_outdated=is_outdated,
                    resolved_by=resolved_by,
                )
                all_issues.append(issue)

    # Deduplicate by description (keep first occurrence)
    seen_descriptions: set[str] = set()
    unique_issues: list[PRIssue] = []
    for issue in all_issues:
        key = f"{issue.location}|{issue.description}"
        if key not in seen_descriptions:
            seen_descriptions.add(key)
            unique_issues.append(issue)

    # Categorize by severity
    critical: list[PRIssue] = []
    major: list[PRIssue] = []
    minor: list[PRIssue] = []
    nitpick: list[PRIssue] = []
    unclassified: list[PRIssue] = []

    for issue in unique_issues:
        if issue.severity == CommentSeverity.CRITICAL:
            critical.append(issue)
        elif issue.severity == CommentSeverity.MAJOR:
            major.append(issue)
        elif issue.severity == CommentSeverity.MINOR:
            minor.append(issue)
        elif issue.severity == CommentSeverity.NITPICK:
            nitpick.append(issue)
        else:
            unclassified.append(issue)

    # Build CollatedIssues
    # Extract PR number from fetched data (it's already resolved by fetch-pr-data)
    actual_pr_number = pr_data.get("pr_number", 0)
    actual_repository = pr_data.get("repository", get_repo_name())
    result = CollatedIssues(
        pr_number=actual_pr_number,
        repository=actual_repository,
        collated_at=datetime.now(),
        critical=critical,
        major=major,
        minor=minor,
        nitpick=nitpick if include_nitpicks else [],
        unclassified=unclassified,
    )

    # Apply resolution filter
    if hide_resolved or show_resolved_only:
        result = result.filter_by_status(
            hide_resolved=hide_resolved,
            show_resolved_only=show_resolved_only,
        )

    return result


# =============================================================================
# Output Formatting
# =============================================================================


def format_issues_human(
    issues: CollatedIssues,
    show_status: bool = True,
    include_nitpicks: bool = False,
) -> str:
    """Format issues for human-readable output.

    Generates a prioritized list of issues grouped by severity with optional
    resolution status indicators.

    Args:
        issues: CollatedIssues instance containing categorized issues.
        show_status: If True, include [RESOLVED]/[OUTDATED] indicators.
        include_nitpicks: If True, include nitpick-level issues.

    Returns:
        Formatted string suitable for terminal display.

    Example:
        >>> output = format_issues_human(issues, show_status=True)
        >>> print(output)
        PR #40 Issues - Prioritized

        :red_circle: CRITICAL (1):
        1. [RESOLVED] Missing test coverage
    """
    lines: list[str] = []

    lines.append(f"PR #{issues.pr_number} Issues - Prioritized")
    lines.append("")

    # Critical
    if issues.critical:
        lines.append(f"🔴 CRITICAL ({len(issues.critical)}):")
        for i, issue in enumerate(issues.critical, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Major
    if issues.major:
        lines.append(f"🟠 MAJOR ({len(issues.major)}):")
        for i, issue in enumerate(issues.major, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Minor
    if issues.minor:
        lines.append(f"🟡 MINOR ({len(issues.minor)}):")
        for i, issue in enumerate(issues.minor, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Nitpicks (if included)
    if include_nitpicks and issues.nitpick:
        lines.append(f"⚪ NITPICK ({len(issues.nitpick)}):")
        for i, issue in enumerate(issues.nitpick, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Unclassified
    if issues.unclassified:
        lines.append(f"❓ UNMATCHED ({len(issues.unclassified)}) - Review manually:")
        for i, issue in enumerate(issues.unclassified, 1):
            status = (
                f" {issue.status_indicator}"
                if show_status and issue.status_indicator
                else ""
            )
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"{i}.{status}{loc} {issue.description}")
        lines.append("")

    # Summary
    lines.append(issues.get_summary(include_nitpicks=include_nitpicks))

    # Resolution stats
    if issues.resolved_count > 0:
        lines.append(
            f"Resolution: {issues.resolved_count} resolved, {issues.open_count} open"
        )

    return "\n".join(lines)


def format_issues_json(issues: CollatedIssues) -> str:
    """Format issues as JSON output.

    Serializes the CollatedIssues model to JSON with indentation.

    Args:
        issues: CollatedIssues instance to serialize.

    Returns:
        JSON string representation of the issues.

    Example:
        >>> json_output = format_issues_json(issues)
        >>> data = json.loads(json_output)
        >>> data["pr_number"]
        40
    """
    return issues.model_dump_json(indent=2)


# =============================================================================
# CLI Entry Point
# =============================================================================


def format_issues_parallel_solve(
    issues: CollatedIssues,
    include_nitpicks: bool = False,
) -> str:
    """Format issues for /parallel-solve command consumption.

    Generates a list format ready to pass to /parallel-solve.

    Args:
        issues: CollatedIssues instance containing categorized issues.
        include_nitpicks: If True, include nitpick-level issues.

    Returns:
        Formatted string suitable for /parallel-solve command.
    """
    lines: list[str] = []

    lines.append(f"Fix all PR #{issues.pr_number} review issues:")
    lines.append("")

    # Critical
    if issues.critical:
        lines.append("🔴 CRITICAL:")
        for issue in issues.critical:
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"-{loc} {issue.description}")
        lines.append("")

    # Major
    if issues.major:
        lines.append("🟠 MAJOR:")
        for issue in issues.major:
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"-{loc} {issue.description}")
        lines.append("")

    # Minor
    if issues.minor:
        lines.append("🟡 MINOR:")
        for issue in issues.minor:
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"-{loc} {issue.description}")
        lines.append("")

    # Nitpicks (if included)
    if include_nitpicks and issues.nitpick:
        lines.append("⚪ NITPICK:")
        for issue in issues.nitpick:
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"-{loc} {issue.description}")
        lines.append("")

    # Unclassified
    if issues.unclassified:
        lines.append("❓ UNMATCHED (review manually - format may have changed):")
        for issue in issues.unclassified:
            loc = f" {issue.location}" if issue.location else ""
            lines.append(f"-{loc} {issue.description}")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    """CLI entry point for collate_issues.

    Parses command-line arguments and runs the issue collation workflow.

    Returns:
        Exit code: 0 for success, 1 for validation errors, 2 for runtime errors.

    Example:
        >>> import sys
        >>> sys.argv = ["collate_issues.py", "40", "--hide-resolved"]
        >>> exit_code = main()
    """
    parser = argparse.ArgumentParser(
        description="Collate PR review issues with resolution detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python collate_issues.py 33                    # All issues
  python collate_issues.py 33 --hide-resolved    # Only open issues
  python collate_issues.py 33 --show-resolved-only  # Only resolved
  python collate_issues.py 33 --show-status      # Show [RESOLVED] indicators
  python collate_issues.py 33 --json             # JSON output
  python collate_issues.py 33 --parallel-solve-format  # For /parallel-solve
  python collate_issues.py https://github.com/OmniNode-ai/omniintelligence/pull/5  # Cross-repo
        """,
    )

    parser.add_argument("pr_input", type=str, help="PR number or GitHub URL")
    parser.add_argument(
        "--hide-resolved",
        action="store_true",
        help="Hide issues that have been resolved on GitHub",
    )
    parser.add_argument(
        "--show-resolved-only",
        action="store_true",
        help="Only show resolved issues",
    )
    parser.add_argument(
        "--no-status",
        dest="show_status",
        action="store_false",
        default=True,
        help="Hide resolution status indicators",
    )
    parser.add_argument(
        "--include-nitpicks",
        action="store_true",
        help="Include nitpick issues in output",
    )
    parser.add_argument(
        "--parallel-solve-format",
        action="store_true",
        help="Output in format ready for /parallel-solve command",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show statistics summary at end",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    args = parser.parse_args()

    # Validate conflicting options
    if args.hide_resolved and args.show_resolved_only:
        print(
            "ERROR: Cannot use both --hide-resolved and --show-resolved-only",
            file=sys.stderr,
        )
        return 1

    try:
        issues = collate_pr_issues(
            args.pr_input,
            hide_resolved=args.hide_resolved,
            show_resolved_only=args.show_resolved_only,
            include_nitpicks=args.include_nitpicks,
        )

        if args.json:
            print(format_issues_json(issues))
        elif args.parallel_solve_format:
            print(
                format_issues_parallel_solve(
                    issues,
                    include_nitpicks=args.include_nitpicks,
                )
            )
        else:
            show_status = args.show_status
            print(
                format_issues_human(
                    issues,
                    show_status=show_status,
                    include_nitpicks=args.include_nitpicks,
                )
            )

        # Show stats if requested
        if args.stats:
            print("")
            print("Statistics:")
            print(f"  Critical: {len(issues.critical)}")
            print(f"  Major: {len(issues.major)}")
            print(f"  Minor: {len(issues.minor)}")
            print(f"  Nitpick: {len(issues.nitpick)}")
            print(f"  Unclassified: {len(issues.unclassified)}")
            print(f"  Total: {issues.total_count}")
            if issues.resolved_count > 0:
                print(f"  Resolved: {issues.resolved_count}")
                print(f"  Open: {issues.open_count}")

        return 0

    except OnexError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
