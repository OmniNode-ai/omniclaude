# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18529: explicit doctrine claims fail closed against injected ticket states.

Tests never call the live tracker. Refusals have passing controls, and passing
assertions have refusing controls so empty scans cannot prove compliance.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "scripts" / "doctrine_claim_gate.py"

_spec = importlib.util.spec_from_file_location("doctrine_claim_gate", _MODULE_PATH)
assert _spec and _spec.loader
gate = importlib.util.module_from_spec(_spec)
sys.modules["doctrine_claim_gate"] = gate
_spec.loader.exec_module(gate)


@pytest.fixture(autouse=True)
def _no_live_tracker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        Mock(side_effect=AssertionError("tests must never call the live tracker")),
    )


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "doctrine.md"
    path.write_text(text, encoding="utf-8")
    return path


def _claims(tmp_path: Path, text: str):
    return gate.collect_claims(_write(tmp_path, text))


def _findings(tmp_path: Path, text: str, states: dict[str, str]):
    return gate.evaluate(_claims(tmp_path, text), states)


def _kinds(findings) -> list[str]:
    return [f.kind for f in findings]


def _marker(
    claim_type: str = "unbuilt",
    ticket: str = "OMN-1001",
    role: str = "implementation",
) -> str:
    return f"<!-- doctrine-claim: type={claim_type} ticket={ticket} role={role} -->"


@pytest.mark.unit
def test_done_ticket_refuses_with_rule_sentence_ticket_and_main_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sentence = "The guard is doctrine only."
    text = f"{sentence} {_marker()}"
    findings = _findings(tmp_path, text, {"OMN-1001": "completed"})
    assert _kinds(findings) == ["CLAIM_CONTRADICTED_BY_TICKET_STATE"]
    rendered = findings[0].render()
    for part in (findings[0].kind, sentence, "OMN-1001"):
        assert part in rendered
    assert _findings(tmp_path, text, {"OMN-1001": "started"}) == []
    resolver = Mock(return_value={"OMN-1001": "completed"})
    monkeypatch.setattr(gate, "resolve_states", resolver)
    assert gate.main([str(_write(tmp_path, text))]) == 1
    resolver.assert_called_once_with({"OMN-1001"}, token=None)
    assert rendered in capsys.readouterr().err


