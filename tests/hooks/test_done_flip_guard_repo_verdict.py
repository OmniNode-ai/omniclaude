# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Durable repo verdicts engage the Done gate through the projection node."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml

pytestmark = pytest.mark.unit
_LIB_DIR = Path(__file__).parents[2] / "plugins" / "onex" / "hooks" / "lib"


def _load_guard() -> Any:
    sys.path.insert(0, str(_LIB_DIR))
    spec = importlib.util.spec_from_file_location(
        "done_flip_guard", _LIB_DIR / "done_flip_guard.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["done_flip_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()
ldv: Any = importlib.import_module("linear_done_verify")
nbe: Any = importlib.import_module("no_pr_bound_evidence")
_TICKET = "OMN-90001"
_REPO = "OmniNode-ai/omnimarket"
_HEAD = "a" * 40
_MERGE = "b" * 40
_NUMBER = 3300
_DESCRIPTION = f"""Implemented in https://github.com/{_REPO}/pull/{_NUMBER}

## Acceptance criteria
- AC1 -- the first check passes
- AC2 -- the second check passes
"""


def _never(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("this reader or OCC probe must not be consulted")


def _merged(ref: Any) -> Any:
    return ldv.PRStatus(
        ref=ref,
        state="MERGED",
        merge_state="CLEAN",
        head_sha=_HEAD,
        merge_commit_sha=_MERGE,
    )


def _contract(*labels: str) -> str:
    return yaml.safe_dump(
        {
            "ticket_id": _TICKET,
            "dod_evidence": [
                {"id": f"dod-{label.lower()}", "binds_ac": [label]} for label in labels
            ],
        }
    )


def _row(**overrides: Any) -> dict[str, Any]:
    return {
        "ticket_id": _TICKET,
        "contract_source": "product_repository",
        "contract_repository": _REPO,
        "contract_commit_sha": _HEAD,
        "contract_repo_path": f"contracts/{_TICKET}.yaml",
        "correlation_id": "repo-verdict-run",
        "completed_at": "2026-10-02T12:00:00Z",
        "status": "verified",
        "outcome": "PASS",
        "projection_cursor": 10,
        **overrides,
    }


def _occ(passed: bool) -> Any:
    return lambda _tid, _desc: nbe.BoundEvidenceVerdict(passed, "OCC probe detail")


def _done(
    row: dict[str, Any] | None = None,
    *,
    read_verdict: Any = None,
    contract: str | None = None,
    head_contract: str | None = None,
    read_contract: Any = None,
    runs: Any = None,
    description: str = _DESCRIPTION,
    **kwargs: Any,
) -> Any:
    def contract_reader(_repo: str, sha: str, _tid: str) -> Any:
        return nbe.ContractRead(
            nbe.ContractReadStatus.FOUND,
            text=head_contract
            if sha == _HEAD and head_contract is not None
            else contract or _contract("AC1", "AC2"),
        )

    def verdict_reader(tid: str) -> Any:
        assert tid == _TICKET
        return nbe.VerdictRead(
            nbe.VerdictReadStatus.FOUND, row=_row() if row is None else row
        )

    probe = partial(
        nbe.evaluate_repo_evidence,
        read_contract=read_contract or contract_reader,
        read_check_runs=lambda *_args: [] if runs is None else runs,
        read_verdict=read_verdict or verdict_reader,
    )
    return guard.decide(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {"id": _TICKET, "state": "Done"},
        },
        linear_fetcher=lambda _tid: {"description": description, "labels": []},
        pr_fetcher=_merged,
        occ_probe=kwargs.pop("occ_probe", _never),
        receipt_lister=_never,
        repo_evidence_probe=probe,
        **kwargs,
    )


@pytest.mark.parametrize("sha", [_HEAD, _MERGE])
def test_verified_repo_verdict_allows_without_occ(sha: str) -> None:
    decision = _done(_row(contract_commit_sha=sha, contract_repository=_REPO.lower()))
    assert decision.allowed, decision.reason
    assert decision.reason.startswith("durable_evidence:repo_bound_checks")


def test_other_commit_refuses_without_occ() -> None:
    decision = _done(_row(contract_commit_sha="c" * 40))
    assert not decision.allowed
    assert "c" * 12 in decision.reason and "merged head" in decision.reason
    assert (
        "repo-verdict-run" in decision.reason
        and "2026-10-02T12:00:00Z" in decision.reason
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_repository": "OmniNode-ai/another"},
        {"contract_repo_path": "contracts/OTHER.yaml"},
    ],
)
def test_wrong_repository_or_path_refuses(overrides: dict[str, Any]) -> None:
    decision = _done(_row(**overrides))
    assert not decision.allowed
    assert next(iter(overrides.values())) in decision.reason
    assert "verify the merged contract" in decision.reason


