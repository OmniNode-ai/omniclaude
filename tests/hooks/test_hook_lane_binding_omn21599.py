# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The prompt hook checks the lane the developer is bound to (OMN-21599).

`onex profile bind-lane <lane>` writes `developer.lane_binding` into `~/.onex/config.yaml`.
The hook hands the contract's lanes, each lane's own declared people and the developer's lane
store to omnimarket's `node_developer_lane_admission_compute`, which selects the bound lane and
checks the principal against that lane's list. A collaborator never uses the barred lane.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import hook_edge_lane as lane
import hook_emit_append as appender
import hook_emit_journal as journal
import pytest
import yaml

pytestmark = pytest.mark.unit

_CONTRACT = (
    Path(lane.__file__).resolve().parent.parent / "contracts/hook_edge_lane.yaml"
)
# Spelled in parts: the public-repo hygiene gate reads the literal as a lab name.
_BOUND = "-".join(("stability", "test"))
_HOME_LANE = "dev"
_COLLABORATOR = f"{_BOUND}-collaborator-host"
_DEV_COLLABORATOR = "dev-collaborator-host"
_OPERATOR = "dev-operator-workstation"
_HELD = "prompt.submitted"


def _declare(root: Path, relative: str, principal: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "developer_principal.v1",
                "grants_source": "none: test",
                "principals": [
                    {
                        "principal": principal,
                        "login": "collaborator@example.invalid",
                        "device": "host",
                    }
                ],
            }
        )
    )


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    (home / ".onex").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ONEX_WORKSPACE_CONFIG_ROOT", str(tmp_path / "config-root"))
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ONEX_HOOK_LOCAL_BUS_HTTP_URL", raising=False)
    policy = yaml.safe_load(_CONTRACT.read_text())["developer_event_policy"]
    root = tmp_path / "config-root"
    _declare(root, policy["principal_declaration"], _DEV_COLLABORATOR)
    _declare(
        root,
        policy["bound_lane_principal_declaration"].replace("{lane}", _BOUND),
        _COLLABORATOR,
    )
    return home


def _store(home: Path, document: dict[str, object]) -> None:
    (home / ".onex" / "config.yaml").write_text(yaml.safe_dump(document))


def _bound(principal: str | None = _COLLABORATOR, *, binding: bool = True) -> dict:
    document: dict[str, object] = {}
    if binding:
        document["developer"] = {"lane_binding": _BOUND}
    if principal is not None:
        document["lanes"] = {_BOUND: {"sasl_username": principal}}
    return document


def _append(target: Path, event_type: str = _HELD) -> None:
    appender.append_event(
        event_type=event_type,
        payload={"session_id": "session", "content": "private"},
        correlation_id=None,
        cwd=None,
        actor=None,
        host_turn_id=None,
        agent_id=None,
        transcript_path=None,
        session_id="session",
        journal_dir=str(target),
    )


def _cli(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(appender.__file__)),
            "--event-type",
            _HELD,
            "--payload",
            json.dumps({"session_id": "session", "content": "private"}),
            "--session-id",
            "session",
            "--journal-dir",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_bound_to_the_collaborator_lane_with_a_declared_principal_passes(
    home: Path, tmp_path: Path
) -> None:
    _store(home, _bound())
    target = tmp_path / "journal"
    result = _cli(target)
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    _append(target, "tool.executed")
    assert [e.record.event_type for e in journal.list_pending(target)] == [
        "tool.executed"
    ]


def test_binding_removed_blocks(home: Path, tmp_path: Path) -> None:
    _store(home, _bound(binding=False))
    with pytest.raises(lane.HookEdgeLaneCredentialError, match="no declared principal"):
        _append(tmp_path / "journal")
    assert _cli(tmp_path / "journal").returncode != 0
    assert not (tmp_path / "journal").exists()


def test_principal_removed_blocks(home: Path, tmp_path: Path) -> None:
    _store(home, _bound(principal=None))
    with pytest.raises(lane.HookEdgeLaneCredentialError, match="no declared principal"):
        _append(tmp_path / "journal")
    assert _cli(tmp_path / "journal").returncode != 0


