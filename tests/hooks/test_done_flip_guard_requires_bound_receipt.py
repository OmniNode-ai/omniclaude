# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A Linear Done needs a passing definition-of-done check [OMN-20368].

On 2026-10-02 OMN-20180, OMN-20181 and OMN-20182 reached Done after dod_verify
refused them with NO_ACCEPTANCE_CHECKS. The guard admitted them on its merged-PR
path once the lane had ticked the acceptance boxes itself: their contracts bind
no criterion, so nothing checked any criterion at all.

These tests pin the replacement contract:

* the ONE sufficient condition for Done is the bound-receipt bar: the OCC
  contract on ``origin/dev`` binds every labelled criterion through
  ``binds_ac``, each discharged by a PASS receipt taken against the current
  contract entry;
* a merged PR, ticked boxes, a deploy-readback marker and an exemption label
  are further conditions or nothing, never substitutes;
* an edit that ticks an acceptance box needs the same receipt;
* the guard fails closed: on its own error, in any cwd, in lite mode, and
  under any hooks mask.

The OCC side is a real local git repository (no network); Linear and GitHub
are injected stubs.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from omnibase_core.validation.validator_receipt_gate import (
    compute_contract_entry_sha256,
)
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

_PLUGIN_ROOT = Path(__file__).parent.parent.parent / "plugins" / "onex"
_LIB_DIR = _PLUGIN_ROOT / "hooks" / "lib"
_SCRIPT = _PLUGIN_ROOT / "hooks" / "scripts" / "pre_tool_use_done_flip_guard.sh"


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
# Sibling modules, importable once _load_guard() put lib/ on sys.path.
ldv: Any = importlib.import_module("linear_done_verify")
nbe: Any = importlib.import_module("no_pr_bound_evidence")

_TICKET = "OMN-20180"
_NOW = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)
_PR_URL = "https://github.com/OmniNode-ai/omnimarket/pull/3144"


@pytest.fixture(autouse=True)
def _hermetic_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "")


# --------------------------------------------------------------------------- #
# Fixtures: a real OCC clone whose origin/dev carries the contract + receipts
# --------------------------------------------------------------------------- #


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(os.environ),
    )


def _occ_clone(tmp_path: Path, contract: str, receipts: dict[str, str]) -> Path:
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True,
        capture_output=True,
        env=scrub_git_location_env(os.environ),
    )
    clone = tmp_path / "onex_change_control"
    subprocess.run(
        ["git", "clone", str(origin), str(clone)],
        check=True,
        capture_output=True,
        env=scrub_git_location_env(os.environ),
    )
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "t")
    _git(clone, "checkout", "-b", "dev")
    (clone / "contracts").mkdir()
    (clone / "contracts" / f"{_TICKET}.yaml").write_text(contract, encoding="utf-8")
    for item, text in receipts.items():
        rp = clone / "drift" / "dod_receipts" / _TICKET / item
        rp.mkdir(parents=True)
        (rp / "command.yaml").write_text(text, encoding="utf-8")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "contract and receipts")
    _git(clone, "push", "origin", "dev")
    return clone


# The OMN-20180 contract as it is on origin/dev: two evidence items, PASS
# receipts for both, and no `binds_ac` anywhere. dod_verify calls that
# NO_ACCEPTANCE_CHECKS.
_UNBOUND_CONTRACT = """\
schema_version: "1.0.0"
ticket_id: "OMN-20180"
dod_evidence:
  - id: "dod-pr-3144"
    checks:
      - check_type: "command"
        check_value: "grep -c PROTECTED_SURFACE scripts/ci/test_selection_models.py"
  - id: "dod-pr-3144-ci"
    checks:
      - check_type: "command"
        check_value: "gh pr view 3144 --repo OmniNode-ai/omnimarket --json files"
"""

_BOUND_CONTRACT = """\
schema_version: "1.0.0"
ticket_id: "OMN-20180"
dod_evidence:
  - id: "dod-ac1"
    binds_ac: ["AC1"]
    checks:
      - check_type: "command"
        check_value: "uv run pytest tests/unit/scripts/test_detect_test_paths.py -k protected"
  - id: "dod-ac2"
    binds_ac: ["AC2"]
    checks:
      - check_type: "command"
        check_value: "uv run pytest tests/unit/scripts/test_detect_test_paths.py -k unmapped"
"""


