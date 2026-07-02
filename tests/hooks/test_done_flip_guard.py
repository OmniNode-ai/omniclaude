# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit + regression tests for the Done-flip durable-evidence guard [OMN-13856].

The two non-negotiable regression proofs (design §2 acceptance):

* the ``wf_1628d9a5`` incident shape — a Backlog→Done flip via ``save_issue``
  with no merged PR and no durable receipt — is BLOCKED;
* a legitimate Done-flip backed by durable evidence (a merged PR **or** a fresh
  PASS receipt) is ALLOWED.

All I/O boundaries (dod_verify runner, GitHub PR fetch, live Linear read) are
injected as deterministic stubs so the suite is hermetic — no ``uv``, no Kafka,
no network.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

# The guard lib lives under plugins/onex/hooks/lib and imports its sibling
# ``linear_done_verify`` by bare name (the shell wrapper runs it with that dir on
# sys.path[0]). Load it the same way so the sibling import resolves.
_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"


def _load_guard() -> Any:
    import sys

    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass can resolve the module by name.
    sys.modules["done_flip_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


# --------------------------------------------------------------------------- #
# Stub factories
# --------------------------------------------------------------------------- #


def _pr_status(state: str, merge_state: str = "CLEAN", error: str | None = None):
    from linear_done_verify import PRRef, PRStatus

    return PRStatus(
        ref=PRRef(number=1, repo="OmniNode-ai/omniclaude"),
        state=state,
        merge_state=merge_state,
        error=error,
    )


def _merged_fetcher(_ref: Any):
    return _pr_status("MERGED")


def _open_fetcher(_ref: Any):
    return _pr_status("OPEN")


def _no_receipt_runner(_ticket_id: str) -> dict[str, Any] | None:
    """dod_verify produced nothing (no OCC contract / node could not run)."""
    return None


def _tally(verified: int, failed: int, skipped: int) -> str:
    """Build a probe_stdout tally blob matching node_dod_verify's output."""
    import json as _json

    return _json.dumps(
        {
            "total": verified + failed + skipped,
            "verified": verified,
            "failed": failed,
            "skipped": skipped,
            "details": [],
        }
    )


def _fresh_pass_receipt(_ticket_id: str) -> dict[str, Any]:
    return {
        "status": "PASS",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
        "probe_stdout": _tally(verified=5, failed=0, skipped=0),
    }


def _vacuous_pass_receipt(_ticket_id: str) -> dict[str, Any]:
    """The no-contract incident shape: status PASS but ZERO checks verified."""
    return {
        "status": "PASS",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
        "probe_stdout": _tally(verified=0, failed=0, skipped=1),
    }


def _fail_receipt(_ticket_id: str) -> dict[str, Any]:
    return {
        "status": "FAIL",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
        "probe_stdout": _tally(verified=0, failed=1, skipped=0),
    }


def _never_called_runner(_ticket_id: str) -> dict[str, Any] | None:
    raise AssertionError("dod_verify runner must not be invoked on this path")


def _no_linear(_ticket_id: str) -> dict[str, Any] | None:
    return {}  # LINEAR_API_KEY-absent shape: no live data


# --------------------------------------------------------------------------- #
# Pass-through / carve-out cases
# --------------------------------------------------------------------------- #


def test_non_linear_tool_allows() -> None:
    d = guard.decide({"tool_name": "Read", "tool_input": {}})
    assert d.allowed


def test_non_done_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "In Progress"},
    }
    d = guard.decide(call, dod_verify_runner=_never_called_runner)
    assert d.allowed
    assert d.reason == "not_done_state"


def test_cancel_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "Canceled"},
    }
    d = guard.decide(call, dod_verify_runner=_never_called_runner)
    assert d.allowed
    assert d.reason == "carve_out:cancel_state"


def test_exempt_label_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-1",
            "state": "Done",
            "description": "decision only",
            "labels": ["close-if-done"],
        },
    }
    d = guard.decide(call, dod_verify_runner=_never_called_runner)
    assert d.allowed
    assert d.reason == "carve_out:exempt_label"


# --------------------------------------------------------------------------- #
# REGRESSION: the wf_1628d9a5 incident shape must be BLOCKED
# --------------------------------------------------------------------------- #


def test_incident_backlog_to_done_no_evidence_is_blocked() -> None:
    """wf_1628d9a5: Done flip, no PR cited, no durable receipt → BLOCK.

    This is the exact escape both legacy guards missed: linear_done_verify
    ALLOWS 'no_pr_references' and dod_completion fails OPEN when
    ONEX_EVIDENCE_ROOT is unset. The merged guard blocks.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-13797",
            "state": "Done",
            "description": "",  # no PR citation, no exemption
        },
    }
    d = guard.decide(
        call,
        dod_verify_runner=_no_receipt_runner,
        pr_fetcher=_open_fetcher,  # must not matter — no PR is cited
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_durable_evidence" in d.reason


def test_incident_vacuous_dod_pass_is_blocked() -> None:
    """No-contract ticket: dod_verify returns PASS but verified 0 checks → BLOCK.

    Guards against the node's own fail-open (a contract-less ticket is reported
    PASS because every check is SKIPPED). This is the live wf_1628d9a5 shape.
    """
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-13798", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call, dod_verify_runner=_vacuous_pass_receipt, linear_fetcher=_no_linear
    )
    assert not d.allowed
    assert "no_verified_checks" in d.reason or "ZERO" in d.reason


def test_incident_status_only_update_no_evidence_is_blocked() -> None:
    """Status-only update (description omitted) with no durable evidence → BLOCK."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-13800", "state": "Done"},
    }
    # Live Linear read returns an issue with no PR reference and no exempt label.
    d = guard.decide(
        call,
        dod_verify_runner=_no_receipt_runner,
        linear_fetcher=lambda _t: {"description": "just closing this", "labels": []},
    )
    assert not d.allowed


