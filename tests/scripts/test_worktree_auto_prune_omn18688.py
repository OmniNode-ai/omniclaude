# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The three absence-defined classes and the reclaim accounting [OMN-18688].

Each acceptance criterion's falsifier is one test here, named after it.

The classes under test are defined by the ABSENCE of what the content-keyed
pass keys off — a registration with no directory, a ticket dir with no
registered worktree, a dirty tree with no pull request — so each needs its own
discovery and each is easy to get silently wrong. In particular:

* AC7 — ``git worktree prune --dry-run --verbose`` writes its ``Removing``
  lines to **stderr**. The proof here is behavioural, not textual: a real git
  repository with a deleted worktree directory, driven through the real
  function, with a clean-clone negative control beside it. A grep over the
  source would pass just as happily against a version that read stdout alone.
* AC5 — a NON-EMPTY orphan directory must survive an ``--execute`` run. The
  test asserts it is still on disk afterwards, not merely that it was named.
* AC4 — a stale-dirty tree must be named INDIVIDUALLY in the report and absent
  from every removal path.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

from omniclaude.hooks.lib.worktree_prune_policy import (
    EnumBranchPrState,
    EnumPruneBlockReason,
    EnumPruneDisposition,
    EnumTicketLifecycle,
    ModelWorktreePruneFacts,
    classify_worktree_prune,
)

