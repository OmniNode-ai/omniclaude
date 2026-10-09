# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18784: CI runs tests or refuses the selection; it never invents evidence."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.ci.skip_count_ratchet import (
    BaselineEntry,
    InputError,
    Observation,
    evaluate,
    observe,
)

ROOT = Path(__file__).resolve().parents[2]
RETIRED = (
    ".github/workflows/integration-tests.yml",
    "tests/hooks/test_integration_kafka.py",
    "tests/e2e/test_omniclaw_proof_of_life.py",
)
pytestmark = pytest.mark.unit


def _synthetic_reports(root: Path) -> list[str]:
    """Inspect executable steps in every workflow, including heredoc XML writers."""
    findings = []
    workflows = sorted((root / ".github/workflows").glob("*.y*ml"))
    assert workflows, "no workflows inspected"
    for path in workflows:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in workflow["jobs"].items():
            for step in job.get("steps", []):
                script = step.get("run", "")
                for tag in re.findall(r"<testsuite\b[^>]*>", script):
                    if re.search(r"\btests\s*=\s*(['\"])0\1", tag):
                        findings.append(
                            f"{path.name}:{job_name}:{step.get('name', '<unnamed>')}"
                        )
    return findings


def test_ac6_no_workflow_fabricates_a_zero_test_report() -> None:
    assert not _synthetic_reports(ROOT)


@pytest.mark.parametrize("quote", ['"', "'"])
def test_ac6_reintroduced_report_is_detected(tmp_path: Path, quote: str) -> None:
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    path = workflows / "fixture.yml"
    workflow = {
        "jobs": {
            "fixture": {
                "steps": [{"name": "run", "run": "pytest tests/ --junitxml=real.xml"}]
            }
        }
    }
    path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    assert _synthetic_reports(tmp_path) == []
    workflow["jobs"]["fixture"]["steps"][0]["run"] = (
        f"cat > junit.xml <<'XML'\n<testsuites><testsuite tests={quote}0{quote} "
        'failures="0" /></testsuites>\nXML'
    )
    path.write_text(yaml.safe_dump(workflow), encoding="utf-8")
    assert _synthetic_reports(tmp_path) == ["fixture.yml:fixture:run"]


@pytest.mark.parametrize("relative", RETIRED)
def test_ac4_ac5_retired_unexecuted_surfaces_are_removed(relative: str) -> None:
    assert not (ROOT / relative).exists(), f"unexecuted surface remains: {relative}"


def test_ac3_coverage_decisions_are_recorded() -> None:
    note = (ROOT / "docs/testing/ci-evidence.md").read_text(encoding="utf-8")
    for name in (
        "test_enhanced_router.py",
        "test_quality_gates.py",
        "test_performance_thresholds.py",
        "test_integration_kafka.py",
        "test_omniclaw_proof_of_life.py",
    ):
        assert name in note


@pytest.mark.parametrize(
    ("state", "expected"), [("missing", 4), ("empty", 5), ("red", 1), ("valid", 0)]
)
def test_ac1_ac2_actual_agent_job_refuses_bad_selection(
    tmp_path: Path, state: str, expected: int
) -> None:
    """Execute the shipped shell step, with pytest fixtures at its actual paths."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["agent-framework-tests"]
    step = next(s for s in job["steps"] if s["name"] == "Run agent framework tests")
    script = step["run"]
    named = sorted(set(re.findall(r"tests/[\w/]+\.py", script)))
    assert "tests/test_enhanced_router.py" in named
    for relative in named:
        test = tmp_path / relative
        test.parent.mkdir(parents=True, exist_ok=True)
        if state != "missing":
            body = (
                ""
                if state == "empty"
                else f"def test_control():\n    assert {state == 'valid'}\n"
            )
            test.write_text(body, encoding="utf-8")
    # Keep the workflow's selection, shell control flow, coverage and JUnit
    # flags. Only uv's environment launcher is replaced by this interpreter.
    script = script.replace("uv run pytest", f"{shlex.quote(sys.executable)} -m pytest")
    result = subprocess.run(
        ["bash", "-e", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    if state == "missing":
        assert "tests/test_enhanced_router.py" in result.stderr
    if state == "valid":
        assert observe([tmp_path / "junit-agent-framework.xml"]).collected == len(named)


def test_gate_is_wired_in_ci_and_precommit() -> None:
    relative = "tests/ci/test_ci_evidence_omn18784.py"
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["agent-framework-tests"]
    step = next(s for s in job["steps"] if s["name"] == "Run agent framework tests")
    assert relative in step["run"]
    hooks = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        h
        for repo in hooks["repos"]
        for h in repo["hooks"]
        if h["id"] == "ci-test-evidence"
    )
    assert relative in hook["entry"]
    assert hook["always_run"] is True
    assert hook["pass_filenames"] is False


def test_ac6_one_empty_shard_cannot_hide_behind_a_real_report(tmp_path: Path) -> None:
    empty = tmp_path / "empty.xml"
    real = tmp_path / "real.xml"
    empty.write_text('<testsuites><testsuite tests="0"/></testsuites>')
    real.write_text(
        '<testsuites><testsuite tests="1"><testcase name="test_control"/></testsuite></testsuites>'
    )
    assert observe([real]).collected == 1
    with pytest.raises(InputError, match="collected 0 tests"):
        observe([empty, real])


def test_verdict_is_derived_from_empty_selection_check() -> None:
    entry = BaselineEntry.load(
        ROOT / "config/skip_count_baseline.yaml", "omniclaude/agent-framework-tests"
    )
    assert evaluate(entry, Observation(frozenset(), 1, 1))[0] == 0
    code, lines = evaluate(entry, Observation(frozenset(), 0, 1))
    assert code != 0, lines
