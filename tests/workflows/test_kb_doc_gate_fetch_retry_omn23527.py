# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-23527: the kb-doc-gate validator fetch retries a rate limit and says so.

Measured 2026-11-10 10:50Z to 10:56Z: GitHub answered "API rate limit exceeded for
installation" to the validator fetch of six omnimarket pull requests. The gate step never
ran, and the check went red as if the documents were wrong. The fetch is now a step that
retries a rate-limit or 5xx answer with backoff a bounded number of times, writes the
reason to the job summary when it is still refused, fails at once on any other error,
and never exits 0 unless the validator was fetched.

These tests drive the step's own ``run:`` text under bash with a fake ``git`` first on
PATH, so a faked rate-limit answer, a faked server error, a refusal that is neither, and
a real gate violation are each exercised through the script the workflow runs.
"""

from __future__ import annotations

import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "kb-doc-gate-reusable.yml"
_REPOSITORY = "OmniNode-ai/omniclaude"
_GOOD_SHA = "ab" * 20

_FAKE_GIT = """#!/usr/bin/env bash
# Fake git: logs every call; `fetch` behaves by FAKE_GIT_FETCH_MODE.
echo "$*" >> "$FAKE_GIT_LOG"
args=("$@")
sub=""
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[$i]}" in
    fetch|rev-parse|checkout|init|remote|config) sub="${args[$i]}"; break ;;
  esac
done
case "$sub" in
  fetch)
    count_file="$FAKE_GIT_LOG.fetchcount"
    count=$(( $(cat "$count_file" 2>/dev/null || echo 0) + 1 ))
    echo "$count" > "$count_file"
    case "${FAKE_GIT_FETCH_MODE:-ok}" in
      ok) exit 0 ;;
      ratelimit)
        echo "remote: API rate limit exceeded for installation." >&2
        exit 128 ;;
      server)
        echo "fatal: unable to access 'https://github.com/x/': The requested URL returned error: 503" >&2
        exit 128 ;;
      notfound)
        echo "fatal: couldn't find remote ref deadbeef" >&2
        exit 128 ;;
      flaky)
        if [ "$count" -le 1 ]; then
          echo "remote: API rate limit exceeded for installation." >&2
          exit 128
        fi
        exit 0 ;;
    esac ;;
  rev-parse) echo "${FAKE_GIT_HEAD:-}" ;;
esac
exit 0
"""

_FAKE_UV = """#!/usr/bin/env bash
# Fake uv: `sync` succeeds; `run` (the guard command) exits FAKE_UV_RUN_EXIT.
echo "$*" >> "$FAKE_UV_LOG"
case "$1" in
  sync) exit 0 ;;
  run) exit "${FAKE_UV_RUN_EXIT:-0}" ;;
