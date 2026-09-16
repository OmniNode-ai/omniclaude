# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The classifier's rescue-only pass [OMN-18442 AC6].

The rescue-only class is the one surface of the morning prune that DESTROYS
work: a branch that never opened a pull request and has none open, holding
uncommitted or unpushed changes that exist nowhere else. The content-keyed
predicate can never reach it — being dirty or ahead-unmerged is exactly why such
a worktree was rescued — so the population only grows (measured live 2026-09-16:
233 of 668 records).

Before this module, the pass ran by hand against the declared policy module and
the LANE collected the facts, which meant the fact collection for the only
destructive surface of the lane was the one half nothing pinned. These tests
pin it: they drive ``main()`` end to end against a real throwaway worktree and
assert on the JSON report it writes.

The age bar is NEVER defaulted in omniclaude. It is a required flag, supplied by
the caller from the declared source, so the tests below type it explicitly the
same way the workflow interpolates its own declared constant.

No network: the only stub is the GitHub pull-request lookup, which no unit test
can perform for real. It is stubbed with a NON-EMPTY map whose control row is a
branch with a known MERGED pull request — the same positive control the pass
requires live, since a branch absent from an EMPTY map proves nothing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumRescueOnlyDisposition,
    EnumRescueOnlyHoldReason,
)

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_auto_prune", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn18442",
    "GIT_COMMITTER_NAME": "omn18442",
    "GIT_AUTHOR_EMAIL": "omn18442@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn18442@example.invalid",
}

# The bar the caller supplies. Typed here because a TEST is a caller; the point
# of AC6 is that omniclaude itself declares no such number.
BAR_DAYS = 7
OVER_AGE_DAYS = 40
RESCUE_BRANCH = "lane/omn-4242-rescued-work"
CONTROL_BRANCH = "lane/omn-0001-control-merged"


