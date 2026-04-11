# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the preflight reality-check gate (OMN-8411)."""

from __future__ import annotations

from pathlib import Path

import pytest

from plugins.onex.hooks.lib.preflight_reality_check import (
    EnumClaimKind,
    diagnosis_path,
    extract_claims,
    run_reality_check,
    write_diagnosis,
)


@pytest.mark.unit
class TestExtractClaims:
    def test_extracts_file_paths(self) -> None:
        desc = "Fix the handler in `src/omni/foo.py` and update tests/test_foo.py."
        claims = extract_claims(desc)
        values = {c.value for c in claims if c.kind == EnumClaimKind.FILE_PATH}
        assert "src/omni/foo.py" in values
        assert "tests/test_foo.py" in values

    def test_extracts_functions(self) -> None:
        desc = "Rename `run_pipeline()` to `execute_pipeline()` in the handler."
        fns = {
            c.value for c in extract_claims(desc) if c.kind == EnumClaimKind.FUNCTION
        }
        assert fns == {"run_pipeline", "execute_pipeline"}

    def test_extracts_classes(self) -> None:
        desc = "The `HandlerFoo` class dispatches to `ModelState`."
        classes = {
            c.value for c in extract_claims(desc) if c.kind == EnumClaimKind.CLASS
        }
        assert "HandlerFoo" in classes
        assert "ModelState" in classes

    def test_extracts_tables(self) -> None:
        desc = "Query the nonexistent_projection table for validation."
        tables = {
            c.value for c in extract_claims(desc) if c.kind == EnumClaimKind.TABLE
        }
        assert "nonexistent_projection" in tables

    def test_extracts_topics(self) -> None:
        desc = "Publish to `onex.evt.omniclaude.session-started.v1`."
        topics = {
            c.value for c in extract_claims(desc) if c.kind == EnumClaimKind.TOPIC
        }
        assert "onex.evt.omniclaude.session-started.v1" in topics

    def test_no_claims_in_narrative_description(self) -> None:
        desc = "Improve the workflow so users feel the pipeline is smoother."
        assert extract_claims(desc) == []


@pytest.mark.unit
class TestRunRealityCheck:
    @pytest.fixture
    def fake_repo(self, tmp_path: Path) -> Path:
        """Create a minimal git repo with a real file and symbol."""
        import subprocess

        repo = tmp_path / "fake_repo"
        repo.mkdir()
        (repo / "src").mkdir()
        (repo / "src" / "real.py").write_text(
            "class RealClass:\n    pass\n\ndef real_function():\n    return 1\n",
        )
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        subprocess.run(["git", "add", "."], cwd=repo, check=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-q",
                "-m",
                "x",
            ],
            cwd=repo,
            check=True,
        )
        return repo

    def test_matching_claims_allow(self, fake_repo: Path) -> None:
        desc = "Update `real_function()` in src/real.py — touches `RealClass` behavior."
        report = run_reality_check("OMN-TEST", desc, [fake_repo])
        assert not report.halted
        assert len(report.results) == 3
        assert all(r.verified for r in report.results)

    def test_missing_file_halts(self, fake_repo: Path) -> None:
        desc = "Fix the handler in src/does_not_exist.py."
        report = run_reality_check("OMN-TEST", desc, [fake_repo])
        assert report.halted
        failures = report.failures
        assert len(failures) == 1
        assert failures[0].claim.kind == EnumClaimKind.FILE_PATH
        assert "does_not_exist.py" in failures[0].evidence

    def test_missing_function_halts(self, fake_repo: Path) -> None:
        desc = "Rename `ghost_function()` to something else."
        report = run_reality_check("OMN-TEST", desc, [fake_repo])
        assert report.halted
        assert report.failures[0].claim.kind == EnumClaimKind.FUNCTION
        assert report.failures[0].claim.value == "ghost_function"

    def test_missing_class_halts(self, fake_repo: Path) -> None:
        desc = "Refactor `GhostClass` to use composition."
        report = run_reality_check("OMN-TEST", desc, [fake_repo])
        assert report.halted
        assert report.failures[0].claim.kind == EnumClaimKind.CLASS

    def test_missing_table_halts(self, fake_repo: Path) -> None:
        desc = "Fix the query on the pipeline_baselines table."

        def verifier(name: str) -> bool:
            return name == "real_table"

        report = run_reality_check(
            "OMN-TEST",
            desc,
            [fake_repo],
            table_verifier=verifier,
        )
        assert report.halted
        assert any(f.claim.kind == EnumClaimKind.TABLE for f in report.failures)

    def test_missing_topic_halts(self, fake_repo: Path) -> None:
        desc = "Subscribe to `onex.evt.ghost.nonexistent.v1`."

        def verifier(name: str) -> bool:
            return False

        report = run_reality_check(
            "OMN-TEST",
            desc,
            [fake_repo],
            topic_verifier=verifier,
        )
        assert report.halted
        assert any(f.claim.kind == EnumClaimKind.TOPIC for f in report.failures)

    def test_no_claims_allows(self, fake_repo: Path) -> None:
        desc = "Improve pipeline ergonomics and make failures more obvious."
        report = run_reality_check("OMN-TEST", desc, [fake_repo])
        assert not report.halted
        assert report.results == ()


@pytest.mark.unit
class TestWriteDiagnosis:
    def test_writes_four_sections(self, tmp_path: Path) -> None:
        from plugins.onex.hooks.lib.preflight_reality_check import (
            ModelClaim,
            ModelClaimResult,
            ModelRealityCheckReport,
        )

        claim = ModelClaim(
            kind=EnumClaimKind.FILE_PATH,
            value="src/missing.py",
            raw="src/missing.py",
        )
        failure = ModelClaimResult(
            claim=claim,
            verified=False,
            evidence="file not found in any target repo: src/missing.py",
        )
        report = ModelRealityCheckReport(
            ticket_id="OMN-9999",
            results=(failure,),
        )

        path = write_diagnosis(report, tmp_path)
        assert path == diagnosis_path("OMN-9999", tmp_path)
        assert path.exists()

        content = path.read_text()
        assert "## What is known" in content
        assert "## What was tried and why it failed" in content
        assert "## Root cause hypothesis" in content
        assert "## Proposed fix with rationale" in content
        assert "OMN-9999" in content
        assert "src/missing.py" in content