esac
exit 0
"""


def _load() -> dict[str, Any]:
    data = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _steps() -> list[dict[str, Any]]:
    return _load()["jobs"]["kb-doc-gate"]["steps"]


def _step(name: str) -> dict[str, Any]:
    (step,) = [s for s in _steps() if s.get("name") == name]
    return step


def _fetch_step() -> dict[str, Any]:
    return _step("Fetch kb-doc-gate validator (omniclaude canonical source)")


def _non_comment_text(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _install(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_step(
    tmp_path: Path,
    step: dict[str, Any],
    env: dict[str, str],
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    _install(bin_dir, "git", _FAKE_GIT)
    _install(bin_dir, "uv", _FAKE_UV)
    _install(bin_dir, "sleep", '#!/usr/bin/env bash\necho "$*" >> "$FAKE_SLEEP_LOG"\n')
    script = tmp_path / "step.sh"
    script.write_text(step["run"], encoding="utf-8")
    full_env = {
        "PATH": f"{bin_dir}:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "FAKE_GIT_LOG": str(tmp_path / "git.log"),
        "FAKE_UV_LOG": str(tmp_path / "uv.log"),
        "FAKE_SLEEP_LOG": str(tmp_path / "sleep.log"),
        "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md"),
        "GITHUB_OUTPUT": str(tmp_path / "output.txt"),
        "GITHUB_WORKSPACE": str(tmp_path),
        **env,
    }
    return subprocess.run(
        ["bash", str(script)],
        cwd=cwd or tmp_path,
        env=full_env,
        capture_output=True,
        text=True,
        check=False,
    )


def _fetch_env(tmp_path: Path, mode: str) -> dict[str, str]:
    return {
        "GH_TOKEN": "dummy",
        "GITHUB_SERVER_URL": "https://github.com",
        "VALIDATOR_REF": _GOOD_SHA,
        "VALIDATOR_REPOSITORY": _CORE_REPOSITORY,
        "VALIDATOR_DEST": str(tmp_path / "omnibase_core"),
        "FETCH_ATTEMPTS": "3",
        "FETCH_BACKOFF_SECONDS": "7",
        "FAKE_GIT_FETCH_MODE": mode,
        "FAKE_GIT_HEAD": _GOOD_SHA,
    }


def _fetch_calls(tmp_path: Path) -> int:
    count_file = tmp_path / "git.log.fetchcount"
    return int(count_file.read_text()) if count_file.exists() else 0


def _summary(tmp_path: Path) -> str:
    path = tmp_path / "summary.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _fetch_env(tmp_path: Path, mode: str) -> dict[str, str]:
    return {
        "GH_TOKEN": "dummy",
        "GITHUB_SERVER_URL": "https://github.com",
        "VALIDATOR_REF": _GOOD_SHA,
        "VALIDATOR_REPOSITORY": _REPOSITORY,
        "VALIDATOR_DEST": str(tmp_path / ".omniclaude-kb-doc-gate"),
        "VALIDATOR_SPARSE_PATH": "scripts/kb_doc_gate.py",
        "FETCH_ATTEMPTS": "3",
        "FETCH_BACKOFF_SECONDS": "7",
        "FAKE_GIT_FETCH_MODE": mode,
        "FAKE_GIT_HEAD": _GOOD_SHA,
    }


def _fetch_calls(tmp_path: Path) -> int:
    count_file = tmp_path / "git.log.fetchcount"
    return int(count_file.read_text()) if count_file.exists() else 0


def _summary(tmp_path: Path) -> str:
    path = tmp_path / "summary.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_fetch_succeeds_first_time_with_one_fetch(tmp_path: Path) -> None:
    result = _run_step(tmp_path, _fetch_step(), _fetch_env(tmp_path, "ok"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _fetch_calls(tmp_path) == 1
    assert _summary(tmp_path) == ""


def test_fetch_rate_limit_is_retried_then_fails_and_says_so(tmp_path: Path) -> None:
    result = _run_step(tmp_path, _fetch_step(), _fetch_env(tmp_path, "ratelimit"))
    assert result.returncode == 1
    assert _fetch_calls(tmp_path) == 3
    assert (tmp_path / "sleep.log").read_text().split() == ["7", "14"]
    summary = _summary(tmp_path)
    assert "rate limit" in summary
    assert "did not run" in summary
    assert "NOT a finding" in summary


def test_fetch_server_error_is_retried_then_fails_and_says_so(tmp_path: Path) -> None:
    result = _run_step(tmp_path, _fetch_step(), _fetch_env(tmp_path, "server"))
    assert result.returncode == 1
    assert _fetch_calls(tmp_path) == 3
    assert "did not run" in _summary(tmp_path)


def test_fetch_that_recovers_passes_after_a_retry(tmp_path: Path) -> None:
    result = _run_step(tmp_path, _fetch_step(), _fetch_env(tmp_path, "flaky"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert _fetch_calls(tmp_path) == 2


def test_fetch_failure_that_is_not_a_rate_limit_fails_at_once(tmp_path: Path) -> None:
    result = _run_step(tmp_path, _fetch_step(), _fetch_env(tmp_path, "notfound"))
    assert result.returncode == 1
    assert _fetch_calls(tmp_path) == 1
    assert not (tmp_path / "sleep.log").exists()
    assert "rate limit" not in _summary(tmp_path)
    assert "THE GATE DID NOT RUN" in result.stdout


def _gate_env(tmp_path: Path, script: Path) -> dict[str, str]:
    return {
        "MODE": "diff",
        "BASE_REF": "dev",
        "RUNNER_TEMP": str(tmp_path),
        "SCRIPT_PATH": str(script),
    }


def test_gate_step_fails_when_the_validator_reports_a_violation(tmp_path: Path) -> None:
    script = tmp_path / "kb_doc_gate.py"
    script.write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    result = _run_step(tmp_path, _step("Run kb-doc-gate"), _gate_env(tmp_path, script))
    assert result.returncode == 1


def test_gate_step_passes_when_the_validator_is_clean(tmp_path: Path) -> None:
    script = tmp_path / "kb_doc_gate.py"
    script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    result = _run_step(tmp_path, _step("Run kb-doc-gate"), _gate_env(tmp_path, script))
    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_step_fails_when_the_validator_was_never_fetched(tmp_path: Path) -> None:
    result = _run_step(
        tmp_path,
        _step("Run kb-doc-gate"),
        _gate_env(tmp_path, tmp_path / "absent.py"),
    )
    assert result.returncode == 1
    assert "THE GATE DID NOT RUN" in result.stdout


def test_no_step_may_soften_a_failure() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "continue-on-error" not in text
    assert not re.search(r"\|\|\s*true", _non_comment_text(text))


def test_fetch_runs_after_the_pin_and_before_the_checkout_assertion() -> None:
    names = [s.get("name", "") for s in _steps()]
    pin = names.index("Resolve the gate pin")
    fetch = names.index("Fetch kb-doc-gate validator (omniclaude canonical source)")
    assert pin < fetch < names.index("Assert the kb-doc-gate checkout is at the pin")
    assert _fetch_step()["env"]["VALIDATOR_REF"] == "${{ steps.pin.outputs.sha }}"
