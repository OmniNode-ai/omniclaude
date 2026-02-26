#!/usr/bin/env python3
"""gather_stats.py — GitHub statistics gatherer for the gather-github-stats omniclaude skill.

Phase 2: Core GitHub data collection layer.
  - preflight_checks(): gh auth, org reachability, git in PATH, local path
  - Cache layer: .stats_cache/ with 86400s TTL, --cached flag, 202_exhausted status
  - discover_org_repos(): list org repos, fallback to DEFAULT_PUBLIC_REPOS
  - get_merged_pr_count() / open PR count via Search API
  - get_commit_count() via Link-header parsing
  - get_code_frequency() with bounded exponential backoff (202 handling)

Phase 3: Local archive discovery + deduplication.
  - discover_git_repos(): recursive walker from --local-path with --max-depth limit
  - get_local_repo_stats(): commit count + dates via git subprocess
  - parse_numstat(): parse git log --numstat output, skipping binary file lines
  - normalize_url(): SSH <-> HTTPS normalisation, strip .git suffix
  - extract_best_remote(): prefer OmniNode-ai GitHub remote over origin
  - Deduplication: GitHub repos registered first; local repos matched by normalized URL
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_DIR_NAME = ".stats_cache"
CACHE_TTL_SECONDS = 86400  # 24 hours

DEFAULT_ORG = "OmniNode-ai"

DEFAULT_PUBLIC_REPOS = [
    "omniclaude",
    "omnibase_core",
    "omnibase_infra",
    "omnibase_spi",
    "omnidash",
    "omniintelligence",
    "omnimemory",
    "omninode_infra",
    "omniweb",
    "onex_change_control",
]

GITHUB_API_BASE = "https://api.github.com"

# Exponential backoff delays for 202 responses (seconds)
BACKOFF_DELAYS = [1, 2, 4, 8, 16, 32]

# Directories to skip during local archive scan
SKIP_DIRS = frozenset(
    [
        "node_modules",
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
        ".eggs",
        "site-packages",
    ]
)

# Timeout for git log --numstat LOC scan (seconds)
LOC_SCAN_TIMEOUT = 120


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class LocalRepoStats:
    """Statistics gathered from a local git repository."""

    path: Path
    is_bare: bool
    commit_count: int
    first_commit_date: str | None
    last_commit_date: str | None
    remote_url: str | None
    normalized_url: str | None
    is_duplicate: bool
    loc_additions: int | None
    loc_deletions: int | None
    non_github_remote: bool


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Path, key: str) -> Path:
    """Return the cache file path for a given key (sanitise slashes)."""
    safe_key = key.replace("/", "__").replace(" ", "_")
    return cache_dir / f"{safe_key}.json"


def cache_read(
    cache_dir: Path, key: str, bypass_ttl: bool = False
) -> dict[str, Any] | None:
    """Read a cached value.

    Returns the cached payload dict if valid (not expired), or None.
    When *bypass_ttl* is True the TTL check is skipped (--cached mode).
    """
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        data: dict[str, Any] = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    if not bypass_ttl:
        stored_at: float = data.get("stored_at", 0.0)
        if time.time() - stored_at > CACHE_TTL_SECONDS:
            return None  # expired

    return data.get("payload")


def cache_write(cache_dir: Path, key: str, payload: Any) -> None:
    """Persist *payload* to the cache under *key*."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, key)
    data = {"stored_at": time.time(), "payload": payload}
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# GitHub API helpers
# ---------------------------------------------------------------------------


