# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18790 — one test per acceptance-criterion falsifier for omniclaude's skip-count ratchet.

Epic OMN-18775 measured, on 2026-09-18, that this repo's ``Hooks System Tests``
job skipped 36 tests on three consecutive runs — 36/36/36, byte-identical, and
the three SETS were identical rather than merely the same size. That stability
is itself the diagnostic: a count that never moves is a fixed set of tests that
never runs, on every run, forever, and nothing on the fleet notices when that
set grows.

The mechanism is the OMN-18776 ratchet, hand-vendored from omnibase_infra. These
tests are the falsifiers. Each is named for the claim it refuses; deleting one
deletes the proof of that acceptance criterion.

Two suites are registered here and they are deliberately in different modes,
chosen by measurement rather than by preference:

``omniclaude/hooks-tests`` (``count``)
    ``pytest tests/hooks/`` runs the whole directory with no selector in front
    of it, so the collected set is stable and the number is comparable.

``omniclaude/test-split`` (``nodeids``)
    the split matrix sits behind the impacted-test selector
    (``vars.ENABLE_SMART_TESTS`` is ``true`` live), whose narrowed runs collect
    6015 and skip 6 against a full-width 14793/43. Comparing counts there would
    false-fail on the selector, so identities are compared instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "skip_count_ratchet.py"
BASELINE = REPO_ROOT / "config" / "skip_count_baseline.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "skip_count_ratchet"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CI_SUMMARY_GATE = REPO_ROOT / "scripts" / "ci" / "ci_summary_gate.py"

HOOKS_SUITE = "omniclaude/hooks-tests"
SPLIT_SUITE = "omniclaude/test-split"
JOB_DISPLAY_NAME = "Skip Count Ratchet (OMN-18776)"

pytestmark = pytest.mark.unit


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )


def _junit(cases: list[tuple[str, bool]], collected: int) -> str:
    """Render a JUnit report. ``cases`` is (node_id, skipped) pairs."""
    body = []
    for node_id, skipped in cases:
        classname, _, name = node_id.rpartition("::")
        inner = "<skipped message='synthetic'/>" if skipped else ""
        body.append(
            f'<testcase classname="{classname}" name="{name}">{inner}</testcase>'
        )
    joined = "".join(body)
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites><testsuite name="pytest" errors="0" failures="0" '
        f'skipped="{sum(1 for _, s in cases if s)}" tests="{collected}" time="1.0">'
        f"{joined}</testsuite></testsuites>"
    )


def _entry(suite: str) -> dict[str, object]:
    loaded = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    entry = loaded["suites"][suite]
    assert isinstance(entry, dict)
    return entry


def _ids(suite: str) -> list[str]:
    ids = _entry(suite)["node_ids"]
    assert isinstance(ids, list)
    return [str(i) for i in ids]


# ---------------------------------------------------------------- AC1


def test_ac1_shipped_baseline_records_provenance_for_every_entry() -> None:
    """Falsifier: a baseline entry with no recorded provenance."""
    loaded = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    suites = loaded["suites"]
    assert suites, "positive control: the shipped baseline declares at least one suite"
    assert {HOOKS_SUITE, SPLIT_SUITE} <= set(suites)
    for key, entry in suites.items():
        provenance = entry.get("provenance")
        assert provenance, f"{key}: no provenance block"
        for field in (
            "measured_at",
            "measured_by",
            "measurement_command",
            "source_runs",
            "notes",
        ):
            assert provenance.get(field), (
                f"{key}: provenance.{field} is missing or empty"
            )


