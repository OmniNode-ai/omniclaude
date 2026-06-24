# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Round-trip gate for the DoD writer/guard path alignment. [OMN-13323]

Enforcement Map F7 — verified plan UWP-17. Proves that the receipt the writer
(``dod_evidence_runner.write_evidence_receipt``, the ``/dod-verify`` writer)
produces lands at the exact absolute path the completion guard
(``pre_tool_use_dod_completion_guard.sh``) reads — both resolved from the same
``ONEX_EVIDENCE_ROOT`` — so a passing ``/dod-verify`` actually unblocks Done.

Honesty caveat (from the ticket): an ACTIVE mismatch was reproduced before this
test was written. With ``ONEX_EVIDENCE_ROOT`` set to anything other than
``<working_dir>/.evidence``, the pre-fix writer defaulted ``output_dir`` to
``<working_dir>/.evidence/<ticket>`` and ignored ``ONEX_EVIDENCE_ROOT``
entirely, so the guard (which reads
``$ONEX_EVIDENCE_ROOT/<ticket>/dod_report.json``) never found the receipt and
blocked Done with "No DoD evidence receipt found". The fix routes the writer's
default through ``resolve_evidence_output_dir``, which mirrors the canonical
``node_dod_verify`` precedence (``ONEX_EVIDENCE_ROOT`` first).

These tests shell the real guard script and call the real writer. They do NOT
require Kafka, Postgres, or any external services (writer is called with
``emit=False``; the guard runs with ``KAFKA_BOOTSTRAP_SERVERS`` unset).
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

from dod_evidence_runner import (  # noqa: E402
    EvidenceRunResult,
    resolve_evidence_output_dir,
    write_evidence_receipt,
)

_TICKET_ID = "OMN-13323"


def _run_guard(
    ticket_id: str,
    evidence_root: str,
    cwd: str,
    *,
    enforcement_mode: str = "hard",
) -> subprocess.CompletedProcess[str]:
    """Run the real completion guard with ONEX_EVIDENCE_ROOT pinned.

    HOME is set to ``cwd`` so common.sh sources nothing from the developer's
    ``~/.omnibase/.env`` — its ambient ONEX_EVIDENCE_ROOT would otherwise
    override the per-test fixture path.
    """
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": cwd,
        "ONEX_STATE_DIR": str(Path(cwd) / ".onex_state"),
        "OMNICLAUDE_MODE": "full",
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "DOD_ENFORCEMENT_MODE": enforcement_mode,
        "ONEX_EVIDENCE_ROOT": evidence_root,
    }
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


def _guard_receipt_path(evidence_root: str, ticket_id: str) -> Path:
    """The absolute path the guard reads: $ONEX_EVIDENCE_ROOT/<ticket>/dod_report.json.

    Mirrors RECEIPT_PATH construction in pre_tool_use_dod_completion_guard.sh
    (EVIDENCE_DIR="$ONEX_EVIDENCE_ROOT/$TICKET_ID").
    """
    return Path(evidence_root) / ticket_id / "dod_report.json"


class TestWriterGuardPathAlignment:
    """The writer's default resolved path equals the guard's read path."""

    def test_writer_default_path_equals_guard_read_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Core DoD: writer resolved path == guard resolved ONEX_EVIDENCE_ROOT path.

        Both are the same absolute path when ONEX_EVIDENCE_ROOT is set.
        """
        evidence_root = tmp_path / "evidence_root"
        evidence_root.mkdir()
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(evidence_root))

        writer_dir = resolve_evidence_output_dir(_TICKET_ID, str(working_dir))
        writer_receipt = (writer_dir / "dod_report.json").resolve()
        guard_receipt = _guard_receipt_path(str(evidence_root), _TICKET_ID).resolve()

        assert writer_receipt == guard_receipt, (
            "Writer default receipt path must equal the guard's read path.\n"
            f"writer: {writer_receipt}\nguard : {guard_receipt}"
        )

    def test_writer_default_diverges_from_legacy_evidence_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression lock: with ONEX_EVIDENCE_ROOT set, the writer must NOT use
        the legacy ``<working_dir>/.evidence`` location (the reproduced mismatch).
        """
        evidence_root = tmp_path / "evidence_root"
        evidence_root.mkdir()
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(evidence_root))

        writer_dir = resolve_evidence_output_dir(_TICKET_ID, str(working_dir))
        legacy_dir = working_dir / ".evidence" / _TICKET_ID

        assert writer_dir.resolve() != legacy_dir.resolve()
        assert writer_dir.resolve() == (evidence_root / _TICKET_ID).resolve()


