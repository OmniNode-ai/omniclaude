# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Unit + regression tests for the Done-flip durable-evidence guard [OMN-13856].

The non-negotiable regression proofs (design §2 acceptance):

* the ``wf_1628d9a5`` incident shape — a Backlog→Done flip via ``save_issue``
  with no merged PR and no durable receipt — is BLOCKED;
* a legitimate Done-flip backed by durable evidence (a merged PR **or** a PASS
  OCC receipt on ``origin/dev``) is ALLOWED;
* freshness: a receipt that exists on ``origin/dev`` but NOT in the local clone's
  working tree is still ALLOWED (the guard reads the ref, not the stale tree).

Decision-level I/O boundaries (OCC probe, GitHub PR fetch, live Linear read) are
injected as deterministic stubs so those tests are hermetic. The git-backed OCC
probe itself is exercised against a real local temp git repo (no network).
"""

from __future__ import annotations

import importlib.util
import subprocess
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


def _no_receipt_probe(_ticket_id: str) -> bool:
    """No PASS OCC receipt on origin/dev (incident / unresolved)."""
    return False


def _receipt_probe(_ticket_id: str) -> bool:
    """A PASS OCC receipt on origin/dev exists for the ticket."""
    return True


def _never_called_probe(_ticket_id: str) -> bool:
    raise AssertionError("OCC probe must not be invoked on this path")


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
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "not_done_state"


def test_cancel_state_allows() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "state": "Canceled"},
    }
    d = guard.decide(call, occ_probe=_never_called_probe)
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
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert d.allowed
    assert d.reason == "carve_out:exempt_label"


# --------------------------------------------------------------------------- #
# REGRESSION: the wf_1628d9a5 incident shape must be BLOCKED
# --------------------------------------------------------------------------- #


def test_incident_backlog_to_done_no_evidence_is_blocked() -> None:
    """wf_1628d9a5: Done flip, no PR cited, no durable receipt → BLOCK.

    This is the exact escape both legacy guards missed: linear_done_verify
    ALLOWS 'no_pr_references' and dod_completion fails OPEN when its evidence
    root is unset. The merged guard blocks.
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
        occ_probe=_no_receipt_probe,
        pr_fetcher=_open_fetcher,  # must not matter — no PR is cited
        linear_fetcher=_no_linear,
    )
    assert not d.allowed
    assert "no_durable_evidence" in d.reason


def test_incident_status_only_update_no_evidence_is_blocked() -> None:
    """Status-only update (description omitted) with no durable evidence → BLOCK."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": "OMN-13800", "state": "Done"},
    }
    # Live Linear read returns an issue with no PR reference and no exempt label.
    d = guard.decide(
        call,
        occ_probe=_no_receipt_probe,
        linear_fetcher=lambda _t: {"description": "just closing this", "labels": []},
    )
    assert not d.allowed


def test_cited_pr_open_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": "OMN-3",
            "state": "Done",
            "description": "Fixes https://github.com/OmniNode-ai/omniclaude/pull/1",
        },
    }
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_open_fetcher)
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_no_ticket_id_done_flip_is_blocked() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"state": "Done", "description": ""},
    }
    d = guard.decide(call, occ_probe=_never_called_probe)
    assert not d.allowed
    assert "no_ticket_id" in d.reason


def test_omni_home_unset_no_pr_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """OMNI_HOME unresolvable + no merged-PR citation → BLOCK (fail-closed).

    The OCC clone cannot be resolved without OMNI_HOME; the guard must NOT
    fail-open on a fake-Done (design requirement 4). No probe is injected, so the
    production default-probe path is exercised.
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
    d = guard.decide(call, occ_probe=_never_called_probe, pr_fetcher=_merged_fetcher)
    assert d.allowed
    assert d.reason == "durable_evidence:all_prs_merged"


def test_legit_occ_receipt_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-7", "state": "Done", "description": ""},
    }
    d = guard.decide(call, occ_probe=_receipt_probe, linear_fetcher=_no_linear)
    assert d.allowed
    assert d.reason == "durable_evidence:occ_receipt_on_dev"


# --------------------------------------------------------------------------- #
# Receipt parsing / binding coverage
# --------------------------------------------------------------------------- #

_PASS_RECEIPT = """---
schema_version: "1.0.0"
ticket_id: OMN-9999
evidence_item_id: dod-001
check_type: command
status: PASS
run_timestamp: "2026-07-02T22:00:00Z"
probe_stdout: |
  status: PASS should not be parsed from this block scalar
commit_sha: "abc1234"
"""

