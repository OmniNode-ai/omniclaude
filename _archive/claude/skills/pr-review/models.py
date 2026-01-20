#!/usr/bin/env python3
"""
Pydantic models for PR review data structures.

This module provides type-safe data models for parsing, validating, and
manipulating PR review data from GitHub. It ensures that no comments are
ever lost, with special attention to bot comments (especially Claude Code).

Usage:
    from models import PRData, PRComment, PRCommentSource, BotType

    # Parse GitHub API response
    comment = PRComment.from_github_response(github_data, PRCommentSource.ISSUE_COMMENT)

    # Check if it's a Claude bot comment
    if comment.is_claude_bot():
        print(f"Claude comment found: {comment.body[:100]}")

    # Full PR analysis
    pr_data = PRData.from_github_responses(...)
    analysis = PRAnalysis.from_pr_data(pr_data)
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from functools import cached_property
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# =============================================================================
# Bot Detection Patterns - CRITICAL: Must be bulletproof
# =============================================================================

CLAUDE_BOT_PATTERNS: list[str] = [
    "claude",
    "anthropic",
    "claude-code",
    "claude[bot]",
    "claude-bot",
    "claudebot",
    "claude-ai",
]

CODERABBIT_PATTERNS: list[str] = [
    "coderabbit",
    "coderabbitai",
    "coderabbit[bot]",
    "code-rabbit",
]

GITHUB_ACTIONS_PATTERNS: list[str] = [
    "github-actions",
    "github-actions[bot]",
]


def detect_bot_type(author: str) -> BotType:
    """
    Detect the type of bot from the author name.

    This is CRITICAL functionality - Claude bot comments must NEVER be
    misclassified as human comments.

    Args:
        author: The GitHub username or display name of the comment author.

    Returns:
        BotType enum indicating the type of author.

    Examples:
        >>> detect_bot_type("claude[bot]")
        BotType.CLAUDE_CODE
        >>> detect_bot_type("coderabbitai[bot]")
        BotType.CODERABBIT
        >>> detect_bot_type("octocat")
        BotType.HUMAN
    """
    if not author:
        return BotType.HUMAN

    author_lower = author.lower().strip()

    # Check Claude patterns first (highest priority)
    if any(pattern in author_lower for pattern in CLAUDE_BOT_PATTERNS):
        return BotType.CLAUDE_CODE

    # Check CodeRabbit patterns
    if any(pattern in author_lower for pattern in CODERABBIT_PATTERNS):
        return BotType.CODERABBIT

    # Check GitHub Actions patterns
    if any(pattern in author_lower for pattern in GITHUB_ACTIONS_PATTERNS):
        return BotType.GITHUB_ACTIONS

    # Generic bot detection
    if "[bot]" in author_lower or author_lower.endswith("-bot"):
        return BotType.OTHER_BOT

    return BotType.HUMAN


# =============================================================================
# Enums
# =============================================================================


class PRCommentSource(str, Enum):
    """
    Source of a PR comment in GitHub.

    GitHub has multiple places where comments can appear:
    - REVIEW: Formal PR review comments
    - INLINE: Inline code comments on specific lines
    - PR_COMMENT: Comments in the PR conversation thread
    - ISSUE_COMMENT: Comments on the associated issue (where Claude bot posts!)
    """

    REVIEW = "review"
    INLINE = "inline"
    PR_COMMENT = "pr_comment"
    ISSUE_COMMENT = "issue_comment"

    def __str__(self) -> str:
        return self.value


class CommentSeverity(str, Enum):
    """
    Severity level of a PR comment/issue.

    Priority order (highest to lowest):
    - CRITICAL: Must fix before merge (security, data loss, crashes)
    - MAJOR: Should fix (bugs, performance issues, missing tests)
    - MINOR: Nice to fix (code quality, documentation)
    - NITPICK: Optional fixes (style, naming conventions)
    - UNCLASSIFIED: Severity not yet determined
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    NITPICK = "nitpick"
    UNCLASSIFIED = "unclassified"

    def __str__(self) -> str:
        return self.value

    @property
    def is_blocking(self) -> bool:
        """Returns True if this severity level blocks merging."""
        return self in (CommentSeverity.CRITICAL, CommentSeverity.MAJOR)

    @property
    def priority_order(self) -> int:
        """Returns numeric priority (lower = higher priority)."""
        order = {
            CommentSeverity.CRITICAL: 0,
            CommentSeverity.MAJOR: 1,
            CommentSeverity.MINOR: 2,
            CommentSeverity.NITPICK: 3,
            CommentSeverity.UNCLASSIFIED: 4,
        }
        return order.get(self, 99)


class CommentStatus(str, Enum):
    """
    Resolution status of a PR comment.

    - UNADDRESSED: Not yet addressed by the PR author
    - POTENTIALLY_ADDRESSED: May have been addressed (needs verification)
    - RESOLVED: Confirmed resolved (GitHub thread marked resolved)
    - OUTDATED: Code has changed since the comment was made
    - WONT_FIX: Acknowledged but won't be fixed
    """

    UNADDRESSED = "unaddressed"
    POTENTIALLY_ADDRESSED = "potentially_addressed"
    RESOLVED = "resolved"
    OUTDATED = "outdated"
    WONT_FIX = "wont_fix"

    def __str__(self) -> str:
        return self.value

    @property
    def needs_attention(self) -> bool:
        """Returns True if this status needs attention."""
        return self in (CommentStatus.UNADDRESSED, CommentStatus.POTENTIALLY_ADDRESSED)

    @property
    def is_resolved(self) -> bool:
        """Returns True if this status indicates resolution."""
        return self in (
            CommentStatus.RESOLVED,
            CommentStatus.OUTDATED,
            CommentStatus.WONT_FIX,
        )


# Alias for backward compatibility and task specification
IssueStatus = CommentStatus
IssueSeverity = CommentSeverity


