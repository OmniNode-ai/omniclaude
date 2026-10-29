# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-20700 AC2-AC4: CI runs the onboarding on a fresh Mac, with no private repository.

omnibase_infra#4630 moved the runtime config owner into a private sibling
repository. The automated onboarding walk (OMN-20224) had
passed four days earlier and nothing re-ran it, so a human walker found the break.
``.github/workflows/onboarding-verify.yml`` re-runs the script from this tree on a
schedule and on pull requests that change it. These tests pin what makes that job
catch this class of regression:

- AC4: it is scheduled and PR-triggered, and runs the script from this checkout to
  the end on a macOS runner.
- AC2: the run has no private sibling checkout and no GitHub credential, the job fails
  on a runtime-config refusal, and the delegation reaches a model. The keyless stub
  model the job serves really answers an OpenAI-style completion.
- AC3: the onboarding guide tells its reader that CI holds the developer install's
  config owner to this.
"""

from __future__ import annotations

import http.client
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "onboarding-verify.yml"
STUB = Path(__file__).resolve().with_name("onboarding_stub_model_server.py")
GUIDE = REPO / "plugins" / "onex" / "ONBOARDING.md"
SCRIPT_REL = "plugins/onex/skills/_bin/lab-onboarding.sh"
HEADING = "### Where `onex` finds its runtime config"

pytestmark = pytest.mark.unit


def _workflow() -> dict:
    assert WORKFLOW.is_file(), f"{WORKFLOW.relative_to(REPO)} does not exist"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(wf: dict) -> dict:
    # PyYAML reads the bare key `on` as the boolean True.
    return wf.get("on", wf.get(True)) or {}


def _job(wf: dict) -> dict:
    return wf["jobs"]["fresh-mac"]


def _runs(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_ac4_job_is_scheduled_and_pr_triggered_on_the_script() -> None:
    on = _triggers(_workflow())
    assert on.get("schedule"), (
        "no schedule: a break from another repository would wait for a walker"
    )
    assert "workflow_dispatch" in on
    paths = on["pull_request"]["paths"]
    assert SCRIPT_REL in paths
    assert ".github/workflows/onboarding-verify.yml" in paths


def test_ac4_job_runs_the_script_from_this_tree_on_macos_to_the_end() -> None:
    job = _job(_workflow())
    assert str(job["runs-on"]).startswith("macos")
    runs = _runs(job)
    assert f"/bin/bash {SCRIPT_REL}" in runs, (
        "the job must run this checkout's script under stock bash"
    )
    assert "--preflight-only" not in runs
    assert "result=COMPLETE" in runs, (
        "the job must require the script's own completion line"
    )


def test_ac2_run_has_no_private_repository_and_no_credential() -> None:
    job = _job(_workflow())
    checkout = next(
        s
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    runs = _runs(job)
    assert "env -i HOME=" in runs, (
        "the script must run with an empty environment and a fresh HOME"
    )
    assert "gh auth status" in runs
    assert "-name '*_internal'" in runs, (
        "the job must assert no private sibling checkout exists"
    )


def test_ac2_job_fails_on_a_runtime_config_refusal_and_on_no_delegation() -> None:
    runs = _runs(_job(_workflow()))
    assert "ProtocolConfigurationError" in runs
    assert "Could not locate runtime config repository" in runs
    assert "--provider local" in runs
    assert "stub-completions.jsonl" in runs, (
        "the job must show a delegation reached the model"
    )


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _call(port: int, method: str, path: str, body: dict | None = None) -> dict:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        payload = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, payload, {"Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200, f"{method} {path} -> {resp.status}"
        return json.loads(resp.read())
    finally:
        conn.close()


def test_ac2_stub_model_answers_a_completion(tmp_path: Path) -> None:
    port, log = _free_port(), tmp_path / "completions.jsonl"
    proc = subprocess.Popen(
        [
            sys.executable,
            str(STUB),
            "--port",
            str(port),
            "--model",
            "m",
            "--log",
            str(log),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(50):
            try:
                _call(port, "GET", "/")
                break
            except OSError:
                time.sleep(0.1)
        models = _call(port, "GET", "/v1/models")
        assert [m["id"] for m in models["data"]] == ["m"]
        messages = [{"role": "user", "content": "say hello"}]
        body = _call(
            port, "POST", "/v1/chat/completions", {"model": "m", "messages": messages}
        )
        assert body["choices"][0]["message"]["content"] == "hello"
        assert len(log.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_ac3_guide_says_ci_holds_the_developer_install_to_its_config_owner() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    start = text.find(HEADING)
    assert start != -1
    end = text.find("\n## ", start)
    section = " ".join(text[start : end if end != -1 else None].split())
    assert "`Onboarding Verify`" in section
    assert "no private sibling checkout" in section
    assert "runtime-config refusal" in section
