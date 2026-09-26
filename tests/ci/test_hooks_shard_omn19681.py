# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19681 — the ``Hooks System Tests`` job is a 2-way matrix, and the
OMN-18776 skip-count ratchet still counts every hooks case across both shards.

Plan task A5 (knowledge-base-internal
``beta/plans/2026-09-25-golden-chain-event-tests-for-pr-validation-plan.md``,
section 5 Part A) measured the unsharded ``Hooks System Tests`` job's pytest
step at 10.2 minutes in CI run 36187640881, on the critical path of every
omniclaude PR. Splitting it into two shards should roughly halve that. The
ratchet job (``skip-count-ratchet``, OMN-18776) downloads that job's JUnit
artifact by name and counts skipped tests in it; a shard split that is not
matched by a corresponding artifact-download and count-source change would
either silently stop counting one shard's skips, or fail closed with no
report at all. Each test below is named for the falsifier it refuses.
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
SCRIPT = REPO_ROOT / "scripts" / "ci" / "skip_count_ratchet.py"
BASELINE = REPO_ROOT / "config" / "skip_count_baseline.yaml"

HOOKS_JOB_KEY = "hooks-tests"
RATCHET_JOB_KEY = "skip-count-ratchet"
JUNIT_BASENAME = "junit-hooks.xml"

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

    Parsed access is used wherever the assertion is about structure. This
    exists for the assertions that are about the literal text of a ``run:``
    script or a ``gh run download --pattern`` argument, where the parsed form
    would lose the shell quoting.
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


