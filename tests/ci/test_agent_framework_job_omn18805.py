# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18805 — the ``Agent Framework Tests`` job runs real tests or does not exist.

Epic OMN-18775 found this job green on every run without executing a test. It
looked for three files — ``tests/test_enhanced_router.py``,
``tests/test_quality_gates.py`` and ``tests/test_performance_thresholds.py`` —
none of which existed, and its ``else`` branch wrote a synthetic empty JUnit
report so the step still exited 0. OMN-18790 refused to register it in the
skip-count baseline for exactly that reason: a baseline of zero that the job's
own placeholder report satisfies forever is a gate entry that proves nothing.

What ``git log`` establishes, rather than what the shape of the job suggests:

``test_enhanced_router.py``
    30 tests, 74 assertions, real coverage of the agent-routing stack. Added by
    ``7f4d00c4c`` at ``agents/tests/``, deleted by ``9f9d3369d`` (2025-10-29).
    Every module it exercises is still on ``dev`` under
    ``src/omniclaude/lib/core/``, so the coverage was LOST, not moved — it is
    restored here, repointed onto the current import path and the current
    ``TriggerMatcher`` name.

``test_quality_gates.py`` / ``test_performance_thresholds.py``
    26 and 36 test functions, every one of them a bare
    ``pytest.skip("Waiting for dependency streams to complete")``, zero
    assertions between them. Archived to ``_archive/`` by ``5cc976275`` and
    deleted with that tree by ``1a605099e``. They stay deleted: restoring them
    would restore an always-skip suite, which is the same false-green class
    this epic exists to remove.

``1a605099e`` (OMN-2228, 2026-02-16) is the commit that made the job phantom by
construction. It deleted ``_archive/`` and, in the same change, rewrote the
job's paths from ``agents/tests/`` to ``tests/`` — a directory that has never
held any of the three.

Each test below is named for the falsifier it refuses. Deleting one deletes the
proof of that acceptance criterion.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
BASELINE = REPO_ROOT / "config" / "skip_count_baseline.yaml"
SCRIPT = REPO_ROOT / "scripts" / "ci" / "skip_count_ratchet.py"
ROUTER_TESTS = REPO_ROOT / "tests" / "test_enhanced_router.py"

JOB_KEY = "agent-framework-tests"
JOB_DISPLAY_NAME = "Agent Framework Tests"
SUITE = "omniclaude/agent-framework-tests"
JUNIT_NAME = "junit-agent-framework.xml"

pytestmark = pytest.mark.unit


def _workflow() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return loaded


def _job(key: str) -> dict[str, Any]:
    jobs: dict[str, Any] = _workflow()["jobs"]
    assert key in jobs, f"job {key!r} is absent from {WORKFLOW.name}"
    job: dict[str, Any] = jobs[key]
    return job


def _job_text(key: str) -> str:
    """The job's own YAML block, sliced out of the raw file.

    Parsed access is used wherever the assertion is about structure. This exists
    for the assertions that are about the literal text of a ``run:`` script,
    where the parsed form would lose the shell.
    """
    raw = WORKFLOW.read_text(encoding="utf-8")
    start = raw.index(f"\n  {key}:\n")
    following = re.compile(r"\n  [a-z0-9_-]+:\n")
    match = following.search(raw, start + 1)
    return raw[start : match.start() if match else len(raw)]


