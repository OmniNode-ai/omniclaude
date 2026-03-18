# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for begin-day skill (OMN-5349).

Tests cover:
- Phase 0: yesterday computation, close-day loading
- Phase 1: pull-all output parsing, infra health mocking
- Phase 3: aggregation, deduplication, severity sorting, malformed artifacts
- Phase 3: carry-forward collision, focus area scoring
- Model validation and serialization roundtrip
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# ---------------------------------------------------------------------------
# Import begin_day.py directly from skills directory
# ---------------------------------------------------------------------------

_SKILL_DIR = (
    Path(__file__).parent.parent.parent.parent / "plugins/onex/skills/_lib/begin_day"
)
_BEGIN_DAY_PATH = _SKILL_DIR / "begin_day.py"

_spec = importlib.util.spec_from_file_location("begin_day", _BEGIN_DAY_PATH)
assert _spec is not None and _spec.loader is not None
_begin_day = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_begin_day)

# Expose module-level functions for convenience
compute_yesterday = _begin_day.compute_yesterday
load_yesterday_close_day = _begin_day.load_yesterday_close_day
parse_pull_all_output = _begin_day.parse_pull_all_output
check_infra_health = _begin_day.check_infra_health
collect_probe_results = _begin_day.collect_probe_results
aggregate_findings = _begin_day.aggregate_findings
compute_focus_areas = _begin_day.compute_focus_areas
build_day_open = _begin_day.build_day_open
serialize_day_open = _begin_day.serialize_day_open
write_day_open = _begin_day.write_day_open
SEVERITY_WEIGHTS = _begin_day.SEVERITY_WEIGHTS
SCHEMA_VERSION = _begin_day.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Phase 0: Yesterday computation
# ---------------------------------------------------------------------------


class TestComputeYesterday:
    """Test yesterday date computation."""

    def test_normal_day(self) -> None:
        assert compute_yesterday("2026-03-18") == "2026-03-17"

    def test_month_boundary(self) -> None:
        assert compute_yesterday("2026-03-01") == "2026-02-28"

    def test_year_boundary(self) -> None:
        assert compute_yesterday("2026-01-01") == "2025-12-31"

    def test_leap_year_boundary(self) -> None:
        assert compute_yesterday("2024-03-01") == "2024-02-29"


# ---------------------------------------------------------------------------
# Phase 0: Close-day loading
# ---------------------------------------------------------------------------


