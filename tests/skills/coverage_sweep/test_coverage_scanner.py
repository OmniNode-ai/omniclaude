# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for CoverageScanner."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from omniclaude.coverage.models import (
    EnumCoverageGapPriority,
    ModelCoverageCache,
    ModelCoverageScanResult,
)
from omniclaude.coverage.scanner import CoverageScanner


def _make_coverage_json(
    files: dict[str, dict[str, object]], totals: dict[str, object] | None = None
) -> str:
    """Build a pytest-cov JSON report string."""
    if totals is None:
        totals = {"percent_covered": 50.0}
    return json.dumps({"files": files, "totals": totals})


@pytest.mark.unit
class TestCoverageScannerParsing:
    """Test coverage JSON parsing logic."""

    def test_parse_identifies_zero_coverage(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/zero_mod.py": {
                        "summary": {
                            "percent_covered": 0.0,
                            "num_statements": 20,
                            "covered_lines": 0,
                            "missing_lines": 20,
                        }
                    },
                    "src/myrepo/ok_mod.py": {
                        "summary": {
                            "percent_covered": 80.0,
                            "num_statements": 50,
                            "covered_lines": 40,
                            "missing_lines": 10,
                        }
                    },
                },
                {"percent_covered": 40.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert result.repo == "myrepo"
        assert result.modules_zero_coverage == 1
        assert result.modules_below_target == 1
        assert len(result.gaps) == 1
        assert result.gaps[0].priority == EnumCoverageGapPriority.ZERO_COVERAGE
        assert result.gaps[0].coverage_pct == 0.0

    def test_parse_identifies_below_target(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/partial_mod.py": {
                        "summary": {
                            "percent_covered": 30.0,
                            "num_statements": 40,
                            "covered_lines": 12,
                            "missing_lines": 28,
                        }
                    },
                },
                {"percent_covered": 30.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert len(result.gaps) == 1
        assert result.gaps[0].priority == EnumCoverageGapPriority.BELOW_TARGET
        assert result.gaps[0].coverage_pct == 30.0

    def test_parse_skips_tiny_modules(self, tmp_path: Path) -> None:
        """Modules with fewer than 3 statements are skipped."""
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/__init__.py": {
                        "summary": {
                            "percent_covered": 0.0,
                            "num_statements": 2,
                            "covered_lines": 0,
                            "missing_lines": 2,
                        }
                    },
                },
                {"percent_covered": 0.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert len(result.gaps) == 0
        assert result.total_modules == 0  # Tiny modules subtracted

    def test_parse_no_gaps_above_target(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/good_mod.py": {
                        "summary": {
                            "percent_covered": 90.0,
                            "num_statements": 100,
                            "covered_lines": 90,
                            "missing_lines": 10,
                        }
                    },
                },
                {"percent_covered": 90.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert len(result.gaps) == 0
        assert result.modules_below_target == 0

    def test_parse_sorts_by_priority(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/low.py": {
                        "summary": {
                            "percent_covered": 30.0,
                            "num_statements": 20,
                            "covered_lines": 6,
                            "missing_lines": 14,
                        }
                    },
                    "src/myrepo/zero.py": {
                        "summary": {
                            "percent_covered": 0.0,
                            "num_statements": 20,
                            "covered_lines": 0,
                            "missing_lines": 20,
                        }
                    },
                },
                {"percent_covered": 15.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert len(result.gaps) == 2
        assert result.gaps[0].priority == EnumCoverageGapPriority.ZERO_COVERAGE
        assert result.gaps[1].priority == EnumCoverageGapPriority.BELOW_TARGET

    def test_parse_malformed_json(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text("not valid json {{{")

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert result.scan_error is not None
        assert "Failed to parse" in result.scan_error


@pytest.mark.unit
class TestCoverageScannerRepoScan:
    """Test repo scanning with subprocess mocking."""

    def test_scan_repo_not_found(self, tmp_path: Path) -> None:
        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)
        result = scanner.scan_repo("nonexistent_repo")

        assert result.scan_error is not None
        assert "not found" in result.scan_error

    def test_scan_repo_uses_cache_when_fresh(self, tmp_path: Path) -> None:
        """If cache is fresh, scan_repo should return cached result without running pytest."""
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        (repo_dir / "src").mkdir()

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cached_result = ModelCoverageScanResult(
            repo="myrepo",
            repo_path=str(repo_dir),
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=60.0,
            target_pct=50.0,
        )
        cache_entry = ModelCoverageCache(
            repo="myrepo",
            scanned_at_unix=time.time(),  # Fresh
            result=cached_result,
        )
        (cache_dir / "myrepo.json").write_text(cache_entry.model_dump_json())

        scanner = CoverageScanner(
            omni_home=tmp_path, target_pct=50.0, cache_dir=cache_dir
        )

        with patch("subprocess.run") as mock_run:
            result = scanner.scan_repo("myrepo")
            mock_run.assert_not_called()

        assert result.total_modules == 5
        assert result.repo_average_pct == 60.0

    def test_scan_repo_ignores_expired_cache(self, tmp_path: Path) -> None:
        """If cache is expired, scan_repo should run pytest."""
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        (repo_dir / "src").mkdir()

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        cached_result = ModelCoverageScanResult(
            repo="myrepo",
            repo_path=str(repo_dir),
            total_modules=5,
            modules_below_target=2,
            modules_zero_coverage=1,
            repo_average_pct=60.0,
            target_pct=50.0,
        )
        cache_entry = ModelCoverageCache(
            repo="myrepo",
            scanned_at_unix=time.time() - 7200,  # 2 hours old = expired
            result=cached_result,
        )
        (cache_dir / "myrepo.json").write_text(cache_entry.model_dump_json())

        scanner = CoverageScanner(
            omni_home=tmp_path, target_pct=50.0, cache_dir=cache_dir
        )

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stderr = ""

        # Write a coverage JSON for the scanner to find
        cov_json_path = repo_dir / ".coverage_report.json"
        cov_json_path.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/mod.py": {
                        "summary": {
                            "percent_covered": 75.0,
                            "num_statements": 20,
                            "covered_lines": 15,
                            "missing_lines": 5,
                        }
                    },
                },
                {"percent_covered": 75.0},
            )
        )

        with patch("subprocess.run", return_value=mock_proc):
            result = scanner.scan_repo("myrepo")

        # Should have re-scanned (different from cached value)
        assert result.repo_average_pct == 75.0

    def test_scan_repo_timeout(self, tmp_path: Path) -> None:
        import subprocess as sp

        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        (repo_dir / "src").mkdir()

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)

        with patch(
            "subprocess.run", side_effect=sp.TimeoutExpired(cmd="pytest", timeout=300)
        ):
            result = scanner.scan_repo("myrepo")

        assert result.scan_error is not None
        assert "timed out" in result.scan_error

    def test_scan_repo_uv_not_found(self, tmp_path: Path) -> None:
        repo_dir = tmp_path / "myrepo"
        repo_dir.mkdir()
        (repo_dir / "src").mkdir()

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)

        with patch("subprocess.run", side_effect=FileNotFoundError("uv")):
            result = scanner.scan_repo("myrepo")

        assert result.scan_error is not None
        assert "uv not found" in result.scan_error


