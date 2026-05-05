# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Tests for DoD completion guard PreToolUse hook.

Validates that the hook correctly blocks/allows Linear status updates
based on evidence receipt presence, freshness, and check results.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

HOOK_SCRIPT = str(
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_dod_completion_guard.sh"
)

DOD_ENFORCEMENT_YAML = str(
    Path(__file__).resolve().parents[2]
    / "plugins"
    / "onex"
    / "hooks"
    / "config"
    / "dod_enforcement.yaml"
)


def _run_hook(
    tool_input: dict[str, object],
    env_overrides: dict[str, str] | None = None,
    cwd: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run the completion guard hook with the given tool input.

    HOME defaults to the test ``cwd`` so common.sh sources nothing from the
    real user's ``~/.omnibase/.env`` — the ambient ``ONEX_EVIDENCE_ROOT``
    there would otherwise override the per-test fixture. Tests that need to
    exercise the env-var policy itself should pass an explicit ``HOME``.
    """
    isolated_home = cwd if cwd is not None else str(Path.home())
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": isolated_home,
        "ONEX_STATE_DIR": str(Path(cwd) / ".onex_state")
        if cwd
        else str(Path.home() / ".onex-state"),
        "OMNICLAUDE_MODE": "full",
    }
    if env_overrides:
        env.update(env_overrides)

    return subprocess.run(
        ["bash", HOOK_SCRIPT],
        input=json.dumps(tool_input),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=10,
        check=False,
    )


class TestAllowsNonCompletionUpdates:
    """Non-completion status updates should always be allowed."""

    def test_allows_non_completion_status_updates(self) -> None:
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "In Progress"},
            }
        )
        assert result.returncode == 0

    def test_allows_non_linear_tool_calls(self) -> None:
        result = _run_hook(
            {
                "tool_name": "Bash",
                "tool_input": {"command": "echo hello"},
            }
        )
        assert result.returncode == 0


class TestEvidenceRootEnvVar:
    """ONEX_EVIDENCE_ROOT env var policy: fail-open when unset, fail-closed when misconfigured."""

    def test_fail_open_when_evidence_root_unset(self, tmp_path: Path) -> None:
        # Use isolated HOME so common.sh can't source ~/.omnibase/.env
        isolated_home = tmp_path / "home"
        isolated_home.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "HOME": str(isolated_home),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert "INACTIVE" in result.stderr or "not set" in result.stderr

    def test_fail_closed_when_evidence_root_not_absolute(self, tmp_path: Path) -> None:
        isolated_home = tmp_path / "home"
        isolated_home.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "HOME": str(isolated_home),
                "ONEX_EVIDENCE_ROOT": "relative/path",
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "not an absolute path" in result.stderr

    def test_fail_closed_when_evidence_root_nonexistent(self, tmp_path: Path) -> None:
        isolated_home = tmp_path / "home"
        isolated_home.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "HOME": str(isolated_home),
                "ONEX_EVIDENCE_ROOT": str(tmp_path / "nonexistent"),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "does not exist" in result.stderr


class TestBlocksDoneWithoutReceipt:
    """Completion without evidence should be handled per policy mode."""

    def test_blocks_done_without_evidence_receipt_hard_mode(
        self, tmp_path: Path
    ) -> None:
        evidence_root = tmp_path / ".evidence"
        evidence_root.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2

    def test_allows_done_without_receipt_advisory_mode(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        evidence_root.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-9999", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "advisory",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 0


def _write_receipt(evidence_root: Path, ticket_id: str, receipt: dict) -> Path:
    """Write a receipt JSON file under <evidence_root>/<ticket_id>/dod_report.json."""
    evidence_dir = evidence_root / ticket_id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = evidence_dir / "dod_report.json"
    receipt_path.write_text(json.dumps(receipt))
    return receipt_path


def _model_dod_receipt(
    ticket_id: str,
    *,
    status: str = "PASS",
    age: timedelta | None = None,
) -> dict:
    """Produce a ModelDodReceipt-shaped receipt dict (OMN-9792 schema)."""
    run_ts = datetime.now(tz=UTC) - (age or timedelta())
    return {
        "schema_version": "1.0.0",
        "ticket_id": ticket_id,
        "evidence_item_id": "dod-run",
        "check_type": "command",
        "check_value": "contracts/test.yaml",
        "status": status,
        "run_timestamp": run_ts.isoformat(),
        "commit_sha": "0000000",
        "runner": "test-runner",
        "verifier": "test-verifier",
        "probe_command": "echo test",
        "probe_stdout": "test",
    }


class TestAllowsDoneWithValidReceipt:
    """Completion with valid, fresh, status=PASS ModelDodReceipt should be allowed."""

    def test_allows_done_with_valid_pass_receipt(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root, "OMN-1234", _model_dod_receipt("OMN-1234", status="PASS")
        )

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 0


class TestBlocksDoneWithStaleReceipt:
    """Stale ModelDodReceipt receipts should trigger policy enforcement."""

    def test_blocks_done_with_stale_receipt_hard_mode(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root,
            "OMN-1234",
            _model_dod_receipt("OMN-1234", status="PASS", age=timedelta(hours=1)),
        )

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "stale" in result.stderr.lower()


class TestBlocksDoneWithFailedChecks:
    """Receipt with status=FAIL should block (OMN-10540)."""

    def test_blocks_done_with_status_fail(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root, "OMN-1234", _model_dod_receipt("OMN-1234", status="FAIL")
        )

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "FAIL" in result.stderr


class TestBlocksLegacyReceiptSchema:
    """Pre-OMN-9792 receipts must be rejected outright (OMN-10540)."""

    def test_blocks_legacy_timestamp_result_schema(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        # Pre-migration shape: top-level 'timestamp' + 'result.failed'.
        legacy_receipt = {
            "ticket_id": "OMN-1234",
            "timestamp": datetime.now(tz=UTC).isoformat(),
            "result": {"total": 2, "verified": 2, "failed": 0, "skipped": 0},
        }
        _write_receipt(evidence_root, "OMN-1234", legacy_receipt)

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "legacy" in result.stderr.lower() or "OMN-9792" in result.stderr


class TestBlocksFailClosed:
    """OMN-10541: any non-PASS or unparseable receipt must block."""

    def test_blocks_status_advisory(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root,
            "OMN-1234",
            _model_dod_receipt("OMN-1234", status="ADVISORY"),
        )
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "ADVISORY" in result.stderr

    def test_blocks_status_pending(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root,
            "OMN-1234",
            _model_dod_receipt("OMN-1234", status="PENDING"),
        )
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "PENDING" in result.stderr

    def test_blocks_status_unknown(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        _write_receipt(
            evidence_root,
            "OMN-1234",
            _model_dod_receipt("OMN-1234", status="skipped"),
        )
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2

    def test_blocks_missing_status(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        receipt = _model_dod_receipt("OMN-1234", status="PASS")
        del receipt["status"]
        _write_receipt(evidence_root, "OMN-1234", receipt)

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2
        assert "status" in result.stderr.lower()

    def test_blocks_missing_run_timestamp(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        receipt = _model_dod_receipt("OMN-1234", status="PASS")
        del receipt["run_timestamp"]
        _write_receipt(evidence_root, "OMN-1234", receipt)

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2

    def test_blocks_unparseable_receipt(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        evidence_dir = evidence_root / "OMN-1234"
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "dod_report.json").write_text("{ not json")

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2

    def test_blocks_run_timestamp_naive(self, tmp_path: Path) -> None:
        """Naive (tz-unaware) run_timestamp must block — ModelDodReceipt requires UTC."""
        evidence_root = tmp_path / ".evidence"
        receipt = _model_dod_receipt("OMN-1234", status="PASS")
        receipt["run_timestamp"] = datetime.now().isoformat()  # noqa: DTZ005 — intentional
        _write_receipt(evidence_root, "OMN-1234", receipt)

        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-1234", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "hard",
                "OMNICLAUDE_MODE": "full",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 2


class TestAllowsDoneWhenNoContractExists:
    """Legacy tickets without contracts should be allowed through."""

    def test_allows_done_when_no_contract_exists(self, tmp_path: Path) -> None:
        evidence_root = tmp_path / ".evidence"
        evidence_root.mkdir()
        result = _run_hook(
            {
                "tool_name": "mcp__linear-server__save_issue",
                "tool_input": {"id": "OMN-LEGACY", "state": "Done"},
            },
            env_overrides={
                "DOD_ENFORCEMENT_MODE": "advisory",
                "ONEX_EVIDENCE_ROOT": str(evidence_root),
            },
            cwd=str(tmp_path),
        )
        assert result.returncode == 0


class TestHardModeInvariant:
    """Lock the hard-mode default so drift requires intentional test update."""

    def test_dod_enforcement_yaml_mode_is_hard(self) -> None:
        import yaml

        with open(DOD_ENFORCEMENT_YAML) as f:
            config = yaml.safe_load(f)
        assert config["mode"] == "hard", (
            f"dod_enforcement.yaml global mode must be 'hard', got '{config['mode']}'"
        )

    def test_shell_script_default_is_hard(self) -> None:
        script = Path(HOOK_SCRIPT).read_text()
        assert 'POLICY_MODE="${DOD_ENFORCEMENT_MODE:-hard}"' in script, (
            "pre_tool_use_dod_completion_guard.sh must default to hard mode"
        )
