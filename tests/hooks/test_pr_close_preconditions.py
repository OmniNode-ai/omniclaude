# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19160: consume the close template before the registered ownership hook."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "plugins/onex/docs/pr-close-preconditions.md"
CLI = ROOT / "scripts/pr_claim_registry_cli.py"
GUARD = [
    sys.executable,
    "-m",
    "omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_cli",
]
HOOK = ROOT / "plugins/onex/hooks/scripts/pre_tool_use_bash_guards.sh"
KEY = "omninode-ai/omniclaude#19160"
COMMAND = "gh pr close 19160 --repo OmniNode-ai/omniclaude"


@pytest.fixture
def caller(tmp_path: Path) -> dict[str, str]:
    # Every write, including the refusal recorder, stays in the fixture.
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ONEX_", "CLAUDE_", "GIT_"))
    }
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "omniclaude").symlink_to(ROOT, target_is_directory=True)
    env.update(
        OMNI_HOME=str(registry),
        ONEX_STATE_DIR=str(tmp_path / "state"),
        ONEX_LANE_ID="fixture-owner",
        ONEX_RUN_ID="fixture-run",
        CLAUDE_CODE_SESSION_ID="fixture-session",
        CLAUDE_PROJECT_DIR=str(ROOT),
        CLAUDE_PLUGIN_ROOT=str(ROOT / "plugins/onex"),
        ONEX_HOOK_LOG=str(tmp_path / "hooks.log"),
        HOME=str(tmp_path),
        pr_repo="OmniNode-ai/omniclaude",
        pr_number="19160",
        close_comment="Fixture close reason",
    )
    return env


def run_hook(caller: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": COMMAND}}),
        env=caller,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )


def test_unclaimed_close_refuses_once_with_missing_claim_then_exact_remedy(caller):
    result = run_hook(caller)
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    lines = payload["reason"].splitlines()
    assert lines[0].startswith("Missing PR claim:")
    assert KEY in lines[0]
    assert "INDETERMINATE" not in lines[0]
    assert "pr_claim_registry_cli.py" in lines[1]
    assert "--action close" in lines[1]
    assert KEY in lines[1]
    # One refusal, with no automatic attribution record written by the guard.
    assert payload["reason"].count("Missing PR claim:") == 1
    assert not list(Path(caller["ONEX_STATE_DIR"]).glob("pr-queue/claims/*.json"))
    remedy = subprocess.run(
        ["bash", "-c", lines[1].strip()],
        env=caller,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert remedy.returncode == 0, remedy.stderr
    assert run_hook(caller).returncode == 0


def test_committed_close_template_claims_before_first_guarded_attempt(caller):
    skill = ROOT / "plugins/onex/skills/dep_cascade_dedup/SKILL.md"
    assert "../../docs/pr-close-preconditions.md" in skill.read_text()
    template = GUIDE.read_text().split("```bash\n", 1)[1].split("```", 1)[0]
    before_close, close = template.split("gh pr close", 1)
    assert " list" in before_close
    assert " claim " in before_close and "--action close" in before_close
    assert "--lane" not in before_close
    result = subprocess.run(
        ["bash", "-c", before_close],
        env=caller,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    # Render the final command without executing a GitHub mutation.
    rendered = subprocess.run(
        ["bash", "-c", "printf '%s\\n' gh pr close" + close],
        env=caller,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert rendered.returncode == 0, rendered.stderr
    command = shlex.join(rendered.stdout.splitlines())
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
        env=caller,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == ""  # The registered entrypoint stays silent on allow.
    claim = json.loads(
        next(Path(caller["ONEX_STATE_DIR"]).glob("pr-queue/claims/*.json")).read_text()
    )
    assert claim["lane_id"] == "fixture-owner"
    assert claim["claimed_by_run"] == "fixture-run"
    peer = run_hook({**caller, "ONEX_LANE_ID": "fixture-peer"})
    assert peer.returncode == 2
    assert "fixture-owner" in json.loads(peer.stdout)["reason"]


@pytest.mark.parametrize(
    ("invalid", "reason"),
    [
        ("expired", "Missing PR claim:"),
        ("malformed", "exists but is unreadable or malformed"),
        ("identity", "this lane has no resolvable identity"),
    ],
)
def test_invalid_close_fixture_refuses_once_with_documented_reason(
    caller, invalid, reason
):
    assert reason in GUIDE.read_text()
    if invalid == "identity":
        caller.pop("ONEX_LANE_ID")
        caller.pop("CLAUDE_CODE_SESSION_ID")
    else:
        claimed = subprocess.run(
            [sys.executable, str(CLI), "claim", KEY, "--action", "close"],
            env=caller,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert claimed.returncode == 0, claimed.stderr
        path = next(Path(caller["ONEX_STATE_DIR"]).glob("pr-queue/claims/*.json"))
        if invalid == "malformed":
            path.write_text("{not json")
        else:
            claim = json.loads(path.read_text())
            claim["claimed_at"] = claim["last_heartbeat_at"] = "2000-01-01T00:00:00Z"
            path.write_text(json.dumps(claim))
    result = run_hook(caller)
    assert result.returncode == 2, result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert payload["reason"].count(reason) == 1


@pytest.mark.parametrize("reader", [[sys.executable, str(CLI)], GUARD])
def test_help_exposes_claim_before_close(reader, caller):
    result = subprocess.run(
        [*reader, "--help"],
        env=caller,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "claim <owner/repo>#<number> --action close" in result.stdout
    assert "before gh pr close" in result.stdout
    assert "plugins/onex/docs/pr-close-preconditions.md" in result.stdout


def test_message_contract_is_pinned_in_precommit_and_live_ci():
    config = (ROOT / ".pre-commit-config.yaml").read_text()
    hook = config.split("- id: pr-close-preconditions", 1)[1].split("- id:", 1)[0]
    assert "tests/hooks/test_pr_close_preconditions.py" in hook
    assert "stages: [pre-commit]" in hook
    assert "pass_filenames: false" in hook
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "uv run pytest tests/hooks/" in workflow
