# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behaviour tests for the rollout drift audit (OMN-18016).

The audit's whole value is that a zero-drift verdict can be believed. That is
only true if two things hold, and both are pinned here: every detector
actually fires against a known-bad input, and a failed API call becomes an
error rather than an empty result. The second half is not hypothetical — four
consecutive confident "zero failures" readings during the trusted-CI re-flip
canary were an errored sweep whose stderr had been discarded, and re-running
without the suppression found 30 real rows.

Every ``gh`` call is stubbed, so these tests make no network call and do not
depend on live org state.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_PATH = REPO_ROOT / "scripts" / "audit_public_repo_hygiene_rollout.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prh_audit", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prh_audit"] = module
    spec.loader.exec_module(module)
    return module


audit_mod = _load()


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub(responses: dict[str, _Proc], default: _Proc) -> Any:
    def run(args: list[str], **_: Any) -> _Proc:
        joined = " ".join(args)
        for needle, proc in responses.items():
            if needle in joined:
                return proc
        return default

    return run


ONE_PUBLIC_REPO = json.dumps({"name": "somerepo", "default_branch": "dev"})


def _base_responses(**overrides: _Proc) -> dict[str, _Proc]:
    responses: dict[str, _Proc] = {
        "orgs/OmniNode-ai/repos": _Proc(0, ONE_PUBLIC_REPO + "\n"),
        "/branches ": _Proc(0, "dev\n"),
        "/pulls": _Proc(0, ""),
        "contents/.github/workflows/public-repo-hygiene.yml": _Proc(0, "x"),
        "contents/.public-repo-hygiene.yaml": _Proc(0, "x"),
        "required_status_checks": _Proc(0, json.dumps([audit_mod.GATE_CONTEXT])),
    }
    responses.update(overrides)
    return responses


def _run_audit(
    monkeypatch: pytest.MonkeyPatch,
    responses: dict[str, _Proc],
    *,
    check_required: bool = True,
) -> list[Any]:
    monkeypatch.setattr(subprocess, "run", _stub(responses, _Proc(0, "")), raising=True)
    return audit_mod.audit(check_required=check_required)


def test_clean_org_reports_no_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _run_audit(monkeypatch, _base_responses()) == []


def test_missing_gate_workflow_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = _run_audit(
        monkeypatch,
        _base_responses(
            **{
                "contents/.github/workflows/public-repo-hygiene.yml": _Proc(
                    1, "", "gh: Not Found (HTTP 404)"
                )
            }
        ),
    )
    assert [f.kind for f in findings] == ["gate-missing"]


def test_missing_repo_config_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = _run_audit(
        monkeypatch,
        _base_responses(
            **{"contents/.public-repo-hygiene.yaml": _Proc(1, "", "HTTP 404 Not Found")}
        ),
    )
    assert [f.kind for f in findings] == ["config-missing"]


def test_removed_required_check_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = _run_audit(
        monkeypatch,
        _base_responses(required_status_checks=_Proc(0, json.dumps(["ci"]))),
    )
    assert [f.kind for f in findings] == ["required-check-missing"]


def test_unprotected_default_branch_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unprotected branch is a finding in its own right, never an empty
    context list that reads as "the check is simply absent".
    """
    findings = _run_audit(
        monkeypatch,
        _base_responses(
            required_status_checks=_Proc(1, "", "gh: Not Found (HTTP 404)")
        ),
    )
    assert [f.kind for f in findings] == ["branch-unprotected"]


def test_branch_without_a_pr_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    findings = _run_audit(
        monkeypatch, _base_responses(**{"/branches ": _Proc(0, "dev\nstranded\n")})
    )
    assert [f.kind for f in findings] == ["branch-without-pr"]
    assert "stranded" in findings[0].detail


def test_skip_required_check_suppresses_only_that_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """While the required-check registration is parked on an operator decision,
    18 copies of a known open item would bury the real drift — the exact
    masking that made an hourly runner-routing audit useless.
    """
    responses = _base_responses(
        **{
            "required_status_checks": _Proc(0, json.dumps(["ci"])),
            "contents/.public-repo-hygiene.yaml": _Proc(1, "", "HTTP 404 Not Found"),
        }
    )
    findings = _run_audit(monkeypatch, responses, check_required=False)
    assert [f.kind for f in findings] == ["config-missing"]


# ---------------------------------------------------------------------------
# An empty result is not evidence of absence
# ---------------------------------------------------------------------------


def test_failed_repo_listing_raises_rather_than_returning_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        _stub({"orgs/": _Proc(1, "", "HTTP 503")}, _Proc(0, "")),
        raising=True,
    )
    with pytest.raises(audit_mod.AuditError, match="false-zero"):
        audit_mod.audit(check_required=False)


def test_empty_repo_listing_raises_rather_than_reporting_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subprocess, "run", _stub({"orgs/": _Proc(0, "")}, _Proc(0, "")), raising=True
    )
    with pytest.raises(audit_mod.AuditError, match="not evidence of absence"):
        audit_mod.audit(check_required=False)


def test_non_404_content_error_raises_rather_than_reading_as_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 is a real answer: the file is absent. A 500 is not, and must never
    be reported as "the gate is missing" — a wrong finding is as corrosive to
    an audit's credibility as a missed one.
    """
    responses = _base_responses(
        **{
            "contents/.github/workflows/public-repo-hygiene.yml": _Proc(
                1, "", "HTTP 500 Internal Server Error"
            )
        }
    )
    monkeypatch.setattr(subprocess, "run", _stub(responses, _Proc(0, "")), raising=True)
    with pytest.raises(audit_mod.AuditError, match="could not read"):
        audit_mod.audit(check_required=False)


def test_umbrella_repos_are_exempt_from_the_required_check_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two repos gate behind a single CI-summary umbrella rather than through
    required_status_checks. "Required" means "can block a merge", not "present
    in required_status_checks", so auditing them on the wrong surface would
    produce a permanent false finding.
    """
    for repo in sorted(audit_mod.UMBRELLA_REPOS):
        responses = _base_responses(
            **{
                "orgs/OmniNode-ai/repos": _Proc(
                    0, json.dumps({"name": repo, "default_branch": "dev"}) + "\n"
                ),
                "required_status_checks": _Proc(0, json.dumps(["ci"])),
            }
        )
        findings = _run_audit(monkeypatch, responses)
        assert findings == [], f"{repo}: {findings}"
