#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18776 — per-suite skip-count baseline ratchet (epic OMN-18775).

VENDORED into omniclaude under OMN-18790 from
``omnibase_infra/scripts/ci/skip_count_ratchet.py`` (PR #3797, squash
``77ea8d01``). There is no automated vendoring path in this estate — every repo
hand-maintains its own ``scripts/ci/`` copy of shared CI tooling, the same way
``ci_summary_gate.py`` is per-repo with no vendor marker anywhere — so this
header IS the vendoring convention. Keep the two files reconcilable by diff.

A skipped test reports nothing. A *set* of tests that skips on every run, for
months, reports nothing and nobody notices, because a green job name looks
identical whether the test ran or was collected and dropped.

Epic OMN-18775 measured this on 2026-09-18. Five per-repo skip counts were
byte-identical across three consecutive CI runs each (17/17/17, 42/42/42,
36/36/36, 26/26/26, 13/13/13). Perfect stability is the diagnostic: a count
that never moves is a fixed set of tests that never runs. The cost is already
paid — 91 PostgreSQL-16 cutover cases were collected and skipped on every
full-matrix run for 49 days (omnibase_infra#2547 → OMN-18762) and no skip
surface anywhere registered it.

This gate refuses the *growth* of that set.

Two comparison modes, because one number does not fit both shapes of CI
-----------------------------------------------------------------------
``count``
    For a suite whose collected set is the same on every run. The observed
    count of unique skipped tests may not exceed ``max_skips``.

``nodeids``
    For a suite behind an impacted-test selector, where the collected set —
    and therefore the raw skip count — legitimately varies run to run
    (omniclaude's split matrix measured 6 unique skips over 6015 collected on
    a selector-narrowed run against 43 over 14793 on a full-width one).
    Comparing counts there produces false failures, so
    this mode compares the *identities*: every skipped test must already be in
    the baseline set. A selector can only ever narrow the collected set, so a
    narrowed run's skip set is a subset of the full-suite baseline and cannot
    false-fail; a newly added environmentally-skipped test is not in the set
    and turns the run red. Verified against two real narrowed runs (0 ids
    outside the baseline) with an injected-id positive control (1).

Lowering a baseline is an edit to ``config/skip_count_baseline.yaml``, reviewed
like any other diff. There is deliberately no command-line and no environment
lever that lowers a verdict — see ``tests/ci/test_skip_count_ratchet_omn18790.py``,
which reads this parser's own option strings and this file's own source.

Honest limit: this counts skips, it does not judge them. A test skipped for a
good structural reason and one skipped because CI never set its env var look
identical to a counter. What the ratchet removes is the silent growth of the
set, not the set.

Usage
-----
    skip_count_ratchet.py --suite KEY --junit FILE [FILE ...] [--baseline FILE]
    skip_count_ratchet.py --suite KEY --junit FILE ... --print-observed
    skip_count_ratchet.py --selftest

``--print-observed`` renders the observed set as a baseline-shaped YAML block on
stdout for a human to paste into the baseline file. It reaches no verdict and
writes no file.

Exit codes: 0 = within baseline; 1 = the skip set grew; 2 = usage or input error
(fail-closed — an absent, unparsable or unregistered input is a failure, never a
pass).

ONE DIVERGENCE FROM THE ORIGIN FILE (OMN-18790), deliberately
-------------------------------------------------------------
omniclaude's ci.yml writes a SYNTHETIC EMPTY JUnit report
(``tests="0" skipped="0"``) as a fallback when a suite's test files are not
found. To a counter that is indistinguishable from a suite that ran and skipped
nothing, so it would read as a clean zero and satisfy this gate forever while
the suite ran no test at all. :func:`refuse_empty_observation` refuses it: a
suite whose recorded baseline collected more than zero, observed collecting
zero, is fail-closed input. This belongs upstream too; it is written as a
generic rule, not an omniclaude special case.

SYNC: ci.yml job ``skip-count-ratchet`` + GATE_JOBS and STRICT_SUCCESS_JOBS
entries in scripts/ci/ci_summary_gate.py + pre-commit hook
``skip-count-ratchet``. Origin: omnibase_infra/scripts/ci/skip_count_ratchet.py.
"""

from __future__ import annotations

import argparse
import sys
import tempfile

# The parse call in `observe` carries the justification for both B405 and B314.
import xml.etree.ElementTree as ET  # nosec B405
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

_DEFAULT_BASELINE = (
    Path(__file__).resolve().parents[2] / "config" / "skip_count_baseline.yaml"
)

_REQUIRED_PROVENANCE_FIELDS = ("measured_at", "measurement_command", "source_runs")
_MODES = ("count", "nodeids")

EXIT_OK = 0
EXIT_RATCHET = 1
EXIT_INPUT = 2


class InputError(Exception):
    """Fail-closed condition: the gate could not reach a trustworthy verdict."""


@dataclass(frozen=True)
class BaselineEntry:
    """One registered suite: what it is, what it may skip, and how that was measured."""

    key: str
    repo: str
    job: str
    mode: str
    max_skips: int
    baseline_collected: int
    node_ids: frozenset[str]

    @classmethod
    def load(cls, path: Path, key: str) -> BaselineEntry:
        if not path.is_file():
            raise InputError(f"baseline file not found: {path}")
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:  # pragma: no cover - defensive
            raise InputError(f"baseline file is not parsable YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise InputError(f"baseline file is not a mapping: {path}")
        suites = raw.get("suites")
        if not isinstance(suites, dict):
            raise InputError(f"baseline file declares no `suites` mapping: {path}")
        entry = suites.get(key)
        if not isinstance(entry, dict):
            raise InputError(
                f"suite {key!r} is not registered in {path}. "
                f"Registered suites: {', '.join(sorted(suites)) or '(none)'}"
            )

        provenance = entry.get("provenance")
        if not isinstance(provenance, dict):
            raise InputError(
                f"suite {key!r} carries no provenance block. A baseline number "
                f"with no recorded measurement is a claim, not a measurement."
            )
        for field in _REQUIRED_PROVENANCE_FIELDS:
            if not provenance.get(field):
                raise InputError(
                    f"suite {key!r}: provenance.{field} is missing or empty"
                )

        mode = str(entry.get("mode", ""))
        if mode not in _MODES:
            raise InputError(
                f"suite {key!r}: mode must be one of {_MODES}, got {mode!r}"
            )
        node_ids = entry.get("node_ids") or []
        if not isinstance(node_ids, list):
            raise InputError(f"suite {key!r}: node_ids must be a list")
        if mode == "nodeids" and not node_ids:
            raise InputError(
                f"suite {key!r}: mode `nodeids` needs a recorded node_ids set"
            )
        try:
            max_skips = int(entry["max_skips"])
            baseline_collected = int(entry["baseline_collected"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InputError(
                f"suite {key!r}: max_skips and baseline_collected must both be integers"
            ) from exc
        if mode == "nodeids" and max_skips != len(set(node_ids)):
            raise InputError(
                f"suite {key!r}: max_skips ({max_skips}) disagrees with the recorded "
                f"node_ids set ({len(set(node_ids))} unique). The two must be written "
                f"together or the count half of the report lies."
            )
        repo = str(entry.get("repo", "") or "")
        job = str(entry.get("job", "") or "")
        if not repo or not job:
            raise InputError(f"suite {key!r}: both `repo` and `job` are required")

        return cls(
            key=key,
            repo=repo,
            job=job,
            mode=mode,
            max_skips=max_skips,
            baseline_collected=baseline_collected,
            node_ids=frozenset(str(i) for i in node_ids),
        )


@dataclass(frozen=True)
class Observation:
    """What one run's JUnit reports actually said."""

    skipped: frozenset[str]
    collected: int
    files: int

    @property
    def count(self) -> int:
        return len(self.skipped)


def node_id(testcase: ET.Element) -> str:
    """The stable identity of a test case across runs and splits."""
    classname = (testcase.get("classname") or "").strip()
    name = (testcase.get("name") or "").strip()
    return f"{classname}::{name}" if classname else name


def observe(paths: list[Path]) -> Observation:
    """Read every JUnit report and return the unique skipped set plus collection size.

    Unique, not summed: a module-level skip is re-reported by every split that
    collected the module (measured: 5 ids appearing 15 times each in one run),
    so a sum would count the same never-run test fifteen times.
    """
    if not paths:
        raise InputError("no JUnit reports named; refusing to report a verdict")
    skipped: set[str] = set()
    collected = 0
    for path in paths:
        if not path.is_file():
            raise InputError(f"JUnit report not found: {path}")
        try:
            # Justification: the input is a JUnit report this same workflow run
            # produced and uploaded, fetched by run id through the GitHub
            # artifact API, never a caller-supplied path in CI. Stdlib
            # ElementTree does not resolve external entities, so XXE is not
            # reachable; the residual is expansion/nesting DoS against a job
            # that is already running that same PR's test code, under its own
            # timeout. Parse errors are caught below and fail CLOSED.
            root = ET.parse(path).getroot()  # noqa: S314  # nosec B314
        except ET.ParseError as exc:
            raise InputError(
                f"JUnit report is not parsable XML: {path}: {exc}"
            ) from exc
        for suite in root.iter("testsuite"):
            try:
                collected += int(suite.get("tests", 0) or 0)
            except ValueError as exc:
                raise InputError(f"{path}: testsuite/@tests is not an integer") from exc
        for testcase in root.iter("testcase"):
            if testcase.find("skipped") is not None:
                skipped.add(node_id(testcase))
    return Observation(
        skipped=frozenset(skipped), collected=collected, files=len(paths)
    )


def refuse_empty_observation(entry: BaselineEntry, observed: Observation) -> None:
    """OMN-18790: a nonzero-baseline suite that collected NOTHING is fail-closed input.

    A workflow that writes a placeholder JUnit report when it finds no test
    files — ``tests="0" skipped="0"`` — hands this gate a document that is
    indistinguishable, to a counter, from a suite that ran and skipped nothing.
    It would read as a clean zero and satisfy the baseline forever while the
    suite executed no test at all: the same false-green shape the ratchet
    exists to refuse, arriving through the gate's own input.

    This is deliberately narrow. It fires only when the RECORDED baseline
    collected more than zero and the OBSERVED run collected zero, so a suite
    that genuinely skips nothing is still a ratchet candidate rather than an
    error, and a suite legitimately baselined at zero is untouched.
    """
    if entry.baseline_collected > 0 and observed.collected == 0:
        raise InputError(
            f"suite {entry.key!r} ({entry.repo} / {entry.job}) collected 0 tests "
            f"across {observed.files} JUnit report(s), against a recorded baseline "
            f"of {entry.baseline_collected}. An empty report is not an empty "
            f"result: it is the shape a workflow writes when it finds no test "
            f"files, and reading it as zero skips would satisfy this gate while "
            f"the suite ran nothing. Failing closed."
        )


def evaluate(entry: BaselineEntry, observed: Observation) -> tuple[int, list[str]]:
    """Return (exit code, report lines). Pure — no I/O, no clock, no environment."""
    lines: list[str] = [
        "================================================================",
        f"Skip Count Ratchet (OMN-18776) — {entry.key}",
        f"  repo          : {entry.repo}",
        f"  job           : {entry.job}",
        f"  mode          : {entry.mode}",
        f"  observed      : {observed.count} unique skipped / {observed.collected} "
        f"collected, across {observed.files} JUnit report(s)",
        f"  baseline      : {entry.max_skips} unique skipped / "
        f"{entry.baseline_collected} collected",
        "================================================================",
    ]

    if entry.mode == "nodeids":
        new_ids = sorted(observed.skipped - entry.node_ids)
        if new_ids:
            lines.append(
                f"::error::{entry.repo} / {entry.job}: the skipped set GREW by "
                f"{len(new_ids)} test(s) (delta +{len(new_ids)}; "
                f"{observed.count} observed against a baseline of {entry.max_skips}). "
                f"These tests are collected and never executed, and are not in "
                f"config/skip_count_baseline.yaml:"
            )
            lines.extend(f"    + {i}" for i in new_ids)
            lines.append(
                "  Either make the test run, or record it in the baseline with its "
                "provenance and say in the PR why it may never execute."
            )
            return EXIT_RATCHET, lines

        narrowed = observed.collected < entry.baseline_collected
        if narrowed:
            lines.append(
                f"  PASS — narrowed selection: the impacted-test selector collected "
                f"{observed.collected} of the baseline's {entry.baseline_collected}, "
                f"so {observed.count} of {entry.max_skips} baseline skips were "
                f"observed. Not a ratchet candidate; the lower number is the "
                f"selector, not progress."
            )
            return EXIT_OK, lines
        if observed.count < entry.max_skips:
            retired = sorted(entry.node_ids - observed.skipped)
            lines.append(
                f"  RATCHET CANDIDATE — a full-width run skipped {observed.count}, "
                f"below the baseline of {entry.max_skips}. Lower `max_skips` to "
                f"{observed.count} in config/skip_count_baseline.yaml and drop these "
                f"{len(retired)} id(s):"
            )
            lines.extend(f"    - {i}" for i in retired[:25])
            if len(retired) > 25:
                lines.append(f"    ... and {len(retired) - 25} more")
            return EXIT_OK, lines
        lines.append(f"  PASS — at baseline ({observed.count} of {entry.max_skips}).")
        return EXIT_OK, lines

    # mode == "count"
    if observed.count > entry.max_skips:
        delta = observed.count - entry.max_skips
        lines.append(
            f"::error::{entry.repo} / {entry.job}: skip count {observed.count} "
            f"exceeds the baseline {entry.max_skips} (delta +{delta})."
        )
        if entry.node_ids:
            new_ids = sorted(observed.skipped - entry.node_ids)
            lines.extend(f"    + {i}" for i in new_ids)
        return EXIT_RATCHET, lines
    if observed.count < entry.max_skips:
        lines.append(
            f"  RATCHET CANDIDATE — skip count {observed.count} is below the "
            f"baseline of {entry.max_skips}. Lower `max_skips` to {observed.count} "
            f"in config/skip_count_baseline.yaml."
        )
        return EXIT_OK, lines
    lines.append(f"  PASS — at baseline ({observed.count} of {entry.max_skips}).")
    return EXIT_OK, lines


def render_observed(entry_key: str, observed: Observation) -> str:
    """A baseline-shaped block for a human to paste. Reaches no verdict."""
    block = {
        "suites": {
            entry_key: {
                "max_skips": observed.count,
                "baseline_collected": observed.collected,
                "node_ids": sorted(observed.skipped),
            }
        }
    }
    return yaml.safe_dump(block, sort_keys=True, default_flow_style=False)


def _selftest() -> int:
    """Drive the gate's own logic over synthetic reports. No network, no DB.

    The case that matters is (b): a reintroduced environmentally-skipped test
    MUST turn the gate red. A selftest that only proves the green path proves
    that the gate can pass, which was never in doubt.
    """
    baseline_ids = ["pkg.mod_a::test_one", "pkg.mod_b::test_two"]
    baseline = {
        "version": 1,
        "suites": {
            "selftest/nodeids": {
                "repo": "selftest",
                "job": "Selftest",
                "mode": "nodeids",
                "max_skips": len(baseline_ids),
                "baseline_collected": 100,
                "node_ids": baseline_ids,
                "provenance": {
                    "measured_at": "2026-09-18",
                    "measurement_command": "selftest",
                    "source_runs": ["selftest"],
                },
            },
            "selftest/count": {
                "repo": "selftest",
                "job": "Selftest Count",
                "mode": "count",
                "max_skips": 2,
                "baseline_collected": 100,
                "provenance": {
                    "measured_at": "2026-09-18",
                    "measurement_command": "selftest",
                    "source_runs": ["selftest"],
                },
            },
        },
    }

    def junit(ids: list[str], collected: int) -> str:
        cases = "".join(
            f'<testcase classname="{i.rpartition("::")[0]}" '
            f'name="{i.rpartition("::")[2]}"><skipped message="s"/></testcase>'
            for i in ids
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?><testsuites>'
            f'<testsuite name="pytest" errors="0" failures="0" skipped="{len(ids)}" '
            f'tests="{collected}" time="1.0">{cases}</testsuite></testsuites>'
        )

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        baseline_path = root / "baseline.yaml"
        baseline_path.write_text(yaml.safe_dump(baseline), encoding="utf-8")

        cases: list[tuple[str, str, list[str], int, int]] = [
            ("nodeids: at baseline is green", "selftest/nodeids", baseline_ids, 100, 0),
            (
                "nodeids: a NEW skipped id is RED",
                "selftest/nodeids",
                [*baseline_ids, "pkg.mod_c::test_new"],
                100,
                1,
            ),
            (
                "nodeids: a narrowed selection is green",
                "selftest/nodeids",
                baseline_ids[:1],
                40,
                0,
            ),
            (
                "nodeids: a full-width run below baseline is green",
                "selftest/nodeids",
                baseline_ids[:1],
                100,
                0,
            ),
            ("count: at baseline is green", "selftest/count", baseline_ids, 100, 0),
            (
                "count: one over baseline is RED",
                "selftest/count",
                [*baseline_ids, "pkg.mod_c::test_new"],
                100,
                1,
            ),
        ]
        for label, suite_key, ids, collected, expected in cases:
            report = root / f"{abs(hash(label))}.xml"
            report.write_text(junit(ids, collected), encoding="utf-8")
            entry = BaselineEntry.load(baseline_path, suite_key)
            code, _ = evaluate(entry, observe([report]))
            if code != expected:
                failures.append(f"{label}: expected exit {expected}, got {code}")

        # Fail-closed inputs must never read as a pass.
        fail_closed_cases: tuple[tuple[str, Callable[[], Observation]], ...] = (
            ("an absent report is exit 2", lambda: observe([root / "absent.xml"])),
            ("no reports at all is exit 2", lambda: observe([])),
        )
        for label, thunk in fail_closed_cases:
            try:
                thunk()
            except InputError:
                continue
            failures.append(f"{label}: did not raise")

        # OMN-18790: the synthetic-empty report must never read as a clean zero.
        empty_report = root / "empty.xml"
        empty_report.write_text(
            '<?xml version="1.0" encoding="utf-8"?><testsuites>'
            '<testsuite name="hooks" tests="0" errors="0" failures="0" '
            'skipped="0"></testsuite></testsuites>',
            encoding="utf-8",
        )
        count_entry = BaselineEntry.load(baseline_path, "selftest/count")
        try:
            refuse_empty_observation(count_entry, observe([empty_report]))
        except InputError:
            pass
        else:
            failures.append("an empty report was accepted for a nonzero baseline")
        # ... and the refusal must not fire on a run that really skipped nothing.
        real_report = root / "real-zero-skips.xml"
        real_report.write_text(junit([], 100), encoding="utf-8")
        try:
            refuse_empty_observation(count_entry, observe([real_report]))
        except InputError as exc:
            failures.append(f"the empty-report refusal over-fired: {exc}")

        bare = root / "bare.yaml"
        bare.write_text(
            yaml.safe_dump(
                {
                    "version": 1,
                    "suites": {
                        "bare/entry": {
                            "repo": "r",
                            "job": "j",
                            "mode": "count",
                            "max_skips": 0,
                            "baseline_collected": 0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        try:
            BaselineEntry.load(bare, "bare/entry")
        except InputError:
            pass
        else:
            failures.append("a provenance-less baseline entry was accepted")

    # The synthetic cases above prove the LOGIC. This proves the SHIPPED file:
    # every registered suite loads, which is where provenance, mode and the
    # count/node_ids agreement are enforced.
    shipped = 0
    if _DEFAULT_BASELINE.is_file():
        raw = yaml.safe_load(_DEFAULT_BASELINE.read_text(encoding="utf-8")) or {}
        suites = raw.get("suites") or {}
        if not suites:
            failures.append(f"{_DEFAULT_BASELINE} registers no suites")
        for key in suites:
            try:
                BaselineEntry.load(_DEFAULT_BASELINE, str(key))
            except InputError as exc:
                failures.append(f"shipped baseline suite {key!r}: {exc}")
            else:
                shipped += 1

    if failures:
        print("skip-count-ratchet selftest FAILED:")
        for line in failures:
            print(f"  - {line}")
        return EXIT_RATCHET
    print(
        f"skip-count-ratchet selftest OK: 6 verdict cases, 5 fail-closed cases, "
        f"{shipped} shipped baseline suite(s) validated."
    )
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    """The parser declares no lever that lowers a verdict. That is load-bearing."""
    parser = argparse.ArgumentParser(
        prog="skip_count_ratchet.py",
        description=(
            "Refuse a run whose set of never-executed tests grew beyond the "
            "recorded baseline. Lowering a baseline is an edit to the baseline "
            "file, never a flag on this command."
        ),
    )
    parser.add_argument(
        "--suite",
        help="baseline key for the suite under test, e.g. omnibase_infra/test-parallel",
    )
    parser.add_argument(
        "--junit",
        nargs="+",
        default=[],
        type=Path,
        help="pytest JUnit-XML report(s) produced by that suite's run",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=_DEFAULT_BASELINE,
        help="path to the baseline file (default: config/skip_count_baseline.yaml)",
    )
    parser.add_argument(
        "--print-observed",
        action="store_true",
        help=(
            "print the observed set as a baseline-shaped YAML block for a human to "
            "paste; reaches no verdict and writes no file"
        ),
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the gate's own logic over synthetic reports (what pre-commit runs)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.selftest:
        return _selftest()

    try:
        if not args.suite:
            raise InputError("--suite is required")
        observed = observe(list(args.junit))
        if args.print_observed:
            print(render_observed(args.suite, observed))
            return EXIT_OK
        entry = BaselineEntry.load(args.baseline, args.suite)
        refuse_empty_observation(entry, observed)
    except InputError as exc:
        print(f"::error::skip-count-ratchet input error (fail-closed): {exc}")
        return EXIT_INPUT

    code, lines = evaluate(entry, observed)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