@pytest.mark.unit
class TestCoverageScannerCache:
    """Test cache save/load."""

    def test_save_and_load_cache(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        scanner = CoverageScanner(
            omni_home=tmp_path, target_pct=50.0, cache_dir=cache_dir
        )

        result = ModelCoverageScanResult(
            repo="testrepo",
            repo_path="/tmp/testrepo",
            total_modules=3,
            modules_below_target=1,
            modules_zero_coverage=0,
            repo_average_pct=72.0,
            target_pct=50.0,
        )

        scanner._save_cache("testrepo", result)

        loaded = scanner._load_cache("testrepo")
        assert loaded is not None
        assert loaded.repo == "testrepo"
        assert loaded.result.repo_average_pct == 72.0
        assert loaded.is_expired(ttl_seconds=3600.0) is False

    def test_load_cache_missing(self, tmp_path: Path) -> None:
        scanner = CoverageScanner(
            omni_home=tmp_path, target_pct=50.0, cache_dir=tmp_path / "cache"
        )
        assert scanner._load_cache("nonexistent") is None

    def test_load_cache_corrupted(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "bad.json").write_text("corrupt data")

        scanner = CoverageScanner(
            omni_home=tmp_path, target_pct=50.0, cache_dir=cache_dir
        )
        assert scanner._load_cache("bad") is None


@pytest.mark.unit
class TestCoverageScannerRecentlyChanged:
    """Test recently-changed file detection."""

    def test_recently_changed_marks_gaps(self, tmp_path: Path) -> None:
        cov_json = tmp_path / "cov.json"
        cov_json.write_text(
            _make_coverage_json(
                {
                    "src/myrepo/changed.py": {
                        "summary": {
                            "percent_covered": 20.0,
                            "num_statements": 30,
                            "covered_lines": 6,
                            "missing_lines": 24,
                        }
                    },
                },
                {"percent_covered": 20.0},
            )
        )

        scanner = CoverageScanner(omni_home=tmp_path, target_pct=50.0)

        # Mock git log to report the file as recently changed
        with patch.object(
            scanner,
            "_get_recently_changed_files",
            return_value={"src/myrepo/changed.py"},
        ):
            result = scanner._parse_coverage_json("myrepo", str(tmp_path), cov_json)

        assert len(result.gaps) == 1
        assert result.gaps[0].priority == EnumCoverageGapPriority.RECENTLY_CHANGED
        assert result.gaps[0].recently_changed is True