_FAIL_RECEIPT = _PASS_RECEIPT.replace("status: PASS", "status: FAIL")

_VACUOUS_RECEIPT = """---
schema_version: "1.0.0"
ticket_id: OMN-9999
status: PASS
run_timestamp: "2026-07-02T22:00:00Z"
"""


def test_parse_receipt_fields_flat_scalars() -> None:
    fields = guard.parse_receipt_fields(_PASS_RECEIPT)
    assert fields["status"] == "PASS"
    assert fields["ticket_id"] == "OMN-9999"
    assert fields["evidence_item_id"] == "dod-001"
    assert fields["check_type"] == "command"
    # Block-scalar body must NOT leak a bogus top-level key.
    assert "should not be parsed" not in " ".join(fields.values())


def test_receipt_is_pass_bound() -> None:
    assert guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_PASS_RECEIPT), "OMN-9999"
    )
    # Wrong ticket
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_PASS_RECEIPT), "OMN-0000"
    )
    # FAIL status
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_FAIL_RECEIPT), "OMN-9999"
    )
    # PASS but no check binding (vacuous)
    assert not guard._receipt_is_pass_bound(
        guard.parse_receipt_fields(_VACUOUS_RECEIPT), "OMN-9999"
    )


# --------------------------------------------------------------------------- #
# Git-backed OCC probe — freshness against origin/dev (real local temp repo)
# --------------------------------------------------------------------------- #


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    )


def _make_occ_clone_with_dev_receipt(
    tmp_path: Path, ticket_id: str, receipt_text: str
) -> Path:
    """Build a clone whose origin/dev carries a receipt absent from its worktree."""
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(origin)], check=True, capture_output=True
    )
    clone = tmp_path / "onex_change_control"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)], check=True, capture_output=True
    )
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-b", "dev")
    rp = clone / "drift" / "dod_receipts" / ticket_id / "dod-001"
    rp.mkdir(parents=True)
    (rp / "command.yaml").write_text(receipt_text, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "add receipt on dev")
    _git(clone, "push", "origin", "dev")
    # Move the WORKING TREE off dev so the receipt is not present locally on-tree.
    _git(clone, "checkout", "-b", "other")
    _git(clone, "rm", "-r", "drift")
    _git(clone, "commit", "-m", "remove receipt from working tree")
    return clone


def test_occ_probe_reads_origin_dev_not_working_tree(tmp_path: Path) -> None:
    """FRESHNESS: receipt on origin/dev but absent from the working tree → True.

    This is the whole reason the guard reads the ref instead of the tree — a
    just-merged OCC receipt must be visible even when the local clone is behind.
    """
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    # Sanity: the receipt is NOT in the checked-out working tree.
    assert not (clone / "drift" / "dod_receipts" / "OMN-9999").exists()
    # But it IS resolvable on origin/dev.
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is True


def test_occ_probe_missing_ticket_is_false(tmp_path: Path) -> None:
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-0000", fetch=True) is False


def test_occ_probe_fail_receipt_is_false(tmp_path: Path) -> None:
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _FAIL_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is False


def test_occ_probe_vacuous_receipt_is_false(tmp_path: Path) -> None:
    """A PASS receipt with no check binding is not durable evidence."""
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _VACUOUS_RECEIPT)
    assert guard.occ_receipt_pass_on_dev(clone, "OMN-9999", fetch=True) is False


def test_occ_probe_missing_clone_is_false(tmp_path: Path) -> None:
    assert (
        guard.occ_receipt_pass_on_dev(tmp_path / "nope", "OMN-9999", fetch=False)
        is False
    )


def test_occ_probe_end_to_end_allows_via_decide(tmp_path: Path) -> None:
    """decide() ALLOWS when the injected probe resolves a real origin/dev receipt."""
    clone = _make_occ_clone_with_dev_receipt(tmp_path, "OMN-9999", _PASS_RECEIPT)
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-9999", "state": "Done", "description": ""},
    }
    d = guard.decide(
        call,
        occ_probe=lambda tid: guard.occ_receipt_pass_on_dev(clone, tid, fetch=True),
        linear_fetcher=_no_linear,
    )
    assert d.allowed
    assert d.reason == "durable_evidence:occ_receipt_on_dev"


# --------------------------------------------------------------------------- #
# main() end-to-end exit codes via stdin
# --------------------------------------------------------------------------- #


def test_main_blocks_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    # Hermetic: no OMNI_HOME (OCC clone can't resolve) and no LINEAR_API_KEY (the
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
