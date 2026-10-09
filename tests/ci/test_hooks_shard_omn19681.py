# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19681 — the ``Hooks System Tests`` job is a duration-planned 3-way
matrix, and the OMN-18776 skip-count ratchet still counts every hooks case
across all shards.

Plan task A5 (knowledge-base-internal
``beta/plans/2026-09-25-golden-chain-event-tests-for-pr-validation-plan.md``,
section 5 Part A) measured the unsharded ``Hooks System Tests`` job's pytest
step at 10.2 minutes in CI run 36187640881, on the critical path of every
omniclaude PR. A 2-way split by test count left shard 1 at 1.6-2.2x shard 2,
and the interleaving rebalance that followed (``least_duration`` without
timings) still ran 220-540 s per shard on PR runs 37915819364-37940464442. The
suite totals 586-749 s of test time on those runs, so even two perfectly
balanced shards sit at 293-375 s plus session overhead, around the 360 s bar
(acceptance AC2). The job is therefore 3 shards planned by the workflow's own
plan step from the committed ``config/hooks_test_file_durations.json``.

The ratchet job (``skip-count-ratchet``, OMN-18776) downloads that job's JUnit
artifacts by name and counts skipped tests in them; a shard split that is not
matched by a corresponding artifact-download and count-source change would
either silently stop counting one shard's skips, or fail closed with no report
at all. Each test below is named for the falsifier it refuses.
"""

from __future__ import annotations

import json
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
SHARDS = 3
DURATIONS = REPO_ROOT / "config" / "hooks_test_file_durations.json"
PLAN_STEP = "Plan this shard's hooks test files (OMN-19681)"
PLANNED_SPREAD_LIMIT = 1.1
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
# AC1 — the job is a 3-way matrix
# ---------------------------------------------------------------------------


def test_hooks_tests_job_is_a_three_way_matrix() -> None:
    """Falsifier: the job carries no ``strategy.matrix.split`` of length 3."""
    job = _job(HOOKS_JOB_KEY)
    assert "strategy" in job, (
        "Hooks System Tests has no strategy block -- it still runs "
        "tests/hooks/ as one unsharded job."
    )
    matrix = job["strategy"].get("matrix", {})
    assert matrix.get("split") == list(range(1, SHARDS + 1)), (
        "Hooks System Tests must declare a 3-way split matrix (split: [1, 2, 3]); "
        f"found matrix={matrix!r}"
    )


def test_hooks_tests_job_name_reports_its_shard() -> None:
    """Falsifier: the job's display name does not vary by matrix.split."""
    job = _job(HOOKS_JOB_KEY)
    assert "${{ matrix.split }}" in job["name"], (
        "the job name must include the shard index so two parallel runs are "
        f"distinguishable in the Actions UI; found name={job['name']!r}"
    )


def test_hooks_tests_run_only_the_files_the_plan_step_assigned() -> None:
    """Falsifier: the pytest step still runs the whole directory, or a pytest-split slice.

    The plan step writes the shard's file list; the pytest step must read that
    exact list and carry no ``--splits``/``--group`` of its own, or every shard
    would run (and collect) the whole tree again.
    """
    steps = _job(HOOKS_JOB_KEY)["steps"]
    plan = next(step for step in steps if step.get("name") == PLAN_STEP)
    run = next(step for step in steps if step.get("name") == "Run hooks tests")
    assert steps.index(plan) < steps.index(run)
    assert "--splits" not in run["run"]
    assert "--group" not in run["run"]
    assert "tests/hooks/ " not in run["run"]
    listing = re.search(r">\s*(\.\S+)", plan["run"])
    assert listing is not None, "the plan step must write the shard's file list"
    assert listing.group(1) in run["run"], "the pytest step must read that list"
    assert f'"${{{{ matrix.split }}}}" {SHARDS}' in plan["run"]


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
# AC1 — the ratchet job reads every shard
# ---------------------------------------------------------------------------


def test_ratchet_downloads_every_hooks_shard_artifact() -> None:
    """Falsifier: the download step's pattern only matches one shard's artifact."""
    text = _job_text(RATCHET_JOB_KEY)
    assert re.search(r"--pattern 'hooks-test-results-\*'", text), (
        "the ratchet job's artifact download step must glob "
        "'hooks-test-results-*' to pick up every shard; an exact "
        "'hooks-test-results' pattern matches none of the per-shard names"
    )


