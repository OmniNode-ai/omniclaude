# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for close-day skill (CDQA-04 / OMN-2981).

Tests cover:
- PR with no OMN-XXXX ref → drift_detected entry with category=SCOPE
- Unknown invariant (missing script) → status=unknown + corrections_for_tomorrow
- Golden path detection reads emitted_at from artifact JSON (not directory name)
- Output validates against ModelDayClose.model_validate()
- ONEX_CC_REPO_PATH not set → prints YAML with warning banner, does not write file
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Import close_day.py directly from skills directory
# ---------------------------------------------------------------------------

_SKILL_DIR = (
    Path(__file__).parent.parent.parent.parent / "plugins/onex/skills/close-day"
)
_CLOSE_DAY_PATH = _SKILL_DIR / "close_day.py"

_spec = importlib.util.spec_from_file_location("close_day", _CLOSE_DAY_PATH)
assert _spec is not None and _spec.loader is not None
_close_day = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_close_day)

# Expose module-level functions for convenience
detect_drift = _close_day.detect_drift
build_actual_by_repo = _close_day.build_actual_by_repo
build_day_close = _close_day.build_day_close
validate_day_close = _close_day.validate_day_close
detect_golden_path_progress = _close_day.detect_golden_path_progress
run_arch_invariant_probe = _close_day.run_arch_invariant_probe
write_or_print = _close_day.write_or_print
serialize_day_close = _close_day.serialize_day_close


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def today() -> str:
    return "2026-02-28"


@pytest.fixture
def pr_with_omn_ref() -> dict:
    return {
        "number": 101,
        "title": "[OMN-2981] feat(skills): add close-day",
        "headRefName": "epic/OMN-2974/OMN-2981/abc123",
        "baseRefName": "main",
    }


@pytest.fixture
def pr_without_omn_ref() -> dict:
    return {
        "number": 202,
        "title": "chore: bump deps",
        "headRefName": "chore/bump-deps",
        "baseRefName": "main",
    }


# ---------------------------------------------------------------------------
# Tests: drift detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetection:
    def test_pr_with_omn_ref_no_drift(self, pr_with_omn_ref: dict) -> None:
        """PR with OMN-XXXX in title → no drift entry."""
        repo_prs = {"omniclaude": [pr_with_omn_ref]}
        drift = detect_drift(repo_prs)
        assert drift == []

    def test_pr_in_branch_name_no_drift(self) -> None:
        """PR with OMN-XXXX only in branch name → no drift entry."""
        pr = {
            "number": 303,
            "title": "Fix something",
            "headRefName": "jonah/omn-9999-fix-something",
            "baseRefName": "main",
        }
        drift = detect_drift({"omniclaude": [pr]})
        assert drift == []

    def test_pr_without_omn_ref_creates_scope_drift(
        self, pr_without_omn_ref: dict
    ) -> None:
        """PR with no OMN-XXXX ref → drift_detected entry with category=scope."""
        repo_prs = {"omniclaude": [pr_without_omn_ref]}
        drift = detect_drift(repo_prs)
        assert len(drift) == 1
        entry = drift[0]
        assert entry["category"] == "scope"
        assert "202" in entry["evidence"]
        assert "omniclaude" in entry["evidence"]
        assert "drift_id" in entry
        assert "correction_for_tomorrow" in entry

    def test_multiple_repos_multiple_drifts(
        self, pr_with_omn_ref: dict, pr_without_omn_ref: dict
    ) -> None:
        """Mix of repos: only unref'd PRs appear in drift."""
        repo_prs = {
            "omniclaude": [pr_with_omn_ref],
            "omnibase_core": [pr_without_omn_ref],
        }
        drift = detect_drift(repo_prs)
        assert len(drift) == 1
        assert "omnibase_core" in drift[0]["evidence"]

    def test_drift_ids_are_unique(self) -> None:
        """Multiple unref'd PRs get unique drift IDs."""
        prs = [
            {
                "number": i,
                "title": "chore: thing",
                "headRefName": "chore/thing",
                "baseRefName": "main",
            }
            for i in range(3)
        ]
        drift = detect_drift({"omniclaude": prs})
        ids = [d["drift_id"] for d in drift]
        assert len(ids) == len(set(ids))

    def test_empty_repo_prs_no_drift(self) -> None:
        """Empty repo_prs → no drift entries."""
        drift = detect_drift({})
        assert drift == []