@pytest.mark.parametrize("status", ["failed", "pending", "skipped", "unresolved"])
def test_non_verified_status_refuses(status: str) -> None:
    decision = _done(_row(status=status))
    assert not decision.allowed
    assert f"status={status}" in decision.reason


def test_head_contract_must_match_merged_contract() -> None:
    decision = _done(head_contract=_contract("AC1"))
    assert not decision.allowed
    assert (
        "contract changed between the verified head and the merge commit"
        in decision.reason
    )


def test_unbound_ac2_refuses_even_with_verified_verdict() -> None:
    decision = _done(contract=_contract("AC1"))
    assert not decision.allowed
    assert "AC2" in decision.reason and "binds_ac" in decision.reason


@pytest.mark.parametrize("passed", [True, False])
def test_unreadable_verdict_falls_back_to_occ(passed: bool) -> None:
    calls: list[str] = []

    def occ(tid: str, _desc: str) -> Any:
        calls.append(tid)
        return nbe.BoundEvidenceVerdict(passed, "OCC probe detail")

    decision = _done(
        read_verdict=lambda _tid: nbe.VerdictRead(
            nbe.VerdictReadStatus.ERROR, error="projection_table_unreadable"
        ),
        occ_probe=occ,
    )
    assert calls == [_TICKET]
    assert decision.allowed is passed
    if passed:
        assert decision.reason == "durable_evidence:occ_bound_receipts:all_prs_merged"
    else:
        assert "OCC probe detail" in decision.reason
        assert (
            "repo-owned dod_verify verdict unreadable: projection_table_unreadable"
            in decision.reason
        )


@pytest.mark.parametrize("passed", [True, False])
def test_absent_verdict_preserves_occ_decision(passed: bool) -> None:
    decision = _done(
        read_verdict=lambda _tid: nbe.VerdictRead(nbe.VerdictReadStatus.ABSENT),
        occ_probe=_occ(passed),
    )
    expected = (
        "durable_evidence:occ_bound_receipts:all_prs_merged"
        if passed
        else guard._bound_receipt_refusal(
            _TICKET,
            "OCC probe detail",
            why="a Done transition needs a passing definition-of-done check for every acceptance criterion",
        ).reason
        + f" {_REPO}#{_NUMBER} carries contracts/{_TICKET}.yaml but no {nbe.REPO_EVIDENCE_CHECK_NAME} run on head {_HEAD[:12]}"
    )
    assert decision.allowed is passed
    assert decision.reason == expected


@pytest.mark.parametrize("passed", [True, False])
@pytest.mark.parametrize(
    "description",
    [_DESCRIPTION, "## Acceptance criteria\n- AC1 -- first\n- AC2 -- second"],
)
def test_no_product_contract_never_reads_verdict(
    passed: bool, description: str
) -> None:
    decision = _done(
        description=description,
        read_contract=lambda *_args: nbe.ContractRead(nbe.ContractReadStatus.ABSENT),
        read_verdict=_never,
        occ_probe=_occ(passed),
    )
    assert decision.allowed is passed
    expected = (
        (
            "durable_evidence:occ_bound_receipts"
            + (":all_prs_merged" if description == _DESCRIPTION else "")
        )
        if passed
        else guard._bound_receipt_refusal(
            _TICKET,
            "OCC probe detail",
            why="a Done transition needs a passing definition-of-done check for every acceptance criterion",
        ).reason
    )
    assert decision.reason == expected