@pytest.mark.unit
def test_open_ticket_passes_and_main_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = f"The guard is doctrine only. {_marker()}"
    assert _findings(tmp_path, text, {"OMN-1001": "backlog"}) == []
    assert _kinds(_findings(tmp_path, text, {"OMN-1001": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]
    resolver = Mock(return_value={"OMN-1001": "backlog"})
    monkeypatch.setattr(gate, "resolve_states", resolver)
    assert gate.main([str(_write(tmp_path, text))]) == 0
    resolver.assert_called_once_with({"OMN-1001"}, token=None)
    output = capsys.readouterr()
    assert output.err == ""
    assert "every claim holds" in output.out


@pytest.mark.unit
@pytest.mark.parametrize(
    ("claim_type", "sentence"),
    [
        ("blocked", "The runner is blocked on delivery."),
        ("blocked", "The runner waits on delivery."),
        ("blocked", "The runner is gated on delivery."),
        ("in_flight", "Hardening is in flight."),
        ("in_flight", "The rollout is pending merge."),
        ("in_flight", "The rollout is pending."),
        ("in_flight", "The guard is being built."),
        ("in_flight", "Hardening is currently in progress."),
        ("unbuilt", "The rule is not mechanically enforced."),
        ("unbuilt", "This is doctrine only."),
        ("unbuilt", "Nothing enforces the rule."),
        ("unbuilt", "The rule is not enforced."),
        ("unbuilt", "The mechanism is never audited."),
        ("unbuilt", "The workflow does not yet read the receipt."),
        ("unbuilt", "The mechanism is not built."),
        ("unbuilt", "The mechanism is not started."),
        ("unbuilt", "The mechanism has never been started."),
    ],
)
def test_claim_phrasings_require_markers(
    tmp_path: Path, claim_type: str, sentence: str
) -> None:
    unmarked = _findings(tmp_path, sentence, {})
    assert _kinds(unmarked) == ["UNMARKED_CLAIM"]
    assert claim_type in unmarked[0].detail
    assert "marker" in unmarked[0].detail
    assert "rewording cannot hide a claim" in unmarked[0].detail
    assert (
        _findings(
            tmp_path, f"{sentence} {_marker(claim_type)}", {"OMN-1001": "started"}
        )
        == []
    )


@pytest.mark.unit
def test_rewording_with_a_different_type_marker_leaves_claim_uncovered(
    tmp_path: Path,
) -> None:
    sentence = "The guard is doctrine only."
    findings = _findings(
        tmp_path, f"{sentence} {_marker('blocked')}", {"OMN-1001": "started"}
    )
    assert _kinds(findings) == ["UNMARKED_CLAIM"]
    assert "unbuilt" in findings[0].detail
    assert _findings(tmp_path, f"{sentence} {_marker()}", {"OMN-1001": "started"}) == []


@pytest.mark.unit
def test_every_distinct_claim_type_in_a_block_requires_a_marker(tmp_path: Path) -> None:
    sentence = "The runner is doctrine only, in flight and blocked on delivery."
    scan = _claims(tmp_path, f"{sentence} {_marker('blocked')}")
    assert scan.claims[0].claim_types == ("blocked", "in_flight", "unbuilt")
    assert scan.claims[0].marker_types == frozenset({"blocked"})
    findings = gate.evaluate(scan, {"OMN-1001": "started"})
    assert _kinds(findings) == ["UNMARKED_CLAIM", "UNMARKED_CLAIM"]
    assert [f.detail.split()[1] for f in findings] == ["in_flight", "unbuilt"]
    marked = f"{sentence} {_marker('blocked')} {_marker('in_flight')} {_marker()}"
    assert _findings(tmp_path, marked, {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "tokens",
    [
        "type=unbuilt role=implementation",
        "type=unbuilt ticket=banana role=implementation",
    ],
)
def test_marker_names_no_ticket(tmp_path: Path, tokens: str) -> None:
    findings = _findings(tmp_path, f"<!-- doctrine-claim: {tokens} -->", {})
    assert _kinds(findings) == ["MARKER_NAMES_NO_TICKET"]
    assert _findings(tmp_path, _marker(), {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "tokens",
    ["type=in_flight ticket=OMN-1001", "type=in_flight ticket=OMN-1001 role=blocker"],
)
def test_marker_has_no_allowed_role(tmp_path: Path, tokens: str) -> None:
    assert _kinds(_findings(tmp_path, f"<!-- doctrine-claim: {tokens} -->", {})) == [
        "MARKER_HAS_NO_ROLE"
    ]
    assert _findings(tmp_path, _marker("in_flight"), {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        "<!-- doctrine-claim: type=unknown ticket=OMN-1001 role=implementation -->",
        f"{_marker()[:-3]} extra=value -->",
        _marker()[:-3],
        "<!-- doctrine-claim: ticket=OMN-1001 role=implementation -->",
        f"{_marker()[:-3]} bare-token -->",
        f"{_marker()[:-3]} type=unbuilt -->",
        "<!-- doctrine-claim type=unbuilt ticket=OMN-1001 role=implementation -->",
    ],
)
def test_malformed_marker(tmp_path: Path, raw: str) -> None:
    assert _kinds(_findings(tmp_path, raw, {})) == ["MARKER_MALFORMED"]
    assert _findings(tmp_path, _marker(), {"OMN-1001": "started"}) == []


@pytest.mark.unit
def test_marker_tokens_accept_any_order_and_whitespace(tmp_path: Path) -> None:
    raw = (
        "<!-- doctrine-claim: role=implementation\t ticket=OMN-1001\n type=unbuilt -->"
    )
    text = f"The guard is doctrine only.\n{raw}"
    scan = _claims(tmp_path, text)
    assert len(scan.markers) == 1
    marker = scan.markers[0]
    assert (marker.claim_type, marker.ticket, marker.role, marker.closed) == (
        "unbuilt",
        "OMN-1001",
        "implementation",
        True,
    )
    assert gate.evaluate(scan, {"OMN-1001": "started"}) == []
    assert _kinds(gate.evaluate(scan, {"OMN-1001": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]


@pytest.mark.unit
def test_unclosed_marker_does_not_hide_the_next_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = f"{_marker()[:-3]}\n{_marker(ticket='OMN-1002')}"
    scan = _claims(tmp_path, text)
    assert [marker.closed for marker in scan.markers] == [False, True]
    resolver = Mock(return_value={"OMN-1001": "started", "OMN-1002": "started"})
    monkeypatch.setattr(gate, "resolve_states", resolver)
    code, findings = gate.run([_write(tmp_path, text)])
    assert code == 1
    assert _kinds(findings) == ["MARKER_MALFORMED"]
    assert findings[0].ticket == "OMN-1001"
    resolver.assert_called_once_with({"OMN-1002"}, token=None)
    resolver.reset_mock()
    assert gate.run(
        [_write(tmp_path, f"{_marker()}\n{_marker(ticket='OMN-1002')}")]
    ) == (0, [])
    resolver.assert_called_once_with({"OMN-1001", "OMN-1002"}, token=None)


@pytest.mark.unit
def test_marker_reports_each_problem(tmp_path: Path) -> None:
    text = "<!-- doctrine-claim: type=unknown ticket=banana extra=value bare-token"
    findings = _findings(tmp_path, text, {})
    assert _kinds(findings) == [
        "MARKER_MALFORMED",
        "MARKER_MALFORMED",
        "MARKER_MALFORMED",
        "MARKER_MALFORMED",
        "MARKER_NAMES_NO_TICKET",
        "MARKER_HAS_NO_ROLE",
    ]
    assert _findings(tmp_path, _marker(), {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    [
        _marker()[:-3],
        f"{_marker()[:-3]} extra=value -->",
        "<!-- doctrine-claim: type=unbuilt role=implementation -->",
        "<!-- doctrine-claim: type=unbuilt ticket=banana role=implementation -->",
        "<!-- doctrine-claim: type=unbuilt ticket=OMN-1001 -->",
        _marker("in_flight", role="blocker"),
    ],
)
def test_invalid_markers_never_call_the_resolver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    resolver = Mock(side_effect=AssertionError("invalid markers must not resolve"))
    monkeypatch.setattr(gate, "resolve_states", resolver)
    code, findings = gate.run([_write(tmp_path, raw)])
    assert code == 1
    assert findings
    resolver.assert_not_called()
    resolver.side_effect = None
    resolver.return_value = {"OMN-1001": "started"}
    assert gate.run([_write(tmp_path, _marker())]) == (0, [])
    resolver.assert_called_once_with({"OMN-1001"}, token=None)


@pytest.mark.unit
def test_only_valid_marker_tickets_are_resolved_across_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = tmp_path / "invalid.md"
    invalid.write_text(_marker(ticket="banana"), encoding="utf-8")
    valid = _write(tmp_path, _marker())
    resolver = Mock(return_value={"OMN-1001": "started"})
    monkeypatch.setattr(gate, "resolve_states", resolver)
    code, findings = gate.run([invalid, valid], token="injected")
    assert code == 1
    assert _kinds(findings) == ["MARKER_NAMES_NO_TICKET"]
    resolver.assert_called_once_with({"OMN-1001"}, token="injected")
    assert gate.run([valid], token="injected") == (0, [])


@pytest.mark.unit
def test_in_flight_refuses_backlog_and_passes_started(tmp_path: Path) -> None:
    text = f"Hardening is in flight. {_marker('in_flight')}"
    assert _kinds(_findings(tmp_path, text, {"OMN-1001": "backlog"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]
    assert _findings(tmp_path, text, {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize("state", ["completed", "canceled"])
def test_unbuilt_refuses_terminal_states(tmp_path: Path, state: str) -> None:
    text = f"The guard is doctrine only. {_marker()}"
    assert _kinds(_findings(tmp_path, text, {"OMN-1001": state})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]
    assert _findings(tmp_path, text, {"OMN-1001": "started"}) == []


@pytest.mark.unit
@pytest.mark.parametrize("state", ["triage", "backlog", "unstarted", "started"])
def test_unbuilt_passes_non_terminal_states(tmp_path: Path, state: str) -> None:
    text = f"The guard is doctrine only. {_marker()}"
    assert _findings(tmp_path, text, {"OMN-1001": state}) == []
    assert _kinds(_findings(tmp_path, text, {"OMN-1001": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]


@pytest.mark.unit
def test_blocked_blocker_refuses_completed_and_passes_started(tmp_path: Path) -> None:
    text = f"The runner is blocked on delivery. {_marker('blocked', role='blocker')}"
    scan = _claims(tmp_path, text)
    assert scan.markers[0].role == "blocker"
    refused = gate.evaluate(scan, {"OMN-1001": "completed"})
    assert _kinds(refused) == ["CLAIM_CONTRADICTED_BY_TICKET_STATE"]
    for part in ("blocked", "blocker", "OMN-1001", "completed", "started"):
        assert part in refused[0].detail
    assert gate.evaluate(scan, {"OMN-1001": "started"}) == []


@pytest.mark.unit
def test_table_rows_cannot_share_a_marker(tmp_path: Path) -> None:
    first = f"| Guard | doctrine only {_marker()} |"
    second = "| Runner | not mechanically enforced |"
    findings = _findings(tmp_path, f"{first}\n{second}", {"OMN-1001": "started"})
    assert _kinds(findings) == ["UNMARKED_CLAIM"]
    assert findings[0].line == 2
    assert findings[0].sentence == second
    assert (
        _findings(
            tmp_path, f"{first}\n{second[:-1]} {_marker()} |", {"OMN-1001": "started"}
        )
        == []
    )


@pytest.mark.unit
def test_fenced_claims_and_markers_are_ignored(tmp_path: Path) -> None:
    text = f"The guard is doctrine only. {_marker()}"
    scan = _claims(tmp_path, f"Real prose.\n\n```markdown\n{text}\n```\n")
    assert scan.markers == ()
    assert scan.claims == ()
    visible = _claims(tmp_path, text)
    assert len(visible.markers) == 1
    assert len(visible.claims) == 1
    assert _kinds(gate.evaluate(visible, {"OMN-1001": "completed"})) == [
        "CLAIM_CONTRADICTED_BY_TICKET_STATE"
    ]


@pytest.mark.unit
def test_markers_anywhere_in_block_are_stripped_before_matching(tmp_path: Path) -> None:
    for text in (
        f"{_marker()}\nThe guard is doctrine only.",
        f"The guard is doctrine only.\n{_marker()}",
        f"The guard {_marker()} is doctrine only.",
    ):
        scan = _claims(tmp_path, text)
        assert len(scan.markers) == 1
        assert len(scan.claims) == 1
        assert "doctrine-claim" not in scan.claims[0].sentence
        assert scan.markers[0].sentence == scan.claims[0].sentence
        assert gate.evaluate(scan, {"OMN-1001": "started"}) == []
        assert _kinds(gate.evaluate(scan, {"OMN-1001": "completed"})) == [
            "CLAIM_CONTRADICTED_BY_TICKET_STATE"
        ]
    scan = _claims(tmp_path, _marker("in_flight"))
    assert len(scan.markers) == 1
    assert scan.claims == ()
    assert scan.markers[0].sentence == ""
    assert _claims(tmp_path, "Hardening is in flight.").claims[0].claim_types == (
        "in_flight",
    )


@pytest.mark.unit
def test_one_marker_per_ticket_and_marker_line_numbers(tmp_path: Path) -> None:
    text = (
        "The runner is blocked on delivery of OMN-1001 and OMN-1002.\n"
        f"{_marker('blocked', role='blocker')}\n"
        f"{_marker('blocked', ticket='OMN-1002')}"
    )
    scan = _claims(tmp_path, text)
    assert [(m.ticket, m.line) for m in scan.markers] == [
        ("OMN-1001", 2),
        ("OMN-1002", 3),
    ]
    assert gate.evaluate(scan, {"OMN-1001": "started", "OMN-1002": "backlog"}) == []
    findings = gate.evaluate(scan, {"OMN-1001": "completed", "OMN-1002": "completed"})
    assert _kinds(findings) == ["CLAIM_CONTRADICTED_BY_TICKET_STATE"] * 2
    assert [f.ticket for f in findings] == ["OMN-1001", "OMN-1002"]


@pytest.mark.unit
def test_zero_claims_and_markers_refuses_but_marker_only_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write(tmp_path, "The guard runs on every pull request.")
    with pytest.raises(gate.GateError, match="ZERO claim sentences or markers"):
        gate.run([path])
    monkeypatch.setattr(
        gate, "resolve_states", Mock(return_value={"OMN-1001": "started"})
    )
    assert gate.run([_write(tmp_path, _marker())]) == (0, [])


@pytest.mark.unit
def test_unmarked_claim_via_run_returns_findings_without_resolving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = Mock(
        side_effect=AssertionError("unmarked prose has no tickets to resolve")
    )
    monkeypatch.setattr(gate, "resolve_states", resolver)
    path = _write(tmp_path, "The guard is doctrine only.")
    code, findings = gate.run([path])
    assert code == 1
    assert _kinds(findings) == ["UNMARKED_CLAIM"]
    resolver.assert_not_called()
    resolver.side_effect = None
    resolver.return_value = {"OMN-1001": "started"}
    assert gate.run([_write(tmp_path, f"The guard is doctrine only. {_marker()}")]) == (
        0,
        [],
    )
    resolver.assert_called_once_with({"OMN-1001"}, token=None)


@pytest.mark.unit
def test_unreadable_file_refuses(tmp_path: Path) -> None:
    with pytest.raises(gate.GateError, match="unreadable"):
        gate.collect_claims(tmp_path / "absent.md")
    assert len(_claims(tmp_path, _marker()).markers) == 1


@pytest.mark.unit
def test_non_utf8_file_refuses(tmp_path: Path) -> None:
    path = tmp_path / "invalid.md"
    path.write_bytes(b"\xff")
    with pytest.raises(gate.GateError, match="not valid UTF-8"):
        gate.collect_claims(path)
    assert len(_claims(tmp_path, _marker()).markers) == 1


@pytest.mark.unit
def test_missing_credential_refuses_and_empty_tickets_need_no_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(gate.TICKET_STATE_ENV, raising=False)
    with pytest.raises(gate.GateError, match="REFUSES rather than skipping"):
        gate.resolve_states({"OMN-1001"})
    assert gate.resolve_states(set()) == {}


@pytest.mark.unit
def test_unreadable_tracker_refuses_and_main_exits_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        Mock(side_effect=gate.urllib.error.URLError("tracker unavailable")),
    )
    with pytest.raises(gate.GateError, match="ticket-state source unreachable"):
        gate.resolve_states({"OMN-1001"}, token="injected")
    assert gate.resolve_states(set(), token="injected") == {}
    monkeypatch.setenv(gate.TICKET_STATE_ENV, "injected")
    assert gate.main([str(_write(tmp_path, _marker()))]) == 2
    assert "COULD NOT RUN" in capsys.readouterr().err
    monkeypatch.setattr(
        gate, "resolve_states", Mock(return_value={"OMN-1001": "started"})
    )
    assert gate.main([str(_write(tmp_path, _marker()))]) == 0


@pytest.mark.unit
def test_the_state_source_is_named_in_the_module() -> None:
    assert gate.TICKET_STATE_ENDPOINT.startswith("https://")
    assert gate.TICKET_STATE_ENV == "LINEAR_API_KEY"
    source = " ".join(_MODULE_PATH.read_text(encoding="utf-8").split()).lower()
    assert "ticket_state_endpoint" in source
    assert "no snapshot file and no offline mode" in source


@pytest.mark.unit
def test_pre_correction_measurement_and_corrected_twin(tmp_path: Path) -> None:
    before = (
        f"The receipt guard is doctrine only. {_marker(ticket='OMN-1001')}\n\n"
        f"Hardening is in flight. {_marker('in_flight', ticket='OMN-1002')}\n\n"
        "The audit mechanism is absent, blocked on delivery of its implementation. "
        f"{_marker('blocked', ticket='OMN-1003')}\n\n"
        "The staging workflow does not yet read the receipt."
    )
    states = {
        "OMN-1001": "completed",
        "OMN-1002": "completed",
        "OMN-1003": "completed",
        "OMN-1004": "started",
    }
    scan = _claims(tmp_path, before)
    assert len(scan.claims) == 4
    assert len(scan.markers) == 3
    findings = gate.evaluate(scan, states)
    assert sorted(_kinds(findings)) == sorted(
        [
            "CLAIM_CONTRADICTED_BY_TICKET_STATE",
            "CLAIM_CONTRADICTED_BY_TICKET_STATE",
            "CLAIM_CONTRADICTED_BY_TICKET_STATE",
            "UNMARKED_CLAIM",
        ]
    )
    assert {f.ticket for f in findings if f.ticket} == {
        "OMN-1001",
        "OMN-1002",
        "OMN-1003",
    }
    corrected = (
        "The receipt guard exists and checks receipts. OMN-1001 delivered it.\n\n"
        "Hardening exists and runs on every pull request. OMN-1002 delivered it.\n\n"
        "The audit mechanism exists and runs automatically. OMN-1003 delivered it.\n\n"
        "The staging workflow does not yet read the receipt. "
        f"{_marker(ticket='OMN-1004')}"
    )
    corrected_scan = _claims(tmp_path, corrected)
    assert len(corrected_scan.claims) == 1
    assert len(corrected_scan.markers) == 1
    assert gate.evaluate(corrected_scan, states) == []
