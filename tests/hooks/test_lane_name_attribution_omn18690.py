# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lane-name attribution at ``SubagentStop`` [OMN-18690].

The defect, measured live
-------------------------
``SubagentStop`` carries no ``tool_input``, so
:func:`lane_termination_guard.classify_lane_termination` falls through to
the harness-native fields and lands on ``agent_id``. The harness spells a
named teammate's agent id as ``a`` + the lane name + ``-`` + 16 hex, so the
closer asks :func:`lane_registry.close_lane` to close a lane called
``aomn18685-sibling-guard-build-1425-a4c6d53620bcd3eb``. No OPEN record
carries that name, and with more than one lane open in the session the
unique-open fallback declines too -- so the death is written under a
synthetic ``unattributed-*`` id while the real dispatch record ages into
``died_no_terminal``. One lane, two failure rows, neither usable.

The two fixtures beside this file are the live pair the ticket cites,
copied verbatim off this host and never read from live state by a test:

* ``lane_omn18690_open_dispatch.json`` -- ``lane-5f79b31e7a191435c9ce``,
  ``status: open``, ``lane_name: omn18685-sibling-guard-build-1425``.
* ``lane_omn18690_unattributed_close.json`` --
  ``unattributed-29ecc418f1eab1ec58bd``, ``status: closed``,
  ``died_usage_limit``, ``lane_name`` the mangled agent id.
* ``lane_omn18690_agent_meta.json`` -- the harness's own
  ``agent-<agent id>.meta.json`` sidecar for that lane, whose ``name`` is
  the dispatch-time lane name. This is the contract OMN-17575 asked for
  and nobody had read: the name is not derived, it is read back from the
  file the harness wrote at spawn.

Refs: OMN-18690; parent OMN-18130; OMN-17575 (payload capture); OMN-16471.
"""

from __future__ import annotations

import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

import pytest

_LIB_DIR = (
    pathlib.Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
)
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import lane_pair_reconcile  # noqa: E402
from lane_registry import (  # noqa: E402
    EnumLaneStatus,
    EnumLaneTerminalState,
    ModelLaneRecord,
    ModelLaneResolution,
    append_resolution,
    close_lane,
    lanes_dir,
    load_records,
    load_resolutions,
    reconcile,
)
from lane_termination_guard import classify_lane_termination  # noqa: E402

pytestmark = pytest.mark.unit

_FIXTURES = pathlib.Path(__file__).parent / "fixtures"
_OPEN_FIXTURE = _FIXTURES / "lane_omn18690_open_dispatch.json"
_CLOSED_FIXTURE = _FIXTURES / "lane_omn18690_unattributed_close.json"
_META_FIXTURE = _FIXTURES / "lane_omn18690_agent_meta.json"

#: The harness's agent id for the lane in the fixtures.
MANGLED_AGENT_ID = "aomn18685-sibling-guard-build-1425-a4c6d53620bcd3eb"
#: The dispatch-time lane name the open record actually carries.
REAL_LANE_NAME = "omn18685-sibling-guard-build-1425"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point ``ONEX_STATE_DIR`` at a per-test tmp dir.

    Tests never read this host's live records: the fixtures are copies.
    """

    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))


def _fixture(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _install_fixture_records() -> tuple[str, str]:
    """Write the live pair into the isolated registry. Returns both lane ids."""

    directory = lanes_dir()
    assert directory is not None
    open_payload = _fixture(_OPEN_FIXTURE)
    closed_payload = _fixture(_CLOSED_FIXTURE)
    for payload in (open_payload, closed_payload):
        (directory / f"{payload['lane_id']}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    return str(open_payload["lane_id"]), str(closed_payload["lane_id"])


def _install_open_record(
    *, lane_id: str, lane_name: str, session_id: str
) -> ModelLaneRecord:
    record = ModelLaneRecord(
        lane_id=lane_id,
        lane_name=lane_name,
        session_id=session_id,
        tool_name="Agent",
        dispatched_at="2026-09-18T12:41:41.140100+00:00",
        status=EnumLaneStatus.OPEN,
    )
    directory = lanes_dir()
    assert directory is not None
    (directory / f"{lane_id}.json").write_text(
        json.dumps(record.to_json(), indent=2), encoding="utf-8"
    )
    return record


def _write_agent_transcript(tmp_path: pathlib.Path, *, with_meta: bool) -> str:
    """Write an ``agent-<id>.jsonl`` (+ optional sidecar) the way the harness does."""

    subagents = tmp_path / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    transcript = subagents / f"agent-{MANGLED_AGENT_ID}.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "2026-09-18T12:41:42+00:00",
                "message": {"content": [{"type": "tool_use", "name": "Bash"}]},
            }
        )
        + "\n"
        + json.dumps({"type": "assistant", "timestamp": "2026-09-18T14:01:59+00:00"})
        + "\n",
        encoding="utf-8",
    )
    if with_meta:
        (subagents / f"agent-{MANGLED_AGENT_ID}.meta.json").write_text(
            _META_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
        )
    return str(transcript)