def test_check_run_engaged_never_reads_verdict() -> None:
    decision = _done(
        read_verdict=_never,
        runs=[
            {
                "id": 7100,
                "name": nbe.REPO_EVIDENCE_CHECK_NAME,
                "app": {"slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
            }
        ],
    )
    assert decision.allowed, decision.reason
    assert decision.reason.startswith("durable_evidence:repo_bound_checks")


def test_default_probe_uses_injected_verdict_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def evaluate(
        tid: str, _descriptions: Any, _statuses: Any, *, read_verdict: Any
    ) -> Any:
        read = read_verdict(tid)
        assert read.row == _row()
        return nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.PASSED, "repo-bound verdict"
        )

    def reader(tid: str) -> Any:
        seen.append(tid)
        return nbe.VerdictRead(nbe.VerdictReadStatus.FOUND, row=_row())

    monkeypatch.setattr(guard, "evaluate_repo_evidence", evaluate)
    decision = guard.decide(
        {
            "tool_name": "mcp__linear-server__update_issue",
            "tool_input": {"id": _TICKET, "state": "Done"},
        },
        linear_fetcher=lambda _tid: {"description": _DESCRIPTION},
        pr_fetcher=_merged,
        verdict_reader=reader,
        occ_probe=_never,
        receipt_lister=_never,
    )
    assert decision.allowed and seen == [_TICKET]


