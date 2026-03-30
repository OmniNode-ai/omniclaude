# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Coverage scanner: runs pytest --cov per repo, parses JSON output, identifies gaps."""

from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

from omniclaude.coverage.models import (
    EnumCoverageGapPriority,
    ModelCoverageCache,
    ModelCoverageGap,
    ModelCoverageScanResult,
)

logger = logging.getLogger(__name__)

# Repos to scan by default (Python repos with src/ layout)
DEFAULT_REPOS: list[str] = [
    "omniclaude",
    "omnibase_core",
    "omnibase_infra",
    "omnibase_spi",
    "omniintelligence",
    "omnimemory",
    "onex_change_control",
    "omnibase_compat",
]

# Default coverage target per repo (can be overridden)
DEFAULT_TARGET_PCT: float = 50.0

# Cache TTL in seconds (1 hour)
CACHE_TTL_SECONDS: float = 3600.0

# Days to look back for recent changes
RECENT_CHANGE_DAYS: int = 14


class CoverageScanner:
    """Scan repositories for test coverage gaps.

    Runs `uv run pytest --cov` per repo, parses the JSON coverage report,
    and identifies modules below the target threshold.
    """

    def __init__(
        self,
        *,
        omni_home: Path,
        target_pct: float = DEFAULT_TARGET_PCT,
        cache_dir: Path | None = None,
        cache_ttl: float = CACHE_TTL_SECONDS,
    ) -> None:
        self._omni_home = omni_home
        self._target_pct = target_pct
        self._cache_dir = cache_dir or (omni_home / ".onex_state" / "coverage_cache")
        self._cache_ttl = cache_ttl

    def scan_repo(self, repo: str) -> ModelCoverageScanResult:
        """Scan a single repo for coverage gaps.

        First checks the cache. If the cache is fresh (< TTL), returns cached result.
        Otherwise runs pytest --cov and parses the output.
        """
        cached = self._load_cache(repo)
        if cached is not None and not cached.is_expired(self._cache_ttl):
            logger.info(
                "Using cached coverage for %s (age: %.0fs)",
                repo,
                time.time() - cached.scanned_at_unix,
            )
            return cached.result

        repo_path = self._omni_home / repo
        if not repo_path.is_dir():
            return ModelCoverageScanResult(
                repo=repo,
                repo_path=str(repo_path),
                total_modules=0,
                modules_below_target=0,
                modules_zero_coverage=0,
                repo_average_pct=0.0,
                target_pct=self._target_pct,
                scan_error=f"Repository directory not found: {repo_path}",
            )

        # Determine src dir
        src_dir = repo_path / "src"
        if not src_dir.is_dir():
            src_dir = repo_path

        cov_json_path = repo_path / ".coverage_report.json"

        try:
            result = subprocess.run(
                [
                    "uv",
                    "run",
                    "pytest",
                    f"--cov={src_dir}",
                    "--cov-report",
                    f"json:{cov_json_path}",
                    "-q",
                    "--no-header",
                    "-x",
                    "--tb=no",
                ],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ModelCoverageScanResult(
                repo=repo,
                repo_path=str(repo_path),
                total_modules=0,
                modules_below_target=0,
                modules_zero_coverage=0,
                repo_average_pct=0.0,
                target_pct=self._target_pct,
                scan_error="pytest timed out after 300s",
            )
        except FileNotFoundError:
            return ModelCoverageScanResult(
                repo=repo,
                repo_path=str(repo_path),
                total_modules=0,
                modules_below_target=0,
                modules_zero_coverage=0,
                repo_average_pct=0.0,
                target_pct=self._target_pct,
                scan_error="uv not found on PATH",
            )

        if not cov_json_path.exists():
            return ModelCoverageScanResult(
                repo=repo,
                repo_path=str(repo_path),
                total_modules=0,
                modules_below_target=0,
                modules_zero_coverage=0,
                repo_average_pct=0.0,
                target_pct=self._target_pct,
                scan_error=f"Coverage report not generated. pytest exit={result.returncode}. stderr={result.stderr[:500]}",
            )

        scan_result = self._parse_coverage_json(repo, str(repo_path), cov_json_path)

        # Clean up temp file
        cov_json_path.unlink(missing_ok=True)

        # Save to cache
        self._save_cache(repo, scan_result)

        return scan_result

    def scan_repos(
        self, repos: list[str] | None = None
    ) -> list[ModelCoverageScanResult]:
        """Scan multiple repos for coverage gaps."""
        target_repos = repos or DEFAULT_REPOS
        results: list[ModelCoverageScanResult] = []
        for repo in target_repos:
            logger.info("Scanning coverage for %s...", repo)
            result = self.scan_repo(repo)
            results.append(result)
        return results

    def _parse_coverage_json(
        self,
        repo: str,
        repo_path: str,
        json_path: Path,
    ) -> ModelCoverageScanResult:
        """Parse pytest-cov JSON output into structured gaps."""
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            return ModelCoverageScanResult(
                repo=repo,
                repo_path=repo_path,
                total_modules=0,
                modules_below_target=0,
                modules_zero_coverage=0,
                repo_average_pct=0.0,
                target_pct=self._target_pct,
                scan_error=f"Failed to parse coverage JSON: {e}",
            )

        files = data.get("files", {})
        totals = data.get("totals", {})

        recently_changed = self._get_recently_changed_files(Path(repo_path))

        gaps: list[ModelCoverageGap] = []
        total_modules = len(files)
        zero_count = 0
        below_count = 0

        for file_path, file_data in files.items():
            summary = file_data.get("summary", {})
            pct = summary.get("percent_covered", 0.0)
            num_statements = summary.get("num_statements", 0)
            covered = summary.get("covered_lines", 0)
            missing = summary.get("missing_lines", 0)

            # Skip __init__.py and tiny modules
            if num_statements < 3:
                total_modules -= 1
                continue

            is_recently_changed = file_path in recently_changed
            is_zero = pct == 0.0
            is_below_target = pct < self._target_pct

            if is_zero:
                zero_count += 1
                priority = EnumCoverageGapPriority.ZERO_COVERAGE
            elif is_recently_changed and is_below_target:
                priority = EnumCoverageGapPriority.RECENTLY_CHANGED
            elif is_below_target:
                priority = EnumCoverageGapPriority.BELOW_TARGET
            else:
                continue

            if is_below_target:
                below_count += 1

            gaps.append(
                ModelCoverageGap(
                    repo=repo,
                    module_path=file_path,
                    coverage_pct=round(pct, 1),
                    total_statements=num_statements,
                    covered_statements=covered,
                    missing_statements=missing,
                    priority=priority,
                    recently_changed=is_recently_changed,
                )
            )

        # Sort: zero coverage first, then recently changed, then by coverage ascending
        priority_order = {
            EnumCoverageGapPriority.ZERO_COVERAGE: 0,
            EnumCoverageGapPriority.RECENTLY_CHANGED: 1,
            EnumCoverageGapPriority.BELOW_TARGET: 2,
        }
        gaps.sort(key=lambda g: (priority_order.get(g.priority, 99), g.coverage_pct))

        repo_avg = totals.get("percent_covered", 0.0)

        return ModelCoverageScanResult(
            repo=repo,
            repo_path=repo_path,
            total_modules=total_modules,
            modules_below_target=below_count,
            modules_zero_coverage=zero_count,
            repo_average_pct=round(repo_avg, 1),
            target_pct=self._target_pct,
            gaps=gaps,
        )

    def _get_recently_changed_files(self, repo_path: Path) -> set[str]:
        """Get files changed in the last RECENT_CHANGE_DAYS via git log."""
        try:
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"--since={RECENT_CHANGE_DAYS} days ago",
                    "--name-only",
                    "--pretty=format:",
                    "--diff-filter=AM",
                    "--",
                    "src/",
                ],
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode != 0:
                return set()
            return {line.strip() for line in result.stdout.splitlines() if line.strip()}
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return set()

    def _cache_path_for(self, repo: str) -> Path:
        """Return the cache file path for a repo."""
        return self._cache_dir / f"{repo}.json"

    def _load_cache(self, repo: str) -> ModelCoverageCache | None:
        """Load cached scan result for a repo."""
        path = self._cache_path_for(repo)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return ModelCoverageCache.model_validate(data)
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def _save_cache(self, repo: str, result: ModelCoverageScanResult) -> None:
        """Save scan result to cache."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path_for(repo)
        cache = ModelCoverageCache(
            repo=repo,
            scanned_at_unix=time.time(),
            result=result,
            cache_path=str(path),
        )
        path.write_text(cache.model_dump_json(indent=2))
