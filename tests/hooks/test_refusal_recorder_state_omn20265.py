# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A refusal can be suppressed only after its ledger row has landed (OMN-20265)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.unit

RECORDER = (
    Path(__file__).resolve().parents[2]
    / "plugins/onex/hooks/lib/hook_refusal_recorder.py"
)
spec = importlib.util.spec_from_file_location("recorder_state_omn20265", RECORDER)
assert spec and spec.loader
recorder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recorder)

ARGS = ["--guard", "test-guard", "--reason", "test-refusal"]
NOW = 10_000.0


@pytest.fixture
def isolated_recorder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "registry"))
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ONEX_HOOK_REFUSAL_STATE_DIR", raising=False)
    monkeypatch.setattr(
        recorder, "resolve_lane_fields", lambda *a, **kw: ("lane", "env")
    )
    monkeypatch.setattr(recorder.time, "time", lambda: NOW)
    return (
        tmp_path
        / "state/hook_refusals"
        / (recorder.dedupe_key("test-guard", "test-refusal", "lane") + ".json")
    )


@pytest.mark.parametrize("prior", [None, {"last_emitted": 1000.0, "suppressed": 7}])
@pytest.mark.parametrize("failure", ["append", "registry"])
def test_recorder_state_not_committed_without_row(
    isolated_recorder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    prior: dict[str, object] | None,
    failure: str,
) -> None:
    state = isolated_recorder
    if prior is not None:
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps(prior))
    before = state.read_bytes() if state.exists() else None
    append = Mock(return_value=False)
    monkeypatch.setattr(recorder, "append_row", append)
    if failure == "registry":
        monkeypatch.delenv("OMNI_HOME")

    result = recorder.main(ARGS)

    assert (state.read_bytes() if state.exists() else None) == before
    assert result != 0
    assert capsys.readouterr().err.strip()
    assert append.call_count == (1 if failure == "append" else 0)


def test_recorder_failed_append_can_retry_immediately(
    isolated_recorder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = isolated_recorder
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"last_emitted": 1000.0, "suppressed": 7}))
    before = state.read_bytes()
    rows: list[str] = []

    def append(row: str, **kwargs: object) -> bool:
        assert state.read_bytes() == before
        rows.append(row)
        return len(rows) == 2

    monkeypatch.setattr(recorder, "append_row", append)
    assert recorder.main(ARGS) != 0
    assert recorder.main(ARGS) == 0
    assert len(rows) == 2
    assert all("suppressed_since_last_row=7" in row for row in rows)
    assert json.loads(state.read_text()) == {
        "last_emitted": NOW,
        "suppressed": 0,
        "attempts": 0,
    }
    assert recorder.main(ARGS) == 0
    assert len(rows) == 2
    assert json.loads(state.read_text()) == {
        "last_emitted": NOW,
        "suppressed": 1,
        "attempts": 0,
    }


def test_recorder_unset_state_dir_resolves_registry(
    isolated_recorder: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEX_STATE_DIR")
    append = Mock(return_value=True)
    monkeypatch.setattr(recorder, "append_row", append)

    assert recorder.main(ARGS) == 0

    expected = tmp_path / "registry/.onex_state/hook_refusals" / isolated_recorder.name
    assert expected.is_file()
    assert not (tmp_path / "home/.onex_state").exists()
    assert append.call_count == 1


def test_recorder_unset_state_dir_without_registry_refuses(
    isolated_recorder: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("ONEX_STATE_DIR")
    monkeypatch.delenv("OMNI_HOME")
    append = Mock(return_value=True)
    monkeypatch.setattr(recorder, "append_row", append)

    assert recorder.main(ARGS) != 0
    assert "OMNI_HOME" in capsys.readouterr().err
    assert not (tmp_path / "home/.onex_state").exists()
    append.assert_not_called()


def test_recorder_print_row_does_not_commit_state(
    isolated_recorder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    append = Mock(return_value=True)
    monkeypatch.setattr(recorder, "append_row", append)
    monkeypatch.delenv("OMNI_HOME")
    assert recorder.main([*ARGS, "--print-row"]) == 0
    assert "| FRICTION |" in capsys.readouterr().out
    assert not isolated_recorder.exists()
    append.assert_not_called()


def test_recorder_unresolved_registry_does_not_increment_suppression(
    isolated_recorder: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state = isolated_recorder
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"last_emitted": NOW, "suppressed": 3}))
    before = state.read_bytes()
    monkeypatch.delenv("OMNI_HOME")
    assert recorder.main(ARGS) != 0
    assert "OMNI_HOME" in capsys.readouterr().err
    assert state.read_bytes() == before


def test_recorder_cli_failed_append_is_loud_and_retryable(tmp_path: Path) -> None:
    """Exercise the actual recorder process and packaged-writer subprocess seam."""
    project = tmp_path / "writer-project"
    project.mkdir()
    (project / "pyproject.toml").write_text("")
    ledger = tmp_path / "fixture-ledger.md"
    ledger.write_text("fixture\n")
    fail = tmp_path / "fail"
    fail.touch()
    captured = tmp_path / "captured-row"
    stub = tmp_path / "uv"
    stub.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"if pathlib.Path({str(fail)!r}).exists():\n"
        "    sys.stderr.write('fixture writer failure\\n')\n"
        "    sys.exit(42)\n"
        f"pathlib.Path({str(captured)!r}).write_text(sys.argv[sys.argv.index('--append') + 1])\n"
    )
    stub.chmod(0o755)
    registry = tmp_path / "registry"
    env = {
        "HOME": str(tmp_path / "home"),
        "PATH": str(tmp_path),
        "OMNI_HOME": str(registry),
        "OMNIBASE_INTERNAL_HOME": str(project),
        "ONEX_LANE": "lane",
    }

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RECORDER), *ARGS, "--ledger", str(ledger)],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )

    failed = run()
    assert failed.returncode != 0
    assert "ledger writer exited 42: fixture writer failure" in failed.stderr
    assert "dedupe state unchanged" in failed.stderr
    assert not (registry / ".onex_state/hook_refusals").exists()
    log = registry / ".onex_state/hooks/logs/hooks.log"
    assert "| FRICTION | lane=lane |" in log.read_text()
    assert not (tmp_path / "home/.onex_state").exists()

    fail.unlink()
    succeeded = run()
    assert succeeded.returncode == 0, succeeded.stderr
    assert succeeded.stderr == ""
    assert "| FRICTION | lane=lane |" in captured.read_text()
    states = list((registry / ".onex_state/hook_refusals").glob("*.json"))
    assert len(states) == 1
    assert json.loads(states[0].read_text())["suppressed"] == 0
    assert log.read_text().count("refusal_count=1 |") == 2
    assert ledger.read_text() == "fixture\n"
    assert not (tmp_path / "home/.onex_state").exists()