class TestTheLiveDefect:
    """The pair the ticket cites, reproduced from its own record files."""

    def test_the_fixtures_are_the_pair_the_ticket_names(self) -> None:
        """Guards the fixtures themselves: a silent copy drift voids the RED."""

        open_payload = _fixture(_OPEN_FIXTURE)
        closed_payload = _fixture(_CLOSED_FIXTURE)
        assert open_payload["lane_id"] == "lane-5f79b31e7a191435c9ce"
        assert open_payload["status"] == "open"
        assert open_payload["lane_name"] == REAL_LANE_NAME
        assert closed_payload["lane_id"] == "unattributed-29ecc418f1eab1ec58bd"
        assert closed_payload["lane_name"] == MANGLED_AGENT_ID
        assert closed_payload["terminal_state"] == "died_usage_limit"
        # Same session: the two records are one lane, not two.
        assert open_payload["session_id"] == closed_payload["session_id"]

    def test_the_agent_id_embeds_the_lane_name(self) -> None:
        """``a`` + name + ``-`` + 16 hex is the harness's id spelling, not a guess."""

        assert f"a{REAL_LANE_NAME}-a4c6d53620bcd3eb" == MANGLED_AGENT_ID


class TestLaneNameResolution:
    """What name the guard hands the registry at close time."""

    def test_the_meta_sidecar_supplies_the_dispatch_time_name(
        self, tmp_path: pathlib.Path
    ) -> None:
        """RED before the fix: the guard returned the raw agent id."""

        transcript = _write_agent_transcript(tmp_path, with_meta=True)
        result = classify_lane_termination(
            {
                "session_id": "9787a4a3-ec49-4819-8bdc-5044efb94550",
                "agent_id": MANGLED_AGENT_ID,
                "agent_transcript_path": transcript,
            }
        )
        assert result.lane_name == REAL_LANE_NAME

    def test_without_a_sidecar_the_agent_id_is_still_used(
        self, tmp_path: pathlib.Path
    ) -> None:
        """No sidecar must not invent a name -- the old value is the honest one."""

        transcript = _write_agent_transcript(tmp_path, with_meta=False)
        result = classify_lane_termination(
            {
                "session_id": "s",
                "agent_id": MANGLED_AGENT_ID,
                "agent_transcript_path": transcript,
            }
        )
        assert result.lane_name == MANGLED_AGENT_ID

    def test_an_explicit_tool_input_still_wins(self, tmp_path: pathlib.Path) -> None:
        """The sidecar is a fallback, never an override of a supplied name."""

        transcript = _write_agent_transcript(tmp_path, with_meta=True)
        result = classify_lane_termination(
            {
                "session_id": "s",
                "agent_transcript_path": transcript,
                "tool_input": {"name": "explicitly-supplied-lane"},
            }
        )
        assert result.lane_name == "explicitly-supplied-lane"

    def test_an_unreadable_sidecar_does_not_raise(self, tmp_path: pathlib.Path) -> None:
        """Fail-open: a malformed sidecar degrades to the agent id."""

        transcript = _write_agent_transcript(tmp_path, with_meta=True)
        pathlib.Path(transcript).with_suffix(".meta.json").write_text(
            "{not json", encoding="utf-8"
        )
        result = classify_lane_termination(
            {
                "session_id": "s",
                "agent_id": MANGLED_AGENT_ID,
                "agent_transcript_path": transcript,
            }
        )
        assert result.lane_name == MANGLED_AGENT_ID


