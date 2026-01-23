#!/usr/bin/env python3
"""
PR Data Fetcher - Type-safe GitHub PR data retrieval

Uses Pydantic models for validation and ensures Claude bot comments
are NEVER missed by fetching from ALL 4 GitHub API endpoints.

Endpoints fetched:
1. /repos/{owner}/{repo}/pulls/{pr}/reviews - Formal reviews
2. /repos/{owner}/{repo}/pulls/{pr}/comments - Inline code comments
3. gh pr view --json comments - PR conversation comments
4. /repos/{owner}/{repo}/issues/{pr}/comments - Issue comments (CLAUDE BOT!)
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Add the script directory to path for relative imports
SCRIPT_DIR = Path(__file__).parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from models import (
    BotType,
    CommentSeverity,
    CommentStatus,
    ModelFileReference,
    ModelPRComment,
    ModelPRCommentSource,
    ModelPRData,
    ModelPRReview,
    ModelStructuredSection,
    detect_bot_type,
)


# Review states as Literal type (no longer enum)
REVIEW_STATES = ["APPROVED", "CHANGES_REQUESTED", "COMMENTED", "PENDING", "DISMISSED"]

CACHE_DIR = Path("/tmp/pr-review-cache-v2")
CACHE_TTL_SECONDS = 300  # 5 minutes


class PRFetchError(Exception):
    """Error during PR data fetching."""

    pass


class PRFetcher:
    """Fetches PR data from GitHub with proper type safety.

    CRITICAL: This fetcher ensures Claude bot comments are NEVER missed
    by explicitly fetching from the issue_comments endpoint, which is
    where Claude Code posts its reviews.
    """

    def __init__(self, repo: str, pr_number: int):
        self.repo = repo
        self.pr_number = pr_number
        self.cache_dir = CACHE_DIR
        self.cache_dir.mkdir(exist_ok=True)

    def fetch(self, use_cache: bool = True) -> ModelPRData:
        """Fetch PR data, using cache if available and valid.

        Args:
            use_cache: Whether to use cached data if available

        Returns:
            ModelPRData model with all comments from all 4 endpoints
        """
        if use_cache:
            cached = self._load_cache()
            if cached:
                return cached

        # Fetch fresh data
        pr_data = self._fetch_from_github()

        # Cache the result
        self._save_cache(pr_data)

        return pr_data

    def _fetch_from_github(self) -> ModelPRData:
        """Fetch all PR data from GitHub API via 4 endpoints."""
        # Fetch PR metadata first
        pr_meta = self._gh_api(f"repos/{self.repo}/pulls/{self.pr_number}")
        if not pr_meta:
            raise PRFetchError(f"Failed to fetch PR #{self.pr_number} metadata")

        # Fetch all 4 comment sources
        # 1. Formal reviews (approve/changes requested/comment)
        reviews_data = self._gh_api(f"repos/{self.repo}/pulls/{self.pr_number}/reviews")

        # 2. Inline code review comments (specific line comments)
        inline_data = self._gh_api(f"repos/{self.repo}/pulls/{self.pr_number}/comments")

        # 3. PR conversation comments (gh pr view format)
        pr_comments_data = self._gh_cli_pr_comments()

        # 4. Issue comments - CRITICAL: This is where Claude Code bot posts!
        issue_comments_data = self._gh_api(
            f"repos/{self.repo}/issues/{self.pr_number}/comments"
        )

        # Parse reviews
        reviews = []
        for r in reviews_data or []:
            review = self._parse_review(r)
            if review:
                reviews.append(review)

        # Parse all comments from all sources
        all_comments = []

        # Inline comments (code review comments with file/line info)
        for c in inline_data or []:
            comment = self._parse_comment(c, ModelPRCommentSource.INLINE)
            if comment:
                all_comments.append(comment)

        # PR conversation comments
        for c in pr_comments_data or []:
            comment = self._parse_comment(c, ModelPRCommentSource.PR_COMMENT)
            if comment:
                all_comments.append(comment)

        # Issue comments (WHERE CLAUDE BOT POSTS!)
        for c in issue_comments_data or []:
            comment = self._parse_comment(c, ModelPRCommentSource.ISSUE_COMMENT)
            if comment:
                all_comments.append(comment)

        # Build and return ModelPRData
        created_at = None
        updated_at = None
        try:
            if pr_meta.get("created_at"):
                created_at = datetime.fromisoformat(
                    pr_meta["created_at"].replace("Z", "+00:00")
                )
            if pr_meta.get("updated_at"):
                updated_at = datetime.fromisoformat(
                    pr_meta["updated_at"].replace("Z", "+00:00")
                )
        except (ValueError, TypeError):
            pass

        return ModelPRData(
            pr_number=self.pr_number,
            repository=self.repo,
            title=pr_meta.get("title", ""),
            author=pr_meta.get("user", {}).get("login", "unknown"),
            base_branch=pr_meta.get("base", {}).get("ref", "main"),
            head_branch=pr_meta.get("head", {}).get("ref", "unknown"),
            state=pr_meta.get("state", "open"),
            created_at=created_at,
            updated_at=updated_at,
            reviews=reviews,
            comments=all_comments,
            fetched_at=datetime.now(),
            fetch_source="github_api",
        )

    def _parse_review(self, data: dict) -> Optional[ModelPRReview]:
        """Parse a GitHub review into a ModelPRReview model."""
        try:
            author = data.get("user", {}).get("login", "unknown")
            state_str = data.get("state", "COMMENTED")

            # Validate state is one of the allowed values (Literal type)
            if state_str not in REVIEW_STATES:
                state_str = "COMMENTED"

            submitted_at_str = data.get("submitted_at")
            if not submitted_at_str:
                submitted_at = datetime.now()
            else:
                submitted_at = datetime.fromisoformat(
                    submitted_at_str.replace("Z", "+00:00")
                )

            return ModelPRReview(
                id=str(data.get("id", "")),
                author=author,
                author_type=detect_bot_type(author),
                state=state_str,
                body=data.get("body"),
                submitted_at=submitted_at,
                raw_json=data,
            )
        except Exception as e:
            # Log but don't fail on individual review parse errors
            print(f"Warning: Failed to parse review: {e}", file=sys.stderr)
            return None

    def _parse_comment(
        self, data: dict, source: ModelPRCommentSource
    ) -> Optional[ModelPRComment]:
        """Parse a GitHub comment into a ModelPRComment model."""
        try:
            # Handle different field names between endpoints
            author = (
                data.get("user", {}).get("login")
                or data.get("author", {}).get("login")
                or "unknown"
            )
            author_type = detect_bot_type(author)
            body = data.get("body", "")

            # Extract file reference if present (inline comments have this)
            file_ref = None
            if "path" in data:
                file_ref = ModelFileReference(
                    path=data["path"],
                    line=data.get("line") or data.get("original_line"),
                    end_line=data.get("end_line"),
                    diff_hunk=data.get("diff_hunk"),
                )

            # Parse structured sections from bot comments
            structured_sections = self._extract_structured_sections(body, author_type)

            # Determine severity from content
            severity = self._determine_severity(body, structured_sections, author_type)

            # Parse timestamps
            created_at_str = data.get("created_at") or data.get("createdAt")
            if not created_at_str:
                created_at = datetime.now()
            else:
                created_at = datetime.fromisoformat(
                    created_at_str.replace("Z", "+00:00")
                )

            updated_at = None
            updated_at_str = data.get("updated_at") or data.get("updatedAt")
            if updated_at_str:
                updated_at = datetime.fromisoformat(
                    updated_at_str.replace("Z", "+00:00")
                )

            return ModelPRComment(
                id=str(data.get("id", "")),
                source=source,
                author=author,
                author_type=author_type,
                body=body,
                severity=severity,
                status=CommentStatus.UNADDRESSED,
                file_ref=file_ref,
                created_at=created_at,
                updated_at=updated_at,
                in_reply_to_id=(
                    str(data["in_reply_to_id"]) if data.get("in_reply_to_id") else None
                ),
                structured_sections=structured_sections,
                raw_json=data,
            )
        except Exception as e:
            # Log but don't fail on individual comment parse errors
            print(f"Warning: Failed to parse comment: {e}", file=sys.stderr)
            return None

    def _extract_structured_sections(
        self, body: str, author_type: BotType
    ) -> list[ModelStructuredSection]:
        """Extract structured sections from bot comments."""
        sections = []

        if not body:
            return sections

        if author_type == BotType.CLAUDE_CODE:
            # Claude bot sections: ### Must Fix, ### Should Fix, ### Nice to Have
            section_patterns = [
                (
                    "must_fix",
                    [
                        "### Must Fix",
                        "### 🔴",
                        "## Must Fix",
                        "**Must Fix**",
                        "## Critical",
                        "### Critical",
                    ],
                ),
                (
                    "should_fix",
                    [
                        "### Should Fix",
                        "### ⚠️",
                        "## Should Fix",
                        "**Should Fix**",
                        "## Major",
                        "### Major",
                    ],
                ),
                (
                    "nice_to_have",
                    [
                        "### Nice to Have",
                        "### 💡",
                        "## Nice to Have",
                        "**Nice to Have**",
                        "## Minor",
                        "### Minor",
                        "## Nitpick",
                        "### Nitpick",
                    ],
                ),
                ("actionable_comments", ["### Actionable", "## Actionable"]),
                ("summary", ["### Summary", "## Summary"]),
            ]

            for section_type, patterns in section_patterns:
                for pattern in patterns:
                    if pattern.lower() in body.lower():
                        # Extract content after the pattern until next section or end
                        start_idx = body.lower().find(pattern.lower())
                        if start_idx != -1:
                            content = body[start_idx:]
                            # Find next section header
                            next_section = len(content)
                            for _, other_patterns in section_patterns:
                                for other_pattern in other_patterns:
                                    idx = content.lower().find(
                                        other_pattern.lower(), len(pattern)
                                    )
                                    if idx != -1 and idx < next_section:
                                        next_section = idx
                            content = content[:next_section].strip()
                            sections.append(
                                ModelStructuredSection(
                                    section_type=section_type,
                                    content=content,
                                    extracted_issues=self._extract_issues_from_section(
                                        content
                                    ),
                                )
                            )
                            break

        elif author_type == BotType.CODERABBIT:
            # CodeRabbit sections
            section_patterns = [
                ("must_fix", ["## 🔴", "### 🔴", "**Critical**", "🔴 Critical"]),
                ("should_fix", ["## ⚠️", "### ⚠️", "**Moderate**", "⚠️ Moderate"]),
                ("nice_to_have", ["## 💡", "### 💡", "**Minor**", "💡 Minor"]),
            ]

            for section_type, patterns in section_patterns:
                for pattern in patterns:
                    if pattern in body:
                        start_idx = body.find(pattern)
                        if start_idx != -1:
                            content = body[start_idx:]
                            next_section = len(content)
                            for _, other_patterns in section_patterns:
                                for other_pattern in other_patterns:
                                    idx = content.find(other_pattern, len(pattern))
                                    if idx != -1 and idx < next_section:
                                        next_section = idx
                            content = content[:next_section].strip()
                            sections.append(
                                ModelStructuredSection(
                                    section_type=section_type,
                                    content=content,
                                    extracted_issues=self._extract_issues_from_section(
                                        content
                                    ),
                                )
                            )
                            break

        return sections

    def _extract_issues_from_section(self, content: str) -> list[str]:
        """Extract individual issues from a section content."""
        issues = []
        lines = content.split("\n")

        for line in lines:
            line = line.strip()
            # Look for bullet points or numbered items
            if line.startswith(("- ", "* ", "• ")):
                issue = line[2:].strip()
                if issue:
                    issues.append(issue)
            elif line and line[0].isdigit() and ". " in line:
                # Numbered list item
                issue = line.split(". ", 1)[1].strip() if ". " in line else line
                if issue:
                    issues.append(issue)

        return issues

    def _determine_severity(
        self, body: str, sections: list[ModelStructuredSection], author_type: BotType
    ) -> CommentSeverity:
        """Determine comment severity from content."""
        body_lower = body.lower() if body else ""

        # Check structured sections first
        for section in sections:
            if section.section_type == "must_fix":
                return CommentSeverity.CRITICAL
            elif section.section_type == "should_fix":
                return CommentSeverity.MAJOR
            elif section.section_type == "nice_to_have":
                return CommentSeverity.NITPICK

        # Keyword-based detection
        critical_keywords = [
            "critical",
            "security",
            "vulnerability",
            "data loss",
            "crash",
            "breaking change",
            "must fix",
            "blocker",
            "urgent",
            "severe",
        ]
        major_keywords = [
            "major",
            "bug",
            "error",
            "incorrect",
            "performance",
            "should fix",
            "important",
            "significant",
        ]
        nitpick_keywords = [
            "nit",
            "nitpick",
            "consider",
            "suggestion",
            "optional",
            "nice to have",
            "style",
            "minor style",
            "could",
        ]

        if any(kw in body_lower for kw in critical_keywords):
            return CommentSeverity.CRITICAL
        if any(kw in body_lower for kw in major_keywords):
            return CommentSeverity.MAJOR
        if any(kw in body_lower for kw in nitpick_keywords):
            return CommentSeverity.NITPICK

        return CommentSeverity.MINOR  # Default

    def _gh_api(self, endpoint: str) -> list | dict:
        """Call GitHub API via gh CLI.

        Args:
            endpoint: API endpoint path (e.g., repos/owner/repo/pulls/1/comments)

        Returns:
            Parsed JSON response (list or dict)
        """
        try:
            result = subprocess.run(
                ["gh", "api", endpoint, "--paginate"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                print(
                    f"Warning: GitHub API error for {endpoint}: {result.stderr}",
                    file=sys.stderr,
                )
                return []

            if not result.stdout.strip():
                return []

            return json.loads(result.stdout)
        except subprocess.TimeoutExpired:
            print(f"Warning: GitHub API timeout for {endpoint}", file=sys.stderr)
            return []
        except json.JSONDecodeError as e:
            print(f"Warning: JSON parse error for {endpoint}: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"Warning: Unexpected error for {endpoint}: {e}", file=sys.stderr)
            return []

    def _gh_cli_pr_comments(self) -> list:
        """Get PR comments via gh pr view.

        This endpoint returns PR conversation comments in a different format
        than the API endpoints.

        Returns:
            List of comment dictionaries
        """
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "view",
                    str(self.pr_number),
                    "--repo",
                    self.repo,
                    "--json",
                    "comments",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                print(f"Warning: gh pr view error: {result.stderr}", file=sys.stderr)
                return []

            if not result.stdout.strip():
                return []

            data = json.loads(result.stdout)
            return data.get("comments", [])
        except subprocess.TimeoutExpired:
            print("Warning: gh pr view timeout", file=sys.stderr)
            return []
        except json.JSONDecodeError as e:
            print(f"Warning: JSON parse error for gh pr view: {e}", file=sys.stderr)
            return []
        except Exception as e:
            print(f"Warning: Unexpected error for gh pr view: {e}", file=sys.stderr)
            return []

    # Cache methods
    def _cache_path(self) -> Path:
        """Get the cache file path for this PR."""
        safe_repo = self.repo.replace("/", "_")
        return self.cache_dir / f"pr_{safe_repo}_{self.pr_number}.json"

    def _load_cache(self) -> Optional[ModelPRData]:
        """Load PR data from cache if valid.

        Returns:
            ModelPRData if cache is valid, None otherwise
        """
        cache_file = self._cache_path()
        if not cache_file.exists():
            return None

        # Check TTL
        try:
            mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if datetime.now() - mtime > timedelta(seconds=CACHE_TTL_SECONDS):
                return None  # Cache expired

            with open(cache_file) as f:
                data = json.load(f)

            return ModelPRData.model_validate(data)
        except Exception as e:
            print(f"Warning: Cache load error: {e}", file=sys.stderr)
            return None

    def _save_cache(self, pr_data: ModelPRData) -> None:
        """Save PR data to cache.

        Args:
            pr_data: ModelPRData to cache
        """
        try:
            cache_file = self._cache_path()
            with open(cache_file, "w") as f:
                f.write(pr_data.model_dump_json(indent=2))
        except Exception as e:
            print(f"Warning: Cache save error: {e}", file=sys.stderr)


def get_repo_from_git() -> Optional[str]:
    """Get repository name from current git directory.

    Returns:
        Repository in "owner/repo" format, or None if not in a git repo
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
    except Exception:
        pass
    return None


