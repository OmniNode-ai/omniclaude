# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20141: the runner-placement hook judges a commit made inside a lane.

A lane has a zero raw GitHub read budget, and no session token can read
organisation Actions variables (HTTP 403). The hook therefore failed at the
VISIBILITY read, before any variable read, with a refusal that named no way
through. These tests run the hook exactly as pre-commit does -- the script as
a subprocess -- against a stub ``gh`` on PATH that answers the visibility read
with the lane refusal text and every Actions-variables read with HTTP 403, so
nothing below the subprocess boundary is replaced.

* AC1: a fresh ``PRRP_VARIABLES_SNAPSHOT`` answers visibility AND the
  variables, and the hook judges the workflow;
* AC2: a private-repo job on a hosted runner is still refused on that path;
* AC3: an input the hook cannot resolve is exit 2, and the output names the
  missing input and how to supply it.

The test ids carry the names the ticket's falsifiers select with ``-k``.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "private_repo_runner_placement_gate.py"

SLUG = "OmniNode-ai/fixture"
OTHER = "OmniNode-ai/fixture-two"
FLEET = '["self-hosted","omnibase-ci"]'
HOSTED = '["ubuntu-latest"]'
LANE_REFUSAL = (
    "REFUSED lane=prrp-fixture raw GitHub read budget=0. Use pr_state_local.py "
    "for PR state and check runs"
)

SEAM_JOB = (
    "name: CI\non:\n  pull_request: {}\njobs:\n"
    "  build:\n    runs-on: >-\n"
    "      ${{ fromJSON(vars.OMNI_TRUSTED_CI_RUNS_ON_JSON || "
    '\'["self-hosted","omnibase-ci"]\') }}\n'
    "    steps:\n      - run: true\n"
)
HOSTED_LITERAL_JOB = (
    "name: CI\non:\n  pull_request: {}\njobs:\n"
    "  build:\n    runs-on: ubuntu-latest\n"
    "    steps:\n      - run: true\n"
)

STUB_GH = """#!/bin/sh
# A lane's gh: the visibility read is refused by the lane read guard and
# every Actions-variables read is HTTP 403. Anything else is unexpected.
echo "$*" >> "$STUB_GH_LOG"
case "$1 $2" in
  "api repos/"*) echo "$STUB_GH_LANE_REFUSAL" >&2; exit 1 ;;
  "variable list")
    echo "HTTP 403: Resource not accessible by integration" >&2; exit 1 ;;
esac
echo "stub gh: unexpected call: $*" >&2
exit 1
"""


def _stamp(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _tree(tmp_path: Path, body: str) -> Path:
    workflows = tmp_path / "tree" / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "ci.yml").write_text(body, encoding="utf-8")
    return tmp_path / "tree"