class TestCloseTargetSelection:
    """The registry's own matcher, independent of where the name came from."""

    def _two_open_lanes(self) -> None:
        """Two open lanes, so the unique-open fallback cannot rescue the match."""

        _install_open_record(
            lane_id="lane-5f79b31e7a191435c9ce",
            lane_name=REAL_LANE_NAME,
            session_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
        )
        _install_open_record(
            lane_id="lane-0000000000000000decoy",
            lane_name="some-other-open-lane",
            session_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
        )

    def test_an_agent_id_closes_the_open_record_it_names(self) -> None:
        """RED before the fix: this minted an ``unattributed-*`` record."""

        self._two_open_lanes()
        closed = close_lane(
            session_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
            lane_name=MANGLED_AGENT_ID,
            terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
            terminal_reason="usage_limit_wall",
        )
        assert closed is not None
        assert closed.lane_id == "lane-5f79b31e7a191435c9ce"
        assert closed.lane_name == REAL_LANE_NAME
        assert closed.status is EnumLaneStatus.CLOSED
        ids = {record.lane_id for record in load_records()}
        assert not [lane_id for lane_id in ids if lane_id.startswith("unattributed-")]

    def test_the_decoy_lane_is_left_open(self) -> None:
        """A match must never close the lane it did not name."""

        self._two_open_lanes()
        close_lane(
            session_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
            lane_name=MANGLED_AGENT_ID,
            terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
            terminal_reason="usage_limit_wall",
        )
        decoy = [
            record
            for record in load_records()
            if record.lane_id == "lane-0000000000000000decoy"
        ]
        assert decoy and decoy[0].status is EnumLaneStatus.OPEN

    def test_an_agent_id_naming_no_open_lane_stays_unattributed(self) -> None:
        """The matcher matches recorded names; it never invents one."""

        _install_open_record(
            lane_id="lane-aaaa",
            lane_name="a-completely-different-lane",
            session_id="s",
        )
        _install_open_record(
            lane_id="lane-bbbb", lane_name="another-one", session_id="s"
        )
        closed = close_lane(
            session_id="s",
            lane_name=MANGLED_AGENT_ID,
            terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
            terminal_reason="usage_limit_wall",
        )
        assert closed is not None
        assert closed.lane_id.startswith("unattributed-")

    def test_an_anonymous_agent_id_has_no_embedded_name(self) -> None:
        """``a`` + 16 hex carries no lane name, so it must not match anything."""

        _install_open_record(lane_id="lane-aaaa", lane_name="lane-one", session_id="s")
        _install_open_record(lane_id="lane-bbbb", lane_name="lane-two", session_id="s")
        closed = close_lane(
            session_id="s",
            lane_name="a01bc2a02096a8a70",
            terminal_state=EnumLaneTerminalState.COMPLETED,
            terminal_reason="completed",
        )
        assert closed is not None
        assert closed.lane_id.startswith("unattributed-")

    def test_a_name_without_the_hex_suffix_is_not_an_agent_id(self) -> None:
        """Only the exact ``a<name>-<16 hex>`` spelling is treated as an id."""

        _install_open_record(
            lane_id="lane-aaaa", lane_name="build-lane", session_id="s"
        )
        _install_open_record(
            lane_id="lane-bbbb", lane_name="other-lane", session_id="s"
        )
        closed = close_lane(
            session_id="s",
            lane_name="abuild-lane-notahexsuffix",
            terminal_state=EnumLaneTerminalState.COMPLETED,
            terminal_reason="completed",
        )
        assert closed is not None
        assert closed.lane_id.startswith("unattributed-")

    def test_a_cross_session_open_lane_is_never_matched(self) -> None:
        """Session scoping is unchanged: an id cannot reach into another session."""

        _install_open_record(
            lane_id="lane-5f79b31e7a191435c9ce",
            lane_name=REAL_LANE_NAME,
            session_id="session-one",
        )
        _install_open_record(
            lane_id="lane-bbbb", lane_name="other", session_id="session-two"
        )
        closed = close_lane(
            session_id="session-two",
            lane_name=MANGLED_AGENT_ID,
            terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
            terminal_reason="usage_limit_wall",
        )
        assert closed is not None
        assert closed.lane_id != "lane-5f79b31e7a191435c9ce"


