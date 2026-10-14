# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-17427: a lab host that cannot read Actions variables reads a snapshot.

The gate resolves a `runs-on` expression against the organisation and
repository variable scopes, and visibility against the API. A lab-host lane
cannot read either (HTTP 403 on the variables, the lane read guard on the
API), so the gate exited 2 -- THE GATE DID NOT RUN -- and no lane could commit
a workflow edit.

The fix is a second SOURCE, not a second verdict. These tests pin the three
properties that keep it honest:

* a snapshot is read only after the live read FAILED, so a live answer always
  wins;
* a snapshot that is stale, absent, unparseable, future-dated or silent about
  the scope asked for is a REFUSAL (exit 2), never a pass; and
* a snapshot carrying a hosted value FAILS the gate, so the positive control
  proves the snapshot path judges rather than waves through.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "private_repo_runner_placement_gate.py"

SLUG = "OmniNode-ai/fixture"
FLEET = '["self-hosted","omnibase-ci"]'
HOSTED = '["ubuntu-latest"]'
NOW = datetime(2026, 10, 14, 12, 0, 0, tzinfo=UTC)
MAX_AGE = timedelta(hours=24)

SEAM_JOB = (
    "name: CI\non:\n  pull_request: {}\njobs:\n"
    "  build:\n    runs-on: >-\n"
    "      ${{ fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\') }}\n'
    "    steps:\n      - run: true\n"
)


def _module():
    if "placement_gate" in sys.modules:
        return sys.modules["placement_gate"]
    spec = importlib.util.spec_from_file_location("placement_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["placement_gate"] = module
    spec.loader.exec_module(module)
    return module


def _tree(tmp_path: Path, body: str = SEAM_JOB) -> Path:
    workflows = tmp_path / "tree" / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(body, encoding="utf-8")
    return tmp_path / "tree"


def _snapshot_file(
    tmp_path: Path,
    *,
    captured_at: datetime = NOW - timedelta(hours=1),
    org: dict[str, str] | None = None,
    repo: dict[str, str] | None = None,
    visibility: str | None = "private",
    slug: str = SLUG,
) -> Path:
    scopes: dict[str, dict[str, str]] = {}
    if org is not None:
        scopes[f"org:{slug.split('/', 1)[0]}"] = org
    if repo is not None:
        scopes[f"repo:{slug}"] = repo
    body: dict[str, object] = {
        "schema": 1,
        "captured_at": captured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scopes": scopes,
        "visibility": {} if visibility is None else {slug: visibility},
    }
    path = tmp_path / "runner-variables-snapshot.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def _snapshot(module, path: Path):
    return module.VariablesSnapshot(path, MAX_AGE, now=lambda: NOW)


def _unreadable_variables(module, snapshot=None):
    """Both live scopes 403, as on a lab host. Only the I/O call is replaced."""

    def fake_read(flag: str, target: str) -> dict[str, str]:
        raise module.GateError("HTTP 403: Resource not accessible by integration")

    instance = module.Variables(SLUG, snapshot=snapshot)
    instance._read = fake_read
    return instance


# --- the snapshot is a source for a FAILED live read -----------------------


def test_a_fresh_snapshot_resolves_the_seam_when_the_live_read_403s(
    tmp_path: Path,
) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, repo={}
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    assert module.scan(_tree(tmp_path), SLUG, variables) == []


def test_positive_control_a_hosted_value_in_the_snapshot_still_fails(
    tmp_path: Path,
) -> None:
    """Without this a snapshot path that waved everything through would pass."""
    module = _module()
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED}, repo={}
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    findings = module.scan(_tree(tmp_path), SLUG, variables)
    assert findings, "a hosted organisation value in the snapshot must be a finding"