def _snapshot(
    tmp_path: Path,
    *,
    read_at: datetime | None = None,
    org: dict[str, str] | None = None,
    visibility: str = "private",
) -> Path:
    stamp = _stamp(read_at or datetime.now(UTC) - timedelta(hours=1))
    scopes: dict[str, object] = {f"repo:{SLUG}": {"variables": {}, "read_at": stamp}}
    if org is not None:
        scopes["org:OmniNode-ai"] = {"variables": org, "read_at": stamp}
    path = tmp_path / "runner-variables-snapshot.json"
    path.write_text(
        json.dumps(
            {
                "schema": 2,
                "captured_at": stamp,
                "visibility": {SLUG: {"value": visibility, "read_at": stamp}},
                "scopes": scopes,
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_hook(
    tmp_path: Path, tree: Path, snapshot: Path | None
) -> subprocess.CompletedProcess[str]:
    """The hook as pre-commit runs it, inside a lane, with a stub gh on PATH."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(STUB_GH, encoding="utf-8")
    gh.chmod(gh.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GITHUB_ACTIONS", "PRRP_VARIABLES_SNAPSHOT", "GITHUB_REPOSITORY"}
    }
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["STUB_GH_LOG"] = str(tmp_path / "gh-calls.log")
    env["STUB_GH_LANE_REFUSAL"] = LANE_REFUSAL
    env["GH_TOKEN"] = "stub-session-token"
    env["ONEX_LEDGER_PATH"] = ""
    if snapshot is not None:
        env["PRRP_VARIABLES_SNAPSHOT"] = str(snapshot)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tree), "--repo", SLUG],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=tmp_path,
    )


def _gh_calls(tmp_path: Path) -> str:
    log = tmp_path / "gh-calls.log"
    return log.read_text(encoding="utf-8") if log.exists() else ""


# --- AC1 ---------------------------------------------------------------------


def test_runner_placement_hook_without_org_variables_read(tmp_path: Path) -> None:
    """Visibility refused, org variables 403: a fresh snapshot answers both."""
    result = _run_hook(
        tmp_path,
        _tree(tmp_path, SEAM_JOB),
        _snapshot(tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET}),
    )
    assert result.returncode == 0, result.stderr
    assert "OK: every job in" in result.stdout
    assert f"visibility of {SLUG} is private, read from snapshot" in result.stderr
    assert "org:OmniNode-ai variables read from snapshot" in result.stderr
    calls = _gh_calls(tmp_path)
    assert f"api repos/{SLUG}" in calls, "the live read must be tried first"
    assert "variable list --org OmniNode-ai" in calls


# --- AC2 ---------------------------------------------------------------------


def test_runner_placement_hook_hosted_runner_still_refused(tmp_path: Path) -> None:
    """The snapshot path judges: a hosted organisation value fails the hook."""
    result = _run_hook(
        tmp_path,
        _tree(tmp_path, SEAM_JOB),
        _snapshot(tmp_path, org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": HOSTED}),
    )
    assert result.returncode == 1, result.stderr
    assert "ubuntu-latest" in result.stdout + result.stderr


def test_runner_placement_hook_hosted_runner_still_refused_as_a_literal(
    tmp_path: Path,
) -> None:
    """A literal hosted pin in a private repository, visibility from the snapshot."""
    result = _run_hook(
        tmp_path,
        _tree(tmp_path, HOSTED_LITERAL_JOB),
        _snapshot(tmp_path, org={}),
    )
    assert result.returncode == 1, result.stderr
    assert "ubuntu-latest" in result.stdout + result.stderr


# --- AC3 ---------------------------------------------------------------------


def _assert_names_remedy(output: str) -> None:
    assert "THE GATE DID NOT RUN" in output
    assert "--write-variables-snapshot" in output
    assert "PRRP_VARIABLES_SNAPSHOT" in output


def test_runner_placement_hook_refusal_names_remedy(tmp_path: Path) -> None:
    """No snapshot: the visibility refusal names the input and the remedy."""
    result = _run_hook(tmp_path, _tree(tmp_path, SEAM_JOB), None)
    assert result.returncode == 2
    assert f"Missing input: the visibility of {SLUG}" in result.stderr
    assert LANE_REFUSAL[:40] in result.stderr
    _assert_names_remedy(result.stderr)


def test_runner_placement_hook_refusal_names_remedy_for_a_variable(
    tmp_path: Path,
) -> None:
    """Visibility recorded, organisation scope not: the variable is named."""
    result = _run_hook(tmp_path, _tree(tmp_path, SEAM_JOB), _snapshot(tmp_path))
    assert result.returncode == 2
    assert "Missing input: OMNI_TRUSTED_CI_RUNS_ON_JSON" in result.stderr
    _assert_names_remedy(result.stderr)


def test_runner_placement_hook_refusal_names_remedy_on_a_stale_snapshot(
    tmp_path: Path,
) -> None:
    result = _run_hook(
        tmp_path,
        _tree(tmp_path, SEAM_JOB),
        _snapshot(
            tmp_path,
            read_at=datetime.now(UTC) - timedelta(hours=25),
            org={"OMNI_TRUSTED_CI_RUNS_ON_JSON": FLEET},
        ),
    )
    assert result.returncode == 2
    assert "stale" in result.stderr
    _assert_names_remedy(result.stderr)


# --- one file answers every repository a lane commits to ---------------------


def _module():
    if "placement_gate" in sys.modules:
        return sys.modules["placement_gate"]
    spec = importlib.util.spec_from_file_location("placement_gate", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["placement_gate"] = module
    spec.loader.exec_module(module)
    return module


def test_a_second_write_keeps_the_first_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()

    def live(args: list[str], env_name: str = "GH_TOKEN"):
        if args[0] == "api":
            return subprocess.CompletedProcess(args, 0, "private\n", "")
        body = [{"name": "OMNI_TRUSTED_CI_RUNS_ON_JSON", "value": FLEET}]
        return subprocess.CompletedProcess(
            args, 0, json.dumps(body if "--org" in args else []), ""
        )

    monkeypatch.setattr(module, "_gh", live)
    out = tmp_path / "snapshot.json"
    first = datetime(2026, 10, 22, 1, 0, 0, tzinfo=UTC)
    monkeypatch.setattr(module, "_utcnow", lambda: first)
    module.write_snapshot(SLUG, out)
    monkeypatch.setattr(module, "_utcnow", lambda: first + timedelta(hours=2))
    module.write_snapshot(OTHER, out)

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["visibility"] == {
        SLUG: {"value": "private", "read_at": "2026-10-22T01:00:00Z"},
        OTHER: {"value": "private", "read_at": "2026-10-22T03:00:00Z"},
    }
    assert written["scopes"][f"repo:{SLUG}"]["read_at"] == "2026-10-22T01:00:00Z"
    assert written["scopes"]["org:OmniNode-ai"]["read_at"] == "2026-10-22T03:00:00Z"

    # The kept entry is judged against its OWN read time, not the last write.
    late = module.VariablesSnapshot(
        out, timedelta(hours=24), now=lambda: first + timedelta(hours=25)
    )
    assert late.visibility(OTHER) == "private"
    with pytest.raises(module.GateError, match="stale for the visibility of"):
        late.visibility(SLUG)