class BotType(str, Enum):
    """
    Type of bot (or human) that authored a comment.

    CLAUDE_CODE is given special treatment as these comments
    must NEVER be missed in analysis.
    """

    CLAUDE_CODE = "claude_code"
    CODERABBIT = "coderabbit"
    GITHUB_ACTIONS = "github_actions"
    OTHER_BOT = "other_bot"
    HUMAN = "human"

    def __str__(self) -> str:
        return self.value

    @property
    def is_bot(self) -> bool:
        """Returns True if this is any type of bot."""
        return self != BotType.HUMAN

    @property
    def is_ai_reviewer(self) -> bool:
        """Returns True if this is an AI code reviewer."""
        return self in (BotType.CLAUDE_CODE, BotType.CODERABBIT)


# =============================================================================
# Data Models
# =============================================================================


class FileReference(BaseModel):
    """
    Reference to a specific location in a file.

    Used for inline comments that reference specific code locations.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    path: str = Field(..., description="File path relative to repository root")
    line: int | None = Field(None, ge=1, description="Line number (1-indexed)")
    end_line: int | None = Field(
        None, ge=1, description="End line for multi-line references"
    )
    diff_hunk: str | None = Field(None, description="Diff context around the line")

    @model_validator(mode="after")
    def validate_line_range(self) -> FileReference:
        """Ensure end_line >= line if both are specified."""
        if self.line is not None and self.end_line is not None:
            if self.end_line < self.line:
                raise ValueError(
                    f"end_line ({self.end_line}) must be >= line ({self.line})"
                )
        return self

    def __repr__(self) -> str:
        if self.line:
            if self.end_line and self.end_line != self.line:
                return f"FileReference({self.path}:{self.line}-{self.end_line})"
            return f"FileReference({self.path}:{self.line})"
        return f"FileReference({self.path})"

    @classmethod
    def from_github_response(cls, data: dict[str, Any]) -> FileReference | None:
        """
        Create a FileReference from GitHub API response data.

        Args:
            data: GitHub API response for a comment with file info.

        Returns:
            FileReference if file info exists, None otherwise.
        """
        path = data.get("path")
        if not path:
            return None

        return cls(
            path=path,
            line=data.get("line") or data.get("original_line"),
            end_line=data.get("end_line") or data.get("original_end_line"),
            diff_hunk=data.get("diff_hunk"),
        )


class StructuredSection(BaseModel):
    """
    A structured section within a bot's comment.

    Bot reviewers (like Claude and CodeRabbit) often structure their
    comments into sections like "Must Fix", "Should Fix", etc.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    section_type: Literal[
        "must_fix",
        "should_fix",
        "nice_to_have",
        "actionable_comments",
        "summary",
        "other",
    ] = Field(..., description="Type of section")
    content: str = Field(..., description="Raw content of the section")
    extracted_issues: list[str] = Field(
        default_factory=list, description="Individual issues extracted from content"
    )

    def __repr__(self) -> str:
        issue_count = len(self.extracted_issues)
        return f"StructuredSection({self.section_type}, {issue_count} issues)"

    @classmethod
    def extract_from_body(cls, body: str) -> list[StructuredSection]:
        """
        Extract structured sections from a comment body.

        Looks for common patterns like:
        - ## Must Fix / ## Critical
        - ## Should Fix / ## Major
        - ## Nice to Have / ## Minor
        - ## Actionable Comments
        - ## Summary

        Args:
            body: The raw comment body text.

        Returns:
            List of StructuredSection objects found in the body.
        """
        if not body:
            return []

        sections: list[StructuredSection] = []

        # Pattern to match markdown headers
        section_patterns = {
            "must_fix": r"(?:##?\s*(?:Must\s*Fix|Critical|Blocking))",
            "should_fix": r"(?:##?\s*(?:Should\s*Fix|Major|Important))",
            "nice_to_have": r"(?:##?\s*(?:Nice\s*to\s*Have|Minor|Optional|Nit))",
            "actionable_comments": r"(?:##?\s*(?:Actionable\s*Comments?|Action\s*Items?))",
            "summary": r"(?:##?\s*(?:Summary|Overview|TL;?DR))",
        }

        for section_type, pattern in section_patterns.items():
            matches = re.finditer(
                pattern + r"\s*\n(.*?)(?=\n##|\n---|\Z)",
                body,
                re.IGNORECASE | re.DOTALL,
            )
            for match in matches:
                content = match.group(1).strip()
                if content:
                    # Extract individual bullet points or numbered items
                    issues = re.findall(
                        r"^[\s]*[-*\d.]+\s*(.+)$", content, re.MULTILINE
                    )
                    sections.append(
                        cls(
                            section_type=section_type,  # type: ignore[arg-type]
                            content=content,
                            extracted_issues=issues,
                        )
                    )

        return sections