def _receipt(
    item: str,
    contract: str,
    *,
    entry_hash: str | None = "auto",
    whole_hash: str | None = None,
    status: str = "PASS",
    run_timestamp: str = "2026-09-30T22:05:00Z",
) -> str:
    fields: dict[str, Any] = {
        "schema_version": "1.0.0",
        "ticket_id": _TICKET,
        "evidence_item_id": item,
        "check_type": "command",
        "status": status,
        "run_timestamp": run_timestamp,
        "runner": "lane-a",
        "verifier": "lane-b",
        "commit_sha": "0ec0302f795b36adabd86bf7d01fd10130384857",
        "probe_stdout": "66 passed\n",
    }
    if entry_hash == "auto":
        fields["contract_entry_sha256"] = compute_contract_entry_sha256(
            yaml.safe_load(contract), item
        )
    elif entry_hash is not None:
        fields["contract_entry_sha256"] = entry_hash
    if whole_hash is not None:
        fields["contract_sha256"] = whole_hash
    return yaml.safe_dump(fields, sort_keys=False)


_TICKED_DESCRIPTION = f"""\
Smart test selection skips the delegation tests.

## Acceptance criteria

- [X] AC1: a delegation-surface change selects the full suite -- falsifier: pytest -k protected
- [X] AC2: an unmapped module escalates to the full suite -- falsifier: pytest -k unmapped

Implemented in {_PR_URL}
"""

_UNTICKED_DESCRIPTION = _TICKED_DESCRIPTION.replace("- [X]", "- [ ]")


def _merged(ref: Any) -> Any:
    return ldv.PRStatus(ref=ref, state="MERGED", merge_state="CLEAN")


def _done(description: str | None = None, **extra: Any) -> dict[str, Any]:
    tool_input: dict[str, Any] = {"id": _TICKET, "state": "Done", **extra}
    if description is not None:
        tool_input["description"] = description
    return {"tool_name": "mcp__linear-server__save_issue", "tool_input": tool_input}


def _live(description: str) -> Any:
    return lambda _t: {
        "description": description,
        "labels": [],
        "attachment_urls": [_PR_URL],
    }


def _decide(
    call: dict[str, Any], clone: Path, monkeypatch: pytest.MonkeyPatch, **kw: Any
) -> Any:
    """Run decide() with its PRODUCTION probe against the fixture OCC clone."""
    monkeypatch.setenv("OMNI_HOME", str(clone.parent))
    kw.setdefault("pr_fetcher", _merged)
    kw.setdefault("receipt_lister", lambda _t: [])
    return guard.decide(call, now=_NOW, **kw)