pytestmark = pytest.mark.unit

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_auto_prune.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("worktree_auto_prune", _MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before executing. The script uses `from __future__ import
    # annotations`, so a model annotated with an enum defers that annotation to
    # a string that pydantic resolves through `sys.modules[__module__]` on first
    # validation. A module executed outside `sys.modules` cannot be resolved
    # that way and the model raises `class-not-fully-defined` at construction —
    # an artifact of loading by path, not a defect in the script, which always
    # runs as a registered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables that OVERRIDE ``cwd=`` (OMN-18434).

    Git exports these into every hook environment, and they beat both ``cwd=``
    and ``git -C``. A fixture that shells out to git under a pre-push hook
    without dropping them mutates the REAL invoking worktree instead of
    ``tmp_path`` — and these tests deliberately delete worktree directories.

    Defined here rather than imported, matching the local definition
    ``tests/scripts/test_converge_canonical_clone.py`` already carries.
    """
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


_GIT_ENV = {
    **{
        k: v
        for k, v in scrub_git_location_env(os.environ).items()
        if not k.startswith("GIT_")
    },
    "GIT_AUTHOR_NAME": "omn18688",
    "GIT_COMMITTER_NAME": "omn18688",
    "GIT_AUTHOR_EMAIL": "omn18688@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn18688@example.invalid",
}


def _git_ok(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_GIT_ENV),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc


@pytest.fixture
def canonical_repo(tmp_path: Path) -> Path:
    """A real, throwaway git clone with one commit."""
    canonical = tmp_path / "registry" / "omnibase_infra"
    canonical.mkdir(parents=True)
    _git_ok(canonical, "init", "-q", "-b", "dev")
    (canonical / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git_ok(canonical, "add", "-A")
    _git_ok(canonical, "commit", "-q", "-m", "init")
    return canonical


def _registered_paths(canonical: Path) -> set[str]:
    out = _git_ok(canonical, "worktree", "list", "--porcelain").stdout
    return {
        line.split(" ", 1)[1].strip()
        for line in out.splitlines()
        if line.startswith("worktree ")
    }


# =============================================================================
# AC7 + AC5 — stale registrations, and the stderr the probe must not discard
# =============================================================================


class TestStaleRegistrations:
    """AC7 falsifier, behaviourally: the probe reads git's stderr.

    A registered worktree whose directory has been deleted is reported by
    ``git worktree prune --dry-run --verbose`` on STDERR. These tests drive the
    real git binary, so a revision that read stdout alone fails them.
    """

    def test_a_deleted_worktree_directory_is_found_by_the_probe(
        self, canonical_repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktrees" / "OMN-1" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "wt", str(worktree))
        # Delete the DIRECTORY without telling git — the MISSING class.
        subprocess.run(["rm", "-rf", str(worktree)], check=True, timeout=60)

        sweeps = mod.collect_stale_registrations([canonical_repo])

        assert len(sweeps) == 1
        sweep = sweeps[0]
        assert sweep.probe_ok, f"probe failed: {sweep.probe_stderr}"
        assert sweep.entries, (
            "the probe found no stale registration for a worktree whose directory "
            "was deleted. git writes those lines to stderr — a probe that reads "
            "stdout alone returns this exact false zero (OMN-18688 AC7, rule 16)."
        )
        assert any(
            "wt" in entry or "omnibase_infra" in entry for entry in sweep.entries
        )

    def test_a_clean_clone_reports_zero_entries(self, canonical_repo: Path) -> None:
        """Negative control for the test above.

        Without this, a `collect_stale_registrations` that returned a constant
        non-empty list would pass the positive test.
        """
        sweeps = mod.collect_stale_registrations([canonical_repo])
        assert sweeps[0].probe_ok
        assert sweeps[0].entries == ()

    def test_the_real_prune_drops_the_registration(
        self, canonical_repo: Path, tmp_path: Path
    ) -> None:
        """AC5 falsifier: the MISSING registration is gone from `git worktree list`."""
        worktree = tmp_path / "worktrees" / "OMN-2" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "wt2", str(worktree))
        subprocess.run(["rm", "-rf", str(worktree)], check=True, timeout=60)
        assert str(worktree) in _registered_paths(canonical_repo)

        pruned = mod.prune_stale_registrations(
            mod.collect_stale_registrations([canonical_repo])
        )

        assert pruned[0].pruned is True
        assert pruned[0].prune_exit_code == 0, pruned[0].prune_stderr
        assert str(worktree) not in _registered_paths(canonical_repo)

    def test_a_live_worktree_is_never_pruned(
        self, canonical_repo: Path, tmp_path: Path
    ) -> None:
        """The registration prune must not touch a worktree that still exists."""
        worktree = tmp_path / "worktrees" / "OMN-3" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "wt3", str(worktree))

        mod.prune_stale_registrations(mod.collect_stale_registrations([canonical_repo]))

        assert str(worktree) in _registered_paths(canonical_repo)
        assert worktree.is_dir()

    def test_an_unprobeable_clone_is_never_pruned(self, tmp_path: Path) -> None:
        """A probe that did not answer has not established that anything is safe."""
        not_a_repo = tmp_path / "not-a-repo"
        not_a_repo.mkdir()

        sweeps = mod.collect_stale_registrations([not_a_repo])
        assert sweeps[0].probe_ok is False

        pruned = mod.prune_stale_registrations(sweeps)
        assert pruned[0].pruned is False


# =============================================================================
# AC5 — orphan ticket dirs: empty removed, non-empty reported and left alone
# =============================================================================


class TestOrphanTicketDirs:
    def test_empty_orphan_is_classified_empty_and_removed(self, tmp_path: Path) -> None:
        root = tmp_path / "omni_worktrees"
        (root / "OMN-EMPTY").mkdir(parents=True)

        orphans = mod.classify_orphan_ticket_dirs(root, [])
        assert orphans.empty == (str(root / "OMN-EMPTY"),)
        assert orphans.non_empty == ()

        removed = mod.remove_empty_orphan_dirs(orphans.empty)
        assert removed == [str(root / "OMN-EMPTY")]
        assert not (root / "OMN-EMPTY").exists()

    def test_non_empty_orphan_is_reported_and_still_on_disk(
        self, tmp_path: Path
    ) -> None:
        """AC5 falsifier: named in the report, still present afterwards."""
        root = tmp_path / "omni_worktrees"
        orphan = root / "OMN-KEEP"
        orphan.mkdir(parents=True)
        (orphan / "someone_elses_clone").mkdir()
        (orphan / "someone_elses_clone" / "data.txt").write_text("x", encoding="utf-8")

        orphans = mod.classify_orphan_ticket_dirs(root, [])
        assert orphans.non_empty == (str(orphan),)
        assert orphans.empty == ()

        # The removal function is only ever handed the EMPTY list, and handing
        # it the non-empty one anyway must still not delete the content: rmdir
        # refuses a non-empty directory. Both gates are asserted.
        mod.remove_empty_orphan_dirs(orphans.empty)
        mod.remove_empty_orphan_dirs(orphans.non_empty)
        assert orphan.is_dir()
        assert (orphan / "someone_elses_clone" / "data.txt").read_text() == "x"

    def test_a_ticket_dir_holding_a_registered_worktree_is_not_an_orphan(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "omni_worktrees"
        live = root / "OMN-LIVE" / "omnibase_infra"
        live.mkdir(parents=True)

        orphans = mod.classify_orphan_ticket_dirs(root, [live])
        assert orphans.empty == ()
        assert orphans.non_empty == ()

    def test_limit_does_not_widen_the_orphan_set(self) -> None:
        """`--limit` bounds the classifier, never the orphan discovery.

        An orphan is defined by the absence of a registered worktree beneath
        it. Deriving that from a `--limit`-truncated list reclassifies every
        ticket dir past the cut as an orphan — a `--limit 5` run reported 337
        non-empty orphans against the census's 22. Nothing would have been
        deleted, but the report would have been wrong in the direction of
        alarm, which is the direction that wastes a human's morning.
        """
        source = _MODULE_PATH.read_text(encoding="utf-8")
        assert "classify_orphan_ticket_dirs(root, all_worktrees)" in source, (
            "the orphan pass must be handed the FULL worktree list, never the "
            "`--limit`-truncated one"
        )
        assert "classify_orphan_ticket_dirs(root, worktrees)" not in source

    def test_report_names_the_non_empty_orphan_and_marks_it_never_removed(
        self, tmp_path: Path
    ) -> None:
        orphans = mod.ModelOrphanTicketDirs(
            empty=(), non_empty=(str(tmp_path / "OMN-KEEP"),)
        )
        report = mod.render_report(
            [],
            root=tmp_path,
            executed=True,
            generated_at="2026-09-18T00:00:00Z",
            removals=[],
            tracker_resolved=0,
            orphan_dirs=orphans,
        )
        assert "OMN-KEEP" in report
        assert "needs individual review" in report


# =============================================================================
# AC4 — the stale-dirty alarm class
# =============================================================================


def _decision(
    path: str,
    *,
    dirty: int,
    pr_state: EnumBranchPrState,
) -> object:
    return classify_worktree_prune(
        ModelWorktreePruneFacts(
            path=path,
            ticket="OMN-9999",
            repo="omnibase_infra",
            branch="lane/omn-9999-x",
            ticket_state=EnumTicketLifecycle.OPEN,
            ledger_has_terminal=False,
            ledger_open_claim=None,
            base_ref="origin/dev",
            dirty_files=tuple(f"f{i}.py" for i in range(dirty)),
            commits_ahead=0,
            unmerged_ahead_commits=(),
            tree_diff_vs_base_empty=True,
            pr_state=pr_state,
            pr_head_oid=None,
            origin_head_oid=None,
            head_oid="a" * 40,
            attributed_stash_count=0,
            unreadable_probes=(),
            timed_out_probes=(),
            load_average=None,
        )
    )


class TestStaleDirty:
    """AC4 falsifier: named by name in the dry run, absent from every removal."""

    @pytest.fixture
    def old_dirty_worktree(self, canonical_repo: Path, tmp_path: Path) -> Path:
        """A real worktree whose only commit is far in the past, with a dirty file."""
        worktree = tmp_path / "worktrees" / "OMN-STALE" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "stale", str(worktree))

        (worktree / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(worktree), "commit", "-q", "-a", "-m", "old"],
            env={
                **scrub_git_location_env(_GIT_ENV),
                "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z",
            },
            check=True,
            timeout=60,
        )
        (worktree / "uncommitted.py").write_text("WIP = True\n", encoding="utf-8")
        return worktree

    def test_dirty_old_and_prless_is_named(self, old_dirty_worktree: Path) -> None:
        rows = mod.select_stale_dirty(
            [
                _decision(
                    str(old_dirty_worktree), dirty=1, pr_state=EnumBranchPrState.NONE
                )
            ],
            age_bar_days=7.0,
            now=time.time(),
        )
        assert [r.path for r in rows] == [str(old_dirty_worktree)]

    def test_an_open_pull_request_excludes_the_row(
        self, old_dirty_worktree: Path
    ) -> None:
        """`NOT_MERGED` is set only from the OPEN listing — it means 'has an open PR'."""
        rows = mod.select_stale_dirty(
            [
                _decision(
                    str(old_dirty_worktree),
                    dirty=1,
                    pr_state=EnumBranchPrState.NOT_MERGED,
                )
            ],
            age_bar_days=7.0,
            now=time.time(),
        )
        assert rows == []

    def test_a_clean_tree_is_never_stale_dirty(
        self, canonical_repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktrees" / "OMN-CLEAN" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "clean", str(worktree))
        rows = mod.select_stale_dirty(
            [_decision(str(worktree), dirty=0, pr_state=EnumBranchPrState.NONE)],
            age_bar_days=7.0,
            now=time.time(),
        )
        assert rows == []

    def test_a_recent_dirty_tree_is_below_the_bar(
        self, canonical_repo: Path, tmp_path: Path
    ) -> None:
        worktree = tmp_path / "worktrees" / "OMN-FRESH" / "omnibase_infra"
        _git_ok(canonical_repo, "worktree", "add", "-q", "-b", "fresh", str(worktree))
        (worktree / "wip.py").write_text("x", encoding="utf-8")
        rows = mod.select_stale_dirty(
            [_decision(str(worktree), dirty=1, pr_state=EnumBranchPrState.NONE)],
            age_bar_days=7.0,
            now=time.time(),
        )
        assert rows == []

    def test_an_unknown_pr_state_is_included_not_dropped(
        self, old_dirty_worktree: Path
    ) -> None:
        """An unresolvable PR state has not established the tree is looked after."""
        rows = mod.select_stale_dirty(
            [
                _decision(
                    str(old_dirty_worktree),
                    dirty=1,
                    pr_state=EnumBranchPrState.UNKNOWN,
                )
            ],
            age_bar_days=7.0,
            now=time.time(),
        )
        assert len(rows) == 1

    def test_the_report_names_each_row_individually(self, tmp_path: Path) -> None:
        rows = [
            mod.ModelStaleDirtyRow(
                path=str(tmp_path / f"OMN-{i}" / "omnibase_infra"),
                ticket=f"OMN-{i}",
                repo="omnibase_infra",
                branch=f"lane/omn-{i}",
                dirty_file_count=3,
                commit_age_days=30.0,
                pr_state=EnumBranchPrState.NONE,
            )
            for i in (11, 22)
        ]
        report = mod.render_report(
            [],
            root=tmp_path,
            executed=False,
            generated_at="2026-09-18T00:00:00Z",
            removals=[],
            tracker_resolved=0,
            stale_dirty=rows,
            stale_dirty_age_bar_days=7.0,
        )
        # `render_report` runs every path through `_portable`, which strips the
        # operator-machine registry prefix so the report can be published to a
        # shared repository whose readers cannot resolve it. Assert the form the
        # report actually carries — asserting the absolute path would be
        # asserting a bug.
        for row in rows:
            portable = row.path.replace(str(tmp_path.parent).rstrip("/") + "/", "")
            assert portable != row.path, (
                "positive control: the portable transform did nothing, so this "
                "assertion would pass against a report that named no row"
            )
            assert portable in report, (
                "a stale-dirty row must be named individually, never counted"
            )
        assert "Never removed" in report

    def test_the_stale_dirty_class_has_no_removal_path(self) -> None:
        """Structural: nothing in the module consumes a stale-dirty row to remove it.

        The class exists to be looked at. If a future change routes these rows
        into a removal, this test is the thing that notices.
        """
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for forbidden in (
            "prune_worktree(stale_dirty",
            "for row in stale_dirty:\n        attempt",
            "remove_empty_orphan_dirs(stale_dirty",
            "remove_empty_orphan_dirs(orphan_dirs.non_empty",
        ):
            assert forbidden not in source, (
                f"{forbidden!r} routes a report-only class into a removal path"
            )


# =============================================================================
# AC3 — the ledger CLAIM is the gate, and it is the ONLY difference
# =============================================================================


class TestClaimIsTheOnlyDifference:
    """AC3 falsifier, as a matched pair over one set of facts.

    The two rows below differ in exactly one field. The pure predicate is
    covered more broadly in ``tests/unit/hooks/lib/test_worktree_prune_policy.py``;
    what this pair pins is the falsifier's own claim — that removing ONLY the
    CLAIM row flips the verdict, so the CLAIM is doing the work and nothing
    else is.
    """

    @staticmethod
    def _facts(*, claim: str | None) -> ModelWorktreePruneFacts:
        return ModelWorktreePruneFacts(
            path="/w/OMN-4242/omnibase_infra",
            ticket="OMN-4242",
            repo="omnibase_infra",
            branch="lane/omn-4242-x",
            ticket_state=EnumTicketLifecycle.OPEN,
            ledger_has_terminal=False,
            ledger_open_claim=claim,
            base_ref="origin/dev",
            dirty_files=(),  # clean
            commits_ahead=0,
            unmerged_ahead_commits=(),
            tree_diff_vs_base_empty=True,
            pr_state=EnumBranchPrState.MERGED,  # merged pull request
            pr_head_oid="b" * 40,
            origin_head_oid=None,
            head_oid="b" * 40,
            attributed_stash_count=0,
            unreadable_probes=(),
            timed_out_probes=(),
            load_average=None,
        )

    def test_clean_and_merged_with_an_open_claim_is_held(self) -> None:
        decision = classify_worktree_prune(
            self._facts(claim="lane=peer-lane | ticket=OMN-4242")
        )
        assert decision.disposition is EnumPruneDisposition.TRIAGE
        assert EnumPruneBlockReason.OPEN_CLAIM in decision.block_reasons

    def test_removing_only_the_claim_flips_it_to_removable(self) -> None:
        decision = classify_worktree_prune(self._facts(claim=None))
        assert decision.disposition is EnumPruneDisposition.PRUNE

    def test_age_is_absent_from_the_predicate_entirely(self) -> None:
        """Age is never a removal key on either host (the consent row's words)."""
        policy_source = (
            Path(mod.__file__).resolve().parents[1]
            / "src"
            / "omniclaude"
            / "hooks"
            / "lib"
            / "worktree_prune_policy.py"
        ).read_text(encoding="utf-8")
        # Scope to the content-keyed predicate itself — the rescue-only
        # classifier further down the same module is a REPORT-ONLY class and
        # legitimately takes an age bar.
        body = policy_source.split("def classify_worktree_prune", 1)[1]
        body = body.split("\ndef ", 1)[0]
        assert "ledger_open_claim" in body, (
            "positive control: the extracted region is not the predicate body"
        )
        for age_token in ("age_days", "commit_age", "mtime_age", "days_old"):
            assert age_token not in body, (
                f"{age_token!r} appears in the content-keyed removal predicate; "
                "age is an alarm input and never a deletion key (OMN-18688 AC3)"
            )


# =============================================================================
# AC6 — before / after / reclaimed
# =============================================================================


class TestAccounting:
    def test_report_states_before_after_and_reclaimed(self, tmp_path: Path) -> None:
        report = mod.render_report(
            [],
            root=tmp_path,
            executed=True,
            generated_at="2026-09-18T00:00:00Z",
            removals=[],
            tracker_resolved=0,
            worktrees_before=100,
            worktrees_after_observed=100,
            reclaim_bytes=3 * 1024**3,
            reclaim_measured_paths=7,
        )
        assert "Worktrees scanned (before):** 100" in report
        assert "Observed after (re-walked on disk):** 100" in report
        assert "3.0 GB" in report

    def test_a_disagreement_between_expected_and_observed_is_stated(
        self, tmp_path: Path
    ) -> None:
        """Never reconciled away: the ordinary cause is a peer lane, but the
        one case that is not ordinary has to be visible."""
        report = mod.render_report(
            [],
            root=tmp_path,
            executed=True,
            generated_at="2026-09-18T00:00:00Z",
            removals=[],
            tracker_resolved=0,
            worktrees_before=100,
            worktrees_after_observed=97,
        )
        assert "DISAGREEMENT" in report

    def test_an_unmeasured_path_is_not_counted_as_zero(self, tmp_path: Path) -> None:
        missing = tmp_path / "gone"
        assert mod.measure_path_size_bytes(missing) is None
        assert mod.measure_paths([str(missing)]) == {}

    def test_a_real_directory_measures_non_zero(self, tmp_path: Path) -> None:
        """Positive control for the test above."""
        real = tmp_path / "real"
        real.mkdir()
        (real / "f.bin").write_bytes(b"x" * 200_000)
        size = mod.measure_path_size_bytes(real)
        assert size is not None and size > 0
