# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Mac CI preserves executable package/boundary checks during the CLI migration.

The companion builds and resolves its wheel and runs stock-Bash dispatch failure
controls. It does not claim a model delegation: the combined installed-package
journey is verified by the primary CLI. The existing keyless model server control
is retained for consumers that use that fixture.
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
    # The required summary must receive this context even for unrelated changes.
    assert "paths" not in on["pull_request"]
    assert "paths-ignore" not in on["pull_request"]
    from scripts.ci.ci_summary_gate import EXPECTED_EXTERNAL_CONTEXTS

    assert _job(_workflow())["name"] in EXPECTED_EXTERNAL_CONTEXTS


def test_ac4_job_runs_the_script_from_this_tree_on_macos_to_the_end() -> None:
    job = _job(_workflow())
    assert str(job["runs-on"]).startswith("macos")
    runs = _runs(job)
    assert "test_thin_onboarding_bootstrap.py" in runs
    assert "test_customer_plugin_wheel.py" in runs
    assert "--no-cov" in runs
    assert "--basetemp" in runs


def test_ac2_run_has_no_private_repository_and_no_credential() -> None:
    job = _job(_workflow())
    checkout = next(
        s
        for s in job["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    runs = _runs(job)
    assert "test_thin_onboarding_bootstrap.py" in runs
    assert "git clone" not in runs
    assert "secrets." not in runs


def test_ac2_job_fails_on_a_runtime_config_refusal_and_on_no_delegation() -> None:
    runs = _runs(_job(_workflow()))
    assert "test_customer_asset_resolution.py" in runs
    assert "test_install_gateway_dispatch.py" in runs
    assert "|| true" not in runs
    # This repository proves its bundle and shell boundary. Cross-package
    # inference is the primary CLI's actual installed-wheel E2E suite.
    assert "fixture" not in str(_job(_workflow())["name"]).lower()


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
    assert "`Onboarding Verify`" in text
    assert "installed-wheel" in text
    assert "does not prove inference" in text