class TestLoadYesterdayCloseDay:
    """Test loading yesterday's close-day corrections."""

    def test_no_cc_path(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = load_yesterday_close_day("2026-03-18", cc_path=None)
        assert result == []

    def test_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = load_yesterday_close_day("2026-03-18", cc_path=tmp)
        assert result == []

    def test_valid_yaml_with_corrections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            day_close_dir = Path(tmp) / "drift" / "day_close"
            day_close_dir.mkdir(parents=True)
            corrections = ["Fix env parity", "Address CI failure"]
            yaml_data = {"corrections_for_tomorrow": corrections}
            (day_close_dir / "2026-03-17.yaml").write_text(
                yaml.dump(yaml_data), encoding="utf-8"
            )
            result = load_yesterday_close_day("2026-03-18", cc_path=tmp)
        assert result == corrections

    def test_yaml_without_corrections_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            day_close_dir = Path(tmp) / "drift" / "day_close"
            day_close_dir.mkdir(parents=True)
            yaml_data = {"schema_version": "1.0.0", "date": "2026-03-17"}
            (day_close_dir / "2026-03-17.yaml").write_text(
                yaml.dump(yaml_data), encoding="utf-8"
            )
            result = load_yesterday_close_day("2026-03-18", cc_path=tmp)
        assert result == []


# ---------------------------------------------------------------------------
# Phase 1: Pull-all output parsing
# ---------------------------------------------------------------------------


class TestParsePullAllOutput:
    """Test parsing of pull-all.sh output."""

    def test_all_up_to_date(self) -> None:
        stdout = (
            "omniclaude: Already up to date.\n"
            "omnibase_core: Already up to date.\n"
        )
        entries = parse_pull_all_output(stdout)
        assert len(entries) == 2
        assert entries[0]["repo"] == "omniclaude"
        assert entries[0]["up_to_date"] is True
        assert entries[1]["repo"] == "omnibase_core"
        assert entries[1]["up_to_date"] is True

    def test_some_updated(self) -> None:
        stdout = (
            "omniclaude: Already up to date.\n"
            "omnibase_core: Updating a1b2c3d..e4f5g6h\n"
        )
        entries = parse_pull_all_output(stdout)
        assert len(entries) == 2
        assert entries[0]["up_to_date"] is True
        assert entries[1]["up_to_date"] is False
        assert entries[1]["head_sha"] == "e4f5g6h"

    def test_error_in_output(self) -> None:
        stdout = "omniclaude: error: cannot lock ref\n"
        entries = parse_pull_all_output(stdout)
        assert len(entries) == 1
        assert entries[0]["error"] is not None

    def test_empty_output(self) -> None:
        assert parse_pull_all_output("") == []
        assert parse_pull_all_output("   \n  ") == []


# ---------------------------------------------------------------------------
# Phase 1: Infra health
# ---------------------------------------------------------------------------


class TestCheckInfraHealth:
    """Test infrastructure health check with mocked subprocess/socket."""

    def test_all_healthy(self) -> None:
        with (
            patch("subprocess.run") as mock_run,
            patch.object(_begin_day, "_check_port", return_value=True),
        ):
            mock_run.return_value = type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stdout": (
                        "omnibase-infra-postgres\n"
                        "omnibase-infra-redpanda\n"
                        "omnibase-infra-valkey\n"
                    ),
                },
            )()
            results = check_infra_health()

        assert len(results) == 3
        assert all(r["running"] for r in results)
        assert all(r["port_responding"] for r in results)
        assert all(r["error"] is None for r in results)

    def test_docker_not_running(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("docker not found")
            results = check_infra_health()

        assert len(results) == 3
        assert all(not r["running"] for r in results)
        assert all(not r["port_responding"] for r in results)


# ---------------------------------------------------------------------------
# Phase 3: Collect probe results — malformed artifacts
# ---------------------------------------------------------------------------


class TestCollectProbeResults:
    """Test adversarial probe artifact validation."""

    def test_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            probe_data = {
                "probe_name": "list_prs",
                "status": "completed",
                "findings": [
                    {
                        "finding_id": "list_prs:ci:omniclaude/PR-1",
                        "severity": "high",
                        "source_probe": "list_prs",
                        "title": "CI failing",
                    }
                ],
                "finding_count": 1,
                "summary": "1 finding",
            }
            (artifact_dir / "list_prs.json").write_text(
                json.dumps(probe_data), encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)

        assert len(results) == 1
        assert results[0]["status"] == "completed"
        assert results[0]["finding_count"] == 1

    def test_malformed_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "bad_probe.json").write_text(
                "{invalid json!!!", encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)

        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert "unparseable" in results[0]["error"]
        assert len(results[0]["_synthetic_findings"]) == 1

    def test_missing_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            probe_data = {"probe_name": "gap_detect", "status": "completed"}
            (artifact_dir / "gap_detect.json").write_text(
                json.dumps(probe_data), encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)

        assert len(results) == 1
        assert results[0]["status"] == "failed"
        assert "missing" in results[0]["error"]
        assert "findings" in results[0]["error"]

    def test_duplicate_finding_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            probe_data = {
                "probe_name": "test_probe",
                "status": "completed",
                "findings": [
                    {
                        "finding_id": "test_probe:cat:same_key",
                        "severity": "high",
                        "source_probe": "test_probe",
                        "title": "First occurrence",
                    },
                    {
                        "finding_id": "test_probe:cat:same_key",
                        "severity": "medium",
                        "source_probe": "test_probe",
                        "title": "Duplicate",
                    },
                ],
            }
            (artifact_dir / "test_probe.json").write_text(
                json.dumps(probe_data), encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)
            # Dedup happens in aggregate_findings, not collect
            assert results[0]["finding_count"] == 2

    def test_unknown_severity_mapped_to_medium(self) -> None:
        """Unknown severity values are mapped to medium during aggregation."""
        findings = [
            {
                "finding_id": "p:c:k",
                "severity": "banana",
                "source_probe": "test",
                "title": "Test",
            }
        ]
        probes = [{"probe_name": "test", "findings": findings}]
        aggregated = aggregate_findings(probes, [])
        assert aggregated[0]["severity"] == "medium"

    def test_empty_artifact_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = collect_probe_results(Path(tmp))
        assert results == []

    def test_mixed_good_bad_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            # Good probe
            good = {
                "probe_name": "good_probe",
                "status": "completed",
                "findings": [],
            }
            (artifact_dir / "good_probe.json").write_text(
                json.dumps(good), encoding="utf-8"
            )
            # Bad probe
            (artifact_dir / "bad_probe.json").write_text(
                "not json", encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)

        assert len(results) == 2
        good_result = next(r for r in results if r["probe_name"] == "good_probe")
        bad_result = next(r for r in results if r["probe_name"] == "bad_probe")
        assert good_result["status"] == "completed"
        assert bad_result["status"] == "failed"

    def test_non_json_file_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            (artifact_dir / "readme.txt").write_text("Not a probe", encoding="utf-8")
            (artifact_dir / "notes.md").write_text("Notes", encoding="utf-8")
            results = collect_probe_results(artifact_dir)
        assert results == []

    def test_finding_count_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            probe_data = {
                "probe_name": "mismatch_probe",
                "status": "completed",
                "findings": [],
                "finding_count": 5,
            }
            (artifact_dir / "mismatch_probe.json").write_text(
                json.dumps(probe_data), encoding="utf-8"
            )
            results = collect_probe_results(artifact_dir)

        assert results[0]["status"] == "completed"
        assert results[0]["finding_count"] == 0  # actual length
        assert len(results[0].get("_synthetic_findings", [])) == 1
        assert "count_mismatch" in results[0]["_synthetic_findings"][0]["finding_id"]


