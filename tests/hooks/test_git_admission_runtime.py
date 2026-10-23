# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Lab proof of the contract-routed command and correlated terminal verdict."""

from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard
from omniclaude.nodes.node_git_effect.models.model_git_admission import (
    ModelGitAdmissionRequest,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("command", "blocked"),
    [("git reset --hard origin/main", True), ("git status", False)],
)
def test_contract_bus_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, blocked: bool
):
    registry = tmp_path / "registry"
    (registry / ".git").mkdir(parents=True)
    (registry / ".git/HEAD").write_text("ref: refs/heads/main\n")
    monkeypatch.setenv("OMNI_HOME", str(registry))
    request = ModelGitAdmissionRequest(
        raw_payload=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "cwd": str(registry),
            }
        )
    )
    state = tmp_path / "state"
    verdict = guard.dispatch(request, state)
    evidence = json.loads((state / "workflow_result.json").read_text())
    assert evidence["result"] == "completed"
    assert evidence["handler_locus"] == "in_process"
    assert evidence["wire_correlation_id"] == str(request.correlation_id)
    assert verdict.blocked is blocked
    assert evidence["terminal_payload"]["admission"] == verdict.model_dump(mode="json")
    assert evidence["handler_result"]["operation"] == "admission_check"


def test_hook_refuses_failed_dispatch(monkeypatch: pytest.MonkeyPatch, capsys):
    def failed(request: ModelGitAdmissionRequest, state_root: Path):
        raise RuntimeError("runtime unavailable")

    monkeypatch.setattr(guard, "dispatch", failed)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO('{"tool_input":{"command":"git reset"}}')
    )
    assert guard.main([]) == 2
    assert json.loads(capsys.readouterr().out)["decision"] == "block"


def test_batched_adapter_reuses_loaded_node_without_changing_verdict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from tests.hooks_system import bash_guard_corpus as corpus

    lib = corpus.REPO_ROOT / "plugins/onex/hooks/lib"
    monkeypatch.syspath_prepend(str(lib))
    import bash_guard_cores

    registry = tmp_path / "registry"
    (registry / ".git").mkdir(parents=True)
    payload = json.dumps(
        {"tool_input": {"command": "git reset --hard"}, "cwd": str(registry)}
    )
    request = bash_guard_cores.Request(
        stderr_mode="merge",
        cwd=str(tmp_path),
        stdin=payload,
        argv=(sys.executable, "-m", guard.__name__),
        env={**os.environ, "OMNI_HOME": str(registry)},
    )
    first = bash_guard_cores.run_core(request)
    second = bash_guard_cores.run_core(request)
    assert first == second
    assert first[0] == 2
    assert json.loads(first[1])["decision"] == "block"


def test_batched_adapter_reports_missing_core_before_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib")
    )
    import bash_guard_cores

    rc, output = bash_guard_cores.run_core(
        bash_guard_cores.Request(
            stderr_mode="merge",
            cwd=str(tmp_path),
            stdin="{}",
            argv=(sys.executable, "-m", "onex_no_such_core_module"),
            env=dict(os.environ),
        )
    )
    first, rest = output.split("\n", 1)
    assert rc == 1
    assert first.startswith(
        "guard core cannot be imported: ModuleNotFoundError: "
        "No module named 'onex_no_such_core_module'"
    )
    assert len(first) < 300
    assert f"(interpreter {sys.executable};" in first
    assert "PLUGIN_PYTHON_BIN/CLAUDE_PLUGIN_DATA/.venv/OMNI_HOME" in first
    assert rest.startswith("Traceback (most recent call last):\n")
    assert rest.rstrip().endswith(
        "ModuleNotFoundError: No module named 'onex_no_such_core_module'"
    )


@pytest.mark.parametrize(
    ("exception", "message", "summary"),
    [
        ("RuntimeError", "boom", "RuntimeError: boom"),
        ("ImportError", "boom", "ImportError: boom"),
        ("RuntimeError", "boom\n  more\t detail", "RuntimeError: boom more detail"),
    ],
)
def test_batched_adapter_reports_main_crash_before_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: str,
    message: str,
    summary: str,
):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib")
    )
    import bash_guard_cores

    name = f"onex_test_crashing_core_{uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(
        f"def main(argv):\n    raise {exception}({message!r})\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    rc, output = bash_guard_cores.run_core(
        bash_guard_cores.Request(
            stderr_mode="merge",
            cwd=str(tmp_path),
            stdin="{}",
            argv=(sys.executable, "-m", name),
            env=dict(os.environ),
        )
    )
    first, rest = output.split("\n", 1)
    assert rc == 1
    assert first == f"guard core crashed: {summary} (core {name})"
    assert rest.startswith("Traceback (most recent call last):\n")
    assert rest.rstrip().endswith(f"{exception}: {message}")