def _gh_api(
    path: str, *, method: str = "GET"
) -> tuple[int, dict[str, Any] | list[Any], dict[str, str]]:
    """Call the GitHub REST API via `gh api`.

    Returns (status_code, body, headers_dict).
    Uses `gh api` so it inherits the authenticated token automatically.
    Raises RuntimeError on subprocess failure unrelated to HTTP status.
    """
    cmd = [
        "gh",
        "api",
        "--method",
        method,
        "--include",  # print response headers before body
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if result.returncode != 0 and result.returncode != 22:
        # returncode 22 = HTTP 4xx/5xx from gh; anything else is a tool failure
        raise RuntimeError(
            f"gh api failed (rc={result.returncode}): {result.stderr.strip()}"
        )

    raw = result.stdout
    # Split headers from body at the blank line separating them
    header_section, _, body_section = raw.partition("\r\n\r\n")
    if not _:
        header_section, _, body_section = raw.partition("\n\n")

    # Parse status code from first header line: "HTTP/2 200"
    status_code = 0
    headers: dict[str, str] = {}
    for i, line in enumerate(header_section.splitlines()):
        line = line.strip()
        if i == 0:
            m = re.search(r"(\d{3})", line)
            if m:
                status_code = int(m.group(1))
        elif ":" in line:
            k, _, v = line.partition(":")
            headers[k.strip().lower()] = v.strip()

    body: dict[str, Any] | list[Any] = {}
    try:
        body = json.loads(body_section.strip()) if body_section.strip() else {}
    except json.JSONDecodeError:
        body = {}

    return status_code, body, headers


def _gh_api_paginated(path: str, per_page: int = 100) -> list[dict[str, Any]]:
    """Fetch all pages of a GitHub list endpoint, returning combined items."""
    results: list[dict[str, Any]] = []
    page = 1
    while True:
        sep = "&" if "?" in path else "?"
        paginated_path = f"{path}{sep}per_page={per_page}&page={page}"
        status, body, _ = _gh_api(paginated_path)
        if status not in (200, 201) or not isinstance(body, list):
            break
        results.extend(body)
        if len(body) < per_page:
            break
        page += 1
    return results


# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------


def preflight_checks(org: str, local_path: str | None, local_only: bool) -> None:
    """Run preflight checks and exit with an actionable error on failure."""

    # 1. git in PATH (always required for local operations)
    if shutil.which("git") is None:
        sys.exit(
            "ERROR: 'git' not found in PATH. Install git before running this tool."
        )

    if local_only:
        # GitHub checks are skipped in local-only mode
        if local_path is not None:
            p = Path(local_path)
            if not p.exists():
                sys.exit(f"ERROR: --local-path '{local_path}' does not exist.")
            if not p.is_dir():
                sys.exit(f"ERROR: --local-path '{local_path}' is not a directory.")
            if not os.access(p, os.R_OK):
                sys.exit(f"ERROR: --local-path '{local_path}' is not readable.")
        return

    # 2. gh CLI in PATH
    if shutil.which("gh") is None:
        sys.exit(
            "ERROR: 'gh' CLI not found in PATH. Install the GitHub CLI (https://cli.github.com)."
        )

    # 3. gh auth status
    auth_result = subprocess.run(
        ["gh", "auth", "status"],
        capture_output=True,
        text=True,
        check=False,
    )
    if auth_result.returncode != 0:
        sys.exit(
            "ERROR: GitHub CLI is not authenticated.\n"
            "Run: gh auth login\n"
            f"Details: {auth_result.stderr.strip()}"
        )

    # 4. Org API reachability
    try:
        status, _body, _ = _gh_api(f"/orgs/{org}")
        if status == 404:
            sys.exit(
                f"ERROR: GitHub org '{org}' not found (404). "
                "Check the org name or your access permissions."
            )
        if status == 401:
            sys.exit(
                "ERROR: GitHub authentication failed (401). "
                "Run 'gh auth login' to refresh your credentials."
            )
        if status not in (200, 201):
            sys.exit(
                f"ERROR: GitHub org API returned unexpected status {status} for org '{org}'."
            )
    except RuntimeError as exc:
        sys.exit(f"ERROR: Could not reach GitHub org API: {exc}")

    # 5. Local path checks (when provided and not github-only)
    if local_path is not None:
        p = Path(local_path)
        if not p.exists():
            sys.exit(f"ERROR: --local-path '{local_path}' does not exist.")
        if not p.is_dir():
            sys.exit(f"ERROR: --local-path '{local_path}' is not a directory.")
        if not os.access(p, os.R_OK):
            sys.exit(f"ERROR: --local-path '{local_path}' is not readable.")


# ---------------------------------------------------------------------------
# Repo discovery (GitHub)
# ---------------------------------------------------------------------------


def discover_org_repos(
    org: str,
    include_private: bool,
    cache_dir: Path,
    bypass_ttl: bool,
) -> list[str]:
    """Return list of repo names for *org*.

    Falls back to DEFAULT_PUBLIC_REPOS if the API is unreachable or empty.
    """
    cache_key = f"repos__{org}__private={include_private}"
    cached = cache_read(cache_dir, cache_key, bypass_ttl=bypass_ttl)
    if cached is not None:
        return cached  # type: ignore[return-value]

    visibility_flag = "" if include_private else "?type=public"
    try:
        repos = _gh_api_paginated(f"/orgs/{org}/repos{visibility_flag}")
        names = [r["name"] for r in repos if isinstance(r, dict) and "name" in r]
    except RuntimeError:
        names = []

    if not names:
        print(
            f"  [warn] Could not list repos for org '{org}'; "
            "falling back to DEFAULT_PUBLIC_REPOS.",
            file=sys.stderr,
        )
        names = list(DEFAULT_PUBLIC_REPOS)

    cache_write(cache_dir, cache_key, names)
    return names


# ---------------------------------------------------------------------------
# PR counts
# ---------------------------------------------------------------------------


def get_merged_pr_count(org: str, repo: str, cache_dir: Path, bypass_ttl: bool) -> int:
    """Return the number of merged PRs for *org/repo* via the Search API."""
    cache_key = f"pr_merged__{org}__{repo}"
    cached = cache_read(cache_dir, cache_key, bypass_ttl=bypass_ttl)
    if cached is not None:
        return int(cached)  # type: ignore[call-overload, no-any-return]

    query = f"is:pr is:merged repo:{org}/{repo}"
    try:
        status, body, _ = _gh_api(f"/search/issues?q={_url_encode(query)}&per_page=1")
        if status == 200 and isinstance(body, dict):
            count: int = body.get("total_count", 0)
            cache_write(cache_dir, cache_key, count)
            return count
    except RuntimeError:
        pass
    return 0


def get_open_pr_count(org: str, repo: str, cache_dir: Path, bypass_ttl: bool) -> int:
    """Return the number of open PRs for *org/repo* via the Search API."""
    cache_key = f"pr_open__{org}__{repo}"
    cached = cache_read(cache_dir, cache_key, bypass_ttl=bypass_ttl)
    if cached is not None:
        return int(cached)  # type: ignore[call-overload, no-any-return]

    query = f"is:pr is:open repo:{org}/{repo}"
    try:
        status, body, _ = _gh_api(f"/search/issues?q={_url_encode(query)}&per_page=1")
        if status == 200 and isinstance(body, dict):
            count: int = body.get("total_count", 0)
            cache_write(cache_dir, cache_key, count)
            return count
    except RuntimeError:
        pass
    return 0


def _url_encode(s: str) -> str:
    """Minimal URL encoding for query strings (spaces → +, special chars → %xx)."""
    from urllib.parse import quote_plus  # noqa: PLC0415

    return quote_plus(s)


# ---------------------------------------------------------------------------
# Commit count (Link-header parsing)
# ---------------------------------------------------------------------------


def get_commit_count(org: str, repo: str, cache_dir: Path, bypass_ttl: bool) -> int:
    """Return total commit count for *org/repo* via Link-header pagination trick.

    Calls GET /repos/<org>/<repo>/commits?per_page=1 and extracts the `last`
    page number from the Link response header.
    """
    cache_key = f"commits__{org}__{repo}"
    cached = cache_read(cache_dir, cache_key, bypass_ttl=bypass_ttl)
    if cached is not None:
        return int(cached)  # type: ignore[call-overload, no-any-return]

    try:
        status, _, headers = _gh_api(f"/repos/{org}/{repo}/commits?per_page=1")
    except RuntimeError:
        return 0

    if status not in (200, 201):
        return 0

    link_header = headers.get("link", "")
    count = _parse_last_page_from_link(link_header)
    if count > 0:
        cache_write(cache_dir, cache_key, count)
    return count


def _parse_last_page_from_link(link_header: str) -> int:
    """Extract the `last` page number from a GitHub Link header.

    Example header value:
      <https://api.github.com/repos/foo/bar/commits?per_page=1&page=2>; rel="next",
      <https://api.github.com/repos/foo/bar/commits?per_page=1&page=1234>; rel="last"
    """
    if not link_header:
        return 1  # single page — at least 1 commit

    # Find rel="last" segment
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="last"' in part:
            m = re.search(r"[?&]page=(\d+)", part)
            if m:
                return int(m.group(1))

    return 1


# ---------------------------------------------------------------------------
# Code frequency
# ---------------------------------------------------------------------------


def get_code_frequency(
    org: str,
    repo: str,
    cache_dir: Path,
    bypass_ttl: bool,
) -> list[list[int]] | str:
    """Return code frequency weekly stats for *org/repo*.

    Returns:
      - list of [timestamp, additions, deletions] entries on success
      - "202_exhausted" string if all retries returned 202
      - empty list on other errors
    """
    cache_key = f"code_frequency__{org}__{repo}"
    cached = cache_read(cache_dir, cache_key, bypass_ttl=bypass_ttl)
    if cached is not None:
        return cached  # type: ignore[return-value]

    path = f"/repos/{org}/{repo}/stats/code_frequency"

    for delay in BACKOFF_DELAYS:
        try:
            status, body, _ = _gh_api(path)
        except RuntimeError:
            return []

        if status == 200 and isinstance(body, list):
            result: list[list[int]] = body
            cache_write(cache_dir, cache_key, result)
            return result

        if status == 202:
            # GitHub is computing stats — wait and retry
            print(
                f"  [info] /stats/code_frequency for {org}/{repo} returned 202; "
                f"retrying in {delay}s …",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue

        # Any other non-success status — bail out
        return []

    # All retries exhausted — cache and return sentinel
    print(
        f"  [warn] code_frequency for {org}/{repo}: "
        "all retries exhausted (202_exhausted).",
        file=sys.stderr,
    )
    cache_write(cache_dir, cache_key, "202_exhausted")
    return "202_exhausted"


# ---------------------------------------------------------------------------
# Phase 3: URL normalisation
# ---------------------------------------------------------------------------


def normalize_url(url: str) -> str:
    """Normalise a git remote URL to a canonical HTTPS form.

    Transformations applied (in order):
    1. Strip surrounding whitespace.
    2. Convert SSH form ``git@github.com:owner/repo`` to
       ``https://github.com/owner/repo``.
    3. Strip a trailing ``.git`` suffix (case-insensitive).
    4. Lowercase the entire result.

    Non-GitHub URLs (no ``github.com`` component) are returned lowercased
    with only the ``.git`` suffix stripped — no SSH→HTTPS rewrite is
    attempted.
    """
    url = url.strip()

    # SSH form: git@github.com:owner/repo[.git]
    ssh_match = re.match(r"git@github\.com[:/](.+)", url, re.IGNORECASE)
    if ssh_match:
        path_part = ssh_match.group(1)
        url = f"https://github.com/{path_part}"

    # Strip trailing .git (case-insensitive)
    url = re.sub(r"\.git$", "", url, flags=re.IGNORECASE)

    return url.lower()


# ---------------------------------------------------------------------------
# Phase 3: Remote extraction
# ---------------------------------------------------------------------------


def extract_best_remote(repo_path: Path) -> tuple[str | None, bool]:
    """Return (remote_url, is_non_github) for the best remote of a git repo.

    Selection priority:
    1. Any remote whose URL contains ``github.com`` and the org ``OmniNode-ai``.
    2. Any remote whose URL contains ``github.com`` (e.g. a fork origin).
    3. ``origin`` remote regardless of host.
    4. The first remote listed.

    Returns:
        (url, is_non_github) where *is_non_github* is True when the chosen
        remote's URL does not contain ``github.com``.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "-v"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None, False

    # Parse "name\turl (fetch|push)" lines; keep fetch lines only
    remotes: dict[str, str] = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or "(fetch)" not in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            name, url = parts[0], parts[1]
            remotes[name] = url

    if not remotes:
        return None, False

    # Priority 1: OmniNode-ai GitHub remote
    for name, url in remotes.items():
        if "github.com" in url.lower() and "omninode-ai" in url.lower():
            return url, False

    # Priority 2: any GitHub remote
    for name, url in remotes.items():
        if "github.com" in url.lower():
            return url, False

    # Priority 3: origin
    if "origin" in remotes:
        url = remotes["origin"]
        is_non_github = "github.com" not in url.lower()
        return url, is_non_github

    # Priority 4: first remote
    first_url = next(iter(remotes.values()))
    is_non_github = "github.com" not in first_url.lower()
    return first_url, is_non_github


# ---------------------------------------------------------------------------
# Phase 3: Bare clone detection
# ---------------------------------------------------------------------------


def _is_bare_clone(path: Path) -> bool:
    """Return True if *path* is a bare git clone.

    A bare clone has ``HEAD`` and ``config`` at the root but no working tree
    (i.e. no top-level ``.git`` directory or file).
    """
    has_head = (path / "HEAD").is_file()
    has_config = (path / "config").is_file()
    has_git_dir = (path / ".git").exists()
    return has_head and has_config and not has_git_dir


# ---------------------------------------------------------------------------
# Phase 3: Local repo discovery
# ---------------------------------------------------------------------------


def discover_git_repos(root: Path, max_depth: int) -> list[Path]:
    """Return all git repository roots found under *root* up to *max_depth*.

    Both regular clones (containing a ``.git`` entry at root) and bare clones
    (``HEAD`` + ``config`` without a ``.git`` directory) are detected.

    Directories listed in ``SKIP_DIRS`` are never descended into.
    """
    found: list[Path] = []
    _scan(root, current_depth=0, max_depth=max_depth, found=found)
    return found


def _scan(
    directory: Path, current_depth: int, max_depth: int, found: list[Path]
) -> None:
    """Recursive helper for *discover_git_repos*."""
    if current_depth > max_depth:
        return

    # Check if this directory itself is a git repo
    has_dot_git = (directory / ".git").exists()
    is_bare = _is_bare_clone(directory)

    if has_dot_git or is_bare:
        found.append(directory)
        # Do not descend into a repo's own subtree (avoids sub-module confusion
        # and worktree directories that contain their own .git files)
        return

    # Descend into subdirectories, skipping excluded names
    try:
        entries = list(directory.iterdir())
    except PermissionError:
        return

    for entry in entries:
        if not entry.is_dir():
            continue
        if entry.name in SKIP_DIRS:
            continue
        # Skip hidden directories (e.g. .cache, .local) except at root depth
        if entry.name.startswith(".") and current_depth > 0:
            continue
        _scan(entry, current_depth + 1, max_depth, found)


# ---------------------------------------------------------------------------
# Phase 3: numstat parsing
# ---------------------------------------------------------------------------


def parse_numstat(numstat_output: str) -> tuple[int, int]:
    """Parse ``git log --numstat`` output and return (total_additions, total_deletions).

    Each line is ``<additions>\\t<deletions>\\t<filename>``.
    Binary file lines have ``-`` in both numeric columns and must be skipped —
    they are NOT treated as 0 additions/deletions.
    """
    total_add = 0
    total_del = 0
    for line in numstat_output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        add_str, del_str = parts[0], parts[1]
        # Binary files use "-" in both columns — skip them
        if add_str == "-" or del_str == "-":
            continue
        try:
            total_add += int(add_str)
            total_del += int(del_str)
        except ValueError:
            continue
    return total_add, total_del


# ---------------------------------------------------------------------------
# Phase 3: Local repo stats collection
# ---------------------------------------------------------------------------


def get_local_repo_stats(
    repo_path: Path,
    include_loc: bool,
) -> dict[str, Any]:
    """Collect statistics from a local git repository.

    Returns a dict with keys:
      - commit_count (int)
      - first_commit_date (str | None)   ISO-8601 datetime string
      - last_commit_date (str | None)    ISO-8601 datetime string
      - loc_additions (int | None)       None unless include_loc=True
      - loc_deletions (int | None)       None unless include_loc=True
    """
    stats: dict[str, Any] = {
        "commit_count": 0,
        "first_commit_date": None,
        "last_commit_date": None,
        "loc_additions": None,
        "loc_deletions": None,
    }

    git_dir_args = ["-C", str(repo_path)]

    # Commit count
    count_result = subprocess.run(
        ["git", *git_dir_args, "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if count_result.returncode == 0:
        try:
            stats["commit_count"] = int(count_result.stdout.strip())
        except ValueError:
            pass

    # First commit date (oldest commit)
    first_result = subprocess.run(
        ["git", *git_dir_args, "log", "--reverse", "--format=%ci", "--", "."],
        capture_output=True,
        text=True,
        check=False,
    )
    if first_result.returncode == 0 and first_result.stdout.strip():
        stats["first_commit_date"] = first_result.stdout.strip().splitlines()[0].strip()

    # Last commit date
    last_result = subprocess.run(
        ["git", *git_dir_args, "log", "-1", "--format=%ci"],
        capture_output=True,
        text=True,
        check=False,
    )
    if last_result.returncode == 0 and last_result.stdout.strip():
        stats["last_commit_date"] = last_result.stdout.strip()

    # Optional LOC scan
    if include_loc:
        try:
            loc_result = subprocess.run(
                ["git", *git_dir_args, "log", "--numstat", "--format="],
                capture_output=True,
                text=True,
                check=False,
                timeout=LOC_SCAN_TIMEOUT,
            )
            if loc_result.returncode == 0:
                add, del_ = parse_numstat(loc_result.stdout)
                stats["loc_additions"] = add
                stats["loc_deletions"] = del_
        except subprocess.TimeoutExpired:
            print(
                f"  [warn] LOC scan timed out for {repo_path} "
                f"(>{LOC_SCAN_TIMEOUT}s); skipping.",
                file=sys.stderr,
            )

    return stats


# ---------------------------------------------------------------------------
# Phase 3: Full local scan
# ---------------------------------------------------------------------------


@dataclass
class LocalScanResult:
    """Aggregated result of a local archive scan."""

    repos: list[LocalRepoStats] = field(default_factory=list)
    duplicate_count: int = 0
    non_github_count: int = 0
    total_local_commits: int = 0


def scan_local_archive(
    local_path: Path,
    max_depth: int,
    include_loc: bool,
    seen_remotes: set[str],
) -> LocalScanResult:
    """Walk *local_path* and collect stats for every git repo found.

    *seen_remotes* is pre-populated with normalised URLs of GitHub repos so
    that local clones of those repos are correctly identified as duplicates and
    excluded from totals.

    Returns a :class:`LocalScanResult` with per-repo stats and aggregate counts.
    """
    result = LocalScanResult()

    print(f"Scanning local archive under '{local_path}' …", file=sys.stderr)
    repo_paths = discover_git_repos(local_path, max_depth)
    print(f"  Found {len(repo_paths)} local git repositories.", file=sys.stderr)

    for repo_path in sorted(repo_paths):
        is_bare = _is_bare_clone(repo_path)
        remote_url, is_non_github = extract_best_remote(repo_path)
        normalized = normalize_url(remote_url) if remote_url else None

        # Deduplication: is this a local clone of an already-counted GitHub repo?
        is_duplicate = bool(normalized and normalized in seen_remotes)

        if is_non_github and remote_url:
            result.non_github_count += 1
            print(
                f"  [info] Non-GitHub remote detected for {repo_path}: {remote_url}",
                file=sys.stderr,
            )

        # Collect git stats (always — even for duplicates, for reporting)
        raw_stats = get_local_repo_stats(repo_path, include_loc=include_loc)

        local_stats = LocalRepoStats(
            path=repo_path,
            is_bare=is_bare,
            commit_count=raw_stats["commit_count"],
            first_commit_date=raw_stats["first_commit_date"],
            last_commit_date=raw_stats["last_commit_date"],
            remote_url=remote_url,
            normalized_url=normalized,
            is_duplicate=is_duplicate,
            loc_additions=raw_stats["loc_additions"],
            loc_deletions=raw_stats["loc_deletions"],
            non_github_remote=is_non_github,
        )
        result.repos.append(local_stats)

        if is_duplicate:
            result.duplicate_count += 1
        else:
            result.total_local_commits += raw_stats["commit_count"]
            # Register this local repo's URL so subsequent entries dedupe against it
            if normalized:
                seen_remotes.add(normalized)

    return result


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _freq_to_str(freq: list[list[int]] | str) -> tuple[str, str]:
    """Return (additions_str, deletions_str) from a code frequency result."""
    if isinstance(freq, list) and freq:
        total_add = sum(w[1] for w in freq if len(w) > 1)
        total_del = abs(sum(w[2] for w in freq if len(w) > 2))
        return f"+{total_add:,}", f"-{total_del:,}"
    if freq == "202_exhausted":
        return "_(computing)_", "_(computing)_"
    return "_(unavailable)_", "_(unavailable)_"


def generate_report(
    org: str,
    repos: list[str],
    cache_dir: Path,
    bypass_ttl: bool,
    local_result: LocalScanResult | None = None,
) -> str:
    """Collect stats for all repos and return a Markdown report string."""
    lines: list[str] = []
    lines.append(f"# GitHub Stats — {org}\n")
    lines.append(f"_Generated at {_now_iso()}_\n")
    lines.append("")

    total_merged = 0
    total_open = 0
    total_commits = 0

    lines.append("## Per-Repository Summary (GitHub)\n")
    lines.append("| Repo | Merged PRs | Open PRs | Commits | Additions | Deletions |")
    lines.append("|------|-----------|---------|---------|-----------|-----------|")

    for repo in sorted(repos):
        merged = get_merged_pr_count(org, repo, cache_dir, bypass_ttl)
        open_prs = get_open_pr_count(org, repo, cache_dir, bypass_ttl)
        commits = get_commit_count(org, repo, cache_dir, bypass_ttl)
        freq = get_code_frequency(org, repo, cache_dir, bypass_ttl)

        total_merged += merged
        total_open += open_prs
        total_commits += commits

        add_str, del_str = _freq_to_str(freq)
        freq_str = f"{add_str} / {del_str}"

        lines.append(
            f"| {repo} | {merged:,} | {open_prs:,} | {commits:,} | {freq_str} |"
        )

    lines.append("")
    lines.append("## Totals (GitHub)\n")
    lines.append(f"- **Repos scanned**: {len(repos)}")
    lines.append(f"- **Total merged PRs**: {total_merged:,}")
    lines.append(f"- **Total open PRs**: {total_open:,}")
    lines.append(f"- **Total commits**: {total_commits:,}")
    lines.append("")

    # Local archive section
    if local_result is not None:
        lines.append("## Local Archive\n")
        unique_local = [r for r in local_result.repos if not r.is_duplicate]
        dup_repos = [r for r in local_result.repos if r.is_duplicate]

        lines.append(f"- **Local repos discovered**: {len(local_result.repos)}")
        lines.append(f"- **Unique (not in GitHub dataset)**: {len(unique_local)}")
        lines.append(
            f"- **Duplicates (skipped in totals)**: {local_result.duplicate_count}"
        )
        lines.append(f"- **Non-GitHub remotes**: {local_result.non_github_count}")
        lines.append(
            f"- **Total local commits (unique only)**: {local_result.total_local_commits:,}"
        )
        lines.append("")

        if unique_local:
            lines.append("### Unique Local Repositories\n")
            lines.append(
                "| Path | Bare | Commits | First Commit | Last Commit | Remote |"
            )
            lines.append(
                "|------|------|---------|-------------|------------|--------|"
            )
            for r in sorted(unique_local, key=lambda x: str(x.path)):
                bare_str = "yes" if r.is_bare else "no"
                first = r.first_commit_date or "—"
                last = r.last_commit_date or "—"
                remote = r.remote_url or "_(no remote)_"
                # Truncate long paths for readability
                path_str = str(r.path)
                lines.append(
                    f"| `{path_str}` | {bare_str} | {r.commit_count:,} "
                    f"| {first} | {last} | {remote} |"
                )
            lines.append("")

        if dup_repos:
            lines.append("### Deduplication Report\n")
            lines.append(
                "The following local repos were matched to GitHub repos and excluded from totals:\n"
            )
            for r in sorted(dup_repos, key=lambda x: str(x.path)):
                lines.append(f"- `{r.path}` → `{r.normalized_url}`")
            lines.append("")

        if local_result.non_github_count > 0:
            non_gh = [r for r in local_result.repos if r.non_github_remote]
            lines.append("### Non-GitHub Remotes\n")
            lines.append(
                "The following repos have non-GitHub remotes and are included in unique totals:\n"
            )
            for r in sorted(non_gh, key=lambda x: str(x.path)):
                lines.append(f"- `{r.path}` → `{r.remote_url}`")
            lines.append("")

    return "\n".join(lines)


def _now_iso() -> str:
    from datetime import UTC, datetime  # noqa: PLC0415

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gather_stats.py",
        description=(
            "Gather GitHub repository statistics — PR counts, commit velocity, "
            "contributor activity, LOC metrics — from the GitHub API and/or a "
            "local archive scan."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python gather_stats.py                              # Full report (GitHub + local)
  python gather_stats.py --github-only               # GitHub API only
  python gather_stats.py --local-only --local-path . # Local archive only
  python gather_stats.py --cached                    # Re-use cached results
  python gather_stats.py --output /tmp/report.md     # Custom output path
  python gather_stats.py --include-local-loc         # Enable LOC scan (slow)
  python gather_stats.py --include-private           # Include private repos
""",
    )

    # Scope flags
    scope = parser.add_argument_group("scope flags")
    scope_exclusive = scope.add_mutually_exclusive_group()
    scope_exclusive.add_argument(
        "--github-only",
        action="store_true",
        default=False,
        help="Skip local archive scan; query GitHub API only.",
    )
    scope_exclusive.add_argument(
        "--local-only",
        action="store_true",
        default=False,
        help="Skip GitHub API calls; scan local archive only.",
    )

    # Cache control
    parser.add_argument(
        "--cached",
        action="store_true",
        default=False,
        help="Use cached results (bypass TTL); skip live API/FS queries.",
    )

    # Output
    parser.add_argument(
        "--output",
        metavar="PATH",
        default="./stats_output.md",
        help="Output file path for the generated stats report (default: ./stats_output.md).",
    )

    # Local scan options
    local = parser.add_argument_group("local scan options")
    local.add_argument(
        "--local-path",
        metavar="PATH",
        default=".",
        help="Root path for local archive scan (default: current working directory).",
    )
    local.add_argument(
        "--max-depth",
        metavar="N",
        type=int,
        default=3,
        help="Maximum recursion depth for local archive scan (default: 3).",
    )
    local.add_argument(
        "--include-local-loc",
        action="store_true",
        default=False,
        help="Enable lines-of-code scan on local repos (can be slow for large trees).",
    )

    # GitHub options
    github = parser.add_argument_group("github options")
    github.add_argument(
        "--include-private",
        action="store_true",
        default=False,
        help="Include private GitHub repositories in API results.",
    )

    # Org override (for testing / alternate orgs)
    parser.add_argument(
        "--org",
        metavar="ORG",
        default=DEFAULT_ORG,
        help=f"GitHub organisation name (default: {DEFAULT_ORG}).",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Resolve paths
    output_path = Path(args.output)
    cache_dir = output_path.parent / CACHE_DIR_NAME

    org: str = args.org
    local_path: str | None = args.local_path if not args.github_only else None

    # Preflight checks
    preflight_checks(org, local_path, local_only=args.local_only)

    # seen_remotes: normalised GitHub repo URLs registered from the GitHub dataset.
    # Local repos whose normalised remote URL matches an entry here are duplicates.
    seen_remotes: set[str] = set()

    github_repos: list[str] = []
    local_result: LocalScanResult | None = None

    if not args.local_only:
        # GitHub data collection
        print(f"Discovering repos in org '{org}' …", file=sys.stderr)
        github_repos = discover_org_repos(
            org,
            include_private=args.include_private,
            cache_dir=cache_dir,
            bypass_ttl=args.cached,
        )
        print(f"  Found {len(github_repos)} repos.", file=sys.stderr)

        # Register GitHub repo URLs into seen_remotes for deduplication
        for repo_name in github_repos:
            canonical = normalize_url(f"https://github.com/{org}/{repo_name}")
            seen_remotes.add(canonical)

    if not args.github_only and local_path is not None:
        # Local archive scan
        local_result = scan_local_archive(
            local_path=Path(local_path),
            max_depth=args.max_depth,
            include_loc=args.include_local_loc,
            seen_remotes=seen_remotes,
        )

    if args.local_only:
        # Local-only report: no GitHub API calls, only local archive section
        report = _generate_local_only_report(org, local_result)
    else:
        # Full or GitHub-only report
        print("Collecting GitHub stats …", file=sys.stderr)
        report = generate_report(
            org,
            github_repos,
            cache_dir,
            bypass_ttl=args.cached,
            local_result=local_result,
        )

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    print(f"Report written to: {output_path.resolve()}", file=sys.stderr)

    return 0


def _generate_local_only_report(org: str, local_result: LocalScanResult | None) -> str:
    """Generate a report containing only local archive stats (no GitHub section)."""
    lines: list[str] = []
    lines.append(f"# Local Archive Stats — {org}\n")
    lines.append(f"_Generated at {_now_iso()}_\n")
    lines.append("")

    if local_result is None or not local_result.repos:
        lines.append("_No local git repositories found._")
        return "\n".join(lines)

    lines.append("## Summary\n")
    lines.append(f"- **Local repos discovered**: {len(local_result.repos)}")
    lines.append(f"- **Total commits**: {local_result.total_local_commits:,}")
    lines.append(f"- **Non-GitHub remotes**: {local_result.non_github_count}")
    lines.append("")

    lines.append("## Repositories\n")
    lines.append("| Path | Bare | Commits | First Commit | Last Commit | Remote |")
    lines.append("|------|------|---------|-------------|------------|--------|")
    for r in sorted(local_result.repos, key=lambda x: str(x.path)):
        bare_str = "yes" if r.is_bare else "no"
        first = r.first_commit_date or "—"
        last = r.last_commit_date or "—"
        remote = r.remote_url or "_(no remote)_"
        lines.append(
            f"| `{r.path}` | {bare_str} | {r.commit_count:,} "
            f"| {first} | {last} | {remote} |"
        )
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