def _junit(tests: int, skipped: int = 0, name: str = "hooks", prefix: str = "a") -> str:
    """A synthetic report. ``prefix`` keeps two shards' node ids disjoint --
    ``observe()`` dedups by ``classname::name``, so two shards reusing the
    same test names would silently collide and undercount, the same way a
    module collected by more than one real split re-reports the same id.
    """
    cases = "".join(
        f'<testcase classname="tests.hooks.test_shard_{prefix}" name="test_{i}">'
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
# AC1 — the job is a 2-way matrix
# ---------------------------------------------------------------------------


def test_hooks_tests_job_is_a_two_way_matrix() -> None:
    """Falsifier: the job carries no ``strategy.matrix.split`` of length 2."""
    job = _job(HOOKS_JOB_KEY)
    assert "strategy" in job, (
        "Hooks System Tests has no strategy block -- it still runs "
        "tests/hooks/ as one unsharded job."
    )
    matrix = job["strategy"].get("matrix", {})
    assert matrix.get("split") == [1, 2], (
        "Hooks System Tests must declare a 2-way split matrix (split: [1, 2]); "
        f"found matrix={matrix!r}"
    )


def test_hooks_tests_job_name_reports_its_shard() -> None:
    """Falsifier: the job's display name does not vary by matrix.split."""
    job = _job(HOOKS_JOB_KEY)
    assert "${{ matrix.split }}" in job["name"], (
        "the job name must include the shard index so two parallel runs are "
        f"distinguishable in the Actions UI; found name={job['name']!r}"
    )


def test_hooks_tests_shards_the_pytest_invocation_two_ways() -> None:
    """Falsifier: the pytest step still runs the whole directory unsplit."""
    text = _job_text(HOOKS_JOB_KEY)
    assert "--splits 2" in text, (
        "the hooks pytest step does not pass --splits 2 to pytest-split"
    )
    assert "--group ${{ matrix.split }}" in text, (
        "the hooks pytest step does not select its shard with "
        "--group ${{ matrix.split }}"
    )


def test_hooks_tests_uploads_a_uniquely_named_artifact_per_shard() -> None:
    """Falsifier: both shards upload under the same artifact name and collide.

    ``actions/upload-artifact`` refuses two uploads of the same name within
    one run, so an un-suffixed name here is not a style nit -- it is one
    shard's upload failing outright.
    """
    text = _job_text(HOOKS_JOB_KEY)
    assert "name: hooks-test-results-${{ matrix.split }}" in text, (
        "the hooks test-results artifact name must be suffixed by "
        "matrix.split so both shards can upload in the same run"
    )
    assert re.search(r"name:\s*hooks-test-results\s*\n", text) is None, (
        "an un-suffixed 'hooks-test-results' artifact name is still present "
        "alongside (or instead of) the per-shard name"
    )


# ---------------------------------------------------------------------------
# AC1 — the ratchet job reads both shards
# ---------------------------------------------------------------------------


def test_ratchet_downloads_every_hooks_shard_artifact() -> None:
    """Falsifier: the download step's pattern only matches one shard's artifact."""
    text = _job_text(RATCHET_JOB_KEY)
    assert re.search(r"--pattern 'hooks-test-results-\*'", text), (
        "the ratchet job's artifact download step must glob "
        "'hooks-test-results-*' to pick up every shard; an exact "
        "'hooks-test-results' pattern matches none of the per-shard names"
    )


def test_ratchet_recursive_find_reads_both_shards_junit_reports(
    tmp_path: Path,
) -> None:
    """Falsifier: the enforcement step's file lookup does not span both shards.

    Reproduces the on-disk layout ``gh run download --dir junit-reports
    --pattern 'hooks-test-results-*'`` produces for two shards -- one
    subdirectory per matched artifact, named for the artifact -- and runs the
    literal ``find`` command extracted from the ratchet job's own step text
    against it.
    """
    text = _job_text(RATCHET_JOB_KEY)
    match = re.search(
        r"find junit-reports -name '" + re.escape(JUNIT_BASENAME) + r"' -type f",
        text,
    )
    assert match is not None, (
        f"the ratchet job no longer looks up {JUNIT_BASENAME} by this exact "
        "find invocation; update this test to match the new lookup"
    )

    junit_reports = tmp_path / "junit-reports"
    for shard in (1, 2):
        shard_dir = junit_reports / f"hooks-test-results-{shard}"
        shard_dir.mkdir(parents=True)
        (shard_dir / JUNIT_BASENAME).write_text(
            _junit(tests=3, skipped=1, prefix=str(shard)), encoding="utf-8"
        )

    command = match.group(0).replace("junit-reports", str(junit_reports))
    result = subprocess.run(
        ["bash", "-c", f"{command} | sort"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    found = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(found) == 2, (
        f"expected the find command to read both shards' {JUNIT_BASENAME}, "
        f"found {found!r} (stderr={result.stderr!r})"
    )


def test_ratchet_script_counts_skips_summed_across_both_shard_reports(
    tmp_path: Path,
) -> None:
    """Falsifier: the ratchet script under-counts when given two shard reports.

    A shard split is only safe if the thing being ratcheted -- the total
    skipped-test count -- is the SUM over both shards' reports, not just one.
    """
    shard_one = tmp_path / "junit-hooks-1.xml"
    shard_one.write_text(_junit(tests=20, skipped=5, prefix="1"), encoding="utf-8")
    shard_two = tmp_path / "junit-hooks-2.xml"
    shard_two.write_text(_junit(tests=20, skipped=7, prefix="2"), encoding="utf-8")

    baseline = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    registered = baseline["suites"].get("omniclaude/hooks-tests", {})
    max_skips = registered.get("max_skips")
    assert max_skips is not None, "omniclaude/hooks-tests must stay registered"

    result = _run_ratchet(
        "--baseline",
        str(BASELINE),
        "--suite",
        "omniclaude/hooks-tests",
        "--junit",
        str(shard_one),
        str(shard_two),
    )
    out = result.stdout + result.stderr
    # 12 combined skips must be compared against the real registered baseline,
    # never against one shard's 5 or 7 in isolation.
    if max_skips < 12:
        assert result.returncode != 0, (
            "12 combined skips exceeds the registered baseline "
            f"({max_skips}) but the ratchet did not fail: {out}"
        )
    else:
        assert result.returncode == 0, out
        assert "12" in out, f"expected the combined skip count (12) in output: {out}"