# ---------------------------------------------------------------------------
# Tests: unknown invariant (missing script) → status=unknown + corrections
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInvariantProbeUnknown:
    def test_missing_script_returns_unknown(self, tmp_path: Path) -> None:
        """Missing script → status=unknown."""
        non_existent = tmp_path / "no_such_script.py"
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        status = run_arch_invariant_probe(src_dir, script_path=non_existent)
        assert status == "unknown"

    def test_missing_src_dir_returns_unknown(self, tmp_path: Path) -> None:
        """Missing src/ dir → status=unknown even if script exists."""
        # Use the real script for this test
        real_script = (
            _SKILL_DIR.parent.parent.parent.parent / "scripts/check_arch_invariants.py"
        )
        if not real_script.exists():
            pytest.skip("check_arch_invariants.py not found at expected location")
        non_existent_src = tmp_path / "src"
        status = run_arch_invariant_probe(non_existent_src, script_path=real_script)
        assert status == "unknown"

    def test_build_day_close_unknown_invariants_generates_corrections(
        self, today: str
    ) -> None:
        """Unknown invariant status → correction entries in corrections_for_tomorrow."""
        invariant_statuses = {
            "reducers_pure": "unknown",
            "orchestrators_no_io": "unknown",
        }
        corrections: list[str] = []
        if invariant_statuses.get("reducers_pure") == "unknown":
            corrections.append(
                "Verify reducers_pure: run check_arch_invariants.py against all repos."
            )
        if invariant_statuses.get("orchestrators_no_io") == "unknown":
            corrections.append(
                "Verify orchestrators_no_io: run check_arch_invariants.py against all repos."
            )

        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses=invariant_statuses,
            golden_path_status="unknown",
            corrections_for_tomorrow=corrections,
        )
        assert raw["invariants_checked"]["reducers_pure"] == "unknown"
        assert raw["invariants_checked"]["orchestrators_no_io"] == "unknown"
        assert len(raw["corrections_for_tomorrow"]) >= 2
        assert any("reducers_pure" in c for c in raw["corrections_for_tomorrow"])
        assert any("orchestrators_no_io" in c for c in raw["corrections_for_tomorrow"])

    def test_real_script_passes_on_clean_src(self) -> None:
        """Real check_arch_invariants.py returns pass on clean (empty) src."""
        real_script = (
            _SKILL_DIR.parent.parent.parent.parent / "scripts/check_arch_invariants.py"
        )
        if not real_script.exists():
            pytest.skip("check_arch_invariants.py not found at expected location")
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp) / "src"
            src_dir.mkdir()
            status = run_arch_invariant_probe(src_dir, script_path=real_script)
            assert status == "pass"


# ---------------------------------------------------------------------------
# Tests: golden path detection reads emitted_at from artifact JSON
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGoldenPathDetection:
    def test_missing_dir_returns_unknown(self, tmp_path: Path, today: str) -> None:
        """No golden-path dir → unknown."""
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "unknown"

    def test_empty_dir_returns_unknown(self, tmp_path: Path, today: str) -> None:
        """Empty today dir → unknown."""
        (tmp_path / today).mkdir(parents=True)
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "unknown"

    def test_artifact_with_pass_status_and_correct_emitted_at(
        self, tmp_path: Path, today: str
    ) -> None:
        """Artifact with status=pass and emitted_at=today → pass."""
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        artifact = {
            "artifact": {
                "status": "pass",
                "emitted_at": f"{today}T12:00:00Z",
                "run_id": "test-run-001",
            }
        }
        (today_dir / "run001.json").write_text(json.dumps(artifact), encoding="utf-8")
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "pass"

    def test_artifact_with_fail_status_returns_unknown(
        self, tmp_path: Path, today: str
    ) -> None:
        """Artifact with status=fail → unknown (no passing artifact)."""
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        artifact = {
            "artifact": {
                "status": "fail",
                "emitted_at": f"{today}T12:00:00Z",
            }
        }
        (today_dir / "run001.json").write_text(json.dumps(artifact), encoding="utf-8")
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "unknown"

    def test_emitted_at_different_date_returns_unknown(
        self, tmp_path: Path, today: str
    ) -> None:
        """Artifact with status=pass but emitted_at from yesterday → unknown."""
        yesterday = "2026-02-27"
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        artifact = {
            "artifact": {
                "status": "pass",
                "emitted_at": f"{yesterday}T23:59:00Z",
            }
        }
        (today_dir / "run001.json").write_text(json.dumps(artifact), encoding="utf-8")
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "unknown"

    def test_top_level_artifact_fields(self, tmp_path: Path, today: str) -> None:
        """Top-level status + emitted_at (no nested 'artifact' key) → pass."""
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        artifact = {
            "status": "pass",
            "emitted_at": f"{today}T08:00:00Z",
        }
        (today_dir / "run001.json").write_text(json.dumps(artifact), encoding="utf-8")
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "pass"

    def test_multiple_artifacts_one_pass(self, tmp_path: Path, today: str) -> None:
        """Multiple artifacts, one passing → overall pass."""
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        (today_dir / "run_fail.json").write_text(
            json.dumps(
                {"artifact": {"status": "fail", "emitted_at": f"{today}T10:00:00Z"}}
            ),
            encoding="utf-8",
        )
        (today_dir / "run_pass.json").write_text(
            json.dumps(
                {"artifact": {"status": "pass", "emitted_at": f"{today}T11:00:00Z"}}
            ),
            encoding="utf-8",
        )
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "pass"

    def test_malformed_json_does_not_raise(self, tmp_path: Path, today: str) -> None:
        """Malformed JSON file → gracefully skip, still return unknown."""
        today_dir = tmp_path / today
        today_dir.mkdir(parents=True)
        (today_dir / "bad.json").write_text("{not valid json}", encoding="utf-8")
        status = detect_golden_path_progress(today, golden_path_base=tmp_path)
        assert status == "unknown"


