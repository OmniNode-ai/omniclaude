# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The registered guards leave dated, attributed refusals on one readable surface."""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.hooks._bash_guard_registration import is_live_on_bash_matcher
from tests.hooks.test_refusal_row_lane_omn19381 import Sandbox

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "plugins/onex/hooks"
GUARDS = (
    "pre_tool_use_worktree_guard.sh",
    "pre_tool_use_git_stash_guard.sh",
    "pre_tool_use_credential_rotation_guard.sh",
    "pre_tool_use_ticket_creation_gate.sh",
)


@pytest.fixture
def surface(tmp_path):
    box = Sandbox(tmp_path)
    box.home.joinpath(".onex_state").mkdir()
    plugin = tmp_path / "plugin"
    shutil.copytree(HOOKS, plugin / "hooks")
    # Interpreter provisioning is outside the contract; paths, registration,
    # wrappers, decision cores, attribution and the recorder remain real.
    (plugin / "hooks/scripts/common.sh").write_text(
        f"PYTHON_CMD={shlex.quote(sys.executable)}\nlog() {{ :; }}\n"
    )
    env = box.env(
        {
            "CLAUDE_PLUGIN_ROOT": str(plugin),
            "PLUGIN_PYTHON_BIN": sys.executable,
            "OMNICLAUDE_MODE": "full",
            "ONEX_LEDGER_PATH": str(box.ledger),
        }
    )
    return box, plugin, env


@pytest.mark.parametrize("attribution", ["env", "claim", "unresolved"])
@pytest.mark.parametrize("guard", GUARDS)
def test_real_registered_refusal_reaches_declared_surface(surface, guard, attribution):
    box, plugin, env = surface
    worktree = box.worktree("OMN-18983")
    worktree.joinpath(".git").write_text("gitdir: /unused/worktrees/test\n")
    cwd = box.home if attribution == "unresolved" else worktree
    if attribution == "env":
        env["ONEX_LANE"] = "refusal-surface-lane"
    elif attribution == "claim":
        box.ledger_rows(
            f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ} | CLAIM | "
            "lane=refusal-surface-lane | ticket=OMN-18983 | actor=codex | "
            "worktree=omni_worktrees/OMN-18983/omniclaude | live replay claim"
        )
    commands = {
        GUARDS[0]: "git worktree add /tmp/stray/refusal-test -b refusal-test",
        GUARDS[1]: "git stash pop",
        GUARDS[2]: "kubectl -n onex-dev delete secret operator-k8s",
    }
    if guard == GUARDS[3]:
        registered = json.loads(HOOKS.joinpath("hooks.json").read_text())["hooks"]
        assert any(
            h["command"].endswith("/" + guard)
            for group in registered["PreToolUse"]
            for h in group["hooks"]
        )
        entrypoint = guard
        payload = box.payload(tool_input={"title": "unbound test creation"})
        payload["tool_name"] = "mcp__linear-server__save_issue"
    else:
        assert is_live_on_bash_matcher(guard)
        entrypoint = "pre_tool_use_bash_guards.sh"
        # A canonical clone is guarded too, but names no worktree lane.
        if attribution == "unresolved" and guard == GUARDS[1]:
            cwd = box.home / "omniclaude"
            cwd.mkdir()
            cwd.joinpath(".git").mkdir()
        payload = box.payload(commands[guard])
    payload["cwd"] = str(cwd)
    before = datetime.now(UTC).replace(microsecond=0)
    proc = subprocess.run(
        ["bash", str(plugin / "hooks/scripts" / entrypoint)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert json.loads(proc.stdout)["decision"] == "block"
    log = box.home / ".onex_state/hooks/logs/hooks.log"
    deadline = time.monotonic() + 5
    lines = []
    while time.monotonic() < deadline:
        if log.exists():
            lines = [
                line
                for line in log.read_text().splitlines()
                if "class=refusal" in line and f"guard={guard} |" in line
            ]
        if lines:
            break
        time.sleep(0.02)
    assert len(lines) == 1, (
        log,
        log.read_text() if log.exists() else "absent",
        proc.stderr,
    )
    row = lines[0]
    timestamp = row.split(" | ", 1)[0]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp)
    assert before <= datetime.fromisoformat(timestamp) <= datetime.now(UTC)
    if attribution != "unresolved":
        assert "lane=refusal-surface-lane |" in row
        assert f"lane_source={attribution} |" in row
    else:
        assert "lane=unresolved |" in row
        assert "lane_source=unresolved |" in row
    assert "refusal_count=1 |" in row
    assert not box.home.joinpath(".onex_state/logs/hooks.log").exists()
    assert not box.tmp.joinpath(".onex_state/hooks/logs/hooks.log").exists()
    # The already-wired aggregate reader still sees the identical attribution.
    while time.monotonic() < deadline:
        ledger_rows = [
            line
            for line in box.ledger.read_text().splitlines()
            if f"guard={guard} |" in line
        ]
        if ledger_rows:
            break
        time.sleep(0.02)
    assert len(ledger_rows) == 1
    assert ledger_rows[0] == row


@pytest.mark.parametrize("root", ["", "relative-root"])
def test_missing_or_relative_registry_refuses_path_resolution(surface, root):
    box, plugin, env = surface
    env["OMNI_HOME"] = root
    proc = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"',
            "test",
            str(plugin / "hooks/scripts/onex-paths.sh"),
        ],
        text=True,
        capture_output=True,
        env=env,
        timeout=5,
        check=False,
    )
    assert proc.returncode != 0
    assert "OMNI_HOME" in proc.stderr
    assert not box.tmp.joinpath(".onex_state").exists()