class TestResolutionJournal:
    """The append-only surface a non-editing repair writes to."""

    def test_a_resolution_closes_an_open_record_without_touching_its_file(self) -> None:
        open_id, closed_id = _install_fixture_records()
        directory = lanes_dir()
        assert directory is not None
        path = directory / f"{open_id}.json"
        before = path.read_bytes()

        append_resolution(
            ModelLaneResolution(
                lane_id=open_id,
                superseded_lane_id=closed_id,
                terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
                terminal_reason="paired with unattributed twin (OMN-18690)",
                resolved_at="2026-09-18T15:00:00+00:00",
                evidence={"agent_id": MANGLED_AGENT_ID},
            )
        )

        assert path.read_bytes() == before
        verdict = reconcile(ttl_seconds=1)
        failed_ids = {record.lane_id for record in verdict.failed}
        assert open_id in failed_ids
        # The twin is superseded, so the pair counts once rather than twice.
        assert closed_id not in failed_ids
        assert len(verdict.failed) == 1

    def test_without_the_resolution_the_pair_counts_twice(self) -> None:
        """The before-state this repair exists to collapse."""

        _install_fixture_records()
        verdict = reconcile(ttl_seconds=1)
        assert len(verdict.failed) == 2

    def test_the_journal_is_append_only(self) -> None:
        open_id, closed_id = _install_fixture_records()
        for index in range(3):
            append_resolution(
                ModelLaneResolution(
                    lane_id=open_id,
                    superseded_lane_id=closed_id,
                    terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
                    terminal_reason=f"attempt {index}",
                    resolved_at="2026-09-18T15:00:00+00:00",
                )
            )
        directory = lanes_dir()
        assert directory is not None
        lines = (
            (directory / "resolutions.jsonl").read_text(encoding="utf-8").splitlines()
        )
        assert len(lines) == 3
        # Last write wins on read, but nothing earlier was erased.
        assert load_resolutions()[open_id].terminal_reason == "attempt 2"

    def test_a_resolution_for_an_unknown_lane_is_inert(self) -> None:
        _install_fixture_records()
        append_resolution(
            ModelLaneResolution(
                lane_id="lane-does-not-exist",
                superseded_lane_id="",
                terminal_state=EnumLaneTerminalState.COMPLETED,
                terminal_reason="noise",
                resolved_at="2026-09-18T15:00:00+00:00",
            )
        )
        assert len(reconcile(ttl_seconds=1).failed) == 2

    def test_a_corrupt_journal_line_is_skipped(self) -> None:
        open_id, closed_id = _install_fixture_records()
        directory = lanes_dir()
        assert directory is not None
        journal = directory / "resolutions.jsonl"
        journal.write_text("{not json\n", encoding="utf-8")
        append_resolution(
            ModelLaneResolution(
                lane_id=open_id,
                superseded_lane_id=closed_id,
                terminal_state=EnumLaneTerminalState.DIED_USAGE_LIMIT,
                terminal_reason="survives a corrupt neighbour",
                resolved_at="2026-09-18T15:00:00+00:00",
            )
        )
        assert open_id in load_resolutions()

    def test_the_journal_is_not_read_as_a_lane_record(self) -> None:
        """``load_records`` globs ``*.json``; the journal must not be swept up."""

        _install_fixture_records()
        append_resolution(
            ModelLaneResolution(
                lane_id="x",
                superseded_lane_id="",
                terminal_state=EnumLaneTerminalState.COMPLETED,
                terminal_reason="r",
                resolved_at="2026-09-18T15:00:00+00:00",
            )
        )
        assert len(load_records()) == 2


