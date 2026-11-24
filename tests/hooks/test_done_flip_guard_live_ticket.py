# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-26655: the Done guard judges a Done on the live ticket, not on the call.

One Linear update used to carry the text and labels the guard then read, so it
could supply its own ``close-if-done`` exemption or leave out the pull request
the live ticket cites. Every read below is injected; nothing reaches Linear or
GitHub.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_LIB_DIR = Path(__file__).parent.parent.parent / "plugins" / "onex" / "hooks" / "lib"
sys.path.insert(0, str(_LIB_DIR))
_spec = importlib.util.spec_from_file_location(
    "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
)
assert _spec is not None and _spec.loader is not None
guard = importlib.util.module_from_spec(_spec)
sys.modules["done_flip_guard"] = guard
_spec.loader.exec_module(guard)

ldv = importlib.import_module("linear_done_verify")
nbe = importlib.import_module("no_pr_bound_evidence")

OPEN_PR_URL = "https://github.com/OmniNode-ai/omniclaude/pull/7"
EXEMPT_LINE = "close-if-done: true"


@pytest.fixture(autouse=True)
def _hermetic_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "")


def _status(state: str) -> Any:
    return ldv.PRStatus(
        ref=ldv.PRRef(number=7, repo="OmniNode-ai/omniclaude"),
        state=state,
        merge_state="CLEAN",
        error=None,
    )


def _open_fetcher(_ref: Any) -> Any:
    return _status("OPEN")


def _merged_fetcher(_ref: Any) -> Any:
    return _status("MERGED")


def _repo_pass_probe(_ticket: str, _descriptions: list[str], _prs: list[Any]) -> Any:
    return nbe.RepoEvidenceVerdict(
        nbe.RepoEvidenceOutcome.PASSED,
        "repo-bound: AC1<-dod-001",
        verified_contract_hashes=(("test/repo", "a" * 64),),
    )


def _call(tool_input: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-26655", **tool_input},
    }


def _live(description: str, labels: list[str] | None = None) -> Any:
    def fetch(_ticket: str) -> dict[str, Any]:
        return {"description": description, "labels": labels or []}

    return fetch


def _recording_verify(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Wrap the guard's ``verify`` so a test reads what it concluded."""
    results: list[Any] = []
    real = guard.verify

    def spy(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        results.append(result)
        return result

    monkeypatch.setattr(guard, "verify", spy)
    return results


# --------------------------------------------------------------------------- #
# AC1: the exemption comes from the live ticket, whatever the call carries
# --------------------------------------------------------------------------- #


def test_ac1_exemption_line_in_the_call_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _recording_verify(monkeypatch)
    decision = guard.decide(
        _call({"state": "Done", "description": f"closing\n{EXEMPT_LINE}\n"}),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_merged_fetcher,
        linear_fetcher=_live("a live description with no exemption"),
    )
    assert decision.allowed, decision.reason
    assert [r.reason for r in results] == ["no_pr_references"]


def test_ac1_exemption_label_in_the_call_is_not_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _recording_verify(monkeypatch)
    guard.decide(
        _call({"state": "Done", "labels": ["close-if-done"]}),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_merged_fetcher,
        linear_fetcher=_live("a live description", labels=["lane"]),
    )
    assert [r.reason for r in results] == ["no_pr_references"]


def test_ac1_legacy_main_does_not_read_the_call_exemption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[Any] = []
    real = ldv.verify

    def spy(*args: Any, **kwargs: Any) -> Any:
        result = real(*args, **kwargs)
        seen.append(result.reason)
        return result

    monkeypatch.setattr(ldv, "verify", spy)
    monkeypatch.setattr(
        ldv,
        "_fetch_linear_issue",
        lambda _t: {"description": "live text", "labels": [], "attachment_urls": []},
    )
    payload = _call({"state": "Done", "description": f"x\n{EXEMPT_LINE}"})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    assert ldv.main() == 0
    assert seen == ["no_pr_references"]


# --------------------------------------------------------------------------- #
# AC2: a PR the live ticket cites cannot be left out of the call
# --------------------------------------------------------------------------- #


def test_ac2_open_pr_cited_live_refuses_when_the_call_leaves_it_out() -> None:
    decision = guard.decide(
        _call({"state": "Done", "description": "Shipped. Nothing else to cite."}),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=_live(f"Implemented in {OPEN_PR_URL}"),
    )
    assert not decision.allowed
    assert "pr_not_merged" in decision.reason


def test_ac2_open_pr_cited_live_refuses_when_a_patch_removes_it() -> None:
    live_text = f"Implemented in {OPEN_PR_URL} today."
    decision = guard.decide(
        _call(
            {
                "state": "Done",
                "patch": [
                    {
                        "op": "replace",
                        "old_string": OPEN_PR_URL,
                        "new_string": "a private note",
                    }
                ],
            }
        ),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=_live(live_text),
    )
    assert not decision.allowed
    assert "pr_not_merged" in decision.reason


def test_ac2_legacy_main_refuses_when_the_call_leaves_the_open_pr_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ldv,
        "_fetch_linear_issue",
        lambda _t: {
            "description": f"Implemented in {OPEN_PR_URL}",
            "labels": [],
            "attachment_urls": [],
        },
    )
    monkeypatch.setattr(
        ldv,
        "verify",
        _bind_fetcher(ldv.verify, _open_fetcher),
    )
    payload = _call({"state": "Done", "description": "nothing to cite"})
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(payload)))
    assert ldv.main() == 2