def test_a_repo_shadow_in_the_snapshot_overrides_the_organisation_value(
    tmp_path: Path,
) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path,
        org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        repo={"OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED},
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    assert module.scan(_tree(tmp_path), SLUG, variables)


def test_a_live_answer_wins_over_the_snapshot(tmp_path: Path) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, repo={}
    )
    variables = module.Variables(SLUG, snapshot=_snapshot(module, path))
    variables._read = lambda flag, target: (
        {"OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED} if flag == "--repo" else {}
    )
    assert module.scan(_tree(tmp_path), SLUG, variables)


def test_the_fallback_is_announced_with_the_snapshot_age(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, repo={}
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    module.scan(_tree(tmp_path), SLUG, variables)
    err = capsys.readouterr().err
    assert "snapshot" in err and "age 1h" in err and "HTTP 403" in err


# --- every way the snapshot cannot be trusted is a refusal -------------------


def test_a_stale_snapshot_refuses(tmp_path: Path) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path,
        captured_at=NOW - timedelta(hours=25),
        org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        repo={},
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "stale" in str(error.value)
    assert "THE GATE DID NOT RUN" in str(error.value)
    assert "--write-variables-snapshot" in str(error.value)


def test_a_future_dated_snapshot_refuses(tmp_path: Path) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path,
        captured_at=NOW + timedelta(hours=2),
        org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        repo={},
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "future" in str(error.value)


def test_a_missing_snapshot_file_refuses(tmp_path: Path) -> None:
    module = _module()
    variables = _unreadable_variables(
        module, _snapshot(module, tmp_path / "does-not-exist.json")
    )
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "THE GATE DID NOT RUN" in str(error.value)


def test_an_unparseable_snapshot_refuses(tmp_path: Path) -> None:
    module = _module()
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    variables = _unreadable_variables(module, _snapshot(module, path))
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "THE GATE DID NOT RUN" in str(error.value)


def test_a_snapshot_without_the_organisation_scope_refuses(tmp_path: Path) -> None:
    """Unset in the repo and unrecorded above it is not "unset"."""
    module = _module()
    path = _snapshot_file(tmp_path, org=None, repo={})
    variables = _unreadable_variables(module, _snapshot(module, path))
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "org:OmniNode-ai" in str(error.value)


def test_a_snapshot_of_another_repository_refuses(tmp_path: Path) -> None:
    module = _module()
    path = _snapshot_file(
        tmp_path,
        org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        repo={},
        slug="OmniNode-ai/other",
    )
    variables = _unreadable_variables(module, _snapshot(module, path))
    with pytest.raises(module.GateError):
        module.scan(_tree(tmp_path), SLUG, variables)


def test_no_snapshot_keeps_the_existing_credential_refusal(tmp_path: Path) -> None:
    module = _module()
    variables = _unreadable_variables(module, None)
    with pytest.raises(module.GateError) as error:
        module.scan(_tree(tmp_path), SLUG, variables)
    assert "ACTIONS_VARIABLES_TOKEN" in str(error.value)


# --- visibility --------------------------------------------------------------


def _failing_gh(module, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        module,
        "_gh",
        lambda args, env_name="GH_TOKEN": subprocess.CompletedProcess(
            args, 1, "", "HTTP 403: refused by the lane read guard"
        ),
    )


def test_visibility_falls_back_to_a_fresh_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    path = _snapshot_file(tmp_path, visibility="private", org={}, repo={})
    assert module.resolve_visibility(SLUG, _snapshot(module, path)) == "private"


def test_visibility_refuses_on_a_stale_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    path = _snapshot_file(
        tmp_path, captured_at=NOW - timedelta(days=3), visibility="private"
    )
    with pytest.raises(module.GateError) as error:
        module.resolve_visibility(SLUG, _snapshot(module, path))
    assert "stale" in str(error.value)


def test_visibility_refuses_when_the_snapshot_does_not_record_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    path = _snapshot_file(tmp_path, visibility=None, org={}, repo={})
    with pytest.raises(module.GateError):
        module.resolve_visibility(SLUG, _snapshot(module, path))


def test_visibility_without_a_snapshot_still_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    with pytest.raises(module.GateError) as error:
        module.resolve_visibility(SLUG, None)
    assert "THE GATE DID NOT RUN" in str(error.value)


# --- the CLI ----------------------------------------------------------------


def _main(module, argv: list[str]) -> int:
    existing = os.environ.pop("GITHUB_ACTIONS", None)
    try:
        return module.main(argv)
    finally:
        if existing is not None:
            os.environ["GITHUB_ACTIONS"] = existing


def test_main_passes_on_a_lab_host_with_a_fresh_fleet_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    monkeypatch.setattr(module, "_utcnow", lambda: NOW)
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, repo={}
    )
    argv = [
        "--repo-root", str(_tree(tmp_path)), "--repo", SLUG,
        "--variables-snapshot", str(path), "--branches-json", "[]",
    ]  # fmt: skip
    assert _main(module, argv) == 0


def test_main_fails_on_a_lab_host_when_the_snapshot_holds_a_hosted_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    monkeypatch.setattr(module, "_utcnow", lambda: NOW)
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED}, repo={}
    )
    argv = [
        "--repo-root", str(_tree(tmp_path)), "--repo", SLUG,
        "--variables-snapshot", str(path), "--branches-json", "[]",
    ]  # fmt: skip
    assert _main(module, argv) == 1


