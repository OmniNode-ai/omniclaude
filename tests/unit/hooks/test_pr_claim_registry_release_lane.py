# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for lane-safe PR claim release (OMN-19696)."""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from plugins.onex.hooks.lib import pr_claim_registry

pytestmark = pytest.mark.unit

PR_KEY = "omninode-ai/omniclaude#19696"
RUN_A = "run-a"
RUN_B = "run-b"
LANE_A = "lane-a"
LANE_B = "lane-b"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI_PATH = _REPO_ROOT / "scripts" / "pr_claim_registry_cli.py"
_LANE_ENV_VARS = (
    "ONEX_LANE_ID",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
)
_MISSING = object()


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(pr_claim_registry, "CLAIMS_DIR", None)
    monkeypatch.setattr(pr_claim_registry, "INSTANCE_ID_PATH", None)


def _clear_lane_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _LANE_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _stamp(*, expired: bool) -> str:
    age = timedelta(days=3) if expired else timedelta(seconds=0)
    return (datetime.now(UTC) - age).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_claim(
    tmp_path: Path,
    *,
    run_id: str = RUN_A,
    lane_id: str | None | object = LANE_B,
    expired: bool = False,
) -> Path:
    claims_dir = tmp_path / "state" / "pr-queue" / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(expired=expired)
    claim_data: dict[str, object] = {
        "pr_key": PR_KEY,
        "claimed_by_run": run_id,
        "claimed_by_host": "test-host",
        "claimed_by_instance_id": "test-instance",
        "claimed_at": stamp,
        "last_heartbeat_at": stamp,
        "action": "close",
    }
    if lane_id is not _MISSING:
        claim_data["lane_id"] = lane_id
    claim_file = claims_dir / f"{pr_claim_registry.filesystem_key(PR_KEY)}.json"
    claim_file.write_text(json.dumps(claim_data, indent=2))
    return claim_file


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pr_claim_registry_release_cli_test", _CLI_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_different_lane_registry_refuses_and_preserves_bytes(tmp_path: Path) -> None:
    claim_file = _write_claim(tmp_path)
    before = claim_file.read_bytes()
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_A, lane_id=LANE_A) is False
    assert claim_file.read_bytes() == before


def test_different_lane_cli_refuses_and_preserves_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claim_file = _write_claim(tmp_path)
    before = claim_file.read_bytes()
    cli = _load_cli()

    result = cli.main(["release", PR_KEY, RUN_A, "--lane", LANE_A])

    captured = capsys.readouterr()
    assert result == 1
    assert LANE_B in captured.err
    assert claim_file.read_bytes() == before


def test_different_lane_cli_resolves_lane_from_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clear_lane_env(monkeypatch)
    monkeypatch.setenv("ONEX_LANE_ID", LANE_A)
    claim_file = _write_claim(tmp_path)
    before = claim_file.read_bytes()
    cli = _load_cli()

    result = cli.main(["release", PR_KEY, RUN_A])

    captured = capsys.readouterr()
    assert result == 1
    assert LANE_B in captured.err
    assert claim_file.read_bytes() == before


def test_own_registry_release_deletes_claim(tmp_path: Path) -> None:
    claim_file = _write_claim(tmp_path, lane_id=LANE_A)
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_A, lane_id=LANE_A) is True
    assert not claim_file.exists()


def test_own_cli_release_deletes_claim(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claim_file = _write_claim(tmp_path, lane_id=LANE_A)
    cli = _load_cli()

    result = cli.main(["release", PR_KEY, RUN_A, "--lane", LANE_A])

    captured = capsys.readouterr()
    assert result == 0
    assert "Released claim" in captured.out
    assert not claim_file.exists()


@pytest.mark.parametrize("lane_id", [_MISSING, None], ids=["absent", "null"])
def test_laneless_legacy_claim_releases_with_caller_lane(
    tmp_path: Path, lane_id: str | None | object
) -> None:
    claim_file = _write_claim(tmp_path, lane_id=lane_id)
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_A, lane_id=LANE_A) is True
    assert not claim_file.exists()


def test_laneless_caller_preserves_run_id_only_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_lane_env(monkeypatch)
    claim_file = _write_claim(tmp_path, lane_id=LANE_B)
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_A) is True
    assert not claim_file.exists()


def test_expired_peer_lane_claim_releases(tmp_path: Path) -> None:
    claim_file = _write_claim(tmp_path, lane_id=LANE_B, expired=True)
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_A, lane_id=LANE_A) is True
    assert not claim_file.exists()


def test_different_run_registry_refuses_and_preserves_bytes(tmp_path: Path) -> None:
    claim_file = _write_claim(tmp_path, run_id=RUN_A, lane_id=LANE_A)
    before = claim_file.read_bytes()
    registry = pr_claim_registry.ClaimRegistry()

    assert registry.release(PR_KEY, RUN_B, lane_id=LANE_A) is False
    assert claim_file.read_bytes() == before


def test_different_run_cli_exits_one_and_preserves_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claim_file = _write_claim(tmp_path, run_id=RUN_A, lane_id=LANE_A)
    before = claim_file.read_bytes()
    cli = _load_cli()

    result = cli.main(["release", PR_KEY, RUN_B, "--lane", LANE_A])

    captured = capsys.readouterr()
    assert result == 1
    assert RUN_A in captured.err
    assert claim_file.read_bytes() == before


def test_no_claim_cli_exits_zero(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _clear_lane_env(monkeypatch)
    cli = _load_cli()

    result = cli.main(["release", PR_KEY, RUN_A, "--lane", LANE_A])

    captured = capsys.readouterr()
    assert result == 0
    assert "No claim to release" in captured.out
