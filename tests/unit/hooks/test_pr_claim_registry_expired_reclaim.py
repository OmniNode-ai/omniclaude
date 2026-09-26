# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression tests for expired PR claim reaping (OMN-19695)."""

from __future__ import annotations

import importlib.util
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from plugins.onex.hooks.lib import pr_claim_registry

pytestmark = pytest.mark.unit

PR_KEY = "omninode-ai/omniclaude#19695"
RUN_A = "run-a"
RUN_B = "run-b"
LANE_A = "lane-a"
LANE_B = "lane-b"
_REPO_ROOT = Path(__file__).resolve().parents[3]
_CLI_PATH = _REPO_ROOT / "scripts" / "pr_claim_registry_cli.py"


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(pr_claim_registry, "CLAIMS_DIR", None)
    monkeypatch.setattr(pr_claim_registry, "INSTANCE_ID_PATH", None)


def _stamp(*, expired: bool) -> str:
    age = timedelta(days=3) if expired else timedelta(seconds=0)
    return (datetime.now(UTC) - age).strftime("%Y-%m-%dT%H:%M:%SZ")


def _claim_data(
    *,
    run_id: str,
    lane_id: str,
    expired: bool,
    action: str = "close",
) -> dict[str, str]:
    stamp = _stamp(expired=expired)
    return {
        "pr_key": PR_KEY,
        "claimed_by_run": run_id,
        "claimed_by_host": "test-host",
        "claimed_by_instance_id": "test-instance",
        "claimed_at": stamp,
        "last_heartbeat_at": stamp,
        "action": action,
        "lane_id": lane_id,
    }


def _write_claim(
    claims_dir: Path,
    *,
    run_id: str,
    lane_id: str,
    expired: bool,
) -> Path:
    claims_dir.mkdir(parents=True, exist_ok=True)
    claim_file = claims_dir / f"{pr_claim_registry.filesystem_key(PR_KEY)}.json"
    claim_file.write_text(
        json.dumps(
            _claim_data(run_id=run_id, lane_id=lane_id, expired=expired),
            indent=2,
        )
    )
    return claim_file


def _load_cli() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pr_claim_registry_cli_test", _CLI_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_expired_claim_is_reaped_and_replaced(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=True)
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)

    assert registry.acquire(PR_KEY, RUN_B, "merge", lane_id=LANE_B) is True

    replacement = json.loads(claim_file.read_text())
    assert replacement["claimed_by_run"] == RUN_B
    assert replacement["lane_id"] == LANE_B


def test_expired_malformed_claim_is_reaped(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_file = claims_dir / f"{pr_claim_registry.filesystem_key(PR_KEY)}.json"
    claim_file.write_text("{not valid JSON")
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)

    assert registry.acquire(PR_KEY, RUN_B, "merge", lane_id=LANE_B) is True
    assert json.loads(claim_file.read_text())["claimed_by_run"] == RUN_B


def test_expired_cli_claim_exits_zero(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    claims_dir = state_dir / "pr-queue" / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=True)
    cli = _load_cli()

    result = cli.main(
        ["claim", PR_KEY, "--lane", LANE_B, "--run-id", RUN_B, "--action", "merge"]
    )

    assert result == 0
    replacement = json.loads(claim_file.read_text())
    assert replacement["claimed_by_run"] == RUN_B
    assert replacement["lane_id"] == LANE_B


def test_same_run_live_reclaim_is_idempotent(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=False)
    before = claim_file.read_text()
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)

    assert registry.acquire(PR_KEY, RUN_A, "merge", lane_id=LANE_B) is True
    assert claim_file.read_text() == before
    assert json.loads(claim_file.read_text())["claimed_by_run"] == RUN_A


def test_same_run_expired_claim_is_reaped_and_refreshed(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=True)
    old_claim = json.loads(claim_file.read_text())
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)

    assert registry.acquire(PR_KEY, RUN_A, "merge", lane_id=LANE_A) is True

    refreshed = json.loads(claim_file.read_text())
    assert refreshed["claimed_by_run"] == RUN_A
    assert refreshed["claimed_at"] > old_claim["claimed_at"]
    assert refreshed["last_heartbeat_at"] > old_claim["last_heartbeat_at"]


def test_different_live_claim_is_refused_and_untouched(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=False)
    before = claim_file.read_text()
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)

    assert registry.acquire(PR_KEY, RUN_B, "merge", lane_id=LANE_B) is False
    assert claim_file.read_text() == before


def test_different_cli_refusal_names_live_holder(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    claims_dir = tmp_path / "state" / "pr-queue" / "claims"
    _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=False)
    cli = _load_cli()

    result = cli.main(["claim", PR_KEY, "--lane", LANE_B, "--run-id", RUN_B])

    captured = capsys.readouterr()
    assert result == 1
    assert LANE_A in captured.err
    assert "actively claimed" in captured.err


def test_different_cli_inactive_failure_is_not_described_as_active(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claims_dir = tmp_path / "state" / "pr-queue" / "claims"
    _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=True)
    monkeypatch.setattr(
        pr_claim_registry.ClaimRegistry, "acquire", lambda *args, **kwargs: False
    )
    cli = _load_cli()

    result = cli.main(["claim", PR_KEY, "--lane", LANE_B, "--run-id", RUN_B])

    captured = capsys.readouterr()
    assert result == 1
    assert "actively claimed" not in captured.err
    assert "could not write" in captured.err.lower()


def test_race_reap_does_not_delete_fresh_different_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    claims_dir = tmp_path / "claims"
    claim_file = _write_claim(claims_dir, run_id=RUN_A, lane_id=LANE_A, expired=True)
    registry = pr_claim_registry.ClaimRegistry(claims_dir=claims_dir)
    real_rename = os.rename
    injected = False

    def _replace_with_fresh_claim_before_rename(
        source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
    ) -> None:
        nonlocal injected
        if Path(source) == claim_file and not injected:
            injected = True
            claim_file.write_text(
                json.dumps(
                    _claim_data(run_id=RUN_B, lane_id=LANE_B, expired=False),
                    indent=2,
                )
            )
        real_rename(source, destination)

    monkeypatch.setattr(os, "rename", _replace_with_fresh_claim_before_rename)

    assert registry.acquire(PR_KEY, RUN_A, "merge", lane_id=LANE_A) is False
    assert injected is True
    winner = json.loads(claim_file.read_text())
    assert winner["claimed_by_run"] == RUN_B
    assert winner["lane_id"] == LANE_B