def _never(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("must not be called on this path")


# --------------------------------------------------------------------------- #
# AC1: NO_ACCEPTANCE_CHECKS is refused, merged PR or not
# --------------------------------------------------------------------------- #


def test_no_acceptance_checks_with_merged_pr_and_ticked_boxes_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The OMN-20180 incident, replayed: merged PR, boxes ticked, PASS receipts
    for items that bind no criterion. Before OMN-20368 this was
    ``durable_evidence:all_prs_merged``."""
    clone = _occ_clone(
        tmp_path,
        _UNBOUND_CONTRACT,
        {
            "dod-pr-3144": _receipt("dod-pr-3144", _UNBOUND_CONTRACT),
            "dod-pr-3144-ci": _receipt("dod-pr-3144-ci", _UNBOUND_CONTRACT),
        },
    )
    d = _decide(
        _done(),
        clone,
        monkeypatch,
        linear_fetcher=_live(_TICKED_DESCRIPTION),
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    assert "AC1: no dod_evidence item" in d.reason
    assert "AC2: no dod_evidence item" in d.reason


def test_no_acceptance_checks_no_contract_at_all_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "onex_change_control").mkdir()
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    d = guard.decide(
        _done(_TICKED_DESCRIPTION),
        pr_fetcher=_merged,
        receipt_lister=lambda _t: [],
        now=_NOW,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    assert "no OCC contract" in d.reason


@pytest.mark.parametrize("label", ["close-if-done", "skip-merge-check"])
def test_no_acceptance_checks_exemption_label_is_not_a_substitute(label: str) -> None:
    d = guard.decide(
        _done("decision only, nothing shipped", labels=[label]),
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "no OCC contract"),
        pr_fetcher=_never,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


def test_no_acceptance_checks_deploy_readback_marker_is_not_a_substitute() -> None:
    desc = "deploy-readback-proven: rebuilt dev effects to dev-tip; probe exit 0\n"
    d = guard.decide(
        _done(desc),
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "no OCC contract"),
        pr_fetcher=_never,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


def test_no_acceptance_checks_a_failed_or_skipped_receipt_does_not_discharge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _occ_clone(
        tmp_path,
        _BOUND_CONTRACT,
        {
            "dod-ac1": _receipt("dod-ac1", _BOUND_CONTRACT, status="FAIL"),
            "dod-ac2": _receipt("dod-ac2", _BOUND_CONTRACT, status="SKIPPED"),
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert not d.allowed
    assert "not a PASS" in d.reason


# --------------------------------------------------------------------------- #
# AC2: ticked boxes alone never pass; ticking without the receipt is refused
# --------------------------------------------------------------------------- #


def test_ticked_boxes_and_merged_pr_without_receipt_is_refused() -> None:
    d = guard.decide(
        _done(_TICKED_DESCRIPTION),
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "nothing bound"),
        pr_fetcher=_merged,
        linear_fetcher=_live(_TICKED_DESCRIPTION),
        receipt_lister=lambda _t: [],
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    assert "Ticked boxes" in d.reason


def test_ticked_box_edit_without_receipt_is_refused() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "description": _TICKED_DESCRIPTION},
    }
    d = guard.decide(
        call,
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "nothing bound"),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
    )
    assert not d.allowed
    assert d.reason.startswith("ac_tick_without_receipt")
    assert "ticks 2 acceptance box(es)" in d.reason


def test_ticked_box_edit_by_patch_without_receipt_is_refused() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": _TICKET,
            "state": "In Review",
            "patch": [
                {
                    "op": "replace",
                    "old_string": "- [ ] AC1:",
                    "new_string": "- [x] AC1:",
                }
            ],
        },
    }
    d = guard.decide(
        call,
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "nothing bound"),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
    )
    assert not d.allowed
    assert d.reason.startswith("ac_tick_without_receipt")
    assert "ticks 1 acceptance box(es)" in d.reason


def test_ticked_box_edit_when_live_description_unreadable_is_refused() -> None:
    """Cannot compare before and after: every checked box counts as a tick."""
    call = {
        "tool_name": "mcp__linear-server__update_issue",
        "tool_input": {"id": _TICKET, "description": _TICKED_DESCRIPTION},
    }
    d = guard.decide(
        call,
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(False, "nothing bound"),
        linear_fetcher=lambda _t: None,
    )
    assert not d.allowed
    assert d.reason.startswith("ac_tick_without_receipt")


def test_ticked_box_on_create_is_refused() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "team": "Omninode",
            "title": "t",
            "description": _TICKED_DESCRIPTION,
        },
    }
    d = guard.decide(call, occ_probe=_never, linear_fetcher=_never)
    assert not d.allowed
    assert d.reason.startswith("ac_tick_without_receipt")


def test_ticked_box_edit_with_bound_receipt_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "description": _TICKED_DESCRIPTION},
    }
    d = guard.decide(
        call,
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(True, "bound: AC1, AC2"),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
    )
    assert d.allowed, d.reason
    assert d.reason == "not_done_state"


def test_ticked_box_unchanged_edit_is_not_gated() -> None:
    """Editing prose on a ticket whose boxes were already ticked ticks nothing."""
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "id": _TICKET,
            "description": _TICKED_DESCRIPTION.replace("skips", "used to skip"),
        },
    }
    d = guard.decide(call, occ_probe=_never, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert d.allowed, d.reason


# --------------------------------------------------------------------------- #
# AC3: a receipt taken against a contract that has changed since is stale
# --------------------------------------------------------------------------- #


def test_stale_receipt_contract_entry_changed_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    edited = _BOUND_CONTRACT.replace("-k protected", "-k protected_surface")
    clone = _occ_clone(
        tmp_path,
        edited,
        {
            # Both receipts were taken against the contract BEFORE the edit.
            "dod-ac1": _receipt("dod-ac1", _BOUND_CONTRACT),
            "dod-ac2": _receipt("dod-ac2", _BOUND_CONTRACT),
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert not d.allowed
    assert "AC1: dod-ac1 receipt is stale" in d.reason
    assert "AC2" not in d.reason.split("What is missing:")[1]


def test_stale_receipt_whole_file_hash_mismatch_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _occ_clone(
        tmp_path,
        _BOUND_CONTRACT,
        {
            item: _receipt(
                item, _BOUND_CONTRACT, entry_hash=None, whole_hash="sha256:" + "0" * 64
            )
            for item in ("dod-ac1", "dod-ac2")
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert not d.allowed
    assert "is stale: the contract changed" in d.reason


def test_stale_receipt_naming_no_contract_version_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone = _occ_clone(
        tmp_path,
        _BOUND_CONTRACT,
        {
            item: _receipt(item, _BOUND_CONTRACT, entry_hash=None)
            for item in ("dod-ac1", "dod-ac2")
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert not d.allowed
    assert "names no contract version" in d.reason


# --------------------------------------------------------------------------- #
# AC4: every criterion bound to a current PASS receipt is allowed
# --------------------------------------------------------------------------- #


def test_bound_pass_with_merged_pr_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The receipts are older than the no-PR freshness window: a receipt about
    merged code is judged by its commit and contract hash, not a state window."""
    clone = _occ_clone(
        tmp_path,
        _BOUND_CONTRACT,
        {
            item: _receipt(item, _BOUND_CONTRACT, run_timestamp="2026-09-01T00:00:00Z")
            for item in ("dod-ac1", "dod-ac2")
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert d.allowed, d.reason
    assert d.reason == "durable_evidence:occ_bound_receipts:all_prs_merged"


def test_bound_pass_whole_file_hash_match_is_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib

    whole = "sha256:" + hashlib.sha256(_BOUND_CONTRACT.encode()).hexdigest()
    clone = _occ_clone(
        tmp_path,
        _BOUND_CONTRACT,
        {
            item: _receipt(item, _BOUND_CONTRACT, entry_hash=None, whole_hash=whole)
            for item in ("dod-ac1", "dod-ac2")
        },
    )
    d = _decide(_done(), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION))
    assert d.allowed, d.reason


def test_bound_pass_status_only_flip_with_unreadable_description_is_refused() -> None:
    """No description, no live read: no criteria can be read, so nothing is bound."""
    d = guard.decide(
        _done(),
        occ_probe=lambda tid, desc: nbe.evaluate_bound_evidence(
            tid, desc, nbe.OccTicketEvidence({"dod_evidence": []}), _NOW
        ),
        pr_fetcher=_never,
        linear_fetcher=lambda _t: None,
    )
    assert not d.allowed
    assert "no acceptance criterion could be read" in d.reason


def test_bound_pass_done_call_cannot_drop_a_live_criterion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Done call rewrites the body to the bound criterion only. Today's AC2,
    which nothing binds, still has to be met."""
    one_bound = _BOUND_CONTRACT.split('  - id: "dod-ac2"', maxsplit=1)[0]
    clone = _occ_clone(tmp_path, one_bound, {"dod-ac1": _receipt("dod-ac1", one_bound)})
    rewritten = _TICKED_DESCRIPTION.split("- [X] AC2", maxsplit=1)[0]
    d = _decide(
        _done(rewritten), clone, monkeypatch, linear_fetcher=_live(_TICKED_DESCRIPTION)
    )
    assert not d.allowed
    assert "AC2: no dod_evidence item" in d.reason


def test_bound_pass_open_cited_pr_still_blocks() -> None:
    d = guard.decide(
        _done(_TICKED_DESCRIPTION),
        occ_probe=lambda _t, _d: nbe.BoundEvidenceVerdict(True, "bound"),
        pr_fetcher=lambda ref: ldv.PRStatus(ref=ref, state="OPEN", merge_state="CLEAN"),
        receipt_lister=lambda _t: [],
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_bound_pass_state_by_id_is_refused() -> None:
    """A Done passed by state id would skip every check if read as not-Done."""
    call = _done(_TICKED_DESCRIPTION)
    call["tool_input"]["state"] = "2be3a0d0-646a-4349-946e-ca395cbb0109"
    d = guard.decide(call, occ_probe=_never, pr_fetcher=_never, linear_fetcher=_never)
    assert not d.allowed
    assert d.reason.startswith("state_by_id")


# --------------------------------------------------------------------------- #
# AC5: fail closed -- own error, any cwd, lite mode, any hooks mask
# --------------------------------------------------------------------------- #


def test_fail_closed_main_refuses_when_decide_raises(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom(_call: dict[str, Any]) -> Any:
        raise RuntimeError("synthetic guard defect")

    monkeypatch.setattr(guard, "decide", _boom)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO(json.dumps(_done())))
    assert guard.main() == 2
    err = capsys.readouterr().err
    assert "guard_error" in err
    assert "synthetic guard defect" in err


def _run_hook(
    payload: dict[str, Any], cwd: Path, plugin_root: Path, env_extra: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CLAUDE_PROJECT_DIR", "PYTHONPATH")
    }
    env.update({"CLAUDE_PLUGIN_ROOT": str(plugin_root), "LINEAR_API_KEY": ""})
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(plugin_root / "hooks" / "scripts" / _SCRIPT.name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize(
    "env_extra",
    [
        {},
        {"OMNICLAUDE_MODE": "lite"},
        {"ONEX_HOOKS_MASK": "0"},
    ],
    ids=["outside-repo", "lite-mode", "mask-all-off"],
)
def test_fail_closed_hook_refuses_in_any_cwd_mode_or_mask(
    tmp_path: Path, env_extra: dict[str, str]
) -> None:
    """The registered script, run from a directory that is no omninode repo,
    refuses a receipt-less Done whatever the mode or mask says."""
    workspace = tmp_path / "workspace"
    (workspace / "onex_change_control").mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    # A ticket id no workspace has: common.sh may load a real Linear key from
    # the operator env file, and the live read must find nothing to rely on.
    payload = _done("## Acceptance criteria\n\n- [x] AC1: done -- falsifier: x\n")
    payload["tool_input"]["id"] = "OMN-99999999"
    result = _run_hook(
        payload,
        outside,
        _PLUGIN_ROOT,
        {"OMNI_HOME": str(workspace), **env_extra},
    )
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "no_bound_dod_receipt" in result.stderr


def test_fail_closed_hook_refuses_when_its_library_is_missing(tmp_path: Path) -> None:
    root = tmp_path / "plugin"
    (root / "hooks" / "scripts").mkdir(parents=True)
    (root / "hooks" / "lib").mkdir(parents=True)
    for name in ("pre_tool_use_done_flip_guard.sh", "common.sh"):
        src = _PLUGIN_ROOT / "hooks" / "scripts" / name
        (root / "hooks" / "scripts" / name).write_text(src.read_text())
    result = _run_hook(_done(), tmp_path, root, {})
    assert result.returncode == 2, (result.stdout, result.stderr)
    assert "guard_error" in result.stderr


def test_fail_closed_occ_fetch_is_bounded_even_when_a_helper_holds_its_pipes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fetch whose helper outlives git must not outlast its deadline.

    Live, 2026-10-02: two Done-class writes passed while the hook ran past the
    harness timeout on a loaded host. A ``git`` that leaves a sleeping child
    behind is the shape a captured-output fetch waits on forever.
    """
    import time

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/bin/sh\nsleep 30 &\nsleep 30\n")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ['PATH']}")
    start = time.monotonic()
    nbe.bounded_fetch(tmp_path, timeout=1)
    assert time.monotonic() - start < 10