def _bind_fetcher(real: Any, fetcher: Any) -> Any:
    def bound(*args: Any, **kwargs: Any) -> Any:
        kwargs["fetcher"] = fetcher
        return real(*args, **kwargs)

    return bound


# --------------------------------------------------------------------------- #
# AC3 is deliberately not asserted: see the lane report. The key-absent shape
# below pins what is kept until that disposition changes, so a later change
# to it is a visible edit and not a silent one.
# --------------------------------------------------------------------------- #


def test_key_absent_keeps_judging_the_call_text_until_ac3_is_decided() -> None:
    decision = guard.decide(
        _call({"state": "Done", "description": ""}),
        repo_evidence_probe=_repo_pass_probe,
        linear_fetcher=lambda _t: None,
    )
    assert decision.allowed, decision.reason


# --------------------------------------------------------------------------- #
# AC4: cancel, duplicate and a live exemption behave as before
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("state", ["Canceled", "Duplicate"])
def test_ac4_cancel_and_duplicate_are_allowed_on_an_unreadable_live_ticket(
    state: str,
) -> None:
    decision = guard.decide(
        _call({"state": state, "description": f"cites {OPEN_PR_URL}"}),
        repo_evidence_probe=lambda *_a: pytest.fail("no evidence read on a cancel"),
        pr_fetcher=_open_fetcher,
        linear_fetcher=lambda _t: None,
    )
    assert decision.allowed, decision.reason
    assert decision.reason == "carve_out:cancel_state"


@pytest.mark.parametrize("state", ["Canceled", "Duplicate"])
def test_ac4_cancel_and_duplicate_are_allowed_on_an_open_pr_ticket(
    state: str,
) -> None:
    decision = guard.decide(
        _call({"state": state}),
        repo_evidence_probe=lambda *_a: pytest.fail("no evidence read on a cancel"),
        pr_fetcher=_open_fetcher,
        linear_fetcher=_live(f"Implemented in {OPEN_PR_URL}"),
    )
    assert decision.allowed, decision.reason


def test_ac4_live_exemption_label_still_closes_a_ticket_with_no_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = _recording_verify(monkeypatch)
    decision = guard.decide(
        _call({"state": "Done"}),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_merged_fetcher,
        linear_fetcher=_live("a decision-only ticket", labels=["close-if-done"]),
    )
    assert decision.allowed, decision.reason
    assert [r.reason for r in results] == ["exempt"]


def test_ac4_live_exemption_label_still_does_not_waive_an_open_cited_pr() -> None:
    decision = guard.decide(
        _call({"state": "Done", "description": f"see {OPEN_PR_URL}"}),
        repo_evidence_probe=_repo_pass_probe,
        pr_fetcher=_open_fetcher,
        linear_fetcher=_live("decision only", labels=["close-if-done"]),
    )
    assert not decision.allowed
    assert "pr_not_merged" in decision.reason
