# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for OMN-18263 -- the branch-claim resolution and the check that records it.

WHAT THIS PINS. One resolution, consumed twice. The pull-request check (OMN-18263)
and the pre-push hook (OMN-18262) must answer the same question the same way, so
the comparison lives in exactly one function and both callers pass through it. A
second implementation of the same comparison is a second place for it to drift,
which is the acceptance criterion's own wording.

THE FOUR FIXTURES THE BRIEF NAMES, and why each is a distinct case rather than a
variation:

  * held by the SAME lane                      -- clean; the common case, and a
                                                  check that fired here would be
                                                  a tax on ordinary work
  * held by ANOTHER lane WITH a release row     -- clean; this is the proof that
                                                  the release path actually
                                                  clears the refusal, which is
                                                  the risk OMN-18262 has to
                                                  retire before it may refuse
  * held by ANOTHER lane WITHOUT a release row  -- FINDING; the 2026-09-12 14:17Z
                                                  shape exactly
  * unclaimed                                   -- clean, deliberately; §6 of the
                                                  design makes an absent claim a
                                                  non-event, because requiring a
                                                  claim for every push turns a
                                                  coordination mechanism into a
                                                  tax, and a tax gets routed
                                                  around

AND THE CASE THAT IS NOT ONE OF THE FOUR: commits carrying no lane trailer must
NOT read as clean. Measured 2026-09-13, that is every commit in the fleet, so a
resolution that treated "no identity" as "no problem" would report green over
the entire corpus while proving nothing.

Design of record: the OMN-18259 lane-identity and claim-index design, sections 3
through 7.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts import branch_claim as bc
from scripts import lane_identity as li

NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)
LEDGER_NAME = "docs/tracking/ROLLING_WORK_LEDGER.md"