def test_gate_is_enforced_by_precommit_and_required_ci():
    import yaml

    from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

    filename = "tests/hooks/test_refusal_surface_omn18983.py"
    config = yaml.safe_load(ROOT.joinpath(".pre-commit-config.yaml").read_text())
    hook = next(
        h
        for repo in config["repos"]
        for h in repo["hooks"]
        if h["id"] == "refusal-surface"
    )
    assert filename in hook["entry"]
    assert hook["always_run"] and not hook["pass_filenames"]
    workflow = yaml.safe_load(ROOT.joinpath(".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["refusal-surface"]
    assert "needs" not in job and "if" not in job
    assert any(filename in step.get("run", "") for step in job["steps"])
    assert job["name"] in GATE_JOBS
    assert job["name"] in STRICT_SUCCESS_JOBS


def test_dormant_surface_guard_is_explicitly_retired():
    script = "skip_token_surface_guard.sh"
    assert "RETIRED (OMN-18983)" in HOOKS.joinpath("scripts", script).read_text()
    assert script not in HOOKS.joinpath("hooks.json").read_text()
    assert (
        "Historical log disposition: abandoned"
        in ROOT.joinpath("docs/guards/refusal-surface.md").read_text()
    )


def test_unresolved_retries_are_counted_even_when_ledger_deduplicates(surface):
    box, plugin, env = surface
    command = [
        sys.executable,
        "-P",
        "-m",
        "omniclaude.nodes.node_hook_refusal_record_effect.handlers.handler_hook_refusal_record",
        "--hooks-lib",
        str(plugin / "hooks/lib"),
        "--guard",
        GUARDS[0],
        "--reason",
        "replayed refusal",
        "--cwd",
        str(box.home),
        "--payload-stdin",
        "--ledger",
        str(box.ledger),
    ]
    for _ in range(2):
        proc = subprocess.run(
            command,
            input=json.dumps(box.payload()),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
    rows = (
        box.home.joinpath(".onex_state/hooks/logs/hooks.log").read_text().splitlines()
    )
    assert len(rows) == 2
    assert all("lane_source=unresolved |" in row for row in rows)
    counts = [int(re.search(r"refusal_count=(\d+) \|", row).group(1)) for row in rows]
    assert sum(counts) == 2
    assert box.ledger.read_text().count("| FRICTION |") == 1