# ---------------------------------------------------------------------------
# Phase 3: Aggregation
# ---------------------------------------------------------------------------


class TestAggregateFindings:
    """Test finding aggregation logic."""

    def test_dedup_within_probe(self) -> None:
        probes = [
            {
                "probe_name": "test",
                "findings": [
                    {
                        "finding_id": "test:cat:key1",
                        "severity": "high",
                        "title": "First",
                    },
                    {
                        "finding_id": "test:cat:key1",
                        "severity": "medium",
                        "title": "Duplicate",
                    },
                ],
            }
        ]
        results = aggregate_findings(probes, [])
        # Deduped: only one finding for key1
        matching = [f for f in results if "key1" in f.get("finding_id", "")]
        assert len(matching) == 1
        assert matching[0]["title"] == "First"

    def test_severity_sorting(self) -> None:
        probes = [
            {
                "probe_name": "test",
                "findings": [
                    {
                        "finding_id": "test:cat:low_item",
                        "severity": "low",
                        "title": "Low",
                    },
                    {
                        "finding_id": "test:cat:critical_item",
                        "severity": "critical",
                        "title": "Critical",
                    },
                    {
                        "finding_id": "test:cat:medium_item",
                        "severity": "medium",
                        "title": "Medium",
                    },
                ],
            }
        ]
        results = aggregate_findings(probes, [])
        severities = [f["severity"] for f in results]
        assert severities == ["critical", "medium", "low"]

    def test_cross_probe_same_resource_higher_severity_wins(self) -> None:
        probes = [
            {
                "probe_name": "probe_a",
                "findings": [
                    {
                        "finding_id": "probe_a:cat:shared_resource",
                        "severity": "medium",
                        "source_probe": "probe_a",
                        "title": "Medium finding",
                    }
                ],
            },
            {
                "probe_name": "probe_b",
                "findings": [
                    {
                        "finding_id": "probe_b:cat:shared_resource",
                        "severity": "critical",
                        "source_probe": "probe_b",
                        "title": "Critical finding",
                    }
                ],
            },
        ]
        results = aggregate_findings(probes, [])
        # Only one finding for shared_resource, the critical one
        matching = [
            f for f in results if "shared_resource" in f.get("finding_id", "")
        ]
        assert len(matching) == 1
        assert matching[0]["severity"] == "critical"

    def test_carryforward_correction_as_finding(self) -> None:
        corrections = ["Fix env parity for OMNIWEB_DB_URL"]
        results = aggregate_findings([], corrections)
        assert len(results) == 1
        assert results[0]["severity"] == "high"
        assert results[0]["source_probe"] == "close_day_carryforward"
        assert "close_day_carryforward:correction:" in results[0]["finding_id"]

    def test_carryforward_suppressed_by_fresh_finding(self) -> None:
        """Fresh finding for same resource suppresses carry-forward."""
        probes = [
            {
                "probe_name": "env_parity",
                "findings": [
                    {
                        "finding_id": "env_parity:missing_key:OMNIWEB_DB_URL",
                        "severity": "medium",
                        "source_probe": "env_parity",
                        "title": "Missing OMNIWEB_DB_URL",
                    }
                ],
            }
        ]
        corrections = ["Fix env parity for OMNIWEB_DB_URL"]
        results = aggregate_findings(probes, corrections)
        # Carry-forward should be suppressed — only fresh finding
        carryforward = [
            f for f in results if f.get("source_probe") == "close_day_carryforward"
        ]
        assert len(carryforward) == 0
        # Fresh finding should remain
        fresh = [f for f in results if f.get("source_probe") == "env_parity"]
        assert len(fresh) == 1

    def test_synthetic_probe_failure_findings(self) -> None:
        probes = [
            {
                "probe_name": "broken",
                "findings": [],
                "_synthetic_findings": [
                    {
                        "finding_id": "broken:artifact_error:unparseable_json",
                        "severity": "high",
                        "source_probe": "broken",
                        "title": "Probe broken wrote unparseable artifact",
                    }
                ],
            }
        ]
        results = aggregate_findings(probes, [])
        assert len(results) == 1
        assert results[0]["severity"] == "high"
        assert "unparseable" in results[0]["title"]