# ---------------------------------------------------------------------------
# Tests: output validates against ModelDayClose.model_validate()
# ---------------------------------------------------------------------------

_ONEX_CC_AVAILABLE = importlib.util.find_spec("onex_change_control") is not None
_skip_no_onex_cc = pytest.mark.skipif(
    not _ONEX_CC_AVAILABLE,
    reason="onex_change_control not installed; skipping ModelDayClose validation tests",
)


@pytest.mark.unit
@_skip_no_onex_cc
class TestModelDayCloseValidation:
    def test_minimal_output_validates(self, today: str) -> None:
        """Minimal output (all unknowns, no PRs) → ModelDayClose validates OK."""
        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses={
                "reducers_pure": "unknown",
                "orchestrators_no_io": "unknown",
            },
            golden_path_status="unknown",
            corrections_for_tomorrow=[],
        )
        validated = validate_day_close(raw)
        assert validated.date == today
        assert validated.schema_version == "1.0.0"

    def test_with_prs_and_drift_validates(
        self, today: str, pr_without_omn_ref: dict
    ) -> None:
        """Output with PRs and drift entries validates against ModelDayClose."""
        repo_prs = {"omniclaude": [pr_without_omn_ref]}
        actual = build_actual_by_repo(repo_prs)
        drift = detect_drift(repo_prs)
        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=actual,
            drift_detected=drift,
            invariant_statuses={"reducers_pure": "pass", "orchestrators_no_io": "pass"},
            golden_path_status="pass",
            corrections_for_tomorrow=["Fix drift by adding OMN-XXXX ref to PR #202."],
        )
        validated = validate_day_close(raw)
        assert len(validated.actual_by_repo) == 1
        assert len(validated.drift_detected) == 1
        assert validated.drift_detected[0].category.value == "scope"

    def test_invalid_date_raises_validation_error(self) -> None:
        """Invalid date format → ValidationError from ModelDayClose."""
        from pydantic import ValidationError

        raw = build_day_close(
            today="not-a-date",
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses={
                "reducers_pure": "unknown",
                "orchestrators_no_io": "unknown",
            },
            golden_path_status="unknown",
            corrections_for_tomorrow=[],
        )
        with pytest.raises(ValidationError):
            validate_day_close(raw)

    def test_invariants_checked_schema(self, today: str) -> None:
        """invariants_checked has all four required fields with valid statuses."""
        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses={"reducers_pure": "pass", "orchestrators_no_io": "fail"},
            golden_path_status="pass",
            corrections_for_tomorrow=[],
        )
        inv = raw["invariants_checked"]
        assert inv["reducers_pure"] == "pass"
        assert inv["orchestrators_no_io"] == "fail"
        assert inv["effects_do_io_only"] == "unknown"
        assert inv["real_infra_proof_progressing"] == "pass"
        validated = validate_day_close(raw)
        assert validated.invariants_checked.reducers_pure.value == "pass"
        assert validated.invariants_checked.orchestrators_no_io.value == "fail"


