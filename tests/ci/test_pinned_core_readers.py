# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run CI's core readers against the pin that broke PR #3121 (OMN-22177)."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
SHA = "9294542b9762de81fec93bbfae2e8db94f4bbbc7"
TAG = "dev-20261103230113-9294542b9762"
LOCK = f"""[[package]]
name = "omnibase-core"
version = "0.47.66"
source = {{ git = "https://github.com/OmniNode-ai/omnibase_core.git?tag={TAG}#{SHA}" }}
"""


def _steps(workflow: str) -> list[dict]:
    jobs = yaml.safe_load((ROOT / ".github/workflows" / workflow).read_text())["jobs"]
    return [step for job in jobs.values() for step in job.get("steps", [])]


def _run(tmp_path: Path, script: str, lock: str = LOCK) -> subprocess.CompletedProcess:
    work = tmp_path / "work"
    work.mkdir()
    (work / "uv.lock").write_text(lock)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Record Git's argv; no network or sibling checkout is involved in this test.
    git = bin_dir / "git"
    git.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "with open(os.environ['GIT_CALLS'], 'a') as out:\n"
        "    out.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    git.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text("#!/bin/sh\nprintf '0.47.66\\n'\n")
    uv.chmod(0o755)
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        cwd=work,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GITHUB_OUTPUT": str(tmp_path / "output"),
            "GITHUB_ENV": str(tmp_path / "env"),
            "RUNNER_TEMP": str(tmp_path),
            "GIT_CALLS": str(tmp_path / "git-calls"),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def _readers() -> list[tuple[str, dict]]:
    return [
        (workflow, step)
        for workflow in ("ci.yml", "receipt-honesty.yml", "hostile-reviewer.yml")
        for step in _steps(workflow)
        if (step.get("id") == "core_pin" and "omnibase-core" in step.get("name", ""))
        or step.get("name", "")
        in (
            "Provide the sibling clones the cross-repo hooks resolve through OMNI_HOME",
            "Clone omnibase_core (provides the receipt-honesty validator)",
            "Clone omnibase_core",
        )
    ]


@pytest.mark.parametrize(("workflow", "step"), _readers())
def test_dev_pin_reads_its_resolved_commit(
    tmp_path: Path, workflow: str, step: dict
) -> None:
    script = step["run"].split("# omnimarket node tree", 1)[0]
    result = _run(tmp_path, script)
    assert result.returncode == 0, (workflow, result.stdout, result.stderr)
    if step.get("id") == "core_pin":
        assert (tmp_path / "output").read_text().strip() == f"rev={SHA}"
        checkouts = [
            s
            for s in _steps(workflow)
            if s.get("with", {}).get("ref")
            in (
                "${{ steps.core_pin.outputs.rev }}",
                "${{ steps.core_pin.outputs.tag }}",
            )
        ]
        assert checkouts
        assert all(
            s["with"]["ref"] == "${{ steps.core_pin.outputs.rev }}" for s in checkouts
        )
    else:
        calls = [
            json.loads(line)
            for line in (tmp_path / "git-calls").read_text().splitlines()
        ]
        fetches = [args for args in calls if "fetch" in args]
        assert len(fetches) == 1, calls
        assert fetches[0][-1] == SHA, calls
        assert any("checkout" in args and args[-1] == "FETCH_HEAD" for args in calls), (
            calls
        )
        assert "v0.47.66" not in json.dumps(calls)


def _index_readers() -> list[tuple[str, dict]]:
    return [
        (workflow, step)
        for workflow in ("ci.yml", "contract-validation.yml")
        for step in _steps(workflow)
        if '--with "$core_src"' in step.get("run", "")
    ]


def _resolve_part(step: dict) -> str:
    lines = step["run"].splitlines()
    first = next(
        i for i, line in enumerate(lines) if line.strip().startswith("core_ref=")
    )
    last = next(i for i, line in enumerate(lines) if "uv run" in line)
    return "\n".join(lines[first:last])


def test_index_readers_are_found() -> None:
    assert {w for w, _ in _index_readers()} == {"ci.yml", "contract-validation.yml"}


@pytest.mark.parametrize(("workflow", "step"), _index_readers())
def test_index_reader_installs_the_locked_commit(
    tmp_path: Path, workflow: str, step: dict
) -> None:
    # The dev pin's version (0.47.66) is not on the package index, so the reader
    # must install the locked commit, never ``omnibase-core==<version>``.
    result = _run(tmp_path, _resolve_part(step))
    assert result.returncode == 0, (workflow, result.stdout, result.stderr)
    calls = [
        json.loads(line) for line in (tmp_path / "git-calls").read_text().splitlines()
    ]
    fetches = [args for args in calls if "fetch" in args]
    assert len(fetches) == 1, calls
    assert fetches[0][-1] == SHA, calls
    assert any("checkout" in args and args[-1] == "FETCH_HEAD" for args in calls), calls
    assert "omnibase-core==" not in step["run"]
    assert '--with "$core_src"' in step["run"]


@pytest.mark.parametrize(("workflow", "step"), _index_readers())
def test_index_reader_refuses_a_lock_with_no_git_pin(
    tmp_path: Path, workflow: str, step: dict
) -> None:
    result = _run(
        tmp_path,
        _resolve_part(step),
        '[[package]]\nname = "omnibase-core"\nversion = "0.47.66"\nsource = { registry = "https://pypi.org/simple" }\n',
    )
    assert result.returncode != 0, (workflow, result.stdout, result.stderr)


@pytest.mark.parametrize(("workflow", "step"), _readers())
def test_missing_git_pin_refuses_before_checkout(
    tmp_path: Path, workflow: str, step: dict
) -> None:
    script = step["run"].split("# omnimarket node tree", 1)[0]
    result = _run(
        tmp_path,
        script,
        '[[package]]\nname = "omnibase-core"\nversion = "0.47.66"\nsource = { registry = "https://pypi.org/simple" }\n',
    )
    if step["name"].startswith("Provide the sibling clones"):
        assert result.returncode == 0, (result.stdout, result.stderr)
        calls = (tmp_path / "git-calls").read_text()
        assert '"v0.47.66"' in calls
    else:
        assert result.returncode != 0, (workflow, result.stdout, result.stderr)
        assert not (tmp_path / "git-calls").exists()


@pytest.mark.parametrize("honest", [True, False])
def test_receipt_honesty_workflow_executes_validator(
    tmp_path: Path, honest: bool
) -> None:
    step = next(
        s
        for s in _steps("receipt-honesty.yml")
        if s.get("name") == "Run receipt-honesty validator"
    )
    argv = shlex.split(step["run"].strip().splitlines()[-1])
    assert argv[-1] == "$files"
    command = "uv run pytest tests/ -v" if honest else "echo all-good"
    receipt = tmp_path / "receipt.yaml"
    receipt.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0.0",
                "ticket_id": "OMN-22177",
                "evidence_item_id": "dod-unit-tests",
                "check_type": "command",
                "check_value": command,
                "status": "PASS",
                "run_timestamp": "2026-11-04T05:06:02+00:00",
                "commit_sha": SHA,
                "runner": "codex-worker",
                "verifier": "receipt-verifier",
                "probe_command": command,
                "probe_stdout": "42 passed in 1.23s",
                "exit_code": 0,
            }
        )
    )
    result = subprocess.run(
        [sys.executable, *argv[1:-1], str(receipt)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == (0 if honest else 1), (result.stdout, result.stderr)
    assert ("GATE PASSED" if honest else "NO_OP_PROBE") in result.stdout
