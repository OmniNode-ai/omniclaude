# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The runtime contract's runtime_paths section feeds the callers that held path literals (OMN-21728)."""

from __future__ import annotations

from pathlib import Path

import pytest

from omniclaude.hook_runtime.__main__ import _build_parser
from omniclaude.hooks.context_config import SessionStartInjectionConfig
from omniclaude.hooks.statusline_parser import read_limit_status
from omniclaude.models.model_runtime_paths import ModelRuntimePaths, runtime_paths
from omniclaude.services.linear_relay.dedup_adapter import DedupStore

pytestmark = pytest.mark.unit

_OVERLAY_ENV = {
    "OMNICLAUDE_HOOK_RUNTIME_SOCKET": "hook.sock",
    "OMNICLAUDE_HOOK_RUNTIME_PID": "hook.pid",
    "OMNICLAUDE_SESSION_INJECTION_MARKER_DIR": "markers",
    "OMNICLAUDE_USAGE_CACHE_PATH": "usage.json",
    "OMNICLAUDE_LINEAR_RELAY_DEDUP_DB": "dedup.db",
}


def _overlay(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    for name, leaf in _OVERLAY_ENV.items():
        monkeypatch.setenv(name, str(root / leaf))


def test_overlay_supplies_every_location(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _overlay(monkeypatch, tmp_path)
    paths = ModelRuntimePaths.from_contract()
    assert paths.hook_socket == str(tmp_path / "hook.sock")
    assert paths.hook_pid == str(tmp_path / "hook.pid")
    assert paths.session_marker_dir == str(tmp_path / "markers")
    assert paths.usage_cache == tmp_path / "usage.json"
    assert paths.linear_relay_dedup_db == tmp_path / "dedup.db"


def test_contract_default_expands_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OMNICLAUDE_STORE_READER_HOME", raising=False)
    paths = ModelRuntimePaths.from_contract()
    assert paths.store_reader_home == Path.home() / ".onex"
    assert "~" not in str(paths.opencode_db)


def test_registry_root_is_none_until_overlay_sets_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OMNI_HOME", raising=False)
    assert ModelRuntimePaths.from_contract().registry_root is None
    with pytest.raises(ValueError, match="OMNI_HOME is not set"):
        runtime_paths().require_registry_root()
    monkeypatch.setenv("OMNI_HOME", str(tmp_path))
    assert ModelRuntimePaths.from_contract().registry_root == tmp_path


def test_empty_required_location_fails_validation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract = tmp_path / "contract.yaml"
    contract.write_text("runtime_paths:\n  usage_cache: ''\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hook_socket"):
        ModelRuntimePaths.from_contract(contract)


def test_hook_runtime_parser_defaults_come_from_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _overlay(monkeypatch, tmp_path)
    args = _build_parser().parse_args(["start"])
    assert args.socket_path == str(tmp_path / "hook.sock")
    assert args.pid_path == str(tmp_path / "hook.pid")


def test_session_marker_dir_comes_from_overlay(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _overlay(monkeypatch, tmp_path)
    assert SessionStartInjectionConfig().marker_file_dir == str(tmp_path / "markers")
    assert SessionStartInjectionConfig.from_env().marker_file_dir == str(
        tmp_path / "markers"
    )


def test_dedup_store_defaults_to_overlay_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _overlay(monkeypatch, tmp_path)
    DedupStore()
    assert (tmp_path / "dedup.db").is_file()


def test_statusline_reads_overlay_usage_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _overlay(monkeypatch, tmp_path)
    (tmp_path / "usage.json").write_text(
        '{"five_hour": {"utilization": 42}, "seven_day": {"utilization": 7}}',
        encoding="utf-8",
    )
    status = read_limit_status(None)
    assert (status.session_percent, status.weekly_percent) == (42, 7)