def _git_ok(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=env or _GIT_ENV,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout.strip()


def _days_ago(days: float) -> float:
    return time.time() - days * 86400.0


def _backdate(path: Path, days: float) -> None:
    stamp = _days_ago(days)
    os.utime(path, (stamp, stamp))


class ModelRescueFixture:
    """A throwaway rescue-only worktree and the paths the classifier needs."""

    def __init__(self, root: Path, worktree: Path, ledger: Path, hand_held: Path):
        self.root = root
        self.worktree = worktree
        self.ledger = ledger
        self.hand_held = hand_held


@pytest.fixture
def rescue_fixture(tmp_path: Path) -> ModelRescueFixture:
    """One over-age, rescue-only worktree: dirty, ahead, no pull request ever.

    Both age limbs are pushed past the bar deliberately and by different means —
    the commit through git's own committer date, the files through their mtime —
    because the predicate is a conjunction and a fixture that moved only one
    limb would pass against a predicate that read only the other.
    """
    canonical = tmp_path / "canonical" / "omnibase_infra"
    canonical.mkdir(parents=True)
    _git_ok(canonical, "init", "-q", "-b", "dev")
    (canonical / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")

    root = tmp_path / "omni_worktrees"
    worktree = root / "OMN-4242" / "omnibase_infra"
    worktree.parent.mkdir(parents=True)
    _git_ok(canonical, "worktree", "add", "-q", str(worktree), "-b", RESCUE_BRANCH)

    # An unpushed commit, committed long ago.
    stale = time.strftime(
        "%Y-%m-%dT%H:%M:%S+0000", time.gmtime(_days_ago(OVER_AGE_DAYS))
    )
    (worktree / "rescued.py").write_text("WORK = 'unpushed'\n", encoding="utf-8")
    _git_ok(worktree, "add", "-A")
    _git_ok(
        worktree,
        "commit",
        "-q",
        "-m",
        "rescue sweep",
        env={**_GIT_ENV, "GIT_AUTHOR_DATE": stale, "GIT_COMMITTER_DATE": stale},
    )
    # …and an uncommitted edit on top, which is what makes the content-keyed
    # predicate refuse this row forever.
    (worktree / "rescued.py").write_text("WORK = 'uncommitted'\n", encoding="utf-8")

    for name in ("app.py", "rescued.py"):
        _backdate(worktree / name, OVER_AGE_DAYS)

    ledger = tmp_path / "ledger.md"
    ledger.write_text("", encoding="utf-8")

    hand_held = tmp_path / "hand_held_worktrees.yaml"
    hand_held.write_text("hand_held: []\n", encoding="utf-8")

    return ModelRescueFixture(root, worktree, ledger, hand_held)


@pytest.fixture
def stub_pr_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-empty pull-request map carrying a known-MERGED positive control.

    The classifier reads a branch absent from a NON-EMPTY map as "no pull
    request"; a branch absent from an empty map stays UNKNOWN and fails closed.
    Stubbing an empty map would therefore assert nothing about the class.
    """
    monkeypatch.setattr(
        mod,
        "collect_branch_pr_states",
        lambda _canonical: {CONTROL_BRANCH: (EnumBranchPrState.MERGED, "0" * 40)},
    )


def _run(
    fixture: ModelRescueFixture,
    tmp_path: Path,
    *extra: str,
    hand_held: bool = True,
) -> dict[str, object]:
    report = tmp_path / "report.json"
    argv = [
        "--worktrees-root",
        str(fixture.root),
        "--ledger",
        str(fixture.ledger),
        "--no-fetch",
        "--no-tracker",
        "--no-debris",
        "--rescue-only",
        "--rescue-only-age-days",
        str(BAR_DAYS),
        "--rescue-only-claim-fence-days",
        str(BAR_DAYS),
        "--report-json",
        str(report),
        *extra,
    ]
    if hand_held:
        argv += ["--rescue-only-hand-held", str(fixture.hand_held)]
    assert mod.main(argv) == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _rows(payload: dict[str, object]) -> list[dict[str, object]]:
    section = payload["rescue_only"]
    assert isinstance(section, dict)
    rows = section["decisions"]
    assert isinstance(rows, list)
    return rows


def _row_for(payload: dict[str, object], branch: str) -> dict[str, object]:
    matches = [r for r in _rows(payload) if r.get("branch") == branch]
    assert len(matches) == 1, f"expected exactly one row for {branch}, got {matches}"
    return matches[0]


# =============================================================================
# AC6 falsifier — the report carries the row, in its own section, with BOTH ages
# =============================================================================


class TestRescueOnlySectionIsEmitted:
    def test_an_over_age_rescue_only_worktree_lands_in_the_rescue_only_section(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """AC6's falsifier, exactly: a dry run against a fixture root holding one
        over-age rescue-only worktree puts that row in a rescue-only section of
        the JSON report, carrying its measured commit age AND its measured
        git-visible mtime age."""
        payload = _run(rescue_fixture, tmp_path)

        section = payload["rescue_only"]
        assert isinstance(section, dict)
        assert section["enabled"] is True
        assert section["max_age_days"] == float(BAR_DAYS)
        assert section["claim_fence_days"] == float(BAR_DAYS)

        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.REMOVE.value
        assert row["hold_reasons"] == []
        assert row["ticket"] == "OMN-4242"

        commit_age = row["commit_age_days"]
        mtime_age = row["mtime_age_days"]
        assert isinstance(commit_age, float)
        assert isinstance(mtime_age, float)
        assert commit_age > BAR_DAYS, commit_age
        assert mtime_age > BAR_DAYS, mtime_age
        assert str(CONTROL_BRANCH) not in json.dumps(row)

    def test_the_content_keyed_pass_still_refuses_the_same_row(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """The rescue-only class never widens the content-keyed predicate. The
        same worktree must still be TRIAGE there — if it were PRUNE, the second
        class would be unnecessary and this one would be double-counting."""
        payload = _run(rescue_fixture, tmp_path)
        assert payload["prune_count"] == 0
        assert payload["triage_count"] == 1


# =============================================================================
# The bar is a caller-supplied value, never an omniclaude constant
# =============================================================================


class TestAgeBarIsRequiredAndCarriesNoDefault:
    def test_rescue_only_without_the_age_flag_refuses_to_run(
        self, rescue_fixture: ModelRescueFixture
    ) -> None:
        """omniclaude declares no age bar. The value is declared in the workflow
        config and passed in, so asking for the pass without supplying it is an
        error rather than a silent default — a wrong default here deletes work."""
        with pytest.raises(SystemExit) as excinfo:
            mod.main(
                [
                    "--worktrees-root",
                    str(rescue_fixture.root),
                    "--ledger",
                    str(rescue_fixture.ledger),
                    "--no-fetch",
                    "--no-tracker",
                    "--rescue-only",
                ]
            )
        assert excinfo.value.code != 0

    def test_no_rescue_only_age_literal_is_declared_in_the_classifier(self) -> None:
        """The number lives in the workflow config and the declared policy
        module. A default here would be a third copy nothing compares."""
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "RESCUE_ONLY_MAX_AGE_DAYS" not in source
        assert "rescue-only-age-days" in source

    def test_a_row_under_a_larger_bar_is_held_on_both_age_limbs(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """Moving the caller's bar past the fixture's age flips the same row to a
        hold, naming both limbs — proof the flag is the value in force and not a
        decoration over a hardcoded one."""
        report = tmp_path / "wide.json"
        assert (
            mod.main(
                [
                    "--worktrees-root",
                    str(rescue_fixture.root),
                    "--ledger",
                    str(rescue_fixture.ledger),
                    "--no-fetch",
                    "--no-tracker",
                    "--no-debris",
                    "--rescue-only",
                    "--rescue-only-age-days",
                    str(OVER_AGE_DAYS + 10),
                    "--rescue-only-claim-fence-days",
                    str(BAR_DAYS),
                    "--rescue-only-hand-held",
                    str(rescue_fixture.hand_held),
                    "--report-json",
                    str(report),
                ]
            )
            == 0
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert set(row["hold_reasons"]) == {
            EnumRescueOnlyHoldReason.COMMIT_WITHIN_WINDOW.value,
            EnumRescueOnlyHoldReason.MTIME_WITHIN_WINDOW.value,
        }


# =============================================================================
# The fences the classifier can observe, and the one it cannot
# =============================================================================


class TestHandHeldExclusion:
    def test_a_named_branch_is_held_whatever_its_age(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        rescue_fixture.hand_held.write_text(
            "hand_held:\n"
            f"  - branch: {RESCUE_BRANCH}\n"
            "    reason: a person is working in this tree by hand\n"
            "    added: '2026-09-16'\n",
            encoding="utf-8",
        )
        payload = _run(rescue_fixture, tmp_path)
        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert EnumRescueOnlyHoldReason.HAND_HELD.value in row["hold_reasons"]

    def test_removing_the_entry_flips_the_same_fixture_back_to_a_candidate(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        rescue_fixture.hand_held.write_text("hand_held: []\n", encoding="utf-8")
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.REMOVE.value

    def test_an_unavailable_list_holds_every_row_rather_than_ignoring_the_fence(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """Fail closed. A pass that cannot read the exclusion list has not proven
        the row is unexcluded — and an unreadable list looks exactly like an
        empty one to a caller that ignores the difference."""
        payload = _run(rescue_fixture, tmp_path, hand_held=False)
        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert (
            EnumRescueOnlyHoldReason.HAND_HELD_LIST_UNAVAILABLE.value
            in row["hold_reasons"]
        )

    def test_a_malformed_list_is_an_error_not_an_empty_list(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        rescue_fixture.hand_held.write_text(
            "hand_held:\n  - branch: a\n    path_contains: b\n"
            "    reason: names both keys\n    added: '2026-09-16'\n",
            encoding="utf-8",
        )
        payload = _run(rescue_fixture, tmp_path)
        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert (
            EnumRescueOnlyHoldReason.HAND_HELD_LIST_UNAVAILABLE.value
            in row["hold_reasons"]
        )


class TestClaimFence:
    def test_a_claim_inside_the_window_holds_the_row(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        recent = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_days_ago(1)))
        rescue_fixture.ledger.write_text(
            f"{recent} | CLAIM | lane=a-peer | ticket=OMN-4242 | scope: still mine\n",
            encoding="utf-8",
        )
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert EnumRescueOnlyHoldReason.CLAIM_WITHIN_WINDOW.value in row["hold_reasons"]

    def test_the_same_claim_dated_outside_the_window_does_not(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        old = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_days_ago(OVER_AGE_DAYS)))
        rescue_fixture.ledger.write_text(
            f"{old} | CLAIM | lane=a-peer | ticket=OMN-4242 | scope: long gone\n",
            encoding="utf-8",
        )
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.REMOVE.value


class TestPullRequestStateFencesTheClass:
    def test_an_unresolvable_lookup_holds_every_row(
        self,
        rescue_fixture: ModelRescueFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An EMPTY map is what a broken `gh` query returns. Reading it as "no
        pull request" is the failure mode CLAUDE.md rule 16 is about, and here it
        would license a deletion."""
        monkeypatch.setattr(mod, "collect_branch_pr_states", lambda _c: {})
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert EnumRescueOnlyHoldReason.FACTS_UNREADABLE.value in row["hold_reasons"]

    def test_a_merged_pull_request_belongs_to_the_other_predicate(
        self,
        rescue_fixture: ModelRescueFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            mod,
            "collect_branch_pr_states",
            lambda _c: {RESCUE_BRANCH: (EnumBranchPrState.MERGED, "0" * 40)},
        )
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert (
            EnumRescueOnlyHoldReason.NOT_RESCUE_ONLY_MERGED_PR.value
            in row["hold_reasons"]
        )

    def test_an_open_pull_request_means_the_work_is_in_review(
        self,
        rescue_fixture: ModelRescueFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            mod,
            "collect_branch_pr_states",
            lambda _c: {RESCUE_BRANCH: (EnumBranchPrState.NOT_MERGED, None)},
        )
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert (
            EnumRescueOnlyHoldReason.NOT_RESCUE_ONLY_OPEN_PR.value
            in row["hold_reasons"]
        )


# =============================================================================
# The mtime limb reads git-visible files only
# =============================================================================


class TestMtimeIsMeasuredOverGitVisibleFilesOnly:
    def test_a_freshly_written_gitignored_cache_does_not_make_the_tree_recent(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """Measured 2026-09-16: a filesystem walk called 663 of 671 worktrees
        recent because a pre-commit run had written `.grimp_cache/`, while every
        uncommitted SOURCE file in the same tree was 33 days old. Asking git
        which files are visible drops tool caches out by construction; excluding
        them by name requires guessing the next tool's cache name."""
        worktree = rescue_fixture.worktree
        (worktree / ".gitignore").write_text(".grimp_cache/\n", encoding="utf-8")
        _backdate(worktree / ".gitignore", OVER_AGE_DAYS)
        cache = worktree / ".grimp_cache"
        cache.mkdir()
        (cache / "graph.json").write_text("{}\n", encoding="utf-8")  # mtime: now

        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["mtime_age_days"] > BAR_DAYS, row
        assert row["disposition"] == EnumRescueOnlyDisposition.REMOVE.value

    def test_an_untracked_but_visible_file_does_make_it_recent(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """The other direction of the same rule: untracked-not-ignored work is
        exactly the unpreserved content this policy destroys, so a recent one
        must hold the row."""
        (rescue_fixture.worktree / "notes.md").write_text("wip\n", encoding="utf-8")
        row = _row_for(_run(rescue_fixture, tmp_path), RESCUE_BRANCH)
        assert row["mtime_age_days"] < 1.0, row
        assert row["disposition"] == EnumRescueOnlyDisposition.HOLD.value
        assert EnumRescueOnlyHoldReason.MTIME_WITHIN_WINDOW.value in row["hold_reasons"]


# =============================================================================
# The pass is report-only in the classifier, on --execute as much as on a dry run
# =============================================================================


class TestTheClassifierNeverRemovesARescueOnlyRow:
    def test_execute_removes_nothing_from_the_rescue_only_set(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """The classifier reports this class; it does not act on it. Removal is
        the Prune phase's, under a re-read of the operator consent row — a
        destructive pass must not ride in on a flag that means something else."""
        payload = _run(rescue_fixture, tmp_path, "--execute")
        row = _row_for(payload, RESCUE_BRANCH)
        assert row["disposition"] == EnumRescueOnlyDisposition.REMOVE.value
        assert rescue_fixture.worktree.is_dir()
        assert (rescue_fixture.worktree / "rescued.py").exists()
        section = payload["rescue_only"]
        assert isinstance(section, dict)
        assert section["removed"] == 0


class TestRescueOnlyIsOffUnlessAskedFor:
    def test_the_section_is_absent_when_the_flag_is_not_passed(
        self, rescue_fixture: ModelRescueFixture, tmp_path: Path
    ) -> None:
        report = tmp_path / "off.json"
        assert (
            mod.main(
                [
                    "--worktrees-root",
                    str(rescue_fixture.root),
                    "--ledger",
                    str(rescue_fixture.ledger),
                    "--no-fetch",
                    "--no-tracker",
                    "--no-debris",
                    "--no-pr-state",
                    "--report-json",
                    str(report),
                ]
            )
            == 0
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        section = payload["rescue_only"]
        assert section["enabled"] is False
        assert section["decisions"] == []


class TestTheMarkdownSectionTheLaneReads:
    def test_the_report_carries_a_rescue_only_candidates_section(
        self,
        rescue_fixture: ModelRescueFixture,
        stub_pr_lookup: None,
        tmp_path: Path,
    ) -> None:
        """The morning-prune format contract names this heading and the columns
        under it. A section the lane's brief cites by name is part of the
        contract, so its absence is a red test rather than a surprise at 04:00."""
        md = tmp_path / "report.md"
        _run(rescue_fixture, tmp_path, "--report-md", str(md))
        text = md.read_text(encoding="utf-8")

        assert "## Rescue-only candidates" in text
        assert "### Rescue-only hold reasons" in text
        assert "Git-visible mtime age (d)" in text
        assert RESCUE_BRANCH in text
        assert "**Removed by this script:** 0" in text
        # Path portability is a required check on the report's destination repo:
        # the table renders worktree paths, so it must go through the same
        # scrubber every other section does.
        assert "/Users/" not in text  # local-path-ok
