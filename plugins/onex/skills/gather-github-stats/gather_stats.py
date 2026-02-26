#!/usr/bin/env python3
"""gather_stats.py — GitHub statistics gatherer for the gather-github-stats omniclaude skill.

Phase 2: Core GitHub data collection layer.
  - preflight_checks(): gh auth, org reachability, git in PATH, local path
  - Cache layer: .stats_cache/ with 86400s TTL, --cached flag, 202_exhausted status
  - discover_org_repos(): list org repos, fallback to DEFAULT_PUBLIC_REPOS
  - get_merged_pr_count() / open PR count via Search API
  - get_commit_count() via Link-header parsing
  - get_code_frequency() with bounded exponential backoff (202 handling)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
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
            if not os.access(p, os.R_OK):  # type: ignore[attr-defined]
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
        import os  # noqa: PLC0415

        p = Path(local_path)
        if not p.exists():
            sys.exit(f"ERROR: --local-path '{local_path}' does not exist.")
        if not p.is_dir():
            sys.exit(f"ERROR: --local-path '{local_path}' is not a directory.")
        if not os.access(p, os.R_OK):
            sys.exit(f"ERROR: --local-path '{local_path}' is not readable.")


# ---------------------------------------------------------------------------
# Repo discovery
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
        return int(cached)

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
        return int(cached)

    query = f"is:pr is:open repo:{org}/{repo}"
    try:
        status, body, _ = _gh_api(f"/search/issues?q={_url_encode(query)}&per_page=1")
        if status == 200 and isinstance(body, dict):
            count = body.get("total_count", 0)
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
        return int(cached)

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
# Report generation
# ---------------------------------------------------------------------------


def generate_report(
    org: str,
    repos: list[str],
    cache_dir: Path,
    bypass_ttl: bool,
) -> str:
    """Collect stats for all repos and return a Markdown report string."""
    lines: list[str] = []
    lines.append(f"# GitHub Stats — {org}\n")
    lines.append(f"_Generated at {_now_iso()}_\n")
    lines.append("")

    total_merged = 0
    total_open = 0
    total_commits = 0

    lines.append("## Per-Repository Summary\n")
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

        if isinstance(freq, list) and freq:
            total_add = sum(w[1] for w in freq if len(w) > 1)
            total_del = abs(sum(w[2] for w in freq if len(w) > 2))
            freq_str = f"+{total_add:,} / -{total_del:,}"
        elif freq == "202_exhausted":
            freq_str = "_(computing)_"
        else:
            freq_str = "_(unavailable)_"

        lines.append(
            f"| {repo} | {merged:,} | {open_prs:,} | {commits:,} | {freq_str} |"
        )

    lines.append("")
    lines.append("## Totals\n")
    lines.append(f"- **Repos scanned**: {len(repos)}")
    lines.append(f"- **Total merged PRs**: {total_merged:,}")
    lines.append(f"- **Total open PRs**: {total_open:,}")
    lines.append(f"- **Total commits**: {total_commits:,}")
    lines.append("")

    return "\n".join(lines)


def _now_iso() -> str:
    from datetime import datetime  # noqa: PLC0415

    return datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    # Phase 2: preflight checks
    preflight_checks(org, local_path, local_only=args.local_only)

    if args.local_only:
        print("Local-only mode: GitHub stats collection skipped.", file=sys.stderr)
        print("Phase 3 (local archive scan) not yet implemented.", file=sys.stderr)
        return 0

    # Discover repos
    print(f"Discovering repos in org '{org}' …", file=sys.stderr)
    repos = discover_org_repos(
        org,
        include_private=args.include_private,
        cache_dir=cache_dir,
        bypass_ttl=args.cached,
    )
    print(f"  Found {len(repos)} repos.", file=sys.stderr)

    # Generate report
    print("Collecting stats …", file=sys.stderr)
    report = generate_report(org, repos, cache_dir, bypass_ttl=args.cached)

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    print(f"Report written to: {output_path.resolve()}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
