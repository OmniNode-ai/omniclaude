# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane attribution on the hook-capture path (OMN-18609).

These tests pin the three things that make a hook event attributable to a lane
without reading ``session_id``:

* a registered worktree resolves to its lane (AC1),
* the hook's own fire time survives the relay (AC2),
* an unregistered directory NEVER inherits a neighbouring lane's name (AC3).

The last one is the fail-closed direction and is why this file exists rather
than a one-line payload addition. A wrong lane on an event is worse than no
lane: a drop detector cannot tell a wrong attribution from a right one, so one
mis-resolved directory reports a dead lane alive on another lane's work.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

HOOKS_LIB = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(HOOKS_LIB))

import hook_emit_journal as journal  # noqa: E402
import hook_lane_attribution as attribution  # noqa: E402

pytestmark = pytest.mark.unit


def _register(
    state_dir: Path, worktree: Path, lane: str, ticket: str = "OMN-18609"
) -> None:
    """Write a lane record the way ``lane_identity register`` writes one.

    *state_dir* is the registry ROOT (the ``.onex_state`` level), matching
    ``lane_identity.registry_root_from_env``; records sit one level below it.
    """
    registry = state_dir / attribution.REGISTRY_SUBDIR
    registry.mkdir(parents=True, exist_ok=True)
    (registry / f"{attribution.record_key(worktree)}.json").write_text(
        json.dumps(
            {
                "lane": lane,
                "session_id": "session-under-test",
                "ticket": ticket,
                "worktree": str(worktree),
                "registered_at": "2026-09-17T17:00:00Z",
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A workspace root with the registry beneath it, isolated from the host.

    Mirrors the live layout exactly: the workspace root is ``$OMNI_HOME``, the
    registry root is ``$OMNI_HOME/.onex_state``, and records live one level
    below that. Getting this wrong in a fixture would make the upward-walk
    tests pass for the wrong reason.
    """
    root = tmp_path / "workspace"
    state_dir = root / attribution.STATE_SUBDIR
    (state_dir / attribution.REGISTRY_SUBDIR).mkdir(parents=True)
    monkeypatch.setenv(attribution.REGISTRY_ROOT_ENV, str(state_dir))
    monkeypatch.delenv(attribution.WORKSPACE_ENV, raising=False)
    return root


# --------------------------------------------------------------------------
# AC1 -- a registered worktree resolves to its lane
# --------------------------------------------------------------------------


def test_a_registered_worktree_resolves_to_its_lane(workspace: Path) -> None:
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    _register(
        workspace / attribution.STATE_SUBDIR,
        worktree,
        "hook-ledger-first-reader-build-1650",
    )

    fields = attribution.attribution_fields(worktree)

    assert fields["lane"] == "hook-ledger-first-reader-build-1650"
    assert fields["lane_source"] == attribution.LANE_SOURCE_REGISTRY
    assert fields["lane_ticket"] == "OMN-18609"


def test_a_subdirectory_of_the_worktree_resolves_to_the_same_lane(
    workspace: Path,
) -> None:
    """A lane working inside its own worktree is still that lane."""
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    nested = worktree / "src" / "deep" / "path"
    nested.mkdir(parents=True)
    _register(
        workspace / attribution.STATE_SUBDIR,
        worktree,
        "hook-ledger-first-reader-build-1650",
    )

    assert (
        attribution.attribution_fields(nested)["lane"]
        == "hook-ledger-first-reader-build-1650"
    )


def test_every_attribution_key_is_always_present(workspace: Path) -> None:
    """An absent key and an empty key mean different things to a reader.

    A reader has to distinguish "this emitter asked and got no answer" from
    "this row predates lane attribution entirely", because only the second kind
    may be excluded from a lane-keyed query without under-reporting.
    """
    unknown = workspace / "not-a-worktree"
    unknown.mkdir()

    fields = attribution.attribution_fields(unknown)

    assert set(fields) == {"lane", "lane_source", "lane_ticket", "workspace_path"}


# --------------------------------------------------------------------------
# AC3 -- the fail-closed direction
# --------------------------------------------------------------------------


def test_an_unregistered_directory_never_inherits_a_neighbouring_lane(
    workspace: Path,
) -> None:
    """The hazard this module exists to refuse.

    ``omnibase_infra`` is a sibling of the registered worktree, not a child of
    it. Walking up from it must not find the neighbour's record.
    """
    registered = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    registered.mkdir(parents=True)
    _register(workspace / attribution.STATE_SUBDIR, registered, "some-other-lane-1234")

    sibling = workspace / "omni_worktrees" / "OMN-18609" / "omnibase_infra"
    sibling.mkdir(parents=True)

    fields = attribution.attribution_fields(sibling)

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_a_lane_registered_at_the_workspace_root_answers_for_nothing(
    workspace: Path,
) -> None:
    """The upward walk stops strictly below the workspace root.

    If it did not, one record at the shared root would attribute every tool
    call on the machine -- including every other lane's -- to a single lane.
    """
    _register(
        workspace / attribution.STATE_SUBDIR,
        workspace,
        "lane-that-claimed-the-whole-box",
    )
    somewhere = workspace / "omnibase_infra"
    somewhere.mkdir()

    fields = attribution.attribution_fields(somewhere)

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_an_unresolvable_registry_reports_unavailable_not_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "I could not look" and "I looked and found nothing" are different facts."""
    monkeypatch.delenv(attribution.REGISTRY_ROOT_ENV, raising=False)
    monkeypatch.delenv(attribution.WORKSPACE_ENV, raising=False)

    fields = attribution.attribution_fields(tmp_path)

    assert fields["lane_source"] == attribution.LANE_SOURCE_UNAVAILABLE


def test_a_malformed_record_stops_the_walk_rather_than_climbing(
    workspace: Path,
) -> None:
    """An unreadable record must not become a licence to use a parent's lane."""
    parent = workspace / "omni_worktrees" / "OMN-18609"
    child = parent / "omniclaude"
    child.mkdir(parents=True)
    _register(workspace / attribution.STATE_SUBDIR, parent, "parent-lane-9999")
    registry = workspace / attribution.STATE_SUBDIR / attribution.REGISTRY_SUBDIR
    (registry / f"{attribution.record_key(child)}.json").write_text(
        "{not json", encoding="utf-8"
    )

    fields = attribution.attribution_fields(child)

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_no_absolute_host_path_reaches_the_payload(workspace: Path) -> None:
    """The workspace-relative path never carries the operator's home directory.

    Hook events land in a shared cloud table collaborators read. An absolute
    local path is both unresolvable for them and a CLAUDE.md rule 6 violation.
    """
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)

    rendered = attribution.attribution_fields(worktree)["workspace_path"]

    assert rendered == "omni_worktrees/OMN-18609/omniclaude"
    assert not rendered.startswith("/")
    assert str(workspace) not in rendered


# --------------------------------------------------------------------------
# Drift -- this module and lane_identity must agree on the key
# --------------------------------------------------------------------------


def test_the_record_key_matches_the_registry_that_writes_it(tmp_path: Path) -> None:
    """Pin the transcription against its authority.

    ``hook_lane_attribution`` re-implements the read half of
    ``lane_identity``'s key on purpose (hooks run under a bare interpreter
    where importing the packaged module is a crash, not an import error). That
    choice is only safe while the two agree, so this test imports the authority
    -- where importing it IS safe -- and asserts they do.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import lane_identity  # noqa: PLC0415

    probe = tmp_path / "some" / "worktree"
    probe.mkdir(parents=True)

    assert attribution.record_key(probe) == lane_identity._key(probe)
    assert (
        lane_identity.record_path(tmp_path, probe).name
        == f"{attribution.record_key(probe)}.json"
    )
    assert (
        lane_identity.record_path(tmp_path, probe).parent.name
        == attribution.REGISTRY_SUBDIR
    )


def test_a_record_written_by_lane_identity_is_read_by_this_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end across the seam: the registry writes, the hook path reads."""
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import lane_identity  # noqa: PLC0415

    root = tmp_path / "workspace"
    state_dir = root / attribution.STATE_SUBDIR
    worktree = root / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    lane_identity.register(
        state_dir,
        lane="hook-ledger-first-reader-build-1650",
        ticket="OMN-18609",
        worktree=worktree,
        session_id="session-under-test",
    )
    monkeypatch.setenv(attribution.REGISTRY_ROOT_ENV, str(state_dir))
    monkeypatch.delenv(attribution.WORKSPACE_ENV, raising=False)

    assert (
        attribution.attribution_fields(worktree)["lane"]
        == "hook-ledger-first-reader-build-1650"
    )


# --------------------------------------------------------------------------
# AC1 wiring -- the CLI actually merges the fields onto the journalled payload
# --------------------------------------------------------------------------


def test_the_emit_cli_merges_lane_fields_onto_the_journalled_event(
    workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    _register(
        workspace / attribution.STATE_SUBDIR,
        worktree,
        "hook-ledger-first-reader-build-1650",
    )
    journal_dir = tmp_path / "journal"

    sys.path.insert(0, str(HOOKS_LIB))
    import hook_emit_append  # noqa: PLC0415

    rc = hook_emit_append.main(
        [
            "--event-type",
            "tool.executed",
            "--payload",
            json.dumps({"tool_name": "Bash", "working_directory": "omniclaude"}),
            "--correlation-id",
            "session-under-test",
            "--cwd",
            str(worktree),
            "--journal-dir",
            str(journal_dir),
        ]
    )

    assert rc == 0
    written = sorted(journal_dir.glob("*.json"))
    assert len(written) == 1
    payload = json.loads(written[0].read_text())["payload"]
    assert payload["lane"] == "hook-ledger-first-reader-build-1650"
    assert payload["lane_source"] == attribution.LANE_SOURCE_REGISTRY
    assert payload["tool_name"] == "Bash"


def test_a_caller_supplied_lane_key_does_not_override_the_registry(
    workspace: Path, tmp_path: Path
) -> None:
    """The registry is the authority; a payload cannot name its own lane.

    Otherwise anything that can reach the hook path can attribute its work to
    another lane, which is the attribution equivalent of self-approval.
    """
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    _register(workspace / attribution.STATE_SUBDIR, worktree, "the-real-lane-1650")
    journal_dir = tmp_path / "journal"

    sys.path.insert(0, str(HOOKS_LIB))
    import hook_emit_append  # noqa: PLC0415

    hook_emit_append.main(
        [
            "--event-type",
            "tool.executed",
            "--payload",
            json.dumps({"lane": "a-lane-i-just-made-up"}),
            "--cwd",
            str(worktree),
            "--journal-dir",
            str(journal_dir),
        ]
    )

    payload = json.loads(sorted(journal_dir.glob("*.json"))[0].read_text())["payload"]
    assert payload["lane"] == "the-real-lane-1650"


# --------------------------------------------------------------------------
# AC2 -- the hook's fire time survives the relay
# --------------------------------------------------------------------------


def test_the_published_payload_carries_the_hook_fire_time() -> None:
    """The instant the hook fired, not the instant the drainer published it.

    Before this, the only surviving timestamp was stamped by the emit envelope
    at publish, so a relay outage moved every event it delayed to the far side
    of the outage.
    """
    import hook_emit_drainer as drainer  # noqa: PLC0415

    fired = datetime(2026, 9, 17, 15, 22, 11, tzinfo=UTC)
    record = journal.JournalRecord(
        event_id="e1",
        event_type="tool.executed",
        payload={"tool_name": "Bash"},
        correlation_id="session-under-test",
        queued_at=fired,
    )

    published = drainer._with_fire_time(record)

    assert published[drainer.FIRE_TIME_KEY] == fired.isoformat()
    assert published["tool_name"] == "Bash"


def test_adding_the_fire_time_does_not_mutate_the_journal_record() -> None:
    """A retry re-publishes the same record; publishing must be idempotent."""
    import hook_emit_drainer as drainer  # noqa: PLC0415

    record = journal.JournalRecord(
        event_id="e1",
        event_type="tool.executed",
        payload={"tool_name": "Bash"},
        correlation_id="c",
        queued_at=datetime(2026, 9, 17, 15, 22, 11, tzinfo=UTC),
    )

    first = drainer._with_fire_time(record)
    second = drainer._with_fire_time(record)

    assert drainer.FIRE_TIME_KEY not in record.payload
    assert first == second


def test_the_fire_time_precedes_publish_across_a_simulated_outage() -> None:
    """AC2's falsifier in miniature, without stopping the live drainer.

    A record queued during an outage and published after it must report a fire
    time on the near side of the gap. This is the property that lets a reader
    tell "nothing happened" from "nothing was delivered".
    """
    import hook_emit_drainer as drainer  # noqa: PLC0415

    fired_during_outage = datetime(2026, 9, 17, 15, 22, 11, tzinfo=UTC)
    published_after = datetime(2026, 9, 17, 16, 2, 0, tzinfo=UTC)
    record = journal.JournalRecord(
        event_id="e1",
        event_type="tool.executed",
        payload={},
        correlation_id="c",
        queued_at=fired_during_outage,
    )

    carried = datetime.fromisoformat(
        drainer._with_fire_time(record)[drainer.FIRE_TIME_KEY]
    )

    assert carried < published_after
    assert (published_after - carried).total_seconds() > 2000


# --------------------------------------------------------------------------
# The hooks themselves must pass the cwd, or none of the above runs in anger
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script",
    [
        "post_tool_use_bus_mirror.sh",
        "user_prompt_submit_bus_mirror.sh",
        "session_start_bus_mirror.sh",
        "session_end_bus_mirror.sh",
    ],
)
def test_every_bus_mirror_passes_the_hook_cwd_to_the_emitter(script: str) -> None:
    """Lane resolution reads the harness's cwd, never the hook process's own.

    A hook forked by the harness does not necessarily inherit the directory the
    tool call was made in, so resolving against ``os.getcwd()`` would attribute
    every lane's work to the session's directory.
    """
    text = (REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / script).read_text()

    assert "hook_emit_append.py" in text
    assert "--cwd" in text


# --------------------------------------------------------------------------
# AC1, second operand -- the harness sidecar (OMN-18609 follow-up)
#
# The cwd chain above is correct and, on this fleet, never fires. Every
# dispatched lane makes its tool calls with the harness ``cwd`` set to the
# SESSION's directory -- the workspace root -- not to its own worktree, so the
# upward walk's first candidate is the root, the "stop below the root" guard
# trips immediately, and the answer is ``unresolved``. Measured on 4,720 live
# journal records: every one carries ``lane: ""``, ``lane_source:
# "unresolved"``, ``workspace_path: "."``.
#
# The operand that DOES identify a lane at emit time is the one OMN-18690 uses
# at close time: the harness writes ``agent-<agent id>.meta.json`` beside each
# subagent transcript, and its ``name`` is the dispatch-time lane name. The
# PostToolUse hook payload carries ``agent_id`` and ``transcript_path``, which
# is enough to find it.
# --------------------------------------------------------------------------


#: Stands in for the harness's project-directory slug. Its spelling is
#: irrelevant to the resolver -- the sidecar directory is derived from the
#: transcript path -- and a real one would carry an operator home directory
#: into a public tree.
_PROJECT_SLUG = "-workspace-omni-home"


def _harness_sidecar(
    projects: Path,
    session_id: str,
    agent_id: str,
    meta: dict[str, str] | None,
    *,
    slug: str = _PROJECT_SLUG,
) -> Path:
    """Write the harness's own spawn artifacts and return the transcript path.

    Mirrors the live layout exactly: ``<projects>/<slug>/<session>.jsonl`` for
    the parent session, and ``<projects>/<slug>/<session>/subagents/agent-<agent
    id>.meta.json`` for each lane spawned from it.
    """
    project_dir = projects / slug
    subagents = project_dir / session_id / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    transcript = project_dir / f"{session_id}.jsonl"
    transcript.write_text("", encoding="utf-8")
    if meta is not None:
        (subagents / f"agent-{agent_id}.meta.json").write_text(
            json.dumps(meta), encoding="utf-8"
        )
    return transcript


def test_a_teammate_tool_call_resolves_its_lane_from_the_harness_sidecar(
    workspace: Path, tmp_path: Path
) -> None:
    """AC1 on the path lanes actually take.

    The cwd is the workspace root -- what every dispatched lane reports -- so
    the registry chain cannot answer. The sidecar can.
    """
    transcript = _harness_sidecar(
        tmp_path / "projects",
        "9787a4a3-ec49-4819-8bdc-5044efb94550",
        "aomn18609-emit-lane-attribution-build-1620-30f8f7a7f0a44bb1",
        {
            "name": "omn18609-emit-lane-attribution-build-1620",
            "agentType": "omn18609-emit-lane-attribution-build-1620",
            "description": "Fix emit-time lane attribution",
        },
    )

    fields = attribution.attribution_fields(
        workspace,
        transcript_path=str(transcript),
        agent_id="aomn18609-emit-lane-attribution-build-1620-30f8f7a7f0a44bb1",
    )

    assert fields["lane"] == "omn18609-emit-lane-attribution-build-1620"
    assert fields["lane_source"] == attribution.LANE_SOURCE_SIDECAR


def test_the_workspace_root_cwd_that_defeats_the_registry_still_resolves(
    workspace: Path, tmp_path: Path
) -> None:
    """The regression this change exists to close, stated as a before/after.

    Same inputs, twice: without the sidecar operand the answer is the live
    defect (``unresolved``); with it the lane is named.
    """
    agent_id = "ahook-drainer-backlog-diag-1610-d7054914fd016c01"
    transcript = _harness_sidecar(
        tmp_path / "projects",
        "9787a4a3-ec49-4819-8bdc-5044efb94550",
        agent_id,
        {"name": "hook-drainer-backlog-diag-1610"},
    )

    before = attribution.attribution_fields(workspace)
    after = attribution.attribution_fields(
        workspace, transcript_path=str(transcript), agent_id=agent_id
    )

    assert before["lane"] == ""
    assert before["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED
    assert after["lane"] == "hook-drainer-backlog-diag-1610"


def test_the_sidecar_is_preferred_over_a_registered_worktree(
    workspace: Path, tmp_path: Path
) -> None:
    """When both answer, the harness's own record wins.

    The sidecar names the lane the harness dispatched; a worktree record names
    whichever lane last registered that path, which outlives the lane itself.
    """
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    _register(workspace / attribution.STATE_SUBDIR, worktree, "a-stale-registration")
    agent_id = "alive-lane-1620-abc123"
    transcript = _harness_sidecar(
        tmp_path / "projects", "session-under-test", agent_id, {"name": "a-live-lane"}
    )

    fields = attribution.attribution_fields(
        worktree, transcript_path=str(transcript), agent_id=agent_id
    )

    assert fields["lane"] == "a-live-lane"
    assert fields["lane_source"] == attribution.LANE_SOURCE_SIDECAR


def test_an_agent_id_with_no_sidecar_falls_back_to_the_registry(
    workspace: Path, tmp_path: Path
) -> None:
    """A missing sidecar degrades to the older operand rather than to nothing."""
    worktree = workspace / "omni_worktrees" / "OMN-18609" / "omniclaude"
    worktree.mkdir(parents=True)
    _register(workspace / attribution.STATE_SUBDIR, worktree, "registered-lane-1650")
    transcript = _harness_sidecar(
        tmp_path / "projects", "session-under-test", "some-other-agent", {"name": "x"}
    )

    fields = attribution.attribution_fields(
        worktree, transcript_path=str(transcript), agent_id="an-agent-never-spawned"
    )

    assert fields["lane"] == "registered-lane-1650"
    assert fields["lane_source"] == attribution.LANE_SOURCE_REGISTRY


# --------------------------------------------------------------------------
# AC3 again -- the sidecar operand must never invent a lane either
# --------------------------------------------------------------------------


def test_no_agent_id_is_the_main_session_and_stays_unresolved(
    workspace: Path, tmp_path: Path
) -> None:
    """The top-level session is not a lane, and must not borrow one.

    Every sidecar in the session directory belongs to some lane; picking any of
    them for an un-agented tool call would attribute the operator's own work to
    whichever lane happened to sort first.
    """
    _harness_sidecar(
        tmp_path / "projects",
        "9787a4a3-ec49-4819-8bdc-5044efb94550",
        "aonly-lane-1600-deadbeef",
        {"name": "only-lane-1600"},
    )
    transcript = (
        tmp_path
        / "projects"
        / _PROJECT_SLUG
        / "9787a4a3-ec49-4819-8bdc-5044efb94550.jsonl"
    )

    fields = attribution.attribution_fields(
        workspace, transcript_path=str(transcript), agent_id=""
    )

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_an_unknown_agent_id_never_borrows_a_sibling_lanes_sidecar(
    workspace: Path, tmp_path: Path
) -> None:
    """AC3 for the sidecar operand: 3,469 sidecars, none of them this lane's."""
    projects = tmp_path / "projects"
    for suffix in ("aaa", "bbb", "ccc"):
        _harness_sidecar(
            projects,
            "session-under-test",
            f"a-peer-{suffix}",
            {"name": f"peer-{suffix}"},
        )
    transcript = projects / _PROJECT_SLUG / "session-under-test.jsonl"

    fields = attribution.attribution_fields(
        workspace, transcript_path=str(transcript), agent_id="a-lane-with-no-sidecar"
    )

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_a_sidecar_carrying_no_name_resolves_unresolved(
    workspace: Path, tmp_path: Path
) -> None:
    """A sidecar the harness wrote differently is not a licence to guess."""
    agent_id = "a-nameless-lane-1620"
    transcript = _harness_sidecar(
        tmp_path / "projects", "session-under-test", agent_id, {"spawnDepth": "0"}
    )

    fields = attribution.attribution_fields(
        workspace, transcript_path=str(transcript), agent_id=agent_id
    )

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_a_malformed_sidecar_resolves_unresolved_and_never_raises(
    workspace: Path, tmp_path: Path
) -> None:
    """Fail-open: a corrupt sidecar must not break the operator's tool call."""
    agent_id = "a-corrupt-lane-1620"
    projects = tmp_path / "projects"
    transcript = _harness_sidecar(projects, "session-under-test", agent_id, None)
    (
        projects
        / _PROJECT_SLUG
        / "session-under-test"
        / "subagents"
        / f"agent-{agent_id}.meta.json"
    ).write_text("{not json", encoding="utf-8")

    fields = attribution.attribution_fields(
        workspace, transcript_path=str(transcript), agent_id=agent_id
    )

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_an_agent_id_is_never_read_as_a_path(workspace: Path, tmp_path: Path) -> None:
    """A traversing agent id must not escape the session's subagents directory.

    The agent id arrives from the harness payload and is interpolated into a
    filename; a value containing separators must be refused rather than
    resolved, or the lookup reads a file outside the directory it is scoped to.
    """
    projects = tmp_path / "projects"
    transcript = _harness_sidecar(
        projects, "session-under-test", "a-normal-lane", {"name": "a-normal-lane"}
    )
    (tmp_path / "elsewhere").mkdir(parents=True, exist_ok=True)
    (tmp_path / "elsewhere" / "agent-x.meta.json").write_text(
        json.dumps({"name": "a-lane-from-outside"}), encoding="utf-8"
    )

    fields = attribution.attribution_fields(
        workspace,
        transcript_path=str(transcript),
        agent_id="../../../../elsewhere/x",
    )

    assert fields["lane"] == ""
    assert fields["lane_source"] == attribution.LANE_SOURCE_UNRESOLVED


def test_the_sidecar_name_keys_match_the_close_time_guard() -> None:
    """Open, close and emit must read the same key, or a lane splits in two.

    ``lane_registry.extract_lane_name`` names the lane at dispatch and
    ``lane_termination_guard`` reads it back at close. If the emit path read a
    different key, a lane's tool calls would land under one name and its
    CLAIM/TERMINAL rows under another, and the reader would report both a
    silent lane and an unclaimed one.
    """
    import lane_termination_guard  # noqa: PLC0415

    assert attribution.SIDECAR_NAME_KEYS == lane_termination_guard._META_NAME_KEYS


# --------------------------------------------------------------------------
# Wiring -- the hooks must hand over the agent id, or none of the above runs
# --------------------------------------------------------------------------


def test_the_emit_cli_resolves_the_lane_from_the_agent_id(
    workspace: Path, tmp_path: Path
) -> None:
    """End to end through the CLI the hook actually invokes."""
    agent_id = "aomn18609-emit-lane-attribution-build-1620-30f8f7a7"
    transcript = _harness_sidecar(
        tmp_path / "projects",
        "9787a4a3-ec49-4819-8bdc-5044efb94550",
        agent_id,
        {"name": "omn18609-emit-lane-attribution-build-1620"},
    )
    journal_dir = tmp_path / "journal"

    sys.path.insert(0, str(HOOKS_LIB))
    import hook_emit_append  # noqa: PLC0415

    rc = hook_emit_append.main(
        [
            "--event-type",
            "tool.executed",
            "--payload",
            json.dumps({"tool_name": "Bash"}),
            "--cwd",
            str(workspace),
            "--agent-id",
            agent_id,
            "--transcript-path",
            str(transcript),
            "--journal-dir",
            str(journal_dir),
        ]
    )

    assert rc == 0
    payload = json.loads(sorted(journal_dir.glob("*.json"))[0].read_text())["payload"]
    assert payload["lane"] == "omn18609-emit-lane-attribution-build-1620"
    assert payload["lane_source"] == attribution.LANE_SOURCE_SIDECAR


@pytest.mark.parametrize(
    "script",
    [
        "post_tool_use_bus_mirror.sh",
        "user_prompt_submit_bus_mirror.sh",
        "session_start_bus_mirror.sh",
        "session_end_bus_mirror.sh",
    ],
)
def test_every_bus_mirror_passes_the_agent_id_and_transcript_path(script: str) -> None:
    """Without both, the sidecar cannot be found and every row is unresolved.

    This is the half that was missing in anger: the resolver was correct and
    nothing handed it the operand it needed.
    """
    text = (REPO_ROOT / "plugins" / "onex" / "hooks" / "scripts" / script).read_text()

    assert "--agent-id" in text
    assert "--transcript-path" in text
    assert ".agent_id" in text
    assert ".transcript_path" in text
