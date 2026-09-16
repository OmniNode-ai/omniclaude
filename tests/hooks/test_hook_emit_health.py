# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18471 AC4: the hook-emit alert reads the path that delivers.

The alert this replaces read ``emit-health/status-<event_type>`` counters
written by ``emit_via_daemon``, which speaks to a Unix socket absent since
2026-06-08. Those counters reported 101,009 consecutive failures for
``tool.executed`` whether the live journal/drainer path was healthy or dead,
and they produced no signal during the 22-hour drainer outage of
2026-09-15/16.

The negative control this module exists for is
:func:`test_alerts_when_the_drainer_is_stopped`: with records queued and a
drainer that has stopped cycling, the evaluator must alert. Its partner
:func:`test_silent_drainer_with_an_empty_journal_does_not_alert` pins the
boundary, so "alerts on everything" cannot pass for "alerts correctly".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "hook_emit_health.py"


def _load_module() -> Any:
    """Load the hook lib by path; it is not an installed package."""
    spec = importlib.util.spec_from_file_location("hook_emit_health", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hook_emit_health"] = module
    spec.loader.exec_module(module)
    return module


health = _load_module()

NOW = 1_800_000_000.0


def _status(
    *,
    last_cycle_at: float,
    last_publish_at: float | None = None,
    published_total: int = 7,
) -> Any:
    return health.ModelDrainerStatus(
        last_cycle_at=last_cycle_at,
        last_publish_at=last_publish_at,
        published_total=published_total,
        pid=4242,
    )


@pytest.mark.unit
class TestEvaluate:
    """The verdict, as a pure function of the two live facts."""

    def test_alerts_when_the_drainer_is_stopped(self) -> None:
        """NEGATIVE CONTROL: stopped drainer + queued records must alert.

        This is the condition the retired counter surface could not see. The
        drainer last completed a cycle an hour ago while 12,000 records sit in
        the journal -- the shape of the 2026-09-15/16 outage.
        """
        result = health.evaluate(
            depth=12_000,
            status=_status(last_cycle_at=NOW - 3600.0, last_publish_at=NOW - 3600.0),
            now=NOW,
        )
        assert result.alerting is True
        assert result.verdict == health.EnumHookEmitHealth.DRAINER_SILENT
        assert result.drainer_silent_seconds == pytest.approx(3600.0)
        assert "12000" in result.detail

    def test_alerts_when_there_is_no_drainer_state_at_all(self) -> None:
        """A backlog with no drainer reporting anything is the worst case."""
        result = health.evaluate(depth=50_000, status=None, now=NOW)
        assert result.alerting is True
        assert result.verdict == health.EnumHookEmitHealth.DRAINER_STATE_ABSENT
        assert result.drainer_silent_seconds is None

    def test_alerts_when_the_drainer_cycles_but_never_clears_the_backlog(self) -> None:
        """Cycling is not delivering.

        A drainer that loops and fails every publish keeps ``last_cycle_at``
        fresh forever, so a liveness check on cycling alone reads green while
        nothing is delivered -- the same class of defect as an offset-based
        freshness check (OMN-18120 AC1).
        """
        result = health.evaluate(
            depth=health.DEFAULT_MAX_BACKLOG,
            status=_status(last_cycle_at=NOW - 1.0, last_publish_at=NOW - 90_000.0),
            now=NOW,
        )
        assert result.alerting is True
        assert result.verdict == health.EnumHookEmitHealth.BACKLOG_NOT_DRAINING
        assert result.last_publish_age_seconds == pytest.approx(90_000.0)

    def test_healthy_drainer_with_a_small_backlog_does_not_alert(self) -> None:
        """POSITIVE CONTROL: the live state at 2026-09-16 must read healthy."""
        result = health.evaluate(
            depth=3,
            status=_status(last_cycle_at=NOW - 2.0, last_publish_at=NOW - 2.0),
            now=NOW,
        )
        assert result.alerting is False
        assert result.verdict == health.EnumHookEmitHealth.OK

    def test_silent_drainer_with_an_empty_journal_does_not_alert(self) -> None:
        """The declared boundary, pinned so it cannot drift silently.

        No drainer and no queued records is a machine that is losing nothing
        -- a CI runner, a fresh checkout. Alerting there would fire everywhere
        and train the reader to ignore the channel, which is how the counter
        surface became useless.
        """
        result = health.evaluate(depth=0, status=None, now=NOW)
        assert result.alerting is False
        assert result.verdict == health.EnumHookEmitHealth.OK

    def test_a_publish_that_has_never_happened_is_not_reported_as_recent(self) -> None:
        result = health.evaluate(
            depth=1,
            status=_status(last_cycle_at=NOW, last_publish_at=None),
            now=NOW,
        )
        assert result.last_publish_age_seconds is None


@pytest.mark.unit
class TestStatusFile:
    """Round-trip and the failure modes that must collapse to 'no state'."""

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / "state" / health.STATUS_FILENAME
        written = _status(last_cycle_at=NOW, last_publish_at=NOW - 5.0)
        health.write_status(path, written)
        assert health.read_status(path) == written

    def test_write_is_atomic_leaving_no_partial_file(self, tmp_path: Path) -> None:
        path = tmp_path / health.STATUS_FILENAME
        health.write_status(path, _status(last_cycle_at=NOW))
        leftovers = [p.name for p in tmp_path.iterdir() if ".tmp." in p.name]
        assert leftovers == []

    @pytest.mark.parametrize(
        ("label", "body"),
        [
            ("not json", "{"),
            ("not a mapping", "[1, 2, 3]"),
            ("missing last_cycle_at", json.dumps({"published_total": 1, "pid": 2})),
            (
                "non-numeric last_cycle_at",
                json.dumps({"last_cycle_at": "soon", "published_total": 1, "pid": 2}),
            ),
            (
                "non-numeric last_publish_at",
                json.dumps(
                    {
                        "last_cycle_at": NOW,
                        "last_publish_at": "recently",
                        "published_total": 1,
                        "pid": 2,
                    }
                ),
            ),
        ],
    )
    def test_unusable_status_reads_as_absent(
        self, tmp_path: Path, label: str, body: str
    ) -> None:
        """A partially-trusted status is worse than none: it reads as evidence."""
        path = tmp_path / health.STATUS_FILENAME
        path.write_text(body, encoding="utf-8")
        assert health.read_status(path) is None, label

    def test_absent_status_reads_as_absent(self, tmp_path: Path) -> None:
        assert health.read_status(tmp_path / "nope.json") is None


@pytest.mark.unit
class TestJournalDepth:
    def test_counts_only_records(self, tmp_path: Path) -> None:
        for name in ("a.json", "b.json", "notes.txt"):
            (tmp_path / name).write_text("{}", encoding="utf-8")
        assert health.journal_depth(tmp_path) == 2

    def test_absent_directory_is_zero_not_a_backlog(self, tmp_path: Path) -> None:
        """A directory that cannot be listed is not evidence of a backlog."""
        assert health.journal_depth(tmp_path / "missing") == 0


@pytest.mark.unit
class TestCli:
    """Exit status is the shell's signal, so it is pinned."""

    def test_exits_1_and_prints_the_detail_when_alerting(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        journal_dir = tmp_path / "hook_emit_journal"
        journal_dir.mkdir()
        for i in range(3):
            (journal_dir / f"{i}.json").write_text("{}", encoding="utf-8")
        rc = health.main(
            [
                "--journal-dir",
                str(journal_dir),
                "--status-path",
                str(tmp_path / "absent.json"),
                "--message",
            ]
        )
        assert rc == 1
        assert "queued" in capsys.readouterr().out

    def test_exits_0_with_json_when_healthy(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        journal_dir = tmp_path / "hook_emit_journal"
        journal_dir.mkdir()
        rc = health.main(
            [
                "--journal-dir",
                str(journal_dir),
                "--status-path",
                str(tmp_path / "absent.json"),
            ]
        )
        assert rc == 0
        assert json.loads(capsys.readouterr().out)["alerting"] is False


@pytest.mark.unit
class TestTheAlertNoLongerReadsTheDeadCounters:
    """AC4's falsifier, as a test rather than a claim.

    'The alert's source reads no ``emit-health/status-*`` file and does read
    the journal directory and drainer state.'
    """

    def test_the_health_module_never_reads_the_counter_surface(self) -> None:
        source = MODULE_PATH.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        # The docstring names the retired surface deliberately, so strip it
        # before asserting -- otherwise this test would forbid explaining what
        # was retired, which is the part a later reader needs most.
        body = code.split('"""', 2)[-1]
        # `emit-health` is the whole path segment of the retired surface
        # (`${ONEX_STATE_DIR}/hooks/logs/emit-health/status-<event_type>`), so
        # its absence is what the falsifier actually asks for. Asserting on the
        # bare `status-` prefix instead would forbid this module's own
        # `--status-path` flag, which reads the drainer state the AC requires.
        assert "emit-health" not in body
        assert "emit_client_wrapper" not in body
        assert "emit.sock" not in body
        assert "hook_emit_journal" in body
        assert "STATUS_FILENAME" in body

    def test_emit_via_daemon_no_longer_raises_the_slack_alert(self) -> None:
        common_sh = (
            REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / "common.sh"
        ).read_text(encoding="utf-8")
        assert "emit_sustained" not in common_sh, (
            "the dead-counter milestone alert is back in emit_via_daemon; it "
            "reports on a socket absent since 2026-06-08 (OMN-18471 AC4)"
        )

    def test_the_live_alert_is_raised_from_the_journal_path(self) -> None:
        mirror = (
            REPO_ROOT
            / "plugins"
            / "onex"
            / "hooks"
            / "scripts"
            / "session_start_bus_mirror.sh"
        ).read_text(encoding="utf-8")
        assert "hook_emit_health.py" in mirror
        assert "hook_emit_delivery" in mirror