def test_done_with_fail_receipt_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-2", "state": "Done", "description": ""},
    }
    d = guard.decide(call, dod_verify_runner=_fail_receipt, linear_fetcher=_no_linear)
    assert not d.allowed
    assert "status_not_pass" in d.reason or "PASS receipt" in d.reason


def test_cited_pr_open_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-3",
            "state": "Done",
            "description": "Fixes https://github.com/OmniNode-ai/omniclaude/pull/1",
        },
    }
    d = guard.decide(
        call, dod_verify_runner=_never_called_runner, pr_fetcher=_open_fetcher
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_stale_receipt_is_blocked() -> None:
    stale = {
        "status": "PASS",
        "run_timestamp": (datetime.now(tz=UTC) - timedelta(hours=2)).isoformat(),
    }
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-4", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call, dod_verify_runner=lambda _t: stale, linear_fetcher=_no_linear
    )
    assert not d.allowed
    assert "stale" in d.reason or "30 minutes" in d.reason


def test_no_ticket_id_done_flip_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"state": "Done", "description": ""},
    }
    d = guard.decide(call, dod_verify_runner=_never_called_runner)
    assert not d.allowed
    assert "no_ticket_id" in d.reason


def test_omni_home_unset_no_pr_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """OMNI_HOME unresolvable + no merged-PR citation → BLOCK (fail-closed).

    dod_verify cannot run without OMNI_HOME; the guard must NOT fail-open on a
    fake-Done (design requirement 4). No runner is injected, so the production
    default-runner path is exercised.
    """
    monkeypatch.delenv("OMNI_HOME", raising=False)
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-5", "state": "Done", "description": ""},
    }
    d = guard.decide(call, linear_fetcher=_no_linear)
    assert not d.allowed
    assert "OMNI_HOME" in d.reason


# --------------------------------------------------------------------------- #
# REGRESSION: legitimate Done-flips backed by durable evidence are ALLOWED
# --------------------------------------------------------------------------- #


def test_legit_merged_pr_citation_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-6",
            "state": "Done",
            "description": (
                "Implemented in https://github.com/OmniNode-ai/omniclaude/pull/1"
            ),
        },
    }
    d = guard.decide(
        call, dod_verify_runner=_never_called_runner, pr_fetcher=_merged_fetcher
    )
    assert d.allowed
    assert d.reason == "durable_evidence:all_prs_merged"


def test_legit_fresh_pass_receipt_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-7", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call, dod_verify_runner=_fresh_pass_receipt, linear_fetcher=_no_linear
    )
    assert d.allowed
    assert d.reason == "durable_evidence:dod_receipt_pass"


# --------------------------------------------------------------------------- #
# classify_receipt unit coverage
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("receipt", "expected"),
    [
        (None, "missing"),
        ({"status": "PASS"}, "missing_run_timestamp"),
        ({"run_timestamp": "not-a-date", "status": "PASS"}, "parse_error:"),
        (
            {"run_timestamp": "2020-01-01T00:00:00", "status": "PASS"},
            "parse_error:",
        ),  # naive timestamp rejected
    ],
)
def test_classify_receipt_failure_tokens(receipt: Any, expected: str) -> None:
    verdict = guard.classify_receipt(receipt)
    assert verdict.startswith(expected) or verdict == expected


def test_classify_receipt_pass() -> None:
    receipt = {
        "status": "PASS",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
        "probe_stdout": _tally(verified=5, failed=0, skipped=0),
    }
    assert guard.classify_receipt(receipt) == "pass"


def test_classify_receipt_vacuous_pass_rejected() -> None:
    """A PASS with zero verified checks (no contract) is NOT durable evidence."""
    receipt = {
        "status": "PASS",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
        "probe_stdout": _tally(verified=0, failed=0, skipped=1),
    }
    assert guard.classify_receipt(receipt) == "no_verified_checks"


def test_classify_receipt_pass_missing_tally_rejected() -> None:
    """PASS with no parseable per-check tally fails closed."""
    receipt = {
        "status": "PASS",
        "run_timestamp": datetime.now(tz=UTC).isoformat(),
    }
    assert guard.classify_receipt(receipt) == "no_verified_checks"


def test_contract_repo_dir_is_deterministic_from_omni_home() -> None:
    """The guard resolves the contract root from OMNI_HOME — not an ambient var."""
    root = guard.contract_repo_dir(Path("/some/omni_home"))
    assert root == Path("/some/omni_home/onex_change_control")


# --------------------------------------------------------------------------- #
# main() end-to-end exit codes via stdin
# --------------------------------------------------------------------------- #


def test_main_blocks_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    # Hermetic: no OMNI_HOME (dod_verify can't run) and no LINEAR_API_KEY (the
    # real fetcher returns {} instead of a live network call) => fail-closed.
    monkeypatch.delenv("OMNI_HOME", raising=False)
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    payload = (
        '{"tool_name": "mcp__linear-server__save_issue", '
        '"tool_input": {"id": "OMN-13797", "state": "Done", "description": ""}}'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert guard.main() == 2


def test_main_allows_non_done(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    payload = (
        '{"tool_name": "mcp__linear-server__save_issue", '
        '"tool_input": {"id": "OMN-1", "state": "In Progress"}}'
    )
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    assert guard.main() == 0
