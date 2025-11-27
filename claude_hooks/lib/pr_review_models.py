#!/usr/bin/env python3
"""
Pydantic models for PR review and CI check data structures.

This module provides type-safe models for:
- GitHub PR comment types (reviews, inline comments, PR comments, issue comments)
- Parsed issue types from collate-issues (severity-based categorization)
- CI check and workflow data structures

These models ensure proper field validation and provide clear documentation
for data structures used by the pr-review and ci-failures skills.

Example usage:
    from claude_hooks.lib.pr_review_models import (
        PRReview,
        InlineComment,
        ParsedIssue,
        IssueSeverity,
        CollatedIssues,
        CIWorkflow,
        CIJob,
        parse_pr_data_response,
        parse_collated_issues,
    )

    # Parse raw GitHub API response
    review = PRReview(
        author="octocat",
        state=ReviewState.APPROVED,
        body="LGTM!",
        submitted_at="2025-01-15T10:30:00Z",
        id=12345
    )

    # Create parsed issue
    issue = ParsedIssue(
        severity=IssueSeverity.CRITICAL,
        location="[src/app.py:42]",
        summary="Missing error handling for database connection"
    )
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums
# =============================================================================


class IssueSeverity(str, Enum):
    """Severity level for PR review issues.

    Used by collate-issues to categorize feedback by priority.

    Priority order (highest to lowest):
        CRITICAL > MAJOR > MINOR > NIT

    Merge requirements:
        - CRITICAL, MAJOR, MINOR must be addressed before merge
        - NIT is optional (nice to have)
    """

    CRITICAL = "critical"
    """Must fix before merge. Security issues, data loss, crashes, breaking changes."""

    MAJOR = "major"
    """Must fix before merge. Performance issues, bugs, missing tests, API changes."""

    MINOR = "minor"
    """Must fix before merge. Code quality, documentation, edge cases."""

    NIT = "nit"
    """Optional. Formatting, naming, minor refactoring suggestions."""


class ReviewState(str, Enum):
    """GitHub PR review state.

    Represents the state of a formal PR review submission.
    """

    APPROVED = "APPROVED"
    """Review approves the changes."""

    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    """Review requests changes before approval."""

    COMMENTED = "COMMENTED"
    """Review contains comments without approval or rejection."""

    DISMISSED = "DISMISSED"
    """Review was dismissed by a maintainer."""

    PENDING = "PENDING"
    """Review is pending (started but not submitted)."""


class CIStatus(str, Enum):
    """GitHub Actions workflow/job status.

    Represents the current execution state of a CI workflow or job.
    """

    QUEUED = "queued"
    """Waiting to be assigned to a runner."""

    IN_PROGRESS = "in_progress"
    """Currently executing."""

    COMPLETED = "completed"
    """Execution finished (check conclusion for result)."""

    WAITING = "waiting"
    """Waiting for required conditions (approval, dependencies)."""

    REQUESTED = "requested"
    """Workflow run was requested."""

    PENDING = "pending"
    """Pending execution."""


class CIConclusion(str, Enum):
    """GitHub Actions workflow/job conclusion.

    Represents the final result of a completed CI workflow or job.
    Only applicable when status is COMPLETED.
    """

    SUCCESS = "success"
    """Completed successfully."""

    FAILURE = "failure"
    """Completed with failures."""

    NEUTRAL = "neutral"
    """Completed neutrally (no pass/fail determination)."""

    CANCELLED = "cancelled"
    """Execution was cancelled."""

    SKIPPED = "skipped"
    """Execution was skipped."""

    TIMED_OUT = "timed_out"
    """Execution timed out."""

    ACTION_REQUIRED = "action_required"
    """Manual action required to proceed."""

    STALE = "stale"
    """Check became stale (superseded by newer run)."""


# =============================================================================
# GitHub PR Comment Models
# =============================================================================


class PRReview(BaseModel):
    """Formal PR review from GitHub API.

    Represents a review submitted on a pull request, including approval
    status and optional review comments.

    Source: repos/{owner}/{repo}/pulls/{pr}/reviews API endpoint

    Example:
        >>> review = PRReview(
        ...     author="reviewer",
        ...     state=ReviewState.APPROVED,
        ...     body="Great work! Just a few minor suggestions.",
        ...     submitted_at="2025-01-15T10:30:00Z",
        ...     id=98765432
        ... )
    """

    author: str = Field(
        ...,
        description="GitHub username of the reviewer",
        min_length=1,
    )

    state: ReviewState = Field(
        ...,
        description="Review state (APPROVED, CHANGES_REQUESTED, etc.)",
    )

    body: Optional[str] = Field(
        default=None,
        description="Review body text (may be empty for approvals)",
    )

    submitted_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when review was submitted",
    )

    id: int = Field(
        ...,
        description="Unique identifier for the review",
        gt=0,
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "author": "octocat",
                "state": "APPROVED",
                "body": "LGTM! Great refactoring work.",
                "submitted_at": "2025-01-15T10:30:00Z",
                "id": 98765432,
            }
        },
    )


class InlineComment(BaseModel):
    """Inline code review comment on a specific file/line.

    Represents a comment attached to a specific location in the PR diff.

    Source: repos/{owner}/{repo}/pulls/{pr}/comments API endpoint

    Example:
        >>> comment = InlineComment(
        ...     author="reviewer",
        ...     path="src/app.py",
        ...     line=42,
        ...     body="Consider using a context manager here.",
        ...     created_at="2025-01-15T10:35:00Z",
        ...     id=12345678
        ... )
    """

    author: str = Field(
        ...,
        description="GitHub username of the commenter",
        min_length=1,
    )

    path: str = Field(
        ...,
        description="File path relative to repository root",
        min_length=1,
    )

    line: Optional[int] = Field(
        default=None,
        description="Line number in the diff (may be null for file-level comments)",
        gt=0,
    )

    body: str = Field(
        ...,
        description="Comment body text",
    )

    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when comment was created",
    )

    id: int = Field(
        ...,
        description="Unique identifier for the comment",
        gt=0,
    )

    position: Optional[int] = Field(
        default=None,
        description="Position in the diff (deprecated, use line instead)",
    )

    commit_id: Optional[str] = Field(
        default=None,
        description="SHA of the commit the comment was made on",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "author": "octocat",
                "path": "src/utils/helpers.py",
                "line": 42,
                "body": "Consider adding error handling for None values.",
                "created_at": "2025-01-15T10:35:00Z",
                "id": 12345678,
            }
        },
    )


class PRComment(BaseModel):
    """PR conversation comment (not attached to code).

    Represents a general comment on the PR conversation thread.

    Source: gh pr view {pr} --json comments API

    Example:
        >>> comment = PRComment(
        ...     author="maintainer",
        ...     body="Please add tests for the new functionality.",
        ...     created_at="2025-01-15T11:00:00Z",
        ...     id=87654321
        ... )
    """

    author: str = Field(
        ...,
        description="GitHub username of the commenter",
        min_length=1,
    )

    body: str = Field(
        ...,
        description="Comment body text",
    )

    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when comment was created",
    )

    updated_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when comment was last updated",
    )

    id: int = Field(
        ...,
        description="Unique identifier for the comment",
        gt=0,
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "author": "maintainer",
                "body": "Please address the CI failures before merging.",
                "created_at": "2025-01-15T11:00:00Z",
                "id": 87654321,
            }
        },
    )


class IssueComment(BaseModel):
    """Issue comment on a PR (where Claude Code bot posts).

    Represents a comment on the PR's associated issue thread.
    This is where automated bot reviews (like Claude Code) are posted.

    Source: repos/{owner}/{repo}/issues/{pr}/comments API endpoint

    Example:
        >>> comment = IssueComment(
        ...     author="claude-code[bot]",
        ...     body="## Code Review\\n\\n### Summary...",
        ...     created_at="2025-01-15T11:30:00Z",
        ...     id=11223344
        ... )
    """

    author: str = Field(
        ...,
        description="GitHub username of the commenter (may include [bot] suffix)",
        min_length=1,
    )

    body: str = Field(
        ...,
        description="Comment body text (may contain structured markdown)",
    )

    created_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when comment was created",
    )

    updated_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when comment was last updated",
    )

    id: int = Field(
        ...,
        description="Unique identifier for the comment",
        gt=0,
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "author": "claude-code[bot]",
                "body": "## Code Review\n\n### Summary\nGood overall structure...",
                "created_at": "2025-01-15T11:30:00Z",
                "id": 11223344,
            }
        },
    )


# =============================================================================
# PR Data Response Model (combined fetch-pr-data output)
# =============================================================================


class PRDataSummary(BaseModel):
    """Summary statistics from fetch-pr-data.

    Provides counts of comments from all 4 GitHub API endpoints.
    """

    total_reviews: int = Field(
        default=0,
        description="Number of formal reviews",
        ge=0,
    )

    total_inline_comments: int = Field(
        default=0,
        description="Number of inline code comments",
        ge=0,
    )

    total_pr_comments: int = Field(
        default=0,
        description="Number of PR conversation comments",
        ge=0,
    )

    total_issue_comments: int = Field(
        default=0,
        description="Number of issue comments (includes bot reviews)",
        ge=0,
    )

    total_all_comments: int = Field(
        default=0,
        description="Total count across all endpoints",
        ge=0,
    )

    model_config = ConfigDict(extra="ignore")


class PRDataResponse(BaseModel):
    """Complete response from fetch-pr-data script.

    Combines data from all 4 GitHub API endpoints into a single response.

    Example:
        >>> response = parse_pr_data_response(raw_json)
        >>> print(f"PR #{response.pr_number} has {response.summary.total_all_comments} comments")
    """

    pr_number: int = Field(
        ...,
        description="Pull request number",
        gt=0,
    )

    repository: str = Field(
        ...,
        description="Repository in owner/name format",
    )

    fetched_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when data was fetched",
    )

    fetch_mode: str = Field(
        default="full",
        description="Fetch mode: 'full', 'limited', or 'summary'",
    )

    limit: Optional[int] = Field(
        default=None,
        description="Comment limit if fetch_mode is 'limited'",
    )

    reviews: List[PRReview] = Field(
        default_factory=list,
        description="Formal PR reviews",
    )

    inline_comments: List[InlineComment] = Field(
        default_factory=list,
        description="Inline code review comments",
    )

    pr_comments: List[PRComment] = Field(
        default_factory=list,
        description="PR conversation comments",
    )

    issue_comments: List[IssueComment] = Field(
        default_factory=list,
        description="Issue comments (includes bot reviews)",
    )

    summary: PRDataSummary = Field(
        default_factory=PRDataSummary,
        description="Comment count statistics",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "pr_number": 33,
                "repository": "owner/repo",
                "fetched_at": "2025-01-15T12:00:00Z",
                "fetch_mode": "full",
                "reviews": [],
                "inline_comments": [],
                "pr_comments": [],
                "issue_comments": [],
                "summary": {
                    "total_reviews": 2,
                    "total_inline_comments": 5,
                    "total_pr_comments": 3,
                    "total_issue_comments": 1,
                    "total_all_comments": 11,
                },
            }
        },
    )


# =============================================================================
# Parsed Issue Models (from collate-issues)
# =============================================================================


class ParsedIssue(BaseModel):
    """Single parsed issue from PR review comments.

    Represents an actionable issue extracted and categorized from
    review comments by the collate-issues script.

    Example:
        >>> issue = ParsedIssue(
        ...     severity=IssueSeverity.CRITICAL,
        ...     location="[src/database.py:156]",
        ...     summary="SQL injection vulnerability in user query"
        ... )
    """

    severity: IssueSeverity = Field(
        ...,
        description="Issue severity level",
    )

    location: str = Field(
        default="",
        description="File location in format [path:line] or empty for general issues",
    )

    summary: str = Field(
        ...,
        description="Concise summary of the issue",
        min_length=1,
    )

    @field_validator("location")
    @classmethod
    def validate_location_format(cls, v: str) -> str:
        """Validate location format is [path:line] or empty."""
        if v and not v.startswith("["):
            # Normalize to bracket format if path is provided
            return f"[{v}]"
        return v

    @property
    def file_path(self) -> Optional[str]:
        """Extract file path from location.

        Returns:
            File path without line number, or None if no location.
        """
        if not self.location or self.location == "":
            return None
        # Remove brackets and line number: [path/file.py:42] -> path/file.py
        path = self.location.strip("[]")
        if ":" in path:
            path = path.rsplit(":", 1)[0]
        return path

    @property
    def line_number(self) -> Optional[int]:
        """Extract line number from location.

        Returns:
            Line number, or None if not specified.
        """
        if not self.location or ":" not in self.location:
            return None
        try:
            line_str = self.location.strip("[]").rsplit(":", 1)[1]
            return int(line_str)
        except (ValueError, IndexError):
            return None

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "severity": "critical",
                "location": "[src/auth.py:89]",
                "summary": "Password stored in plaintext without hashing",
            }
        },
    )


class CollatedIssues(BaseModel):
    """Categorized issues from collate-issues script.

    Groups all parsed issues by severity level for easy access.

    Example:
        >>> issues = CollatedIssues(
        ...     critical=["[auth.py:10] SQL injection vulnerability"],
        ...     major=["[api.py:50] Missing rate limiting"],
        ...     minor=["[utils.py:30] Add docstring"],
        ...     nit=["Consider renaming variable"]
        ... )
        >>> print(f"Must fix: {issues.actionable_count} issues")
    """

    critical: List[str] = Field(
        default_factory=list,
        description="Critical issues (must fix: security, crashes, data loss)",
    )

    major: List[str] = Field(
        default_factory=list,
        description="Major issues (must fix: bugs, performance, missing tests)",
    )

    minor: List[str] = Field(
        default_factory=list,
        description="Minor issues (must fix: code quality, docs, edge cases)",
    )

    nit: List[str] = Field(
        default_factory=list,
        description="Nitpick issues (optional: formatting, naming)",
    )

    @property
    def total_count(self) -> int:
        """Total count of all issues."""
        return len(self.critical) + len(self.major) + len(self.minor) + len(self.nit)

    @property
    def actionable_count(self) -> int:
        """Count of issues that must be fixed before merge."""
        return len(self.critical) + len(self.major) + len(self.minor)

    @property
    def can_merge(self) -> bool:
        """Whether PR can be merged (no critical, major, or minor issues)."""
        return self.actionable_count == 0

    def to_parsed_issues(self) -> List[ParsedIssue]:
        """Convert to list of ParsedIssue objects.

        Returns:
            List of ParsedIssue objects for all issues.
        """
        issues = []

        for text in self.critical:
            location, summary = self._parse_issue_text(text)
            issues.append(
                ParsedIssue(
                    severity=IssueSeverity.CRITICAL,
                    location=location,
                    summary=summary,
                )
            )

        for text in self.major:
            location, summary = self._parse_issue_text(text)
            issues.append(
                ParsedIssue(
                    severity=IssueSeverity.MAJOR,
                    location=location,
                    summary=summary,
                )
            )

        for text in self.minor:
            location, summary = self._parse_issue_text(text)
            issues.append(
                ParsedIssue(
                    severity=IssueSeverity.MINOR,
                    location=location,
                    summary=summary,
                )
            )

        for text in self.nit:
            location, summary = self._parse_issue_text(text)
            issues.append(
                ParsedIssue(
                    severity=IssueSeverity.NIT,
                    location=location,
                    summary=summary,
                )
            )

        return issues

    @staticmethod
    def _parse_issue_text(text: str) -> tuple[str, str]:
        """Parse issue text into location and summary.

        Args:
            text: Issue text, optionally prefixed with [path:line]

        Returns:
            Tuple of (location, summary)
        """
        text = text.strip()
        if text.startswith("[") and "]" in text:
            bracket_end = text.index("]") + 1
            location = text[:bracket_end]
            summary = text[bracket_end:].strip()
            return location, summary
        return "", text

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "critical": ["[auth.py:89] Password stored without hashing"],
                "major": ["[api.py:50] Missing rate limiting on login endpoint"],
                "minor": ["[utils.py:30] Add docstring to helper function"],
                "nit": ["Consider using more descriptive variable name"],
            }
        },
    )


# =============================================================================
# CI Check Models
# =============================================================================


class CIStep(BaseModel):
    """Individual step within a CI job.

    Represents a single step in a GitHub Actions job.

    Example:
        >>> step = CIStep(
        ...     name="Run tests",
        ...     status=CIStatus.COMPLETED,
        ...     conclusion=CIConclusion.FAILURE,
        ...     number=3
        ... )
    """

    name: str = Field(
        ...,
        description="Step name as defined in workflow",
    )

    status: CIStatus = Field(
        ...,
        description="Current execution status",
    )

    conclusion: Optional[CIConclusion] = Field(
        default=None,
        description="Final result (only set when status is COMPLETED)",
    )

    number: int = Field(
        ...,
        description="Step number within the job",
        ge=1,
    )

    started_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when step started",
    )

    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when step completed",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "Run pytest",
                "status": "completed",
                "conclusion": "failure",
                "number": 3,
                "started_at": "2025-01-15T12:05:00Z",
                "completed_at": "2025-01-15T12:10:00Z",
            }
        },
    )


class CIJob(BaseModel):
    """CI job within a workflow run.

    Represents a single job in a GitHub Actions workflow.

    Example:
        >>> job = CIJob(
        ...     id=12345,
        ...     name="test",
        ...     status=CIStatus.COMPLETED,
        ...     conclusion=CIConclusion.FAILURE,
        ...     steps=[...]
        ... )
    """

    id: int = Field(
        ...,
        description="Unique job identifier",
        gt=0,
    )

    name: str = Field(
        ...,
        description="Job name as defined in workflow",
    )

    status: CIStatus = Field(
        ...,
        description="Current execution status",
    )

    conclusion: Optional[CIConclusion] = Field(
        default=None,
        description="Final result (only set when status is COMPLETED)",
    )

    steps: List[CIStep] = Field(
        default_factory=list,
        description="Steps within the job",
    )

    started_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when job started",
    )

    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when job completed",
    )

    runner_name: Optional[str] = Field(
        default=None,
        description="Name of the runner that executed this job",
    )

    html_url: Optional[str] = Field(
        default=None,
        description="URL to view job details on GitHub",
    )

    @property
    def failed_steps(self) -> List[CIStep]:
        """Get list of failed steps."""
        return [s for s in self.steps if s.conclusion == CIConclusion.FAILURE]

    @property
    def is_failed(self) -> bool:
        """Check if job failed."""
        return self.conclusion == CIConclusion.FAILURE

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": 12345678,
                "name": "test-python-3.11",
                "status": "completed",
                "conclusion": "failure",
                "steps": [],
                "started_at": "2025-01-15T12:00:00Z",
                "completed_at": "2025-01-15T12:15:00Z",
            }
        },
    )


class CIWorkflow(BaseModel):
    """GitHub Actions workflow run.

    Represents a complete workflow run with all its jobs.

    Example:
        >>> workflow = CIWorkflow(
        ...     id=9876543,
        ...     name="CI",
        ...     status=CIStatus.COMPLETED,
        ...     conclusion=CIConclusion.FAILURE,
        ...     jobs=[...]
        ... )
    """

    id: int = Field(
        ...,
        description="Unique workflow run identifier",
        gt=0,
    )

    name: str = Field(
        ...,
        description="Workflow name as defined in .github/workflows/",
    )

    status: CIStatus = Field(
        ...,
        description="Current execution status",
    )

    conclusion: Optional[CIConclusion] = Field(
        default=None,
        description="Final result (only set when status is COMPLETED)",
    )

    jobs: List[CIJob] = Field(
        default_factory=list,
        description="Jobs within the workflow",
    )

    head_sha: Optional[str] = Field(
        default=None,
        description="Git SHA of the commit that triggered the workflow",
    )

    head_branch: Optional[str] = Field(
        default=None,
        description="Branch that triggered the workflow",
    )

    event: Optional[str] = Field(
        default=None,
        description="Event that triggered the workflow (push, pull_request, etc.)",
    )

    started_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when workflow started",
    )

    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when workflow completed",
    )

    html_url: Optional[str] = Field(
        default=None,
        description="URL to view workflow run on GitHub",
    )

    @property
    def failed_jobs(self) -> List[CIJob]:
        """Get list of failed jobs."""
        return [j for j in self.jobs if j.is_failed]

    @property
    def is_failed(self) -> bool:
        """Check if workflow failed."""
        return self.conclusion == CIConclusion.FAILURE

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "id": 9876543210,
                "name": "CI/CD Pipeline",
                "status": "completed",
                "conclusion": "failure",
                "jobs": [],
                "head_sha": "abc123def456",
                "head_branch": "feature/new-feature",
                "event": "pull_request",
            }
        },
    )


class CICheck(BaseModel):
    """Simplified CI check status.

    Lightweight model for quick CI status checks without full job details.

    Example:
        >>> check = CICheck(
        ...     name="lint",
        ...     status=CIStatus.COMPLETED,
        ...     conclusion=CIConclusion.SUCCESS
        ... )
    """

    name: str = Field(
        ...,
        description="Check name",
    )

    status: CIStatus = Field(
        ...,
        description="Current execution status",
    )

    conclusion: Optional[CIConclusion] = Field(
        default=None,
        description="Final result (only set when status is COMPLETED)",
    )

    started_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when check started",
    )

    completed_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when check completed",
    )

    details_url: Optional[str] = Field(
        default=None,
        description="URL for more details about the check",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "name": "lint",
                "status": "completed",
                "conclusion": "success",
                "started_at": "2025-01-15T12:00:00Z",
                "completed_at": "2025-01-15T12:02:00Z",
            }
        },
    )


# =============================================================================
# CI Failure Research Models (from fetch-ci-data research feature)
# =============================================================================


class CIErrorResearch(BaseModel):
    """Research data for unrecognized CI errors.

    Contains prepared search queries and suggestions for debugging.
    """

    search_queries: List[str] = Field(
        default_factory=list,
        description="Prepared search queries for web research",
    )

    suggestions: List[str] = Field(
        default_factory=list,
        description="Actionable debugging suggestions",
    )

    context: Optional[str] = Field(
        default=None,
        description="Extracted technology context (Python, JavaScript, etc.)",
    )

    auto_research_hint: Optional[str] = Field(
        default=None,
        description="Hint for Claude Code automation",
    )

    model_config = ConfigDict(extra="ignore")


class CIFailure(BaseModel):
    """Single CI failure with optional research data.

    Represents a failed CI step/job with error details and research hints.
    """

    job_name: str = Field(
        ...,
        description="Name of the failed job",
    )

    step_name: Optional[str] = Field(
        default=None,
        description="Name of the failed step (if applicable)",
    )

    error_message: str = Field(
        ...,
        description="Error message or log excerpt",
    )

    error_type: str = Field(
        default="unrecognized",
        description="Error classification: 'recognized' or 'unrecognized'",
    )

    research: Optional[CIErrorResearch] = Field(
        default=None,
        description="Research data for unrecognized errors",
    )

    log_url: Optional[str] = Field(
        default=None,
        description="URL to full job logs",
    )

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "job_name": "test-python-3.11",
                "step_name": "Run pytest",
                "error_message": "FAILED tests/test_api.py::test_auth - AssertionError",
                "error_type": "recognized",
                "research": None,
            }
        },
    )


class CIDataResponse(BaseModel):
    """Complete response from fetch-ci-data script.

    Contains all CI failure information with research data for debugging.
    """

    pr_number: Optional[int] = Field(
        default=None,
        description="PR number if fetching for a PR",
    )

    branch: Optional[str] = Field(
        default=None,
        description="Branch name",
    )

    workflow_name: Optional[str] = Field(
        default=None,
        description="Workflow name filter (if applied)",
    )

    failures: List[CIFailure] = Field(
        default_factory=list,
        description="List of CI failures",
    )

    summary: Dict[str, Any] = Field(
        default_factory=dict,
        description="Summary statistics including 'researched' count",
    )

    fetched_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp when data was fetched",
    )

    model_config = ConfigDict(extra="ignore")


# =============================================================================
# Parser Functions
# =============================================================================


def parse_pr_data_response(data: Dict[str, Any]) -> PRDataResponse:
    """Parse raw JSON from fetch-pr-data into typed model.

    Args:
        data: Raw JSON dictionary from fetch-pr-data script

    Returns:
        PRDataResponse model with validated data

    Example:
        >>> import json
        >>> raw = json.loads(subprocess.check_output(["fetch-pr-data", "33"]))
        >>> response = parse_pr_data_response(raw)
        >>> print(f"Found {response.summary.total_all_comments} comments")
    """
    # Handle reviews - may be array or summary object
    reviews = []
    if isinstance(data.get("reviews"), list):
        reviews = [
            PRReview(**r)
            for r in data["reviews"]
            if isinstance(r, dict) and "author" in r
        ]

    # Handle inline comments
    inline_comments = []
    if isinstance(data.get("inline_comments"), list):
        inline_comments = [
            InlineComment(**c)
            for c in data["inline_comments"]
            if isinstance(c, dict) and "author" in c
        ]

    # Handle PR comments
    pr_comments = []
    if isinstance(data.get("pr_comments"), list):
        pr_comments = [
            PRComment(**c)
            for c in data["pr_comments"]
            if isinstance(c, dict) and "author" in c
        ]

    # Handle issue comments
    issue_comments = []
    if isinstance(data.get("issue_comments"), list):
        issue_comments = [
            IssueComment(**c)
            for c in data["issue_comments"]
            if isinstance(c, dict) and "author" in c
        ]

    # Parse summary
    summary_data = data.get("summary", {})
    summary = PRDataSummary(**summary_data) if summary_data else PRDataSummary()

    return PRDataResponse(
        pr_number=data.get("pr_number", 0),
        repository=data.get("repository", ""),
        fetched_at=data.get("fetched_at"),
        fetch_mode=data.get("fetch_mode", "full"),
        limit=data.get("limit"),
        reviews=reviews,
        inline_comments=inline_comments,
        pr_comments=pr_comments,
        issue_comments=issue_comments,
        summary=summary,
    )


def parse_collated_issues(data: Dict[str, Any]) -> CollatedIssues:
    """Parse raw collate-issues output into typed model.

    Args:
        data: Dictionary with critical/major/minor/nit arrays

    Returns:
        CollatedIssues model with validated data

    Example:
        >>> raw = {"critical": ["[file.py:10] Issue"], "major": [], "minor": [], "nit": []}
        >>> issues = parse_collated_issues(raw)
        >>> print(f"Can merge: {issues.can_merge}")
    """
    return CollatedIssues(
        critical=data.get("critical", []),
        major=data.get("major", []),
        minor=data.get("minor", []),
        nit=data.get("nit", []),
    )


def parse_ci_data_response(data: Dict[str, Any]) -> CIDataResponse:
    """Parse raw JSON from fetch-ci-data into typed model.

    Args:
        data: Raw JSON dictionary from fetch-ci-data script

    Returns:
        CIDataResponse model with validated data
    """
    failures = []
    for f in data.get("failures", []):
        research = None
        if f.get("research"):
            research = CIErrorResearch(**f["research"])

        failures.append(
            CIFailure(
                job_name=f.get("job_name", "unknown"),
                step_name=f.get("step_name"),
                error_message=f.get("error_message", ""),
                error_type=f.get("error_type", "unrecognized"),
                research=research,
                log_url=f.get("log_url"),
            )
        )

    return CIDataResponse(
        pr_number=data.get("pr_number"),
        branch=data.get("branch"),
        workflow_name=data.get("workflow_name"),
        failures=failures,
        summary=data.get("summary", {}),
        fetched_at=data.get("fetched_at"),
    )


# =============================================================================
# Utility Functions
# =============================================================================


def severity_to_emoji(severity: IssueSeverity) -> str:
    """Get emoji for severity level.

    Args:
        severity: Issue severity level

    Returns:
        Emoji string for display
    """
    return {
        IssueSeverity.CRITICAL: "!",
        IssueSeverity.MAJOR: "!",
        IssueSeverity.MINOR: "!",
        IssueSeverity.NIT: " ",
    }[severity]


def severity_to_color_emoji(severity: IssueSeverity) -> str:
    """Get colored circle emoji for severity level.

    Args:
        severity: Issue severity level

    Returns:
        Colored circle emoji for display
    """
    return {
        IssueSeverity.CRITICAL: "[CRITICAL]",
        IssueSeverity.MAJOR: "[MAJOR]",
        IssueSeverity.MINOR: "[MINOR]",
        IssueSeverity.NIT: "[NIT]",
    }[severity]


if __name__ == "__main__":
    # Example usage demonstration
    import json

    print("PR Review Models - Example Usage\n")

    # Example: Create a parsed issue
    issue = ParsedIssue(
        severity=IssueSeverity.CRITICAL,
        location="[src/auth.py:89]",
        summary="Password stored in plaintext without hashing",
    )
    print(f"Parsed Issue: {issue.severity.value.upper()}")
    print(f"  Location: {issue.location}")
    print(f"  File: {issue.file_path}")
    print(f"  Line: {issue.line_number}")
    print(f"  Summary: {issue.summary}")
    print()

    # Example: Create collated issues
    collated = CollatedIssues(
        critical=["[auth.py:89] Password stored without hashing"],
        major=["[api.py:50] Missing rate limiting"],
        minor=["[utils.py:30] Add docstring"],
        nit=["Consider renaming variable"],
    )
    print(f"Collated Issues:")
    print(f"  Critical: {len(collated.critical)}")
    print(f"  Major: {len(collated.major)}")
    print(f"  Minor: {len(collated.minor)}")
    print(f"  Nit: {len(collated.nit)}")
    print(f"  Actionable: {collated.actionable_count}")
    print(f"  Can merge: {collated.can_merge}")
    print()

    # Example: Create CI check
    check = CICheck(
        name="lint",
        status=CIStatus.COMPLETED,
        conclusion=CIConclusion.SUCCESS,
        started_at="2025-01-15T12:00:00Z",
        completed_at="2025-01-15T12:02:00Z",
    )
    print(f"CI Check: {check.name}")
    print(f"  Status: {check.status.value}")
    print(f"  Conclusion: {check.conclusion.value if check.conclusion else 'N/A'}")
    print()

    # Show JSON schema
    print("JSON Schema (ParsedIssue):")
    print(json.dumps(ParsedIssue.model_json_schema(), indent=2))