def test_ac1_entry_missing_provenance_is_refused(tmp_path: Path) -> None:
    """Falsifier control: the validator must actually reject a bare entry."""
    bare = tmp_path / "baseline.yaml"
    bare.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "suites": {
                    HOOKS_SUITE: {
                        "repo": "omniclaude",
                        "job": "Hooks System Tests",
                        "mode": "count",
                        "max_skips": 1,
                        "baseline_collected": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    junit = tmp_path / "j.xml"
    junit.write_text(_junit([("a.b::test_c", True)], 1), encoding="utf-8")
    result = _run(
        "--baseline", str(bare), "--suite", HOOKS_SUITE, "--junit", str(junit)
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "provenance" in (result.stdout + result.stderr)


# ---------------------------------------------------------------- AC2


@pytest.mark.parametrize("suite", [HOOKS_SUITE, SPLIT_SUITE])
def test_ac2_added_environmental_skip_fails_naming_repo_job_and_delta(
    suite: str, tmp_path: Path
) -> None:
    """Falsifier: a deliberately added environmentally-skipped test produces a green run."""
    entry = _entry(suite)
    cases: list[tuple[str, bool]] = [(i, True) for i in _ids(suite)]
    cases.append(("tests.ci.test_synthetic_omn18790::test_needs_absent_service", True))
    junit = tmp_path / "j.xml"
    junit.write_text(_junit(cases, int(entry["baseline_collected"])), encoding="utf-8")

    result = _run("--baseline", str(BASELINE), "--suite", suite, "--junit", str(junit))
    out = result.stdout + result.stderr
    assert result.returncode == 1, out
    assert "omniclaude" in out
    assert str(entry["job"]) in out
    assert "test_needs_absent_service" in out
    assert "+1" in out, "the failure must name the delta"


@pytest.mark.parametrize("suite", [HOOKS_SUITE, SPLIT_SUITE])
def test_ac2_positive_control_baseline_set_alone_passes(
    suite: str, tmp_path: Path
) -> None:
    """Positive control for the test above: without the added skip the run is green."""
    entry = _entry(suite)
    cases = [(i, True) for i in _ids(suite)]
    junit = tmp_path / "j.xml"
    junit.write_text(_junit(cases, int(entry["baseline_collected"])), encoding="utf-8")
    result = _run("--baseline", str(BASELINE), "--suite", suite, "--junit", str(junit))
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------- AC3


@pytest.mark.parametrize("suite", [HOOKS_SUITE, SPLIT_SUITE])
def test_ac3_removed_skip_passes_and_prints_a_ratchet_candidate(
    suite: str, tmp_path: Path
) -> None:
    """Falsifier: removing a skipped test turns the run red."""
    entry = _entry(suite)
    ids = _ids(suite)
    cases = [(i, True) for i in ids[:-1]]
    junit = tmp_path / "j.xml"
    junit.write_text(_junit(cases, int(entry["baseline_collected"])), encoding="utf-8")

    result = _run("--baseline", str(BASELINE), "--suite", suite, "--junit", str(junit))
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "RATCHET CANDIDATE" in out
    assert str(len(ids) - 1) in out, "the new lower number must be printed"


# ---------------------------------------------------------------- AC4


def test_ac4_ratchet_job_carries_no_continue_on_error() -> None:
    """Falsifier: `continue-on-error` appears anywhere in the new job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert JOB_DISPLAY_NAME in text, "positive control: the job is declared in ci.yml"
    workflow = yaml.safe_load(text)
    job = workflow["jobs"]["skip-count-ratchet"]
    assert "continue-on-error" not in job
    for step in job["steps"]:
        assert "continue-on-error" not in step, step.get("name")

    # The falsifier is a grep, so the raw block must not even mention the
    # setting in prose -- a comment naming it reads as a hit to the same probe
    # that is supposed to prove its absence.
    block = text.split("\n  skip-count-ratchet:\n", 1)[1].split("\n  # ====", 1)[0]
    assert "skip_count_ratchet.py" in block, "positive control: the block was located"
    assert "continue-on-error" not in block


def test_ac4_ratchet_job_is_registered_under_the_ci_summary_umbrella() -> None:
    """Falsifier: the context appears in neither enforcement surface.

    omniclaude's ``dev`` requires ``CI Summary``; a raw required context is
    deliberately NOT added, because branch protection would immediately block
    every in-flight pull request whose run predates the job. Registration in
    ``GATE_JOBS`` is the enforcement-equivalent surface, and
    ``STRICT_SUCCESS_JOBS`` is what makes a *skipped* job fail rather than pass
    — the same pairing the OMN-18031 route job carries here.
    """
    gate = CI_SUMMARY_GATE.read_text(encoding="utf-8")
    assert f'"{JOB_DISPLAY_NAME}"' in gate, (
        "omniclaude's CI Summary is the umbrella; an unregistered job that is "
        "skipped or absent yields SUCCESS"
    )
    gate_block = gate.split("GATE_JOBS: tuple[str, ...] = (", 1)[1].split("\n)", 1)[0]
    assert f'"{JOB_DISPLAY_NAME}"' in gate_block
    strict_block = gate.split("STRICT_SUCCESS_JOBS: frozenset[str] = frozenset(", 1)[
        1
    ].split("\n)", 1)[0]
    assert f'"{JOB_DISPLAY_NAME}"' in strict_block


def test_ac4_ratchet_job_is_unconditional() -> None:
    """A registered job that can legitimately skip wedges the umbrella; ours uses always()."""
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["skip-count-ratchet"]
    assert str(job.get("if", "")).strip() == "always()"


# ---------------------------------------------------------------- AC5
#
# The comparison mode was chosen by measurement, and these are the measurements.


@pytest.mark.parametrize(
    "fixture_name",
    ["hooks-run-35397791807.xml", "hooks-run-35396322080.xml"],
)
def test_ac5_hooks_count_mode_holds_across_real_consecutive_runs(
    fixture_name: str,
) -> None:
    """Falsifier: the 36/36/36 stability that justified `count` mode is not real.

    Both fixtures carry the real skipped-case set of a live ``Hooks System
    Tests`` run other than the one the baseline was measured from.
    """
    result = _run(
        "--baseline",
        str(BASELINE),
        "--suite",
        HOOKS_SUITE,
        "--junit",
        str(FIXTURES / fixture_name),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "PASS — at baseline" in out, (
        "count mode was chosen because these runs sit exactly at the baseline; "
        "a RATCHET CANDIDATE here would mean the measurement was wrong"
    )


@pytest.mark.parametrize(
    "fixture_name",
    ["narrowed-run-35404945505.xml", "narrowed-run-35396322080.xml"],
)
def test_ac5_selector_narrowed_real_runs_do_not_false_fail(fixture_name: str) -> None:
    """Falsifier: a run fails on a count the impacted-test selector explains.

    Both fixtures are the real skipped-case sets of two live selector-narrowed
    omniclaude split runs (6 unique skips over 6015 collected, against a
    full-width 43 over 14793).
    """
    result = _run(
        "--baseline",
        str(BASELINE),
        "--suite",
        SPLIT_SUITE,
        "--junit",
        str(FIXTURES / fixture_name),
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "narrowed selection" in out.lower()
    assert "RATCHET CANDIDATE" not in out, (
        "a narrowed run's lower count is the selector, not a ratchet opportunity"
    )


def test_ac5_positive_control_one_new_id_in_a_narrowed_run_still_fails(
    tmp_path: Path,
) -> None:
    """The zero above is not a broken probe: one unknown id in the same shape is red."""
    original = (FIXTURES / "narrowed-run-35404945505.xml").read_text(encoding="utf-8")
    injected = original.replace(
        "</testsuite>",
        '<testcase classname="tests.ci.test_control_omn18790" '
        'name="test_positive_control"><skipped message="synthetic"/></testcase>'
        "</testsuite>",
    )
    junit = tmp_path / "j.xml"
    junit.write_text(injected, encoding="utf-8")
    result = _run(
        "--baseline", str(BASELINE), "--suite", SPLIT_SUITE, "--junit", str(junit)
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "test_positive_control" in result.stdout + result.stderr


# ---------------------------------------------------------------- AC6


def test_ac6_parser_declares_no_override_option() -> None:
    """Falsifier: the argument parser declares any skip, force or baseline-override option.

    Lowering a baseline is an edit to the baseline file, reviewed like any other
    diff. A command-line lever would make it a decision one lane takes alone.
    """
    result = _run("--help")
    assert result.returncode == 0, result.stdout + result.stderr
    help_text = result.stdout.lower()
    forbidden = (
        "--force",
        "--skip",
        "--allow",
        "--ignore",
        "--override",
        "--no-fail",
        "--update-baseline",
        "--set-baseline",
        "--write-baseline",
        "--max-skips",
        "--tolerance",
        "--threshold",
        "--warn-only",
        "--advisory",
    )
    for option in forbidden:
        assert option not in help_text, f"{option} would make the ratchet optional"
    assert "--junit" in help_text, "positive control: the parser's help was read"


def test_ac6_no_environment_variable_lowers_the_verdict(tmp_path: Path) -> None:
    """An env var escape hatch is the same hole wearing a different hat."""
    entry = _entry(HOOKS_SUITE)
    cases = [(i, True) for i in _ids(HOOKS_SUITE)]
    cases.append(("tests.ci.test_synthetic_omn18790::test_env_escape", True))
    junit = tmp_path / "j.xml"
    junit.write_text(_junit(cases, int(entry["baseline_collected"])), encoding="utf-8")

    env_names = (
        "SKIP_COUNT_RATCHET",
        "SKIP_COUNT_RATCHET_FORCE",
        "SKIP_COUNT_RATCHET_ADVISORY",
        "ENABLE_SKIP_COUNT_RATCHET",
        "SKIP_RATCHET_OVERRIDE",
    )
    source = SCRIPT.read_text(encoding="utf-8")
    assert "os.environ" not in source and "getenv" not in source, (
        "the gate must read no environment variable at all"
    )
    for name in env_names:
        assert name not in source


# ------------------------------------------- AC7: the synthetic-empty defence
#
# omniclaude's ci.yml writes a SYNTHETIC EMPTY JUnit report
# (`tests="0" skipped="0"`) as a fallback when a suite's test files are not
# found, in both `hooks-tests` and `agent-framework-tests`. To a counter that is
# indistinguishable from a suite that ran and skipped nothing, so it would read
# as a clean zero and satisfy the gate forever while the suite ran no test at
# all — the exact false-green shape this gate exists to refuse. omniclaude
# therefore carries ONE addition over the omnibase_infra origin file: a
# nonzero-baseline suite whose reports collected zero tests is fail-closed
# input, never a pass.


def test_ac7_synthetic_empty_junit_is_refused_for_a_nonzero_baseline(
    tmp_path: Path,
) -> None:
    """Falsifier: the workflow's own empty-report fallback reads as a clean zero."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    synthetic = (
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        '<testsuite name="hooks" tests="0" errors="0" failures="0" skipped="0">'
        "</testsuite></testsuites>"
    )
    assert synthetic in workflow, (
        "positive control: this is the literal fallback report ci.yml writes; if "
        "this assertion fails the workflow changed and this defence must be "
        "re-aimed rather than deleted"
    )

    junit = tmp_path / "junit-hooks.xml"
    junit.write_text(synthetic, encoding="utf-8")
    result = _run(
        "--baseline", str(BASELINE), "--suite", HOOKS_SUITE, "--junit", str(junit)
    )
    out = result.stdout + result.stderr
    assert result.returncode == 2, out
    assert "collected 0 test" in out
    assert HOOKS_SUITE in out


def test_ac7_positive_control_a_real_report_with_the_same_zero_skips_passes(
    tmp_path: Path,
) -> None:
    """The refusal above is aimed at the EMPTY report, not at a zero skip count.

    A suite that genuinely collected its tests and skipped none is a ratchet
    candidate, not an error. Without this control the AC7 refusal could be a
    blanket "zero is bad" rule that would fire on real progress.
    """
    zero_baseline = tmp_path / "baseline.yaml"
    zero_baseline.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "suites": {
                    HOOKS_SUITE: {
                        "repo": "omniclaude",
                        "job": "Hooks System Tests",
                        "mode": "count",
                        "max_skips": 2,
                        "baseline_collected": 10,
                        "provenance": {
                            "measured_at": "2026-09-18",
                            "measured_by": "OMN-18790",
                            "measurement_command": "test fixture",
                            "source_runs": ["fixture"],
                            "notes": "fixture",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    junit = tmp_path / "j.xml"
    junit.write_text(
        _junit([(f"pkg.mod::test_{i}", False) for i in range(10)], 10), encoding="utf-8"
    )
    result = _run(
        "--baseline", str(zero_baseline), "--suite", HOOKS_SUITE, "--junit", str(junit)
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "RATCHET CANDIDATE" in out


def test_ac7_the_ratchet_job_reads_each_suite_from_its_own_reports() -> None:
    """Falsifier: one invocation over every report, where a peer suite masks an empty one.

    The AC7 refusal only bites if the empty report is a suite's SOLE input. A
    single invocation pooling ``junit-hooks.xml`` with the split matrix's
    reports would see a nonzero collection and never reach the refusal, so the
    per-suite invocation is load-bearing, not stylistic.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text.split("\n  skip-count-ratchet:\n", 1)[1].split("\n  # ====", 1)[0]

    # Derived from the baseline rather than hardcoded (OMN-18805 added a third
    # suite and a literal count made that a red test for the wrong reason). The
    # claim is one invocation per REGISTERED suite, so the baseline is the only
    # honest source for the number; a suite registered and then never invoked
    # here is exactly the drift this assertion exists to catch.
    registered = sorted(yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["suites"])
    assert block.count("skip_count_ratchet.py") == len(registered), (
        "each registered suite is enforced by its own invocation over its own "
        f"reports; the baseline registers {registered}"
    )
    for suite in registered:
        assert f"--suite {suite}" in block, (
            f"{suite} is registered in the baseline but never enforced by the job"
        )
    assert "junit-hooks.xml" in block
    assert "junit-test-" in block
    assert "junit-agent-framework.xml" in block


# ---------------------------------------------------------------- fail-closed


def test_missing_junit_input_fails_closed(tmp_path: Path) -> None:
    result = _run(
        "--baseline",
        str(BASELINE),
        "--suite",
        HOOKS_SUITE,
        "--junit",
        str(tmp_path / "nope.xml"),
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_unparsable_junit_fails_closed(tmp_path: Path) -> None:
    junit = tmp_path / "j.xml"
    junit.write_text("this is not xml", encoding="utf-8")
    result = _run(
        "--baseline", str(BASELINE), "--suite", HOOKS_SUITE, "--junit", str(junit)
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_unknown_suite_fails_closed(tmp_path: Path) -> None:
    junit = tmp_path / "j.xml"
    junit.write_text(_junit([("a.b::test_c", True)], 1), encoding="utf-8")
    result = _run(
        "--baseline", str(BASELINE), "--suite", "nope/nope", "--junit", str(junit)
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_selftest_mode_passes_and_is_what_the_pre_commit_hook_runs() -> None:
    result = _run("--selftest")
    assert result.returncode == 0, result.stdout + result.stderr
    hook_config = (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    assert "skip_count_ratchet.py --selftest" in hook_config


def test_vendored_from_omnibase_infra_names_its_origin() -> None:
    """There is no automated vendoring path in this estate; the header IS the convention.

    Every repo hand-maintains its own ``scripts/ci/`` copy of shared CI tooling
    (``ci_summary_gate.py`` is per-repo with no vendor marker anywhere). A copy
    that does not name where it came from cannot be reconciled with its origin
    later.
    """
    source = SCRIPT.read_text(encoding="utf-8")
    assert "omnibase_infra/scripts/ci/skip_count_ratchet.py" in source
    assert "OMN-18776" in source