# ---------------------------------------------------------------------------
# Tests: ONEX_CC_REPO_PATH not set → prints YAML with banner, does not write
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWriteOrPrint:
    def test_no_repo_path_prints_yaml_with_banner(
        self, today: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ONEX_CC_REPO_PATH not set → warning banner + YAML printed to stdout."""
        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses={
                "reducers_pure": "unknown",
                "orchestrators_no_io": "unknown",
            },
            golden_path_status="unknown",
            corrections_for_tomorrow=[],
        )
        yaml_str = serialize_day_close(raw)
        result = write_or_print(yaml_str, today, onex_cc_repo_path=None)
        assert result == "printed"
        captured = capsys.readouterr()
        assert "ONEX_CC_REPO_PATH not set" in captured.out
        assert "schema_version" in captured.out  # YAML is present

    def test_no_repo_path_does_not_write_file(
        self, today: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ONEX_CC_REPO_PATH not set → no file is written anywhere."""
        yaml_str = "schema_version: 1.0.0\n"
        write_or_print(yaml_str, today, onex_cc_repo_path=None)
        # Verify no YAML file was written under tmp_path (shouldn't be since we didn't pass it)
        yaml_files = list(tmp_path.rglob("*.yaml"))
        assert yaml_files == []

    def test_with_valid_repo_path_writes_file(self, today: str, tmp_path: Path) -> None:
        """ONEX_CC_REPO_PATH set to valid dir → file written to drift/day_close/."""
        yaml_str = "schema_version: 1.0.0\ndate: " + today + "\n"
        result = write_or_print(yaml_str, today, onex_cc_repo_path=str(tmp_path))
        assert result.startswith("written:")
        out_file = tmp_path / "drift" / "day_close" / f"{today}.yaml"
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "schema_version" in content

    def test_with_nonexistent_repo_path_falls_back_to_print(
        self, today: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """ONEX_CC_REPO_PATH set to non-existent path → falls back to print with banner."""
        yaml_str = "schema_version: 1.0.0\n"
        result = write_or_print(yaml_str, today, onex_cc_repo_path="/nonexistent/path")
        assert result == "printed"
        captured = capsys.readouterr()
        assert "ONEX_CC_REPO_PATH not set" in captured.out


# ---------------------------------------------------------------------------
# Tests: actual_by_repo construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildActualByRepo:
    def test_pr_with_omn_ref_has_correct_notes(self, pr_with_omn_ref: dict) -> None:
        """PR with OMN-XXXX ref → notes contain the ref."""
        actual = build_actual_by_repo({"omniclaude": [pr_with_omn_ref]})
        assert len(actual) == 1
        assert actual[0]["repo"] == "OmniNode-ai/omniclaude"
        pr_entry = actual[0]["prs"][0]
        assert pr_entry["state"] == "merged"
        assert "OMN-2981" in pr_entry["notes"]

    def test_empty_repo_prs_excluded(self) -> None:
        """Repos with no PRs → not included in actual_by_repo."""
        actual = build_actual_by_repo({"omniclaude": [], "omnibase_core": []})
        assert actual == []

    def test_multiple_prs_per_repo(self) -> None:
        """Multiple PRs in one repo → all included."""
        prs = [
            {
                "number": 1,
                "title": "[OMN-1] feat: a",
                "headRefName": "epic/1",
                "baseRefName": "main",
            },
            {
                "number": 2,
                "title": "[OMN-2] feat: b",
                "headRefName": "epic/2",
                "baseRefName": "main",
            },
        ]
        actual = build_actual_by_repo({"omniclaude": prs})
        assert len(actual[0]["prs"]) == 2


# ---------------------------------------------------------------------------
# Tests: serialize_day_close produces valid YAML
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSerializeDayClose:
    def test_serialized_yaml_is_parseable(self, today: str) -> None:
        """serialize_day_close produces valid YAML."""
        raw = build_day_close(
            today=today,
            plan_items=[],
            actual_by_repo=[],
            drift_detected=[],
            invariant_statuses={"reducers_pure": "pass", "orchestrators_no_io": "pass"},
            golden_path_status="pass",
            corrections_for_tomorrow=[],
        )
        yaml_str = serialize_day_close(raw)
        parsed = yaml.safe_load(yaml_str)
        assert parsed["schema_version"] == "1.0.0"
        assert parsed["date"] == today