class PRComment(BaseModel):
    """
    A single comment on a PR from any source.

    This is the core model for tracking PR feedback. It unifies comments
    from all GitHub endpoints (reviews, inline comments, PR comments,
    issue comments) into a single type-safe structure.

    CRITICAL: Claude bot comments are given special handling to ensure
    they are NEVER missed in analysis.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    id: str = Field(..., description="GitHub comment ID")
    source: PRCommentSource = Field(..., description="Where this comment came from")
    author: str = Field(..., description="GitHub username of comment author")
    author_type: BotType = Field(default=BotType.HUMAN, description="Type of author")
    body: str = Field(..., description="Comment body text")
    severity: CommentSeverity = Field(
        default=CommentSeverity.UNCLASSIFIED, description="Severity level"
    )
    status: CommentStatus = Field(
        default=CommentStatus.UNADDRESSED, description="Resolution status"
    )
    file_ref: FileReference | None = Field(None, description="File location if inline")
    created_at: datetime = Field(..., description="When comment was created")
    updated_at: datetime | None = Field(
        None, description="When comment was last updated"
    )
    in_reply_to_id: str | None = Field(None, description="Parent comment ID if reply")
    structured_sections: list[StructuredSection] = Field(
        default_factory=list, description="Parsed structured sections"
    )
    raw_json: dict[str, Any] = Field(
        default_factory=dict, description="Original GitHub API response"
    )
    # Resolution tracking fields
    thread_id: str | None = Field(
        None, description="GitHub review thread ID if part of a thread"
    )
    resolved_at: datetime | None = Field(
        None, description="When the thread was resolved"
    )
    resolved_by: str | None = Field(
        None, description="Username who resolved the thread"
    )
    is_outdated: bool = Field(
        default=False, description="True if the code has changed since comment"
    )

    @model_validator(mode="after")
    def detect_author_type_and_sections(self) -> PRComment:
        """Auto-detect author type and parse structured sections."""
        # Always re-detect author type to ensure Claude comments aren't missed
        self.author_type = detect_bot_type(self.author)

        # Parse structured sections if not already done
        if not self.structured_sections and self.body:
            self.structured_sections = StructuredSection.extract_from_body(self.body)

        # Auto-classify severity if unclassified
        if self.severity == CommentSeverity.UNCLASSIFIED:
            self.severity = self.extract_severity_from_content()

        return self

    def is_bot(self) -> bool:
        """Check if comment is from any bot."""
        return self.author_type.is_bot

    def is_claude_bot(self) -> bool:
        """
        Check if comment is from Claude Code bot.

        CRITICAL: This method must NEVER miss a Claude bot comment.
        Uses multiple fallback checks.
        """
        # Primary check via author_type
        if self.author_type == BotType.CLAUDE_CODE:
            return True

        # Fallback safety check - scan author name directly
        author_lower = self.author.lower()
        if any(pattern in author_lower for pattern in CLAUDE_BOT_PATTERNS):
            return True

        return False

    def is_actionable(self) -> bool:
        """
        Check if comment requires action.

        Returns True if:
        - Status needs attention (unaddressed or potentially addressed)
        - AND severity is not just a nitpick
        """
        return self.status.needs_attention and self.severity != CommentSeverity.NITPICK

    def is_blocking(self) -> bool:
        """Check if this comment blocks merge."""
        return self.severity.is_blocking and self.status == CommentStatus.UNADDRESSED

    def extract_severity_from_content(self) -> CommentSeverity:
        """
        Extract severity level from comment content.

        Looks for common patterns in the comment body:
        - Critical/blocking/security -> CRITICAL
        - Major/important/bug -> MAJOR
        - Minor/suggestion -> MINOR
        - Nit/nitpick/optional -> NITPICK

        Returns:
            Detected severity or UNCLASSIFIED if none found.
        """
        if not self.body:
            return CommentSeverity.UNCLASSIFIED

        body_lower = self.body.lower()

        # Critical patterns
        critical_patterns = [
            r"\bcritical\b",
            r"\bblocking\b",
            r"\bsecurity\b",
            r"\bvulnerab",
            r"\bdata\s*loss\b",
            r"\bcrash",
            r"\bmust\s*fix\b",
            r"\bbreak(?:ing|s)?\b",
            r"\btest\s*failure\b",
            r"\bfails?\b",
            r"\bbroken\b",
            r"\bexploit\b",
            r"\binjection\b",
        ]
        if any(re.search(p, body_lower) for p in critical_patterns):
            return CommentSeverity.CRITICAL

        # Major patterns
        major_patterns = [
            r"\bmajor\b",
            r"\bimportant\b",
            r"\bbug\b",
            r"\berror\b",
            r"\bshould\s*fix\b",
            r"\bperformance\b",
            r"\bmissing\s*test",
            r"\bincorrect\b",
            r"\bwrong\b",
            r"\barchitecture\b",
            r"\binconsistent\b",
        ]
        if any(re.search(p, body_lower) for p in major_patterns):
            return CommentSeverity.MAJOR

        # Minor patterns
        minor_patterns = [
            r"\bminor\b",
            r"\bsuggestion\b",
            r"\bconsider\b",
            r"\bcould\b",
            r"\bmight\b",
            r"\bnice\s*to\s*have\b",
        ]
        if any(re.search(p, body_lower) for p in minor_patterns):
            return CommentSeverity.MINOR

        # Nitpick patterns
        nitpick_patterns = [
            r"\bnit(?:pick)?\b",
            r"\boptional\b",
            r"\bstyle\b",
            r"\bformatting\b",
            r"\bnaming\b",
            r"\bcosmetic\b",
        ]
        if any(re.search(p, body_lower) for p in nitpick_patterns):
            return CommentSeverity.NITPICK

        return CommentSeverity.UNCLASSIFIED

    @classmethod
    def classify_severity(cls, body: str) -> CommentSeverity:
        """
        Classify comment severity based on body content.

        Class method for external use without creating an instance.

        Args:
            body: The comment body text.

        Returns:
            Detected severity level.
        """
        # Create a temporary instance to use the instance method
        temp = cls(
            id="temp",
            source=PRCommentSource.PR_COMMENT,
            author="temp",
            body=body,
            created_at=datetime.now(),
            severity=CommentSeverity.UNCLASSIFIED,
        )
        return temp.severity

    def __repr__(self) -> str:
        source_str = self.source.value
        author_str = f"{self.author} ({self.author_type.value})"
        severity_str = self.severity.value
        body_preview = self.body[:50] + "..." if len(self.body) > 50 else self.body
        body_preview = body_preview.replace("\n", " ")
        return (
            f"PRComment(id={self.id}, source={source_str}, "
            f"author={author_str}, severity={severity_str}, "
            f"body={body_preview!r})"
        )

    @classmethod
    def from_github_response(
        cls,
        data: dict[str, Any],
        source: PRCommentSource,
        *,
        default_severity: CommentSeverity = CommentSeverity.UNCLASSIFIED,
        default_status: CommentStatus = CommentStatus.UNADDRESSED,
    ) -> PRComment:
        """
        Create a PRComment from GitHub API response data.

        Args:
            data: Raw GitHub API response for a single comment.
            source: The endpoint this comment came from.
            default_severity: Default severity if not detected.
            default_status: Default status for new comments.

        Returns:
            PRComment instance with all fields populated.

        Example:
            >>> data = {"id": 123, "user": {"login": "claude[bot]"}, ...}
            >>> comment = PRComment.from_github_response(data, PRCommentSource.ISSUE_COMMENT)
            >>> comment.is_claude_bot()
            True
        """
        # Extract author from various GitHub response formats
        author = ""
        if data.get("user"):
            author = data["user"].get("login", "")
        elif data.get("author"):
            if isinstance(data["author"], dict):
                author = data["author"].get("login", "")
            else:
                author = str(data["author"])

        # Extract timestamps
        created_at_str = data.get("created_at") or data.get("submitted_at")
        created_at = (
            datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if created_at_str
            else datetime.now()
        )

        updated_at = None
        if data.get("updated_at"):
            updated_at = datetime.fromisoformat(
                data["updated_at"].replace("Z", "+00:00")
            )

        # Extract body
        body = data.get("body") or ""

        # Extract file reference for inline comments
        file_ref = FileReference.from_github_response(data)

        # Extract reply-to ID
        in_reply_to_id = None
        if data.get("in_reply_to_id"):
            in_reply_to_id = str(data["in_reply_to_id"])

        return cls(
            id=str(data.get("id", "")),
            source=source,
            author=author,
            body=body,
            severity=default_severity,
            status=default_status,
            file_ref=file_ref,
            created_at=created_at,
            updated_at=updated_at,
            in_reply_to_id=in_reply_to_id,
            raw_json=data,
        )


class PRReview(BaseModel):
    """
    A formal PR review (approve, request changes, comment).

    Represents a single review submission, which may contain
    multiple inline comments.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    id: str = Field(..., description="GitHub review ID")
    author: str = Field(..., description="GitHub username of reviewer")
    author_type: BotType = Field(default=BotType.HUMAN, description="Type of author")
    state: Literal[
        "APPROVED", "CHANGES_REQUESTED", "COMMENTED", "PENDING", "DISMISSED"
    ] = Field(..., description="Review state")
    body: str | None = Field(None, description="Review body text")
    submitted_at: datetime = Field(..., description="When review was submitted")
    comments: list[PRComment] = Field(
        default_factory=list, description="Inline comments in this review"
    )
    structured_sections: list[StructuredSection] = Field(
        default_factory=list, description="Parsed structured sections from body"
    )
    raw_json: dict[str, Any] = Field(
        default_factory=dict, description="Original GitHub API response"
    )

    @model_validator(mode="after")
    def detect_author_type_and_sections(self) -> PRReview:
        """Auto-detect author type and parse structured sections."""
        self.author_type = detect_bot_type(self.author)

        if not self.structured_sections and self.body:
            self.structured_sections = StructuredSection.extract_from_body(self.body)

        return self

    def is_bot(self) -> bool:
        """Check if review is from any bot."""
        return self.author_type.is_bot

    def is_claude_bot(self) -> bool:
        """Check if review is from Claude Code bot."""
        return self.author_type == BotType.CLAUDE_CODE

    def is_blocking(self) -> bool:
        """Check if review blocks merging."""
        return self.state == "CHANGES_REQUESTED"

    def __repr__(self) -> str:
        return (
            f"PRReview(id={self.id}, author={self.author} ({self.author_type.value}), "
            f"state={self.state}, comments={len(self.comments)})"
        )

    @classmethod
    def from_github_response(cls, data: dict[str, Any]) -> PRReview:
        """
        Create a PRReview from GitHub API response data.

        Args:
            data: Raw GitHub API response for a review.

        Returns:
            PRReview instance.
        """
        author = ""
        if data.get("user"):
            author = data["user"].get("login", "")

        submitted_at_str = data.get("submitted_at")
        submitted_at = (
            datetime.fromisoformat(submitted_at_str.replace("Z", "+00:00"))
            if submitted_at_str
            else datetime.now()
        )

        return cls(
            id=str(data.get("id", "")),
            author=author,
            state=data.get("state", "COMMENTED"),
            body=data.get("body"),
            submitted_at=submitted_at,
            raw_json=data,
        )