# ---------------------------------------------------------------------------
# Phase 3: Focus area scoring
# ---------------------------------------------------------------------------


class TestComputeFocusAreas:
    """Test weighted severity focus area scoring."""

    def test_one_critical_outranks_five_mediums(self) -> None:
        findings = [
            {"severity": "critical", "repo": "repo_a"},
            {"severity": "medium", "repo": "repo_b"},
            {"severity": "medium", "repo": "repo_b"},
            {"severity": "medium", "repo": "repo_b"},
            {"severity": "medium", "repo": "repo_b"},
            {"severity": "medium", "repo": "repo_b"},
        ]
        areas = compute_focus_areas(findings)
        # repo_b = 5*4 = 20 points, repo_a = 16 points
        assert areas[0].startswith("repo_b")
        assert areas[1].startswith("repo_a")

    def test_platform_findings(self) -> None:
        findings = [
            {"severity": "high", "repo": None},
            {"severity": "low", "repo": "omniclaude"},
        ]
        areas = compute_focus_areas(findings)
        assert any("platform" in a for a in areas)

    def test_empty_findings(self) -> None:
        assert compute_focus_areas([]) == []

    def test_max_areas_respected(self) -> None:
        findings = [{"severity": "info", "repo": f"repo_{i}"} for i in range(20)]
        areas = compute_focus_areas(findings, max_areas=3)
        assert len(areas) == 3