def _run_ratchet(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def _junit(tests: int, skipped: int = 0, name: str = "agent-framework") -> str:
    cases = "".join(
        f'<testcase classname="tests.test_enhanced_router" name="test_{i}">'
        + ("<skipped/>" if i < skipped else "")
        + "</testcase>"
        for i in range(tests)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        f'<testsuite name="{name}" tests="{tests}" errors="0" failures="0" '
        f'skipped="{skipped}">{cases}</testsuite></testsuites>'
    )


# ---------------------------------------------------------------------------
# AC1 — the synthetic-empty-JUnit branch is gone
# ---------------------------------------------------------------------------


def test_ac1_job_writes_no_synthetic_empty_junit_report() -> None:
    """Falsifier: the job still fabricates a report when it finds no tests."""
    text = _job_text(JOB_KEY)
    assert 'testsuite name="agent-framework"' not in text, (
        "the Agent Framework Tests job still writes a synthetic JUnit report. "
        "A fabricated empty report is indistinguishable from a suite that ran "
        "and found nothing, which is the false green OMN-18775 exists to remove."
    )
    assert "skipping" not in text.lower(), (
        "the job still carries a skip-and-succeed branch; a suite with no tests "
        "to run must fail, not announce that it skipped itself."
    )


def test_ac1_job_does_not_guard_its_pytest_call_behind_a_file_existence_test() -> None:
    """Falsifier: an ``if [ -f ... ]`` fallback returns, so absence passes again."""
    text = _job_text(JOB_KEY)
    assert "-f " not in text, (
        "the job tests for its test files' existence before running them. That "
        "construct is precisely what let three deleted paths report success for "
        "seven months: a missing file must fail the job, not narrow it."
    )


# ---------------------------------------------------------------------------
# AC3 — every path the job names exists, established from git log
# ---------------------------------------------------------------------------


def test_ac3_every_test_path_the_job_names_exists_on_disk() -> None:
    """Falsifier: the job names a path that is not in the repository."""
    text = _job_text(JOB_KEY)
    named = sorted(set(re.findall(r"tests/[\w/]+\.py", text)))
    assert named, (
        "the Agent Framework Tests job names no test file at all. A job that "
        "selects nothing cannot prove anything."
    )
    missing = [p for p in named if not (REPO_ROOT / p).is_file()]
    assert not missing, (
        f"the job points at {missing}, which do not exist. This is the original "
        "OMN-18775 finding recurring."
    )


def test_ac3_the_restored_router_suite_is_real_coverage_not_a_placeholder() -> None:
    """Falsifier: the restored file is an always-skip placeholder like its peers.

    The two files that stayed deleted were 26 and 36 bare ``pytest.skip`` calls
    with zero assertions. Restoring that shape would swap one false green for
    another, so the restored file is held to the opposite standard.
    """
    assert ROUTER_TESTS.is_file(), f"{ROUTER_TESTS} is absent"
    body = ROUTER_TESTS.read_text(encoding="utf-8")
    assert "pytest.skip" not in body, (
        "the restored suite contains a skip. It was restored because it is real "
        "coverage; a skip in it means it is not."
    )
    assert body.count("assert ") >= 50, (
        "the restored suite asserts too little to be the 74-assertion file the "
        "commit history records."
    )


# ---------------------------------------------------------------------------
# AC4 — the ratchet registers the suite, and the deliberate-omission note is gone
# ---------------------------------------------------------------------------


def test_ac4_baseline_registers_the_suite_with_a_nonzero_collected_count() -> None:
    """Falsifier: the suite is absent, or registered with a zero baseline."""
    loaded = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    suites = loaded["suites"]
    assert SUITE in suites, (
        f"{SUITE} is not registered in the skip-count baseline. The job now runs "
        "real tests, so the reason OMN-18790 recorded for leaving it out no "
        "longer holds."
    )
    entry = suites[SUITE]
    assert entry["job"] == JOB_DISPLAY_NAME
    assert int(entry["baseline_collected"]) > 0, (
        "a baseline of zero collected is satisfied by an empty report forever — "
        "the exact entry OMN-18790 refused to write."
    )
    assert entry["provenance"]["measured_by"] == "OMN-18805"


def test_ac4_baseline_no_longer_carries_the_deliberate_omission_paragraph() -> None:
    """Falsifier: the NOT REGISTERED note survives the suite's registration."""
    text = BASELINE.read_text(encoding="utf-8")
    assert "NOT REGISTERED" not in text, (
        "the baseline still explains why Agent Framework Tests is unregistered "
        "while registering it. A stale reason reads as a current decision."
    )


def test_ac4_ratchet_job_enforces_this_suite_from_its_own_report() -> None:
    """Falsifier: the ratchet never reads this job's JUnit, so nothing enforces it."""
    text = _job_text("skip-count-ratchet")
    assert f"--suite {SUITE}" in text, (
        f"the ratchet job has no enforcement step for {SUITE}."
    )
    assert JUNIT_NAME in text, (
        f"the ratchet job never locates {JUNIT_NAME}, so the suite is registered "
        "but unread."
    )
    assert "agent-framework-test-results" in text, (
        "the ratchet job does not download this job's artifact, so its find "
        "would return nothing and the suite would be enforced over air."
    )
    ratchet = _job("skip-count-ratchet")
    assert JOB_KEY in ratchet["needs"], (
        "the ratchet does not wait on Agent Framework Tests, so it can run "
        "before the report exists."
    )


def test_ac4_neither_job_carries_an_advisory_setting() -> None:
    """Falsifier: the job is made advisory instead of being made to enforce."""
    for key in (JOB_KEY, "skip-count-ratchet"):
        text = _job_text(key)
        assert "continue-on-error" not in text, (
            f"job {key!r} carries continue-on-error. Epic OMN-18775 AC4 refuses "
            "relabelling a check rather than making it enforce."
        )


# ---------------------------------------------------------------------------
# AC2 — a job that collects zero tests FAILS, with a positive control
# ---------------------------------------------------------------------------


def test_ac2_zero_collection_is_refused_for_this_suite(tmp_path: Path) -> None:
    """Falsifier: an empty report passes, so the phantom shape returns silently."""
    junit = tmp_path / JUNIT_NAME
    junit.write_text(_junit(tests=0), encoding="utf-8")
    result = _run_ratchet(
        "--baseline", str(BASELINE), "--suite", SUITE, "--junit", str(junit)
    )
    assert result.returncode != 0, (
        "a report collecting zero tests passed the ratchet. That is the phantom "
        f"job restored: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "collected 0 tests" in (result.stdout + result.stderr)


def test_ac2_positive_control_a_real_report_with_no_skips_passes(
    tmp_path: Path,
) -> None:
    """The control for the zero above: the same gate, on an input that should pass.

    Without it, the refusal above is also satisfied by a gate that refuses
    everything, and a gate that always fails is removed rather than fixed.
    """
    entry = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["suites"][SUITE]
    junit = tmp_path / JUNIT_NAME
    junit.write_text(_junit(tests=int(entry["baseline_collected"])), encoding="utf-8")
    result = _run_ratchet(
        "--baseline", str(BASELINE), "--suite", SUITE, "--junit", str(junit)
    )
    assert result.returncode == 0, (
        f"a real, full, skip-free report was refused: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_ac2_a_new_skip_in_this_suite_fails(tmp_path: Path) -> None:
    """Falsifier: the suite may quietly convert its tests into skips instead."""
    entry = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["suites"][SUITE]
    junit = tmp_path / JUNIT_NAME
    junit.write_text(
        _junit(tests=int(entry["baseline_collected"]), skipped=1), encoding="utf-8"
    )
    result = _run_ratchet(
        "--baseline", str(BASELINE), "--suite", SUITE, "--junit", str(junit)
    )
    assert result.returncode != 0, (
        "a newly skipped test in the restored suite passed the ratchet; the "
        "restored coverage can therefore be hollowed out one skip at a time."
    )