class PRData(BaseModel):
    """
    Complete PR data aggregated from all GitHub endpoints.

    This is the main container for all PR information, unifying
    data from reviews, inline comments, PR comments, and issue comments.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    pr_number: int = Field(..., ge=1, description="PR number")
    repository: str = Field(..., description="Repository in owner/repo format")
    title: str = Field(default="", description="PR title")
    author: str = Field(default="", description="PR author username")
    base_branch: str = Field(default="main", description="Target branch")
    head_branch: str = Field(default="", description="Source branch")
    state: Literal["open", "closed", "merged"] = Field(
        default="open", description="PR state"
    )
    created_at: datetime | None = Field(None, description="When PR was created")
    updated_at: datetime | None = Field(None, description="When PR was last updated")
    reviews: list[PRReview] = Field(default_factory=list, description="Formal reviews")
    comments: list[PRComment] = Field(
        default_factory=list, description="All unified comments"
    )
    fetched_at: datetime = Field(
        default_factory=datetime.now, description="When data was fetched"
    )
    fetch_source: Literal["github_api", "cache", "gh_cli"] = Field(
        default="github_api", description="How data was fetched"
    )
    raw_json: dict[str, Any] = Field(
        default_factory=dict, description="Original PR data from GitHub"
    )

    def __repr__(self) -> str:
        return (
            f"PRData(#{self.pr_number} {self.repository}, "
            f"reviews={len(self.reviews)}, comments={len(self.comments)})"
        )

    def get_all_comments(self) -> list[PRComment]:
        """
        Get all comments from all sources.

        Returns comments from:
        - PR-level comments
        - Review inline comments
        - Issue comments (where Claude posts!)

        Returns:
            List of all PRComment objects, sorted by created_at.
        """
        all_comments: list[PRComment] = list(self.comments)

        # Add comments from reviews
        for review in self.reviews:
            all_comments.extend(review.comments)

        # Sort by creation time
        return sorted(all_comments, key=lambda c: c.created_at)

    def get_bot_comments(self, bot_type: BotType | None = None) -> list[PRComment]:
        """
        Get all comments from bots.

        Args:
            bot_type: Specific bot type to filter, or None for all bots.

        Returns:
            List of bot comments, sorted by created_at.
        """
        all_comments = self.get_all_comments()

        if bot_type:
            return [c for c in all_comments if c.author_type == bot_type]

        return [c for c in all_comments if c.is_bot()]

    def get_claude_comments(self) -> list[PRComment]:
        """
        Get all Claude Code bot comments.

        CRITICAL: This method ensures Claude comments are NEVER missed.

        Returns:
            List of Claude bot comments.
        """
        return self.get_bot_comments(BotType.CLAUDE_CODE)

    def get_unaddressed_comments(self) -> list[PRComment]:
        """
        Get all comments that need attention.

        Returns:
            Comments with UNADDRESSED or POTENTIALLY_ADDRESSED status.
        """
        all_comments = self.get_all_comments()
        return [c for c in all_comments if c.status.needs_attention]

    def get_by_severity(self, severity: CommentSeverity) -> list[PRComment]:
        """
        Get all comments with a specific severity.

        Args:
            severity: The severity level to filter by.

        Returns:
            Comments matching the severity level.
        """
        all_comments = self.get_all_comments()
        return [c for c in all_comments if c.severity == severity]

    def get_actionable_issues(self) -> list[PRComment]:
        """
        Get all actionable issues that need resolution.

        Filters comments that:
        - Need attention (unaddressed or potentially addressed)
        - Are not just nitpicks

        Returns:
            List of actionable comments, sorted by severity.
        """
        all_comments = self.get_all_comments()
        actionable = [c for c in all_comments if c.is_actionable()]

        # Sort by severity (critical first)
        return sorted(actionable, key=lambda c: c.severity.priority_order)

    def get_comments_by_source(self, source: PRCommentSource) -> list[PRComment]:
        """
        Get comments from a specific source.

        Args:
            source: The source endpoint to filter by.

        Returns:
            Comments from that source.
        """
        return [c for c in self.comments if c.source == source]

    @property
    def total_comments(self) -> int:
        """Total number of comments across all sources."""
        return len(self.get_all_comments())

    @property
    def total_reviews(self) -> int:
        """Total number of formal reviews."""
        return len(self.reviews)

    @classmethod
    def from_github_responses(
        cls,
        pr_data: dict[str, Any],
        reviews: list[dict[str, Any]] | None = None,
        inline_comments: list[dict[str, Any]] | None = None,
        pr_comments: list[dict[str, Any]] | None = None,
        issue_comments: list[dict[str, Any]] | None = None,
        *,
        fetch_source: Literal["github_api", "cache", "gh_cli"] = "github_api",
    ) -> PRData:
        """
        Create PRData from GitHub API responses.

        Args:
            pr_data: PR details from GitHub API.
            reviews: List of reviews from /pulls/{pr}/reviews.
            inline_comments: List of inline comments from /pulls/{pr}/comments.
            pr_comments: List of PR comments (if separate endpoint).
            issue_comments: List of issue comments (where Claude posts!).
            fetch_source: How the data was fetched.

        Returns:
            PRData instance with all data unified.
        """
        reviews = reviews or []
        inline_comments = inline_comments or []
        pr_comments = pr_comments or []
        issue_comments = issue_comments or []

        # Parse PR metadata
        created_at = None
        if pr_data.get("created_at"):
            created_at = datetime.fromisoformat(
                pr_data["created_at"].replace("Z", "+00:00")
            )

        updated_at = None
        if pr_data.get("updated_at"):
            updated_at = datetime.fromisoformat(
                pr_data["updated_at"].replace("Z", "+00:00")
            )

        # Determine state
        state: Literal["open", "closed", "merged"] = "open"
        if pr_data.get("merged"):
            state = "merged"
        elif pr_data.get("state") == "closed":
            state = "closed"

        # Parse reviews
        parsed_reviews: list[PRReview] = []
        for review_data in reviews:
            review = PRReview.from_github_response(review_data)

            # Find inline comments that belong to this review
            review_id = str(review_data.get("id", ""))
            review_comments = [
                PRComment.from_github_response(c, PRCommentSource.INLINE)
                for c in inline_comments
                if str(c.get("pull_request_review_id", "")) == review_id
            ]
            review.comments = review_comments
            parsed_reviews.append(review)

        # Parse standalone inline comments (not part of a review)
        review_ids = {str(r.id) for r in parsed_reviews}
        standalone_inline = [
            PRComment.from_github_response(c, PRCommentSource.INLINE)
            for c in inline_comments
            if str(c.get("pull_request_review_id", "")) not in review_ids
        ]

        # Parse PR comments
        parsed_pr_comments = [
            PRComment.from_github_response(c, PRCommentSource.PR_COMMENT)
            for c in pr_comments
        ]

        # Parse issue comments (CRITICAL: This is where Claude posts!)
        parsed_issue_comments = [
            PRComment.from_github_response(c, PRCommentSource.ISSUE_COMMENT)
            for c in issue_comments
        ]

        # Combine all comments
        all_comments = standalone_inline + parsed_pr_comments + parsed_issue_comments

        # Extract repository info
        repository = ""
        if pr_data.get("base", {}).get("repo", {}).get("full_name"):
            repository = pr_data["base"]["repo"]["full_name"]
        elif pr_data.get("repository"):
            repository = pr_data["repository"]

        # Extract author
        author = ""
        if pr_data.get("user", {}).get("login"):
            author = pr_data["user"]["login"]
        elif pr_data.get("author", {}).get("login"):
            author = pr_data["author"]["login"]

        return cls(
            pr_number=pr_data.get("number", 0),
            repository=repository,
            title=pr_data.get("title", ""),
            author=author,
            base_branch=pr_data.get("base", {}).get("ref", "main"),
            head_branch=pr_data.get("head", {}).get("ref", ""),
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            reviews=parsed_reviews,
            comments=all_comments,
            fetch_source=fetch_source,
            raw_json=pr_data,
        )


class PRAnalysis(BaseModel):
    """
    Analysis results for a PR.

    Provides aggregated statistics and categorized issues
    for easy consumption by review workflows.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    pr_data: PRData = Field(..., description="Source PR data")
    analyzed_at: datetime = Field(
        default_factory=datetime.now, description="When analysis was performed"
    )
    total_comments: int = Field(default=0, description="Total comment count")
    by_severity: dict[str, int] = Field(
        default_factory=dict, description="Comment counts by severity"
    )
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Comment counts by status"
    )
    by_author_type: dict[str, int] = Field(
        default_factory=dict, description="Comment counts by author type"
    )
    critical_issues: list[PRComment] = Field(
        default_factory=list, description="Critical severity issues"
    )
    major_issues: list[PRComment] = Field(
        default_factory=list, description="Major severity issues"
    )
    minor_issues: list[PRComment] = Field(
        default_factory=list, description="Minor severity issues"
    )
    nitpick_issues: list[PRComment] = Field(
        default_factory=list, description="Nitpick severity issues"
    )
    claude_issues: list[PRComment] = Field(
        default_factory=list, description="All Claude bot comments (NEVER MISS)"
    )
    merge_blockers: list[PRComment] = Field(
        default_factory=list, description="Issues that block merging"
    )
    summary: str = Field(default="", description="Human-readable summary")

    def __repr__(self) -> str:
        return (
            f"PRAnalysis(PR #{self.pr_data.pr_number}, "
            f"total={self.total_comments}, critical={len(self.critical_issues)}, "
            f"major={len(self.major_issues)}, claude={len(self.claude_issues)})"
        )

    def can_merge(self) -> bool:
        """
        Check if PR can be merged based on analysis.

        Returns True if no blocking issues remain.
        """
        return len(self.merge_blockers) == 0

    def is_merge_ready(self) -> bool:
        """Alias for can_merge() for backward compatibility."""
        return self.can_merge()

    def get_blocking_count(self) -> int:
        """Get count of merge-blocking issues."""
        return len(self.merge_blockers)

    def get_merge_status(self) -> str:
        """Get human-readable merge status."""
        if self.can_merge():
            return "Ready to merge"

        blockers = len(self.merge_blockers)
        critical = len(self.critical_issues)
        major = len(self.major_issues)

        parts = []
        if critical:
            parts.append(f"{critical} critical")
        if major:
            parts.append(f"{major} major")

        return f"Blocked: {', '.join(parts)} issue(s) remaining"

    @classmethod
    def from_pr_data(cls, pr_data: PRData) -> PRAnalysis:
        """
        Create analysis from PR data.

        Args:
            pr_data: PRData instance to analyze.

        Returns:
            PRAnalysis with all statistics computed.
        """
        all_comments = pr_data.get_all_comments()

        # Count by severity
        by_severity: dict[str, int] = {}
        for severity in CommentSeverity:
            count = len([c for c in all_comments if c.severity == severity])
            by_severity[severity.value] = count

        # Count by status
        by_status: dict[str, int] = {}
        for status in CommentStatus:
            count = len([c for c in all_comments if c.status == status])
            by_status[status.value] = count

        # Count by author type
        by_author_type: dict[str, int] = {}
        for author_type in BotType:
            count = len([c for c in all_comments if c.author_type == author_type])
            by_author_type[author_type.value] = count

        # Categorize issues
        critical_issues = pr_data.get_by_severity(CommentSeverity.CRITICAL)
        major_issues = pr_data.get_by_severity(CommentSeverity.MAJOR)
        minor_issues = pr_data.get_by_severity(CommentSeverity.MINOR)
        nitpick_issues = pr_data.get_by_severity(CommentSeverity.NITPICK)
        claude_issues = pr_data.get_claude_comments()

        # Determine merge blockers (critical + major that need attention)
        merge_blockers = [
            c
            for c in all_comments
            if c.severity.is_blocking and c.status.needs_attention
        ]

        # Generate summary
        summary_parts = [
            f"PR #{pr_data.pr_number}: {pr_data.title}",
            f"Total comments: {len(all_comments)}",
        ]

        if critical_issues:
            summary_parts.append(f"Critical issues: {len(critical_issues)}")
        if major_issues:
            summary_parts.append(f"Major issues: {len(major_issues)}")
        if claude_issues:
            summary_parts.append(f"Claude Code comments: {len(claude_issues)}")

        if merge_blockers:
            summary_parts.append(
                f"BLOCKED: {len(merge_blockers)} issues must be resolved"
            )
        else:
            summary_parts.append("Ready to merge")

        summary = "\n".join(summary_parts)

        return cls(
            pr_data=pr_data,
            total_comments=len(all_comments),
            by_severity=by_severity,
            by_status=by_status,
            by_author_type=by_author_type,
            critical_issues=critical_issues,
            major_issues=major_issues,
            minor_issues=minor_issues,
            nitpick_issues=nitpick_issues,
            claude_issues=claude_issues,
            merge_blockers=merge_blockers,
            summary=summary,
        )

    def to_json(self) -> str:
        """Serialize analysis to JSON string."""
        return self.model_dump_json(indent=2)

    def to_dict(self) -> dict[str, Any]:
        """Convert analysis to dictionary."""
        return self.model_dump()