# ---------------------------------------------------------------------------
# Phase 3: Build, serialize, write
# ---------------------------------------------------------------------------


class TestBuildAndSerialize:
    """Test day-open assembly, serialization, and file writing."""

    def test_build_day_open_structure(self) -> None:
        result = build_day_open(
            today="2026-03-18",
            run_id="test123",
            yesterday_corrections=["Fix something"],
            repo_sync_status=[],
            infra_health=[],
            probe_results=[],
            aggregated_findings=[],
            recommended_focus_areas=["area 1"],
            total_duration_seconds=42.0,
        )
        assert result["schema_version"] == SCHEMA_VERSION
        assert result["date"] == "2026-03-18"
        assert result["run_id"] == "test123"
        assert result["total_duration_seconds"] == 42.0

    def test_build_strips_internal_keys(self) -> None:
        probes = [
            {
                "probe_name": "test",
                "status": "completed",
                "findings": [{"id": "x"}],
                "_synthetic_findings": [{"id": "y"}],
            }
        ]
        result = build_day_open(
            today="2026-03-18",
            run_id="x",
            yesterday_corrections=[],
            repo_sync_status=[],
            infra_health=[],
            probe_results=probes,
            aggregated_findings=[],
            recommended_focus_areas=[],
            total_duration_seconds=0.0,
        )
        # Internal keys should be stripped
        for pr in result["probe_results"]:
            assert "findings" not in pr
            assert "_synthetic_findings" not in pr

    def test_serialize_produces_yaml(self) -> None:
        data = {
            "schema_version": "1.0.0",
            "date": "2026-03-18",
            "run_id": "test",
        }
        yaml_str = serialize_day_open(data)
        parsed = yaml.safe_load(yaml_str)
        assert parsed["schema_version"] == "1.0.0"

    def test_write_day_open_creates_file_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "run123"
            yaml_str = "schema_version: '1.0.0'\ndate: '2026-03-18'\n"
            path = write_day_open(yaml_str, artifact_dir)

            assert Path(path).exists()
            assert (Path(tmp) / "latest").is_symlink()
            assert (Path(tmp) / "latest").resolve().name == "run123"

    def test_write_day_open_overwrites_latest_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # First run
            write_day_open("v1", Path(tmp) / "run1")
            assert (Path(tmp) / "latest").resolve().name == "run1"

            # Second run
            write_day_open("v2", Path(tmp) / "run2")
            assert (Path(tmp) / "latest").resolve().name == "run2"

            # First run artifact still exists
            assert (Path(tmp) / "run1" / "day_open.yaml").exists()


# ---------------------------------------------------------------------------
# Aggregation edge cases
# ---------------------------------------------------------------------------


class TestAggregationEdgeCases:
    """Test semantically ugly but valid aggregation inputs."""

    def test_absurdly_large_detail_preserved(self) -> None:
        """Large detail fields are preserved in findings."""
        long_detail = "x" * 6000
        probes = [
            {
                "probe_name": "verbose",
                "findings": [
                    {
                        "finding_id": "verbose:cat:key",
                        "severity": "low",
                        "title": "Verbose",
                        "detail": long_detail,
                    }
                ],
            }
        ]
        results = aggregate_findings(probes, [])
        assert len(results[0]["detail"]) == 6000

    def test_platform_findings_compete_fairly_in_focus_areas(self) -> None:
        """Platform (repo=None) findings compete with repo-scoped ones."""
        findings = [
            {"severity": "critical", "repo": None},  # platform: 16
            {"severity": "high", "repo": "omniclaude"},  # omniclaude: 8
            {"severity": "high", "repo": "omniclaude"},  # omniclaude: 16 total
        ]
        areas = compute_focus_areas(findings)
        # Both should appear
        assert len(areas) == 2
        # omniclaude (16) and platform (16) — tied, order is deterministic
        repos = [a.split(":")[0].strip() for a in areas]
        assert "platform" in repos
        assert "omniclaude" in repos