def _stamp(offset_hours: float = 0.0) -> str:
    return (NOW - timedelta(hours=offset_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim_index_module() -> Path:
    """Where the claim index module is, resolved fail-fast.

    There is deliberately no fallback and no skip. The module lives in the
    private workspace repository; a test that SKIPPED when it could not be found
    would turn "the gate could not run" into a green run, which is the precise
    failure this whole phase exists to remove.
    """
    explicit = os.environ.get("ONEX_CLAIM_INDEX_MODULE")
    if explicit:
        # Resolved, never passed through as given. The hook tests hand this path
        # to a `git push` running in a scratch clone elsewhere on disk, so a
        # relative value would resolve against a different directory there than
        # here -- which is exactly how ten of them failed the first time they ran
        # in continuous integration.
        return Path(explicit).resolve()
    workspace = os.environ.get("OMNI_HOME")
    if workspace:
        return Path(workspace) / "docs" / "workflows" / "_shared" / "claim_index.py"
    raise AssertionError(
        "neither ONEX_CLAIM_INDEX_MODULE nor OMNI_HOME is set, so the claim index "
        "module cannot be located and these tests cannot run. They FAIL rather "
        "than skip: a gate that cannot run has not passed."
    )


@pytest.fixture(scope="module")
def claim_index():
    return bc.load_claim_index(_claim_index_module())


def _commit(message: str, sha: str = "a" * 40) -> tuple[str, str]:
    return sha, message


def _stamped(
    lane: str, *, fence: int | None = None, sha: str = "a" * 40
) -> tuple[str, str]:
    lines = [f"{li.LANE_TRAILER}: {lane}", f"{li.SESSION_TRAILER}: {'0' * 32}"]
    if fence is not None:
        lines.append(f"{bc.FENCE_TRAILER}: {fence}")
    return _commit(li.apply_trailers("fix(OMN-9999): a change\n", lines), sha)


def _ledger(*rows: str) -> str:
    return "\n".join(rows) + "\n"


# ---------------------------------------------------------------------------
# The four fixtures the ruling's sequencing rests on
# ---------------------------------------------------------------------------


def test_held_by_the_same_lane_is_clean(claim_index) -> None:
    text = _ledger(
        f"{_stamp(2)} | CLAIM | lane=alpha | tickets=OMN-9999 | taking it",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-by-pusher"
    assert verdict.findings == []
    assert verdict.ticket == "OMN-9999"


def test_held_by_another_lane_with_a_release_row_is_clean(claim_index) -> None:
    """The release path clears the refusal. This is the fixture that has to pass
    before the hook of OMN-18262 is allowed to refuse anything -- a release that
    did not clear the gate would make the refusal unescapable."""
    text = _ledger(
        f"{_stamp(4)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it",
        f"{_stamp(3)} | RELEASE | lane=beta | tickets=OMN-9999 | handing it back",
        f"{_stamp(2)} | CLAIM | lane=alpha | tickets=OMN-9999 | picking it up",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-by-pusher"
    assert verdict.findings == []


def test_handover_row_also_clears_it(claim_index) -> None:
    text = _ledger(
        f"{_stamp(4)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it",
        f"{_stamp(3)} | HANDOVER | lane=beta | tickets=OMN-9999 | to=alpha | passing it on",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-by-pusher"
    assert verdict.findings == []


def test_held_by_another_lane_without_a_release_row_is_a_finding(claim_index) -> None:
    """The 2026-09-12T14:17Z shape."""
    text = _ledger(
        f"{_stamp(2)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-elsewhere"
    assert len(verdict.findings) == 1
    body = verdict.findings[0]
    # Naming the holder, the citable row, and the release path is the criterion,
    # not decoration: a refusal a lane cannot act on is a stall.
    assert "beta" in body
    assert f"{LEDGER_NAME}:1" in body
    assert "RELEASE" in body and "HANDOVER" in body and "RECLAIM" in body


def test_unclaimed_is_clean(claim_index) -> None:
    text = _ledger(
        f"{_stamp(2)} | CLAIM | lane=beta | tickets=OMN-1111 | an unrelated ticket",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "unclaimed"
    assert verdict.findings == []


# ---------------------------------------------------------------------------
# The zeros that must not read as clean
# ---------------------------------------------------------------------------


def test_commits_with_no_lane_trailer_are_unidentified_not_clean(claim_index) -> None:
    text = _ledger(f"{_stamp(2)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it")
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_commit("fix(OMN-9999): a change with no trailers\n")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "unidentified"
    assert verdict.findings, "an unidentifiable push must report, never read as clean"
    assert "no resolvable lane identity" in verdict.findings[0]


def test_a_branch_with_no_ticket_is_not_applicable(claim_index) -> None:
    verdict = bc.resolve(
        claim_index,
        branch="lane/some-branch-with-no-ticket",
        commits=[_stamped("alpha")],
        ledger_text=_ledger(f"{_stamp(2)} | CLAIM | lane=beta | tickets=OMN-9999 | x"),
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "no-ticket"
    assert verdict.findings == []


def test_a_stale_claim_does_not_hold_the_branch(claim_index) -> None:
    text = _ledger(
        f"{_stamp(48)} | CLAIM | lane=beta | tickets=OMN-9999 | taking it, then dying",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "unclaimed"
    assert verdict.findings == []


def test_two_lanes_in_one_push_are_both_evaluated(claim_index) -> None:
    text = _ledger(f"{_stamp(2)} | CLAIM | lane=alpha | tickets=OMN-9999 | taking it")
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha", sha="a" * 40), _stamped("gamma", sha="b" * 40)],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-elsewhere"
    assert len(verdict.findings) == 1
    assert "gamma" in verdict.findings[0]


# ---------------------------------------------------------------------------
# The fence, and the honest gap where it is not stamped yet
# ---------------------------------------------------------------------------


def test_a_commit_whose_fence_is_behind_the_live_claim_is_a_finding(
    claim_index,
) -> None:
    text = _ledger(
        f"{_stamp(48)} | CLAIM | lane=alpha | tickets=OMN-9999 | taking it",
        f"{_stamp(2)} | RECLAIM | lane=alpha | tickets=OMN-9999 | "
        f"stale={LEDGER_NAME}:1 | last_activity={_stamp(48)} | it went quiet",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha", fence=1)],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "fence-behind"
    assert len(verdict.findings) == 1
    assert "fence 1" in verdict.findings[0]


def test_an_absent_fence_trailer_does_not_invent_one(claim_index) -> None:
    """OMN-18260's stamping hook writes the lane and session trailers and NOT the
    fence. Reading an absent fence as zero would refuse every correctly-held push
    the moment any ticket reached fence 1, so an absent fence disables the fence
    comparison and nothing else. The gap is named in the module docstring rather
    than papered over."""
    text = _ledger(
        f"{_stamp(48)} | CLAIM | lane=alpha | tickets=OMN-9999 | taking it",
        f"{_stamp(2)} | RECLAIM | lane=alpha | tickets=OMN-9999 | "
        f"stale={LEDGER_NAME}:1 | last_activity={_stamp(48)} | it went quiet",
    )
    verdict = bc.resolve(
        claim_index,
        branch="lane/omn-9999-thing",
        commits=[_stamped("alpha")],
        ledger_text=text,
        ledger_name=LEDGER_NAME,
        now=NOW,
    )
    assert verdict.outcome == "held-by-pusher"
    assert verdict.findings == []


# ---------------------------------------------------------------------------
# Fail-closed loading
# ---------------------------------------------------------------------------


def test_a_missing_claim_index_module_raises_rather_than_returning_empty(
    tmp_path: Path,
) -> None:
    with pytest.raises(bc.ResolutionUnavailable) as caught:
        bc.load_claim_index(tmp_path / "nope.py")
    assert "nope.py" in str(caught.value)


def test_a_claim_index_module_missing_its_entry_point_raises(tmp_path: Path) -> None:
    impostor = tmp_path / "claim_index.py"
    impostor.write_text("VERSION = 1\n", encoding="utf-8")
    with pytest.raises(bc.ResolutionUnavailable):
        bc.load_claim_index(impostor)


# ---------------------------------------------------------------------------
# The two modes -- the ruling lives here
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str], ledger: Path, index_module: Path
) -> subprocess.CompletedProcess:
    repo_root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "branch_claim.py"),
            *args,
            "--ledger",
            str(ledger),
            "--ledger-name",
            LEDGER_NAME,
            "--claim-index-module",
            str(index_module),
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def collision_ledger(tmp_path: Path) -> Path:
    path = tmp_path / "LEDGER.md"
    fresh_stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(
        _ledger(f"{fresh_stamp} | CLAIM | lane=beta | tickets=OMN-9999 | taking it"),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def stamped_message_file(tmp_path: Path) -> Path:
    path = tmp_path / "message.txt"
    path.write_text(_stamped("alpha")[1], encoding="utf-8")
    return path


def test_record_mode_reports_the_finding_and_still_exits_zero(
    collision_ledger: Path, stamped_message_file: Path
) -> None:
    """The operator ruling of 2026-09-13T09:11:33Z, in the only place it can be
    enforced: the pull-request check RECORDS. Exiting non-zero here would make
    the check land as a refusal, which is the half the ruling deferred."""
    result = _run_cli(
        [
            "check",
            "--mode",
            "record",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(stamped_message_file),
        ],
        collision_ledger,
        _claim_index_module(),
    )
    assert result.returncode == 0, result.stderr
    assert "beta" in result.stdout + result.stderr
    assert "held-elsewhere" in result.stdout + result.stderr


def test_refuse_mode_exits_non_zero_on_the_same_input(
    collision_ledger: Path, stamped_message_file: Path
) -> None:
    result = _run_cli(
        [
            "check",
            "--mode",
            "refuse",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(stamped_message_file),
        ],
        collision_ledger,
        _claim_index_module(),
    )
    assert result.returncode == 1
    assert "beta" in result.stdout + result.stderr


def test_an_unreadable_ledger_fails_closed_in_both_modes(
    tmp_path: Path, stamped_message_file: Path
) -> None:
    """Record mode tolerates a FINDING, never a broken gate. A ledger it cannot
    read yields no holders and would report every branch unclaimed -- the zero
    that reads exactly like a clean bill of health."""
    for mode in ("record", "refuse"):
        result = _run_cli(
            [
                "check",
                "--mode",
                mode,
                "--branch",
                "lane/omn-9999-thing",
                "--messages-from",
                str(stamped_message_file),
            ],
            tmp_path / "absent-ledger.md",
            _claim_index_module(),
        )
        assert result.returncode == 2, f"mode={mode}: {result.stdout}{result.stderr}"
        assert "absent-ledger.md" in result.stdout + result.stderr


# ---------------------------------------------------------------------------
# What refuse mode refuses, and what it only reports
# ---------------------------------------------------------------------------


@pytest.fixture
def unstamped_message_file(tmp_path: Path) -> Path:
    path = tmp_path / "unstamped.txt"
    path.write_text("fix(OMN-9999): a change with no trailers\n", encoding="utf-8")
    return path


def test_refuse_mode_reports_but_does_not_refuse_an_unidentified_push(
    collision_ledger: Path, unstamped_message_file: Path
) -> None:
    """The wrong-lane case is the criterion. An unstamped push is a different and
    far wider policy -- measured 2026-09-13 that is every commit in the fleet --
    so refusing it by default would be a fleet-wide push freeze on the day the
    hook is installed. It is still printed, so the gap is visible."""
    result = _run_cli(
        [
            "check",
            "--mode",
            "refuse",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(unstamped_message_file),
        ],
        collision_ledger,
        _claim_index_module(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "no resolvable lane identity" in combined
    assert "not refused" in combined


def test_refuse_mode_refuses_an_unidentified_push_when_asked(
    collision_ledger: Path, unstamped_message_file: Path
) -> None:
    result = _run_cli(
        [
            "check",
            "--mode",
            "refuse",
            "--refuse-outcomes",
            "held-elsewhere,fence-behind,unidentified",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(unstamped_message_file),
        ],
        collision_ledger,
        _claim_index_module(),
    )
    assert result.returncode == 1


def test_record_mode_never_refuses_even_on_the_wrong_lane(
    collision_ledger: Path, stamped_message_file: Path
) -> None:
    """A positive control for the mode split: the same input that exits 1 under
    refuse mode exits 0 under record mode, so 'record' is a real mode rather
    than a label on the same behaviour."""
    result = _run_cli(
        [
            "check",
            "--mode",
            "record",
            "--refuse-outcomes",
            "held-elsewhere",
            "--branch",
            "lane/omn-9999-thing",
            "--messages-from",
            str(stamped_message_file),
        ],
        collision_ledger,
        _claim_index_module(),
    )
    assert result.returncode == 0