@pytest.fixture
def runtime_server(monkeypatch: pytest.MonkeyPatch) -> Any:
    state: dict[str, Any] = {
        "requests": [],
        "status": 200,
        "response": {"ok": True, "output_payloads": [{"ok": True, "rows": []}]},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            state["requests"].append(
                (
                    self.path,
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(state["status"])
            self.end_headers()
            self.wfile.write(state.get("raw", json.dumps(state["response"]).encode()))

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("ONEX_RUNTIME_URL", f"http://127.0.0.1:{server.server_port}/")
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("nested", [True, False])
def test_runtime_reads_latest_repo_row_and_posts_projection_request(
    runtime_server: Any, nested: bool
) -> None:
    newest = _row(completed_at="2026-10-03T12:00:00+00:00", projection_cursor=11)
    rows = [
        _row(
            contract_source="onex_change_control", completed_at="2026-10-06T12:00:00Z"
        ),
        _row(),
        newest,
        _row(ticket_id="OMN-OTHER", completed_at="2026-10-07T12:00:00Z"),
        _row(completed_at=newest["completed_at"], projection_cursor=9),
    ]
    payload = {"ok": True, "rows": rows}
    runtime_server["response"] = {
        "ok": True,
        "output_payloads": [
            {"unrelated": True},
            {"payload": payload} if nested else payload,
        ],
    }
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.FOUND and read.row == newest
    path, body = runtime_server["requests"][0]
    assert path == "/skill"
    assert body["command_name"] == "node_projection_read_effect"
    assert UUID(body["correlation_id"]).version == 4
    assert 0 < body["timeout_ms"] <= 15000
    assert body["payload"] == {
        "topic": "onex.snapshot.projection.dod-verdict.v1",
        "row_ticket_id": _TICKET,
        "order_by": "completed_at",
        "order": "desc",
        "limit": 100,
    }


@pytest.mark.parametrize(
    "code",
    [
        "unknown_topic",
        "not_yet_bus_backed",
        "projection_table_unreadable",
        "tenant_context_unresolved",
    ],
)
def test_runtime_refusal_is_error(runtime_server: Any, code: str) -> None:
    runtime_server["response"] = {
        "ok": False,
        "error": {
            "code": "dispatch_error",
            "message": f"RuntimeError: {code}",
            "retryable": False,
        },
    }
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR
    assert "dispatch_error" in read.error and code in read.error


def test_runtime_empty_rows_are_absent(runtime_server: Any) -> None:
    assert nbe.runtime_read_repo_verdict(_TICKET).status is nbe.VerdictReadStatus.ABSENT


@pytest.mark.parametrize(
    "response",
    [
        {"ok": True, "output_payloads": []},
        {"ok": True, "output_payloads": [{"ok": True}]},
        {
            "ok": True,
            "output_payloads": [
                {
                    "ok": False,
                    "error": {"code": "dispatch_error", "message": "unknown_topic"},
                }
            ],
        },
        {"ok": True, "output_payloads": [{"ok": True, "rows": "bad"}]},
    ],
)
def test_runtime_malformed_or_refused_payload_is_error(
    runtime_server: Any, response: Any
) -> None:
    runtime_server["response"] = response
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR
    assert read.error


def test_runtime_non_json_is_error(runtime_server: Any) -> None:
    runtime_server["raw"] = b"not JSON"
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR and "JSON" in read.error


def test_runtime_http_500_is_error(runtime_server: Any) -> None:
    runtime_server["status"] = 500
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR and "500" in read.error


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_runtime_has_no_io(
    runtime_server: Any, monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("ONEX_RUNTIME_URL")
    else:
        monkeypatch.setenv("ONEX_RUNTIME_URL", value)
    monkeypatch.setattr(nbe.http.client, "HTTPConnection", _never)
    monkeypatch.setattr(nbe.http.client, "HTTPSConnection", _never)
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR
    assert read.error == "ONEX_RUNTIME_URL is unset"
    assert runtime_server["requests"] == []


def test_runtime_connection_refused_is_error(monkeypatch: pytest.MonkeyPatch) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_port
    server.server_close()
    monkeypatch.setenv("ONEX_RUNTIME_URL", f"http://127.0.0.1:{port}")
    read = nbe.runtime_read_repo_verdict(_TICKET)
    assert read.status is nbe.VerdictReadStatus.ERROR and read.error


def test_verdict_pass_detail_names_run_commit_and_bindings() -> None:
    verdict = nbe.evaluate_repo_evidence(
        _TICKET,
        [_DESCRIPTION],
        [_merged(ldv.PRRef(_NUMBER, _REPO))],
        read_contract=lambda *_args: nbe.ContractRead(
            nbe.ContractReadStatus.FOUND, text=_contract("AC1", "AC2")
        ),
        read_check_runs=lambda *_args: [],
        read_verdict=lambda _tid: nbe.VerdictRead(
            nbe.VerdictReadStatus.FOUND, row=_row()
        ),
    )
    assert verdict.outcome is nbe.RepoEvidenceOutcome.PASSED
    assert (
        verdict.detail
        == f"repo-bound verdict repo-verdict-run at {_HEAD[:12]}: AC1<-dod-ac1 ({_REPO}#{_NUMBER}), AC2<-dod-ac2 ({_REPO}#{_NUMBER})"
    )


@pytest.mark.parametrize(
    ("description", "fragment"),
    [
        ("No criteria", "no acceptance criterion"),
        (_DESCRIPTION.replace("AC2 -- ", ""), "carry no label"),
    ],
)
def test_verdict_uses_same_criterion_reader(description: str, fragment: str) -> None:
    decision = _done(
        description=description + f"\nhttps://github.com/{_REPO}/pull/{_NUMBER}"
    )
    assert not decision.allowed and fragment in decision.reason


def test_merge_bound_verdict_does_not_read_head_contract() -> None:
    def contract_reader(_repo: str, sha: str, _tid: str) -> Any:
        assert sha == _MERGE
        return nbe.ContractRead(
            nbe.ContractReadStatus.FOUND, text=_contract("AC1", "AC2")
        )

    decision = _done(_row(contract_commit_sha=_MERGE), read_contract=contract_reader)
    assert decision.allowed, decision.reason