class TestRoundTrip:
    """Writer writes -> guard reads at the same resolved path."""

    def test_round_trip_writer_then_guard_allows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Writer writes a PASS receipt; the real guard reads it and allows Done."""
        evidence_root = tmp_path / "evidence_root"
        evidence_root.mkdir()
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(evidence_root))

        run_result = EvidenceRunResult(total=1, verified=1, failed=0, skipped=0)
        written = write_evidence_receipt(
            ticket_id=_TICKET_ID,
            contract_path="contract.yaml",
            run_result=run_result,
            working_dir=str(working_dir),
            output_dir=None,  # exercise the resolver — the /dod-verify default
            emit=False,
        )

        # Writer landed the receipt exactly where the guard looks.
        assert (
            written.resolve()
            == _guard_receipt_path(str(evidence_root), _TICKET_ID).resolve()
        )
        assert written.exists()

        result = _run_guard(_TICKET_ID, str(evidence_root), str(working_dir))
        assert result.returncode == 0, (
            "Guard must allow Done after a fresh PASS receipt at the resolved path.\n"
            f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_planted_missing_receipt_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Plant-missing the receipt the writer produced -> guard fail-closed (exit 2).

        Deleting the receipt at the resolved path must make the guard block Done
        with the documented missing-receipt reason.
        """
        evidence_root = tmp_path / "evidence_root"
        evidence_root.mkdir()
        working_dir = tmp_path / "worktree"
        working_dir.mkdir()

        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(evidence_root))

        run_result = EvidenceRunResult(total=1, verified=1, failed=0, skipped=0)
        written = write_evidence_receipt(
            ticket_id=_TICKET_ID,
            contract_path="contract.yaml",
            run_result=run_result,
            working_dir=str(working_dir),
            output_dir=None,
            emit=False,
        )
        assert written.exists()

        # Plant-missing: remove the receipt at the resolved (guard-read) path.
        written.unlink()
        assert not written.exists()

        result = _run_guard(_TICKET_ID, str(evidence_root), str(working_dir))
        assert result.returncode == 2, (
            "Guard must fail closed (exit 2) when the receipt is missing.\n"
            f"exit={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "No DoD evidence receipt found" in result.stderr, (
            "Guard must report the documented missing-receipt reason.\n"
            f"stderr: {result.stderr}"
        )


class TestResolveEvidenceOutputDir:
    """Unit coverage for the shared path resolver (writer side of F7)."""

    def test_uses_evidence_root_when_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", str(tmp_path / "root"))
        resolved = resolve_evidence_output_dir(_TICKET_ID, str(tmp_path / "wd"))
        assert resolved == tmp_path / "root" / _TICKET_ID

    def test_falls_back_to_working_dir_evidence_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ONEX_EVIDENCE_ROOT", raising=False)
        resolved = resolve_evidence_output_dir(_TICKET_ID, str(tmp_path / "wd"))
        assert resolved == tmp_path / "wd" / ".evidence" / _TICKET_ID

    def test_blank_evidence_root_treated_as_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ONEX_EVIDENCE_ROOT", "   ")
        resolved = resolve_evidence_output_dir(_TICKET_ID, str(tmp_path / "wd"))
        assert resolved == tmp_path / "wd" / ".evidence" / _TICKET_ID