class TestPairReconcile:
    """The one-shot, non-editing pairing over records already on disk.

    The fixture's dispatch is recent by construction (it was copied off a
    live host), so these tests name a short ``ttl_seconds`` to isolate the
    pairing rule. The TTL rule itself is proven by its own two tests below,
    and the default is asserted in
    :meth:`test_the_default_ttl_is_the_registry_default`.
    """

    def test_dry_run_pairs_the_live_fixture_pair_and_writes_nothing(self) -> None:
        open_id, closed_id = _install_fixture_records()
        report = lane_pair_reconcile.pair_lanes(ttl_seconds=60)
        assert [(p.open_lane_id, p.unattributed_lane_id) for p in report.pairs] == [
            (open_id, closed_id)
        ]
        directory = lanes_dir()
        assert directory is not None
        assert not (directory / "resolutions.jsonl").exists()

    def test_execute_appends_one_resolution_per_pair(self) -> None:
        open_id, _ = _install_fixture_records()
        report = lane_pair_reconcile.pair_lanes(execute=True, ttl_seconds=60)
        assert len(report.pairs) == 1
        assert load_resolutions()[open_id].terminal_state is (
            EnumLaneTerminalState.DIED_USAGE_LIMIT
        )
        assert len(reconcile(ttl_seconds=1).failed) == 1

    def test_execute_never_modifies_an_existing_record_file(self) -> None:
        open_id, closed_id = _install_fixture_records()
        directory = lanes_dir()
        assert directory is not None
        before = {
            lane_id: (directory / f"{lane_id}.json").read_bytes()
            for lane_id in (open_id, closed_id)
        }
        lane_pair_reconcile.pair_lanes(execute=True, ttl_seconds=60)
        for lane_id, payload in before.items():
            assert (directory / f"{lane_id}.json").read_bytes() == payload

    def test_an_ambiguous_pairing_is_declined(self) -> None:
        """Two open records with the same name: never guess between them."""

        _install_fixture_records()
        _install_open_record(
            lane_id="lane-duplicate-name",
            lane_name=REAL_LANE_NAME,
            session_id="9787a4a3-ec49-4819-8bdc-5044efb94550",
        )
        report = lane_pair_reconcile.pair_lanes(ttl_seconds=60)
        assert report.pairs == ()
        assert report.ambiguous == 1

    def test_an_anonymous_agent_id_is_reported_unpairable(self) -> None:
        directory = lanes_dir()
        assert directory is not None
        payload = _fixture(_CLOSED_FIXTURE)
        payload["lane_name"] = "a01bc2a02096a8a70"
        (directory / f"{payload['lane_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        report = lane_pair_reconcile.pair_lanes(ttl_seconds=60)
        assert report.pairs == ()
        assert report.unpairable == 1

    def test_a_pairing_requires_the_dispatch_to_precede_the_close(self) -> None:
        """A lane dispatched after the death cannot be the one that died."""

        _install_fixture_records()
        directory = lanes_dir()
        assert directory is not None
        path = directory / "lane-5f79b31e7a191435c9ce.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["dispatched_at"] = "2026-09-19T00:00:00+00:00"
        path.write_text(json.dumps(payload), encoding="utf-8")
        assert lane_pair_reconcile.pair_lanes(ttl_seconds=60).pairs == ()

    def _recent_pair(self) -> None:
        """A twin closed just now, and a dispatch record 5 minutes old.

        This is the shape a usage-limit *pause* leaves behind while the
        lane is still working.
        """

        _install_fixture_records()
        directory = lanes_dir()
        assert directory is not None
        now = datetime.now(UTC)

        open_path = directory / "lane-5f79b31e7a191435c9ce.json"
        open_payload = json.loads(open_path.read_text(encoding="utf-8"))
        open_payload["dispatched_at"] = (now - timedelta(minutes=5)).isoformat()
        open_path.write_text(json.dumps(open_payload), encoding="utf-8")

        twin_path = directory / "unattributed-29ecc418f1eab1ec58bd.json"
        twin_payload = json.loads(twin_path.read_text(encoding="utf-8"))
        twin_payload["closed_at"] = now.isoformat()
        twin_path.write_text(json.dumps(twin_payload), encoding="utf-8")

    def test_an_open_lane_still_within_ttl_is_never_resolved(self) -> None:
        """A twin can be written at a pause the lane resumes from.

        Resolving such a record would report a lane that is still working
        as dead. 33 of this host's records were in exactly that state on
        the first pass over live state, so the bound is measured rather
        than defensive.
        """

        self._recent_pair()
        report = lane_pair_reconcile.pair_lanes()
        assert report.pairs == ()
        assert report.still_within_ttl == 1

    def test_the_same_lane_pairs_once_its_ttl_elapses(self) -> None:
        """The TTL guard defers the repair; it does not cancel it.

        Same two records as the test above, read with a TTL they have
        outlived. Nothing else differs.
        """

        self._recent_pair()
        report = lane_pair_reconcile.pair_lanes(ttl_seconds=60)
        assert len(report.pairs) == 1
        assert report.still_within_ttl == 0

    def test_rerunning_execute_is_idempotent(self) -> None:
        _install_fixture_records()
        lane_pair_reconcile.pair_lanes(execute=True, ttl_seconds=60)
        second = lane_pair_reconcile.pair_lanes(execute=True, ttl_seconds=60)
        assert second.pairs == ()
        assert second.already_resolved == 1

    def test_the_default_ttl_is_the_registry_default(self) -> None:
        """The repair must not use a looser TTL than the gate it feeds."""

        import inspect

        signature = inspect.signature(lane_pair_reconcile.pair_lanes)
        assert signature.parameters["ttl_seconds"].default == (
            lane_pair_reconcile.DEFAULT_OPEN_TTL_SECONDS
        )

    def test_the_cli_reports_the_pair_count_and_defaults_to_dry_run(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _install_fixture_records()
        assert lane_pair_reconcile.main(["--ttl-seconds", "60"]) == 0
        captured = capsys.readouterr().out
        assert "pairs: 1" in captured
        assert "DRY RUN" in captured
        directory = lanes_dir()
        assert directory is not None
        assert not (directory / "resolutions.jsonl").exists()