def main():
    """CLI interface for fetching PR data."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch PR data with type safety from all 4 GitHub API endpoints"
    )
    parser.add_argument("pr_number", type=int, help="PR number")
    parser.add_argument("--repo", default=None, help="Repository (owner/repo)")
    parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    parser.add_argument(
        "--output",
        choices=["json", "summary", "claude-only"],
        default="json",
        help="Output format",
    )
    args = parser.parse_args()

    # Get repo from git if not provided
    repo = args.repo
    if not repo:
        repo = get_repo_from_git()
        if not repo:
            print(
                "Error: Could not determine repository. Use --repo flag.",
                file=sys.stderr,
            )
            sys.exit(1)

    try:
        fetcher = PRFetcher(repo, args.pr_number)
        pr_data = fetcher.fetch(use_cache=not args.no_cache)

        if args.output == "json":
            print(pr_data.model_dump_json(indent=2))
        elif args.output == "claude-only":
            # Output only Claude bot comments
            claude_comments = pr_data.get_claude_comments()
            for c in claude_comments:
                print(f"\n{'='*60}")
                print(f"Source: {c.source.value}")
                print(f"Severity: {c.severity.value}")
                print(f"Created: {c.created_at}")
                print(f"{'='*60}")
                print(c.body)
        else:
            # Print summary
            print(f"PR #{pr_data.pr_number}: {pr_data.title}")
            print(f"Repository: {pr_data.repository}")
            print(f"State: {pr_data.state}")
            print(f"Author: {pr_data.author}")
            print()
            print("=== Comment Summary ===")
            print(f"Total comments: {pr_data.total_comments}")
            print(f"Total reviews: {pr_data.total_reviews}")
            print()

            # By source
            print("By Source:")
            for source in ModelPRCommentSource:
                count = len(pr_data.get_comments_by_source(source))
                if count > 0:
                    print(f"  {source.value}: {count}")
            print()

            # Bot comments
            claude_comments = pr_data.get_claude_comments()
            bot_comments = pr_data.get_bot_comments()
            print(f"Claude bot comments: {len(claude_comments)}")
            print(f"Other bot comments: {len(bot_comments) - len(claude_comments)}")
            print()

            # By severity
            print("By Severity:")
            for severity in CommentSeverity:
                count = len(pr_data.get_by_severity(severity))
                if count > 0:
                    print(f"  {severity.value}: {count}")

            # Show Claude comments if any
            if claude_comments:
                print()
                print("=== Claude Bot Comments ===")
                for c in claude_comments:
                    print(f"\n[{c.severity.value.upper()}] ({c.source.value})")
                    # Show first 200 chars
                    preview = c.body[:200] + "..." if len(c.body) > 200 else c.body
                    print(f"  {preview}")

    except PRFetchError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