def test_ratchet_recursive_find_reads_every_shards_junit_reports(
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
    for shard in range(1, SHARDS + 1):
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
    assert len(found) == SHARDS, (
        f"expected the find command to read every shard's {JUNIT_BASENAME}, "
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


def _planner_source() -> str:
    """The python the plan step feeds ``uv run python -`` (its heredoc body)."""
    step = next(
        step for step in _job(HOOKS_JOB_KEY)["steps"] if step.get("name") == PLAN_STEP
    )
    match = re.search(r"<<'PY'\n(.*?)\nPY\n", step["run"], re.S)
    assert match is not None, "the plan step has no PY heredoc"
    return match.group(1)


def _plan(
    root: Path, group: int, splits: int = SHARDS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _planner_source(), str(group), str(splits)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def _tree(root: Path, files: dict[str, float], extra: list[str]) -> None:
    (root / "config").mkdir()
    (root / "config" / DURATIONS.name).write_text(json.dumps(files), encoding="utf-8")
    for name in [*files, *extra]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")


def test_hooks_plan_assigns_every_file_exactly_once_and_an_unrecorded_one_too(
    tmp_path: Path,
) -> None:
    """Falsifier: a test file runs in no shard or in two, recorded or not."""
    recorded = {
        f"tests/hooks/test_{name}.py": float(weight)
        for name, weight in zip("abcdefg", (50, 40, 30, 20, 10, 5, 1), strict=True)
    }
    _tree(
        tmp_path,
        recorded,
        [
            "tests/hooks/test_brand_new.py",
            "tests/hooks/sub/check_x_test.py",
            "tests/hooks/helper.py",
        ],
    )
    planned = []
    for group in range(1, SHARDS + 1):
        result = _plan(tmp_path, group)
        assert result.returncode == 0, result.stderr
        planned.append(result.stdout.split())
    flat = sorted(name for shard in planned for name in shard)
    assert flat == sorted(
        [*recorded, "tests/hooks/test_brand_new.py", "tests/hooks/sub/check_x_test.py"]
    )
    # The heaviest recorded file is not stacked with the next heaviest.
    assert not {"tests/hooks/test_a.py", "tests/hooks/test_b.py"} <= set(planned[0])


def test_hooks_plan_is_the_same_on_every_runner(tmp_path: Path) -> None:
    _tree(tmp_path, {f"tests/hooks/test_{i}.py": 1.0 for i in range(9)}, [])
    first = [_plan(tmp_path, group).stdout for group in range(1, SHARDS + 1)]
    assert first == [_plan(tmp_path, group).stdout for group in range(1, SHARDS + 1)]


def test_hooks_plan_refuses_a_shard_with_no_files(tmp_path: Path) -> None:
    """Falsifier: an empty shard runs pytest with no paths, i.e. the whole default tree."""
    _tree(tmp_path, {"tests/hooks/test_only.py": 1.0}, [])
    result = _plan(tmp_path, 3)
    assert result.returncode != 0
    assert "has no test files" in result.stderr


def test_hooks_plan_is_exactly_the_set_of_files_pytest_collects() -> None:
    """Falsifier: the plan's discovery drifts from pytest's, dropping a file.

    Runs the plan step's own script over the real ``tests/hooks`` tree for all
    three shards and compares the union with the files a real
    ``pytest --collect-only`` reports. Positive controls: the union is large and
    each file appears in exactly one shard.
    """
    collected = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/hooks",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-cov",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert collected.returncode == 0, (
        collected.stdout[-2000:] + collected.stderr[-2000:]
    )
    expected = {
        line.split("::", 1)[0]
        for line in collected.stdout.splitlines()
        if "::" in line and line.startswith("tests/")
    }
    assert len(expected) > 150
    planned: list[str] = []
    for group in range(1, SHARDS + 1):
        result = _plan(REPO_ROOT, group)
        assert result.returncode == 0, result.stderr
        planned += result.stdout.split()
    assert len(planned) == len(set(planned)), "a file is in two shards"
    assert expected <= set(planned), sorted(expected - set(planned))


def test_hooks_plan_balances_the_committed_record_within_the_bar() -> None:
    """Falsifier: a stale or lopsided record leaves one shard over the 6 minute bar."""
    record: dict[str, float] = json.loads(DURATIONS.read_text(encoding="utf-8"))
    assert len(record) > 150, "the committed record is truncated"
    totals = []
    for group in range(1, SHARDS + 1):
        result = _plan(REPO_ROOT, group)
        assert result.returncode == 0, result.stderr
        files = result.stdout.split()
        totals.append(sum(record.get(name, 0.0) for name in files))
    assert max(totals) / min(totals) <= PLANNED_SPREAD_LIMIT, totals
    # AC2 allows 360 s for a shard's whole pytest step, session overhead included.
    assert max(totals) <= 300, totals


@pytest.mark.parametrize("report_count", [0, 1, 2, 3, 4])
def test_ratchet_refuses_incomplete_hooks_shard_reports(
    tmp_path: Path,
    report_count: int,
) -> None:
    step = next(
        step
        for step in _job(RATCHET_JOB_KEY)["steps"]
        if step.get("name") == "Enforce the skip-count baseline — Hooks System Tests"
    )
    # Execute the workflow's report admission check before the ratchet command.
    admission = step["run"].split("uv run", 1)[0]
    for shard in range(report_count):
        directory = tmp_path / "junit-reports" / f"hooks-test-results-{shard + 1}"
        directory.mkdir(parents=True)
        (directory / JUNIT_BASENAME).write_text(_junit(2, prefix=str(shard)))
    (tmp_path / "junit-reports").mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", "-e", "-c", admission],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) == (report_count == SHARDS), (
        f"expected exactly {SHARDS} hooks reports, found {report_count}: "
        + result.stdout
        + result.stderr
    )
    if report_count == SHARDS:
        assert f"Reading {SHARDS} JUnit report(s)." in result.stdout