class PRIssue(BaseModel):
    """
    A collated PR review issue with resolution tracking.

    This model is used by the collate-issues script to represent
    a single actionable issue extracted from PR review comments.
    It includes resolution status detection based on GitHub thread
    status and file modification tracking.

    Usage:
        from models import PRIssue, IssueSeverity, IssueStatus

        issue = PRIssue(
            file_path="src/main.py",
            line_number=42,
            severity=IssueSeverity.CRITICAL,
            description="Missing null check",
            status=IssueStatus.UNADDRESSED,
        )

        if issue.is_resolved:
            print(f"Resolved at {issue.resolved_at}")
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    file_path: str = Field(
        default="", description="File path relative to repository root"
    )
    line_number: int | None = Field(
        None, ge=1, description="Line number (1-indexed) if applicable"
    )
    severity: CommentSeverity = Field(
        ..., description="Issue severity level (critical/major/minor/nitpick)"
    )
    description: str = Field(..., description="Issue description/summary")
    status: CommentStatus = Field(
        default=CommentStatus.UNADDRESSED, description="Resolution status"
    )
    comment_id: int | None = Field(None, description="GitHub comment ID for tracking")
    thread_id: str | None = Field(
        None, description="GitHub review thread ID if part of a thread"
    )
    resolved_at: datetime | None = Field(
        None, description="When the issue was resolved"
    )
    resolved_by: str | None = Field(None, description="Username who resolved the issue")
    is_outdated: bool = Field(
        default=False, description="True if file changed after comment"
    )
    source_comment: PRComment | None = Field(
        None, description="Original PRComment this issue was extracted from"
    )

    @property
    def is_resolved(self) -> bool:
        """Check if this issue is resolved (any resolution status)."""
        return self.status.is_resolved

    @property
    def is_open(self) -> bool:
        """Check if this issue is still open."""
        return not self.is_resolved

    @property
    def location(self) -> str:
        """Get formatted location string like '[path:line]'."""
        if not self.file_path:
            return ""
        if self.line_number:
            return f"[{self.file_path}:{self.line_number}]"
        return f"[{self.file_path}]"

    @property
    def severity_emoji(self) -> str:
        """Get emoji indicator for severity level."""
        emoji_map = {
            CommentSeverity.CRITICAL: "🔴",
            CommentSeverity.MAJOR: "🟠",
            CommentSeverity.MINOR: "🟡",
            CommentSeverity.NITPICK: "⚪",
            CommentSeverity.UNCLASSIFIED: "❓",
        }
        return emoji_map.get(self.severity, "❓")

    @property
    def status_indicator(self) -> str:
        """Get status indicator prefix for display."""
        if self.status == CommentStatus.RESOLVED:
            return "[RESOLVED]"
        if self.status == CommentStatus.OUTDATED or self.is_outdated:
            return "[OUTDATED]"
        if self.status == CommentStatus.WONT_FIX:
            return "[WONT_FIX]"
        return ""

    def format_display(self, show_status: bool = True) -> str:
        """Format issue for display output.

        Args:
            show_status: Whether to include resolution status indicator.

        Returns:
            Formatted string like "🔴 [RESOLVED] [path:42] Issue description"
        """
        parts = [self.severity_emoji]
        if show_status and self.status_indicator:
            parts.append(self.status_indicator)
        if self.location:
            parts.append(self.location)
        parts.append(self.description)
        return " ".join(parts)

    @classmethod
    def from_pr_comment(
        cls,
        comment: PRComment,
        description: str | None = None,
        severity: CommentSeverity | None = None,
    ) -> PRIssue:
        """Create a PRIssue from a PRComment.

        Args:
            comment: The source PRComment.
            description: Override description (defaults to first line of body).
            severity: Override severity (defaults to comment's severity).

        Returns:
            PRIssue instance linked to the source comment.
        """
        # Extract file path and line from file_ref
        file_path = ""
        line_number = None
        if comment.file_ref:
            file_path = comment.file_ref.path
            line_number = comment.file_ref.line

        # Use first meaningful line of body as description if not provided
        if description is None:
            lines = comment.body.strip().split("\n")
            for line in lines:
                line = line.strip()
                # Skip headers, empty lines, and common prefixes
                if line and not line.startswith("#") and not line.startswith("<!--"):
                    description = line[:200]  # Truncate if very long
                    break
            if not description:
                description = comment.body[:200]

        # Determine status based on resolution fields
        status = comment.status
        if comment.is_outdated:
            status = CommentStatus.OUTDATED
        elif comment.resolved_at or comment.resolved_by:
            status = CommentStatus.RESOLVED

        return cls(
            file_path=file_path,
            line_number=line_number,
            severity=severity or comment.severity,
            description=description,
            status=status,
            # Safe conversion: only convert purely numeric IDs (REST API)
            # GraphQL node IDs like "IC_kwDOABC123" cannot be stored as int
            comment_id=int(comment.id) if comment.id and comment.id.isdigit() else None,
            thread_id=comment.thread_id,
            resolved_at=comment.resolved_at,
            resolved_by=comment.resolved_by,
            is_outdated=comment.is_outdated,
            source_comment=comment,
        )

    def __repr__(self) -> str:
        status_str = f" [{self.status.value}]" if self.is_resolved else ""
        loc = self.location or "(no location)"
        return f"PRIssue({self.severity.value}{status_str}, {loc}, {self.description[:40]}...)"


class CollatedIssues(BaseModel):
    """
    Container for collated PR issues organized by severity.

    This model represents the output of the collate-issues script,
    providing easy access to issues grouped by severity and status.

    Note:
        For optimal performance, treat instances as immutable after creation.
        The ``all_issues`` property is cached and won't reflect post-creation
        modifications to the issue lists.
    """

    model_config = ConfigDict(extra="allow", frozen=False)

    pr_number: int = Field(..., ge=1, description="PR number")
    repository: str = Field(default="", description="Repository in owner/repo format")
    collated_at: datetime = Field(
        default_factory=datetime.now, description="When issues were collated"
    )
    critical: list[PRIssue] = Field(
        default_factory=list, description="Critical severity issues"
    )
    major: list[PRIssue] = Field(
        default_factory=list, description="Major severity issues"
    )
    minor: list[PRIssue] = Field(
        default_factory=list, description="Minor severity issues"
    )
    nitpick: list[PRIssue] = Field(
        default_factory=list, description="Nitpick severity issues"
    )
    unclassified: list[PRIssue] = Field(
        default_factory=list, description="Unclassified issues"
    )

    @cached_property
    def all_issues(self) -> list[PRIssue]:
        """Get all issues across all severity levels.

        Returns a cached concatenation of all issue lists. The cache is
        invalidated if the model is modified (note: Pydantic models should
        be treated as immutable after creation for caching to work correctly).
        """
        return (
            self.critical + self.major + self.minor + self.nitpick + self.unclassified
        )

    @property
    def open_issues(self) -> list[PRIssue]:
        """Get all issues that are not resolved."""
        return [i for i in self.all_issues if i.is_open]

    @property
    def resolved_issues(self) -> list[PRIssue]:
        """Get all resolved issues."""
        return [i for i in self.all_issues if i.is_resolved]

    @property
    def total_count(self) -> int:
        """Total number of issues."""
        return len(self.all_issues)

    @property
    def open_count(self) -> int:
        """Number of open issues."""
        return len(self.open_issues)

    @property
    def resolved_count(self) -> int:
        """Number of resolved issues."""
        return len(self.resolved_issues)

    @property
    def blocking_count(self) -> int:
        """Number of open critical + major issues (blocking merge)."""
        return sum(1 for i in self.critical + self.major if i.is_open)

    def filter_by_status(
        self, hide_resolved: bool = False, show_resolved_only: bool = False
    ) -> CollatedIssues:
        """Return a new CollatedIssues with filtered issues.

        Args:
            hide_resolved: If True, exclude resolved issues.
            show_resolved_only: If True, only include resolved issues.

        Returns:
            New CollatedIssues instance with filtered issues.

        Raises:
            ValueError: If both hide_resolved and show_resolved_only are True.

        Example:
            >>> issues = CollatedIssues(pr_number=40, critical=[...])
            >>> open_only = issues.filter_by_status(hide_resolved=True)
            >>> resolved_only = issues.filter_by_status(show_resolved_only=True)
        """
        if hide_resolved and show_resolved_only:
            raise ValueError("Cannot use both hide_resolved and show_resolved_only")

        def filter_list(issues: list[PRIssue]) -> list[PRIssue]:
            if hide_resolved:
                return [i for i in issues if i.is_open]
            if show_resolved_only:
                return [i for i in issues if i.is_resolved]
            return issues

        return CollatedIssues(
            pr_number=self.pr_number,
            repository=self.repository,
            collated_at=self.collated_at,
            critical=filter_list(self.critical),
            major=filter_list(self.major),
            minor=filter_list(self.minor),
            nitpick=filter_list(self.nitpick),
            unclassified=filter_list(self.unclassified),
        )

    def get_summary(self, include_nitpicks: bool = False) -> str:
        """Generate a human-readable summary string.

        Args:
            include_nitpicks: Whether to include nitpicks in count.

        Returns:
            Summary string like "3 critical, 5 major, 2 minor = 10 actionable"
        """
        parts = []
        if self.critical:
            parts.append(f"{len(self.critical)} critical")
        if self.major:
            parts.append(f"{len(self.major)} major")
        if self.minor:
            parts.append(f"{len(self.minor)} minor")
        if include_nitpicks and self.nitpick:
            parts.append(f"{len(self.nitpick)} nitpick")

        actionable = len(self.critical) + len(self.major) + len(self.minor)
        if include_nitpicks:
            actionable += len(self.nitpick)

        if not parts:
            return "No issues found"

        return f"Summary: {', '.join(parts)} = {actionable} actionable issues"


# =============================================================================
# Utility Functions
# =============================================================================


def parse_github_datetime(dt_str: str | None) -> datetime | None:
    """
    Parse a GitHub API datetime string.

    Args:
        dt_str: ISO format datetime string from GitHub API.

    Returns:
        datetime object or None if parsing fails.
    """
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def merge_comments_by_id(comments: list[PRComment]) -> list[PRComment]:
    """
    Merge duplicate comments by ID.

    If the same comment appears from multiple sources, keep the most
    complete version.

    Args:
        comments: List of comments that may contain duplicates.

    Returns:
        Deduplicated list of comments.
    """
    seen: dict[str, PRComment] = {}

    for comment in comments:
        if comment.id in seen:
            # Keep the one with more information
            existing = seen[comment.id]
            if len(comment.body) > len(existing.body):
                seen[comment.id] = comment
        else:
            seen[comment.id] = comment

    return list(seen.values())


def classify_severity(body: str) -> CommentSeverity:
    """
    Classify comment severity based on body content.

    Standalone function for use without creating a PRComment instance.

    Args:
        body: The comment body text.

    Returns:
        Detected severity level.
    """
    return PRComment.classify_severity(body)


# =============================================================================
# Module-level exports
# =============================================================================

__all__ = [
    # Constants
    "CLAUDE_BOT_PATTERNS",
    "CODERABBIT_PATTERNS",
    "GITHUB_ACTIONS_PATTERNS",
    "BotType",
    "CollatedIssues",
    "CommentSeverity",
    "CommentStatus",
    # Models
    "FileReference",
    # Enum aliases (for backward compatibility)
    "IssueSeverity",
    "IssueStatus",
    "PRAnalysis",
    "PRComment",
    # Enums
    "PRCommentSource",
    "PRData",
    "PRIssue",
    "PRReview",
    "StructuredSection",
    "classify_severity",
    # Functions
    "detect_bot_type",
    "merge_comments_by_id",
    "parse_github_datetime",
]