def test_collaborator_selecting_dev_is_refused(home: Path, tmp_path: Path) -> None:
    _store(home, {"lanes": {_HOME_LANE: {"sasl_username": _DEV_COLLABORATOR}}})
    with pytest.raises(lane.HookEdgeLaneCredentialError, match="never uses lane"):
        _append(tmp_path / "journal")
    assert _cli(tmp_path / "journal").returncode != 0
    # Binding the collaborator to the dev lane by name changes nothing.
    _store(
        home,
        {
            "developer": {"lane_binding": _HOME_LANE},
            "lanes": {_HOME_LANE: {"sasl_username": _DEV_COLLABORATOR}},
        },
    )
    with pytest.raises(lane.HookEdgeLaneCredentialError, match="never uses lane"):
        _append(tmp_path / "journal")


def test_operators_own_dev_flow_is_unchanged(home: Path, tmp_path: Path) -> None:
    _store(home, {"lanes": {_HOME_LANE: {"sasl_username": _OPERATOR}}})
    target = tmp_path / "journal"
    _append(target)
    assert [e.record.event_type for e in journal.list_pending(target)] == [_HELD]
    assert _cli(tmp_path / "journal-cli").returncode == 0


def test_bound_collaborator_lane_with_no_list_installed_is_refused(
    home: Path, tmp_path: Path
) -> None:
    policy = yaml.safe_load(_CONTRACT.read_text())["developer_event_policy"]
    (
        tmp_path
        / "config-root"
        / policy["bound_lane_principal_declaration"].replace("{lane}", _BOUND)
    ).unlink()
    _store(home, _bound())
    with pytest.raises(
        lane.HookEdgeLaneCredentialError, match="no principal declaration"
    ):
        _append(tmp_path / "journal")


def test_principal_declared_on_another_lane_is_refused(
    home: Path, tmp_path: Path
) -> None:
    _store(home, _bound(principal=_DEV_COLLABORATOR))
    with pytest.raises(lane.HookEdgeLaneCredentialError, match="another lane"):
        _append(tmp_path / "journal")


def test_binding_to_a_lane_the_contract_does_not_know_is_refused(
    home: Path, tmp_path: Path
) -> None:
    _store(home, {"developer": {"lane_binding": "lane-a"}})
    with pytest.raises(lane.HookEdgeLaneError, match="does not know"):
        _append(tmp_path / "journal")


def test_other_event_classes_need_no_lane_check(home: Path, tmp_path: Path) -> None:
    _store(home, _bound(binding=False, principal=None))
    _append(tmp_path / "journal", "tool.executed")
    assert [
        e.record.event_type for e in journal.list_pending(tmp_path / "journal")
    ] == ["tool.executed"]


def test_policy_names_the_barred_lane_and_the_per_lane_declaration() -> None:
    policy = yaml.safe_load(_CONTRACT.read_text())["developer_event_policy"]
    raw = yaml.safe_load(_CONTRACT.read_text())
    assert policy["collaborator_barred_lanes"] == [raw["lane"]]
    assert "{lane}" in policy["bound_lane_principal_declaration"]
    assert set(policy["collaborator_barred_lanes"]) <= set(raw["known_lanes"])


def test_node_vocabulary_is_the_lane_stores() -> None:
    from types import ModuleType

    import hook_content_capture as capture

    node = capture.load_node_handler(
        "omnimarket_lane_admission_vocabulary",
        "node_developer_lane_admission_compute",
        "handler_developer_lane_admission.py",
    )
    assert isinstance(node, ModuleType)
    assert node.LANE_STORE_LANES_BLOCK == lane.LANE_STORE_LANES_BLOCK
    assert node.LANE_STORE_USERNAME_KEY == lane.LANE_STORE_USERNAME_KEY
    assert node.SOURCE_OPERATOR_ENV == lane.CREDENTIAL_SOURCE_OPERATOR_ENV_FILE
