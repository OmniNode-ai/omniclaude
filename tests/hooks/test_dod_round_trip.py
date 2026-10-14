# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Round-trip gate for the DoD writer/guard path alignment. [OMN-13323, OMN-20074]

Proves that the receipt the writer (``dod_evidence_runner.write_evidence_receipt``,
the ``/dod-verify`` writer) produces lands at the exact path the completion guard
(``pre_tool_use_dod_completion_guard.sh``) reads, so a passing ``/dod-verify``
actually unblocks Done.

OMN-20074: both sides use the repo-local ``<working_dir>/.evidence/<ticket>`` (the
receipt gate's caller mode). Neither reads ``onex_change_control``, ``OMNI_HOME``
or ``ONEX_EVIDENCE_ROOT``; the round trip runs with no ``onex_change_control`` on
disk.

These tests shell the real guard script and call the real writer. They do NOT
require Kafka, Postgres, or any external services (the writer emits nothing,
OMN-19153; the guard runs with ``KAFKA_BOOTSTRAP_SERVERS`` unset).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

HOOK_SCRIPT = str(
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_dod_completion_guard.sh"
)

# Import the writer from the skill lib (same pattern as tests/lib).
_RUNNER_DIR = REPO_ROOT / "plugins" / "onex" / "skills" / "_lib" / "dod-evidence-runner"
sys.path.insert(0, str(_RUNNER_DIR))

import dod_evidence_runner  # noqa: E402
from dod_evidence_runner import (  # noqa: E402
    EvidenceRunResult,
    resolve_evidence_output_dir,
    write_evidence_receipt,
)

_TICKET_ID = "OMN-13323"


def _run_guard(
    ticket_id: str,
    cwd: str,
    *,
    enforcement_mode: str = "hard",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the real completion guard from ``cwd`` (the writer's working dir).

    HOME is set to ``cwd`` so common.sh sources nothing from the developer's
    ``~/.omnibase/.env``.
    """
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": cwd,
        "ONEX_STATE_DIR": str(Path(cwd) / ".onex_state"),
        "OMNICLAUDE_MODE": "full",
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "DOD_ENFORCEMENT_MODE": enforcement_mode,
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", HOOK_SCRIPT],
        input=json.dumps(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": ticket_id, "state": "Done"},
            }
        ),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=10,
        check=False,
    )


def _guard_receipt_path(working_dir: str, ticket_id: str) -> Path:
    """The path the guard reads: <cwd>/.evidence/<ticket>/dod_report.json."""
    return Path(working_dir) / ".evidence" / ticket_id / "dod_report.json"


def _write_pass_receipt(working_dir: Path) -> Path:
    return write_evidence_receipt(
        ticket_id=_TICKET_ID,
        contract_path="contract.yaml",
        run_result=EvidenceRunResult(total=1, verified=1, failed=0, skipped=0),
        working_dir=str(working_dir),
        output_dir=None,  # exercise the resolver, the /dod-verify default
    )


class TestWriterGuardPathAlignment:
    """The writer's default resolved path equals the guard's read path."""

    def test_writer_default_path_equals_guard_read_path(self, tmp_path: Path) -> None:
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        writer_dir = resolve_evidence_output_dir(_TICKET_ID, str(working_dir))
        writer_receipt = (writer_dir / "dod_report.json").resolve()
        guard_receipt = _guard_receipt_path(str(working_dir), _TICKET_ID).resolve()

        assert writer_receipt == guard_receipt, (
            "Writer default receipt path must equal the guard's read path.\n"
            f"writer: {writer_receipt}\nguard : {guard_receipt}"
        )

    def test_writer_does_not_read_a_core_resolver_or_registry_root(self) -> None:
        assert not hasattr(dod_evidence_runner, "resolve_evidence_root")
        source = Path(dod_evidence_runner.__file__).read_text()
        assert "resolve_evidence_root" not in source
        assert "onex_change_control/evidence" not in source

    def test_ambient_env_does_not_steer_the_writer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(tmp_path / "legacy"))
        monkeypatch.setenv("OMNI_HOME", str(tmp_path / "registry"))
        resolved = resolve_evidence_output_dir(_TICKET_ID, str(tmp_path / "wd"))
        assert resolved == tmp_path / "wd" / ".evidence" / _TICKET_ID


class TestRoundTrip:
    """Writer writes -> guard reads at the same path, with no onex_change_control on disk."""

    def test_round_trip_writer_then_guard_allows(self, tmp_path: Path) -> None:
        """Writer writes a PASS receipt; the real guard reads it and allows Done."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()
        registry = tmp_path / "registry"
        registry.mkdir()
        env = {"OMNI_HOME": str(registry)}

        written = _write_pass_receipt(working_dir)

        assert (
            written.resolve()
            == _guard_receipt_path(str(working_dir), _TICKET_ID).resolve()
        )
        assert written.exists()

        result = _run_guard(_TICKET_ID, str(working_dir), extra_env=env)
        assert result.returncode == 0, (
            "Guard must allow Done after a fresh PASS receipt at the resolved path.\n"
            f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not (registry / "onex_change_control").exists()
        assert not any(registry.iterdir())

    def test_planted_missing_receipt_fails_closed(self, tmp_path: Path) -> None:
        """Plant-missing the receipt the writer produced -> guard fail-closed (exit 2)."""
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        written = _write_pass_receipt(working_dir)
        assert written.exists()

        written.unlink()
        assert not written.exists()

        result = _run_guard(_TICKET_ID, str(working_dir))
        assert result.returncode == 2, (
            "Guard must fail closed (exit 2) when the receipt is missing.\n"
            f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "No DoD evidence receipt found" in result.stderr, (
            "Guard must report the documented missing-receipt reason.\n"
            f"stderr: {result.stderr}"
        )

    def test_receipt_outside_working_dir_does_not_satisfy_guard(
        self, tmp_path: Path
    ) -> None:
        """A receipt written for another working dir is invisible to the guard."""
        writer_dir = tmp_path / "writer_wd"
        guard_dir = tmp_path / "guard_wd"
        writer_dir.mkdir()
        guard_dir.mkdir()

        _write_pass_receipt(writer_dir)

        result = _run_guard(_TICKET_ID, str(guard_dir))
        assert result.returncode == 2
