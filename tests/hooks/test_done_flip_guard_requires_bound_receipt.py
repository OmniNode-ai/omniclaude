# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Repo-evidence gating for ticks, exemptions and fail-closed hooks [OMN-20368].

A merged PR, checked boxes, deploy readback and labels cannot substitute for
repo evidence. Keep these controls after retiring the receipt-specific tests.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

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
_PR_URL = "https://github.com/OmniNode-ai/omnimarket/pull/3144"


@pytest.fixture(autouse=True)
def _hermetic_linear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "")


# --------------------------------------------------------------------------- #
# Fixtures: live ticket descriptions and injected readers
# --------------------------------------------------------------------------- #


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


def _never(*_a: Any, **_k: Any) -> Any:
    raise AssertionError("must not be called on this path")


# --------------------------------------------------------------------------- #
# AC1: NO_ACCEPTANCE_CHECKS is refused, merged PR or not
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("label", ["close-if-done", "skip-merge-check"])
def test_no_acceptance_checks_exemption_label_is_not_a_substitute(label: str) -> None:
    d = guard.decide(
        _done("decision only, nothing shipped", labels=[label]),
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.NOT_ENGAGED, "no product contract"
        ),
        pr_fetcher=_never,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


def test_no_acceptance_checks_deploy_readback_marker_is_not_a_substitute() -> None:
    desc = "deploy-readback-proven: rebuilt dev effects to dev-tip; probe exit 0\n"
    d = guard.decide(
        _done(desc),
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.NOT_ENGAGED, "no product contract"
        ),
        pr_fetcher=_never,
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason


# --------------------------------------------------------------------------- #
# AC2: ticked boxes alone never pass; ticking requires repo evidence
# --------------------------------------------------------------------------- #


def test_ticked_boxes_and_merged_pr_without_receipt_is_refused() -> None:
    d = guard.decide(
        _done(_TICKED_DESCRIPTION),
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.REFUSED, "nothing bound"
        ),
        pr_fetcher=_merged,
        linear_fetcher=_live(_TICKED_DESCRIPTION),
    )
    assert not d.allowed
    assert "no_bound_dod_receipt" in d.reason
    assert "repo-evidence" in d.reason


def test_ticked_box_edit_without_receipt_is_refused() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "description": _TICKED_DESCRIPTION},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.REFUSED, "nothing bound"
        ),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
        pr_fetcher=_merged,
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
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.REFUSED, "nothing bound"
        ),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
        pr_fetcher=_merged,
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
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.REFUSED, "nothing bound"
        ),
        linear_fetcher=lambda _t: None,
        pr_fetcher=_merged,
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
    d = guard.decide(call, repo_evidence_probe=_never, linear_fetcher=_never)
    assert not d.allowed
    assert d.reason.startswith("ac_tick_without_receipt")


def test_ticked_box_edit_with_repo_evidence_is_allowed() -> None:
    call = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": _TICKET, "description": _TICKED_DESCRIPTION},
    }
    d = guard.decide(
        call,
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.PASSED, "repo-bound: AC1, AC2"
        ),
        linear_fetcher=_live(_UNTICKED_DESCRIPTION),
        pr_fetcher=_merged,
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
    d = guard.decide(
        call, repo_evidence_probe=_never, linear_fetcher=_live(_TICKED_DESCRIPTION)
    )
    assert d.allowed, d.reason


def test_repo_pass_open_cited_pr_still_blocks() -> None:
    d = guard.decide(
        _done(_TICKED_DESCRIPTION),
        repo_evidence_probe=lambda _t, _d, _prs: nbe.RepoEvidenceVerdict(
            nbe.RepoEvidenceOutcome.PASSED, "repo-bound"
        ),
        pr_fetcher=lambda ref: ldv.PRStatus(ref=ref, state="OPEN", merge_state="CLEAN"),
    )
    assert not d.allowed
    assert "pr_not_merged" in d.reason


def test_repo_pass_state_by_id_is_refused() -> None:
    """A Done passed by state id would skip every check if read as not-Done."""
    call = _done(_TICKED_DESCRIPTION)
    call["tool_input"]["state"] = "2be3a0d0-646a-4349-946e-ca395cbb0109"
    d = guard.decide(
        call, repo_evidence_probe=_never, pr_fetcher=_never, linear_fetcher=_never
    )
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
    refuses a Done without repo evidence whatever the mode or mask says."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
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