def test_main_exits_2_on_a_stale_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    monkeypatch.setattr(module, "_utcnow", lambda: NOW)
    path = _snapshot_file(
        tmp_path,
        captured_at=NOW - timedelta(hours=30),
        org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        repo={},
    )
    argv = [
        "--repo-root", str(_tree(tmp_path)), "--repo", SLUG,
        "--variables-snapshot", str(path), "--branches-json", "[]",
    ]  # fmt: skip
    assert _main(module, argv) == 2


def test_inside_github_actions_a_snapshot_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CI must resolve live: a token outage there must not read a file."""
    module = _module()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    path = _snapshot_file(tmp_path, org={}, repo={})
    argv = ["--repo-root", str(_tree(tmp_path)), "--repo", SLUG,
            "--variables-snapshot", str(path)]  # fmt: skip
    assert module.main(argv) == 2
    assert "--variables-snapshot" in capsys.readouterr().err


def test_the_environment_names_a_snapshot_path_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    monkeypatch.setattr(module, "_utcnow", lambda: NOW)
    path = _snapshot_file(
        tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}, repo={}
    )
    monkeypatch.setenv("PRRP_VARIABLES_SNAPSHOT", str(path))
    argv = ["--repo-root", str(_tree(tmp_path)), "--repo", SLUG,
            "--branches-json", "[]"]  # fmt: skip
    assert _main(module, argv) == 0


# --- the refresh command ----------------------------------------------------


def _live_gh(module, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(args: list[str], env_name: str = "GH_TOKEN"):
        if args[:2] == ["api", f"repos/{SLUG}"]:
            return subprocess.CompletedProcess(args, 0, "private\n", "")
        if args[:2] == ["variable", "list"]:
            org = "--org" in args
            body = (
                [{"name": "OMNI_TRUSTED_CI_RUNS_ON_JSON", "value": FLEET}]
                if org
                else []
            )
            return subprocess.CompletedProcess(args, 0, json.dumps(body), "")
        raise AssertionError(args)

    monkeypatch.setattr(module, "_gh", fake)


def test_the_refresh_command_writes_a_snapshot_the_gate_then_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _live_gh(module, monkeypatch)
    monkeypatch.setattr(module, "_utcnow", lambda: NOW)
    out = tmp_path / "written.json"
    assert _main(module, ["--repo", SLUG, "--write-variables-snapshot", str(out)]) == 0
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["captured_at"] == "2026-10-14T12:00:00Z"
    assert written["visibility"] == {SLUG: "private"}
    assert written["scopes"] == {
        "org:OmniNode-ai": {"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        f"repo:{SLUG}": {},
    }
    variables = _unreadable_variables(module, _snapshot(module, out))
    assert module.scan(_tree(tmp_path), SLUG, variables) == []


def test_the_refresh_command_writes_nothing_when_a_scope_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    _failing_gh(module, monkeypatch)
    out = tmp_path / "written.json"
    assert _main(module, ["--repo", SLUG, "--write-variables-snapshot", str(out)]) == 2
    assert not out.exists()
