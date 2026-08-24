# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit + regression tests for the lane-liveness guard [OMN-16478].

The non-negotiable regression proofs, taken straight from friction report
``docs/tracking/2026-08-24-system-friction-report.md`` §F-10:

* the **F-10 incident shape** — "take over OMN-16432 and land it.
  ``supersede-binding-fix`` is dead (stale auth, Not logged in), so no reply
  will come" — is BLOCKED while that lane's transcript is fresh;
* ``UNREACHABLE`` blocks a takeover exactly as hard as ``ALIVE`` does (the
  2026-08-17 ``occ-6118-close`` shape, where a stall-check gap was read as
  death);
* a failed send, an absent ``ListAgents`` row, and an ``idle`` status cannot
  produce ``DEAD`` — they are not inputs to the prober at all;
* a bare harness ref used as an address is refused (the ``resume-coordinator``
  stale-raw-ID shape);
* the guard fails OPEN on a missing registry, an unparsable call, and its own
  internal error — it blocks on a corroborated wrong claim, never on a defect.

Every filesystem source is built in a tmp_path fixture, so these are hermetic:
no real ``~/.claude`` and no real ledger are read.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"


def _load(name: str) -> Any:
    """Load a hook lib by bare name, the way the shell wrapper runs it."""
    if str(_LIB_DIR) not in sys.path:
        sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(name, _LIB_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


liveness = _load("lane_liveness")
guard = _load("lane_liveness_guard")


# --------------------------------------------------------------------------- #
# Fixtures — a synthetic ~/.claude tree and ledger
# --------------------------------------------------------------------------- #

TEAM = "session-24d8c7fe"
PROJECT = "-Users-jonah-Code-omni-home"
SESSION = "e2583369-b006-4c23-9a79-b13061f0ea09"


def _write_registry(root: Path, lanes: dict[str, str]) -> None:
    """lanes: name -> agentId."""
    team_dir = root / "teams" / TEAM
    team_dir.mkdir(parents=True, exist_ok=True)
    (team_dir / "config.json").write_text(
        json.dumps(
            {
                "name": TEAM,
                "leadAgentId": f"team-lead@{TEAM}",
                "members": [
                    {"name": name, "agentId": agent_id, "agentType": "general-purpose"}
                    for name, agent_id in lanes.items()
                ],
            }
        )
    )


def _write_transcript(root: Path, lane: str, age_s: float) -> Path:
    subagents = root / "projects" / PROJECT / SESSION / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    path = subagents / f"agent-a{lane}-275c679a51172240.jsonl"
    path.write_text('{"type":"assistant"}\n')
    stamp = time.time() - age_s
    os.utime(path, (stamp, stamp))
    return path


def _write_ledger(tmp_path: Path, rows: list[tuple[float, str, str]]) -> Path:
    """rows: (age_seconds, lane, kind)."""
    path = tmp_path / "ROLLING_WORK_LEDGER.md"
    lines = ["# Rolling Work Ledger", ""]
    for age_s, lane, kind in rows:
        stamp = time.gmtime(time.time() - age_s)
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", stamp)
        lines.append(f"{ts} | {lane} | OMN-16432 | {kind} | synthetic row")
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def claude_root(tmp_path: Path) -> Path:
    root = tmp_path / "claude"
    root.mkdir()
    return root


# --------------------------------------------------------------------------- #
# The prober — verdict lattice
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_fresh_transcript_is_alive(claude_root: Path, tmp_path: Path) -> None:
    _write_registry(
        claude_root, {"supersede-binding-fix": f"supersede-binding-fix@{TEAM}"}
    )
    _write_transcript(claude_root, "supersede-binding-fix", age_s=120)
    ledger = _write_ledger(tmp_path, [])

    verdict = liveness.probe("supersede-binding-fix", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.ALIVE
    assert verdict.takeover_permitted is False


@pytest.mark.unit
def test_stale_transcript_but_fresh_ledger_row_is_alive(
    claude_root: Path, tmp_path: Path
) -> None:
    """Independent sources: a lane grinding on one long tool call is alive."""
    _write_registry(claude_root, {"occ-6118-close": f"occ-6118-close@{TEAM}"})
    _write_transcript(claude_root, "occ-6118-close", age_s=5 * 3600)
    ledger = _write_ledger(tmp_path, [(300, "occ-6118-close", "CLAIM")])

    verdict = liveness.probe("occ-6118-close", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.ALIVE


@pytest.mark.unit
def test_all_sources_stale_is_dead(claude_root: Path, tmp_path: Path) -> None:
    _write_registry(claude_root, {"occ-6118-close": f"occ-6118-close@{TEAM}"})
    _write_transcript(claude_root, "occ-6118-close", age_s=6 * 3600)
    ledger = _write_ledger(tmp_path, [(7 * 3600, "occ-6118-close", "CLAIM")])

    verdict = liveness.probe("occ-6118-close", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.DEAD
    assert verdict.takeover_permitted is True


@pytest.mark.unit
def test_dead_reason_does_not_overclaim_an_absent_ledger_row(
    claude_root: Path, tmp_path: Path
) -> None:
    """A DEAD receipt is read by a human deciding whether to take over, so it
    must not present "this lane has no ledger row" as "this lane was quiet in
    the ledger" — those are an absent source and an observation, respectively."""
    _write_registry(claude_root, {"forkci-ticket": f"forkci-ticket@{TEAM}"})
    _write_transcript(claude_root, "forkci-ticket", age_s=6 * 3600)
    ledger = _write_ledger(tmp_path, [])

    verdict = liveness.probe("forkci-ticket", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.DEAD
    assert "no ledger row at all" in verdict.reason
    assert verdict.evidence.ledger_age_s is None


@pytest.mark.unit
def test_recent_ledger_row_rescues_a_stale_transcript_from_dead(
    claude_root: Path, tmp_path: Path
) -> None:
    """The ledger can only ever rescue a lane, never condemn it."""
    _write_registry(claude_root, {"node-ci-track": f"node-ci-track@{TEAM}"})
    _write_transcript(claude_root, "node-ci-track", age_s=6 * 3600)
    ledger = _write_ledger(tmp_path, [(70 * 60, "node-ci-track", "CLAIM")])

    verdict = liveness.probe("node-ci-track", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.UNREACHABLE


@pytest.mark.unit
def test_terminal_row_alone_cannot_condemn_when_transcripts_are_unreadable(
    claude_root: Path, tmp_path: Path
) -> None:
    """A TERMINAL row is a statement about one assignment, not about the process.

    A lane can post TERMINAL and keep running on the next thing, so a single
    uncorroborated source must not authorize supersession. With no transcript
    root on this host we did not observe the lane going quiet — we merely failed
    to look, which the module contract says resolves to UNREACHABLE.
    """
    _write_registry(claude_root, {"wave2-closeout": f"wave2-closeout@{TEAM}"})
    # No projects/ tree at all -> the transcript source cannot be consulted.
    ledger = _write_ledger(tmp_path, [(3 * 3600, "wave2-closeout", "TERMINAL")])

    verdict = liveness.probe("wave2-closeout", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.UNREACHABLE
    assert verdict.evidence.transcript_source_available is False


@pytest.mark.unit
def test_self_declared_terminal_row_is_dead(claude_root: Path, tmp_path: Path) -> None:
    """A lane's own TERMINAL row is the one clean, unambiguous death."""
    _write_registry(claude_root, {"wave2-closeout": f"wave2-closeout@{TEAM}"})
    _write_transcript(claude_root, "wave2-closeout", age_s=4 * 3600)
    ledger = _write_ledger(tmp_path, [(3 * 3600, "wave2-closeout", "TERMINAL")])

    verdict = liveness.probe("wave2-closeout", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.DEAD


@pytest.mark.unit
def test_ambiguous_band_is_unreachable_not_dead(
    claude_root: Path, tmp_path: Path
) -> None:
    """Between the alive and dead windows the answer is 'I do not know'."""
    _write_registry(claude_root, {"rds-cutover-exec-1": f"rds-cutover-exec-1@{TEAM}"})
    _write_transcript(claude_root, "rds-cutover-exec-1", age_s=60 * 60)
    ledger = _write_ledger(tmp_path, [])

    verdict = liveness.probe("rds-cutover-exec-1", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.UNREACHABLE
    assert verdict.takeover_permitted is False


@pytest.mark.unit
def test_no_transcript_is_unreachable_not_dead(
    claude_root: Path, tmp_path: Path
) -> None:
    """Absence of evidence is not evidence of death — the whole F-10 bug."""
    _write_registry(claude_root, {"omnibase-infra-migrate-fix-1": "x@" + TEAM})
    (claude_root / "projects" / PROJECT / SESSION / "subagents").mkdir(parents=True)
    ledger = _write_ledger(tmp_path, [])

    verdict = liveness.probe(
        "omnibase-infra-migrate-fix-1", root=claude_root, ledger=ledger
    )

    assert verdict.state == liveness.UNREACHABLE


@pytest.mark.unit
def test_unregistered_lane_is_unreachable_not_dead(
    claude_root: Path, tmp_path: Path
) -> None:
    """Cross-session lanes are absent from this session's registry, and that is
    exactly the 'not addressable this session' case that was read as death."""
    _write_registry(claude_root, {"other-lane": f"other-lane@{TEAM}"})
    ledger = _write_ledger(tmp_path, [])

    verdict = liveness.probe("ghost-lane", root=claude_root, ledger=ledger)

    assert verdict.state == liveness.UNREACHABLE
    assert verdict.evidence.registered is False


@pytest.mark.unit
def test_missing_evidence_roots_are_unreachable_not_dead(tmp_path: Path) -> None:
    """A host with no ~/.claude at all must never yield DEAD."""
    verdict = liveness.probe("anything", root=tmp_path / "absent", ledger=None)

    assert verdict.state == liveness.UNREACHABLE


@pytest.mark.unit
def test_probe_signature_admits_no_reachability_inputs() -> None:
    """The F-10 invariant, enforced by the call signature itself.

    Send success, ListAgents presence, and agent status have no parameter to
    arrive through, so they cannot contribute to a DEAD verdict.
    """
    import inspect

    params = set(inspect.signature(liveness.probe).parameters)

    forbidden = {
        "send_failed",
        "send_ok",
        "reachable",
        "in_list_agents",
        "listagents",
        "status",
        "idle",
        "agent_status",
    }
    assert not (params & forbidden), (
        f"reachability leaked into probe(): {params & forbidden}"
    )
    assert params == {"lane", "root", "ledger", "alive_window_s", "dead_window_s"}


# --------------------------------------------------------------------------- #
# Namespace resolution
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_raw_ref_resolves_back_to_lane_name(claude_root: Path) -> None:
    _write_registry(
        claude_root,
        {"supersede-binding-fix": f"supersede-binding-fix@{TEAM}-8a2709"},
    )
    lane, form = liveness.resolve_address("8a2709", root=claude_root)

    assert (lane, form) == ("supersede-binding-fix", "raw_ref")


@pytest.mark.unit
def test_lane_name_is_the_canonical_form(claude_root: Path) -> None:
    _write_registry(
        claude_root, {"build-drive-closeout": f"build-drive-closeout@{TEAM}"}
    )
    assert liveness.resolve_address("build-drive-closeout", root=claude_root) == (
        "build-drive-closeout",
        "lane_name",
    )


@pytest.mark.unit
def test_real_lane_names_are_never_mistaken_for_raw_refs() -> None:
    for name in (
        "supersede-binding-fix",
        "occ-6118-close-2",
        "build-drive-closeout",
        "main",
        "wave2-defect-fix",
    ):
        assert not liveness.RAW_REF_RE.match(name), name


# --------------------------------------------------------------------------- #
# The guard — Rule A (one namespace)
# --------------------------------------------------------------------------- #


def _call(to: str, message: str) -> dict[str, Any]:
    return {"tool_name": "SendMessage", "tool_input": {"to": to, "message": message}}


def _prober(state: str):
    def _p(lane: str):
        return liveness.Verdict(
            lane, state, "synthetic", liveness.Evidence(registered=True)
        )

    return _p


@pytest.mark.unit
def test_bare_hex_address_is_blocked() -> None:
    decision = guard.decide(
        _call("8a2709", "status?"),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["supersede-binding-fix"],
    )
    assert decision.allowed is False
    assert "raw harness ref" in decision.reason


@pytest.mark.unit
def test_lane_name_address_passes_rule_a() -> None:
    decision = guard.decide(
        _call("supersede-binding-fix", "status?"),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["supersede-binding-fix"],
    )
    assert decision.allowed is True


# --------------------------------------------------------------------------- #
# The guard — Rule B (liveness is a proof obligation)
# --------------------------------------------------------------------------- #

#: Verbatim shape of the F-10 message, per the friction report.
F10_MESSAGE = (
    "take over OMN-16432 and land it. supersede-binding-fix is dead "
    "(stale auth, Not logged in), so no reply will come."
)


@pytest.mark.unit
def test_f10_incident_shape_is_blocked_when_lane_is_alive() -> None:
    decision = guard.decide(
        _call("build-drive-closeout", F10_MESSAGE),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["build-drive-closeout", "supersede-binding-fix"],
    )
    assert decision.allowed is False
    assert "supersede-binding-fix" in decision.reason


@pytest.mark.unit
def test_f10_incident_shape_is_blocked_end_to_end_against_real_evidence(
    claude_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No stub prober: the real filesystem probe must refuse the takeover."""
    _write_registry(
        claude_root,
        {
            "supersede-binding-fix": f"supersede-binding-fix@{TEAM}",
            "build-drive-closeout": f"build-drive-closeout@{TEAM}",
        },
    )
    _write_transcript(claude_root, "supersede-binding-fix", age_s=90)  # mid-push
    ledger = _write_ledger(tmp_path, [(4 * 3600, "supersede-binding-fix", "CLAIM")])

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude_root))
    monkeypatch.setenv("ONEX_LEDGER_PATH", str(ledger))

    decision = guard.decide(_call("build-drive-closeout", F10_MESSAGE))

    assert decision.allowed is False
    assert "ALIVE" in decision.reason


@pytest.mark.unit
def test_unreachable_blocks_takeover_as_hard_as_alive() -> None:
    decision = guard.decide(
        _call("build-drive-closeout", F10_MESSAGE),
        prober=_prober(liveness.UNREACHABLE),
        registry_lanes=["build-drive-closeout", "supersede-binding-fix"],
    )
    assert decision.allowed is False
    assert "UNREACHABLE is not DEAD" in decision.reason


@pytest.mark.unit
def test_corroborated_dead_verdict_allows_the_takeover() -> None:
    decision = guard.decide(
        _call("build-drive-closeout", F10_MESSAGE),
        prober=_prober(liveness.DEAD),
        registry_lanes=["build-drive-closeout", "supersede-binding-fix"],
    )
    assert decision.allowed is True


@pytest.mark.unit
def test_stand_down_supersession_shape_is_blocked() -> None:
    """The 2026-08-17 occ-6118-close shape, in the other direction."""
    decision = guard.decide(
        _call(
            "main",
            "occ-6118-close-2 is superseding occ-6118-close, which stalled out. "
            "Standing down the older lane.",
        ),
        prober=_prober(liveness.UNREACHABLE),
        registry_lanes=["occ-6118-close", "occ-6118-close-2"],
    )
    assert decision.allowed is False
    assert "occ-6118-close" in decision.reason


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        "supersede-binding-fix landed #2025 — nice. I'll take over the follow-up ticket.",
        "Ping supersede-binding-fix for the receipt-gate SHA when you get a chance.",
        "supersede-binding-fix is pushing right now; hold off on OMN-16432.",
        "Ask supersede-binding-fix whether the dead-letter topic drained.",
        "The dead-letter queue for supersede-binding-fix drained overnight.",
        "Gone-away handling for supersede-binding-fix is still on the backlog.",
        "Status from supersede-binding-fix: green, merged, worktree removed.",
    ],
)
def test_ordinary_coordination_is_not_blocked(message: str) -> None:
    """No liveness claim, no proof obligation — the guard must stay quiet.

    The hyphenated-compound cases carry the weight: ``\\b`` treats ``-`` as a
    word boundary, so a naive ``\\bdead\\b`` fires inside ``dead-letter`` and
    condemns "The dead-letter queue for <lane> drained." Both word orders are
    covered here, since only the death-word-first order can reach the label
    matcher. A lane whose own name contains "supersede" must likewise not match
    the takeover matcher against itself.
    """
    decision = guard.decide(
        _call("build-drive-closeout", message),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["build-drive-closeout", "supersede-binding-fix"],
    )
    assert decision.allowed is True, decision.reason


@pytest.mark.unit
@pytest.mark.parametrize(
    "message",
    [
        "The dead lane supersede-binding-fix still owns OMN-16432.",
        "Reassigning: dead -> supersede-binding-fix.",
    ],
)
def test_death_label_still_fires_on_a_genuine_label(message: str) -> None:
    """The hyphen fence must not blunt the label matcher on real death labels."""
    assert guard.find_triggers(message, "supersede-binding-fix") == ["death assertion"]


@pytest.mark.unit
def test_trigger_does_not_cross_a_sentence_boundary() -> None:
    """'take over X. <lane> shipped' is not a takeover of <lane>."""
    decision = guard.decide(
        _call(
            "build-drive-closeout",
            "Take over OMN-16432 and land it. supersede-binding-fix already "
            "shipped its half.",
        ),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["build-drive-closeout", "supersede-binding-fix"],
    )
    assert decision.allowed is True


@pytest.mark.unit
def test_claim_about_the_recipient_itself_is_not_a_takeover() -> None:
    decision = guard.decide(
        _call("supersede-binding-fix", "Are you dead? No reply in an hour."),
        prober=_prober(liveness.ALIVE),
        registry_lanes=["supersede-binding-fix"],
    )
    assert decision.allowed is True


# --------------------------------------------------------------------------- #
# Failure posture — never block on our own defect
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_non_sendmessage_calls_pass_through() -> None:
    assert guard.decide({"tool_name": "Bash", "tool_input": {"command": "ls"}}).allowed


@pytest.mark.unit
def test_unparsable_tool_input_fails_open() -> None:
    assert guard.decide({"tool_name": "SendMessage", "tool_input": "nonsense"}).allowed


@pytest.mark.unit
def test_absent_registry_fails_open() -> None:
    decision = guard.decide(
        _call("build-drive-closeout", F10_MESSAGE),
        prober=_prober(liveness.ALIVE),
        registry_lanes=[],
    )
    assert decision.allowed is True
    assert decision.reason == "no_lane_registry"


@pytest.mark.unit
def test_prober_exception_fails_open_at_the_entrypoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(_call: dict[str, Any]) -> Any:
        raise RuntimeError("hook defect")

    monkeypatch.setattr(guard, "decide", _boom)
    monkeypatch.setattr(guard.sys, "stdin", _Stdin(json.dumps(_call("x", "y"))))

    assert guard.main() == 0


@pytest.mark.unit
def test_block_emits_exit_2_and_json_on_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        guard, "decide", lambda _c: guard.Decision(False, "synthetic block reason")
    )
    monkeypatch.setattr(guard.sys, "stdin", _Stdin(json.dumps(_call("x", "y"))))

    assert guard.main() == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload["decision"] == "block"
    assert "OMN-16478" in payload["reason"]


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


# --------------------------------------------------------------------------- #
# Registration is part of the fix — a detached guard is an advisory guard
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_guard_is_registered_in_hooks_json() -> None:
    hooks_json = (
        Path(__file__).parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "hooks.json"
    )
    data = json.loads(hooks_json.read_text())
    commands = [
        hook.get("command", "")
        for group in data["hooks"]["PreToolUse"]
        for hook in group.get("hooks", [])
    ]
    matchers = [group.get("matcher") for group in data["hooks"]["PreToolUse"]]

    assert any("pre_tool_use_lane_liveness_guard.sh" in c for c in commands)
    assert "^SendMessage$" in matchers


@pytest.mark.unit
def test_hook_contract_yaml_exists_and_is_shaped() -> None:
    import yaml  # type: ignore[import-untyped]

    contract = (
        Path(__file__).parent.parent.parent
        / "plugins"
        / "onex"
        / "hooks"
        / "contracts"
        / "hook_lane_liveness_guard.yaml"
    )
    data = yaml.safe_load(contract.read_text())

    assert data["ticket_id"] == "OMN-16478"
    assert data["matcher"] == "^SendMessage$"
    assert data["golden_path"]
    assert isinstance(data["dod_evidence"], list) and data["dod_evidence"]
