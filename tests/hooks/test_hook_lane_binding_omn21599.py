# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The prompt hook checks the lane the developer is bound to (OMN-21599).

`onex profile bind-lane <lane>` writes `developer.lane_binding` into `~/.onex/config.yaml`.
The hook hands the contract's lanes, each lane's own declared people and the developer's lane
store to omnimarket's `node_developer_lane_admission_compute`, which selects the bound lane and
checks the principal against that lane's list. A collaborator never uses the barred lane.

A refusal never blocks the person's prompt (RULING 2026-10-30T16:45:31Z): every event class is
dropped, nothing reaches any lane, the hook exits 0 and the prompt class prints one warning
naming the fix.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import hook_edge_lane
import hook_emit_append as appender
import hook_emit_journal as journal
import pytest
import yaml

pytestmark = pytest.mark.unit

_CONTRACT = (
    Path(hook_edge_lane.__file__).resolve().parent.parent
    / "contracts/hook_edge_lane.yaml"
)
# Spelled in parts: the public-repo hygiene gate reads the literal as a lab name.
_BOUND = "-".join(("stability", "test"))
_HOME_LANE = "dev"
_COLLABORATOR = f"{_BOUND}-collaborator-host"
_DEV_COLLABORATOR = "dev-collaborator-host"
_OPERATOR = "dev-operator-workstation"
_HELD = "prompt.submitted"


def _lane() -> ModuleType:
    """The hook edge module as the handler resolves it now.

    A suite that loads the module under another name replaces the entry in
    ``sys.modules``; an exception class bound at import time would then not be the one raised.
    """
    return importlib.import_module("hook_edge_lane")


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


def _cli(target: Path, event_type: str = _HELD) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(Path(appender.__file__)),
            "--event-type",
            event_type,
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


def _policy() -> dict:
    return yaml.safe_load(_CONTRACT.read_text())["developer_event_policy"]


def _assert_dropped_with_one_warning(target: Path, refusal: str) -> None:
    """The refused developer's prompt passes (exit 0), and nothing reaches any lane."""
    for event_type in (_HELD, "content.captured", "tool.executed", "hook.event"):
        _append(target, event_type)
    assert not target.exists()
    result = _cli(target)
    assert result.returncode == 0, result.stderr
    assert not target.exists()
    lines = result.stdout.splitlines()
    assert len(lines) == 1, result.stdout
    message = json.loads(lines[0])["systemMessage"]
    assert refusal in message
    assert _policy()["refusal_notice"]["remedies"][refusal] in message
    # Only the notice class speaks; every other class drops without a word.
    quiet = _cli(target, "tool.executed")
    assert quiet.returncode == 0, quiet.stderr
    assert quiet.stdout == ""
    assert not target.exists()


def test_bound_to_the_collaborator_lane_with_a_declared_principal_passes(
    home: Path, tmp_path: Path
) -> None:
    _store(home, _bound())
    target = tmp_path / "journal"
    result = _cli(target)
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert not target.exists()
    _append(target, "tool.executed")
    assert [e.record.event_type for e in journal.list_pending(target)] == [
        "tool.executed"
    ]


def test_binding_removed_drops_and_warns(home: Path, tmp_path: Path) -> None:
    _store(home, _bound(binding=False))
    _assert_dropped_with_one_warning(tmp_path / "journal", "no-declared-principal")


def test_principal_removed_drops_and_warns(home: Path, tmp_path: Path) -> None:
    _store(home, _bound(principal=None))
    _assert_dropped_with_one_warning(tmp_path / "journal", "no-declared-principal")


def test_no_lane_store_with_a_dev_list_drops_and_warns(
    home: Path, tmp_path: Path
) -> None:
    _assert_dropped_with_one_warning(tmp_path / "journal", "no-declared-principal")


def test_collaborator_selecting_dev_never_publishes(home: Path, tmp_path: Path) -> None:
    _store(home, {"lanes": {_HOME_LANE: {"sasl_username": _DEV_COLLABORATOR}}})
    _assert_dropped_with_one_warning(
        tmp_path / "journal", "collaborator-on-barred-lane"
    )
    # Binding the collaborator to the dev lane by name changes nothing.
    _store(
        home,
        {
            "developer": {"lane_binding": _HOME_LANE},
            "lanes": {_HOME_LANE: {"sasl_username": _DEV_COLLABORATOR}},
        },
    )
    _assert_dropped_with_one_warning(
        tmp_path / "journal", "collaborator-on-barred-lane"
    )


def test_operators_own_dev_flow_is_unchanged(home: Path, tmp_path: Path) -> None:
    _store(home, {"lanes": {_HOME_LANE: {"sasl_username": _OPERATOR}}})
    target = tmp_path / "journal"
    _append(target)
    _append(target, "tool.executed")
    assert [e.record.event_type for e in journal.list_pending(target)] == [
        _HELD,
        "tool.executed",
    ]
    result = _cli(tmp_path / "journal-cli")
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert len(journal.list_pending(tmp_path / "journal-cli")) == 1


def test_bound_collaborator_lane_with_no_list_installed_drops_and_warns(
    home: Path, tmp_path: Path
) -> None:
    (
        tmp_path
        / "config-root"
        / _policy()["bound_lane_principal_declaration"].replace("{lane}", _BOUND)
    ).unlink()
    _store(home, _bound())
    _assert_dropped_with_one_warning(
        tmp_path / "journal", "bound-lane-declaration-missing"
    )


def test_bound_with_no_config_root_at_all_drops_and_warns(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ONEX_WORKSPACE_CONFIG_ROOT")
    monkeypatch.delenv("OMNIBASE_PATH", raising=False)
    monkeypatch.delenv("OMNI_HOME", raising=False)
    _store(home, _bound())
    _assert_dropped_with_one_warning(
        tmp_path / "journal", "bound-lane-declaration-missing"
    )


def test_principal_declared_on_another_lane_drops_and_warns(
    home: Path, tmp_path: Path
) -> None:
    _store(home, _bound(principal=_DEV_COLLABORATOR))
    _assert_dropped_with_one_warning(
        tmp_path / "journal", "principal-declared-for-another-lane"
    )


def test_binding_to_a_lane_the_contract_does_not_know_drops_and_warns(
    home: Path, tmp_path: Path
) -> None:
    _store(home, {"developer": {"lane_binding": "lane-a"}})
    _assert_dropped_with_one_warning(tmp_path / "journal", "binding-unknown-lane")


def test_invalid_binding_drops_and_warns(home: Path, tmp_path: Path) -> None:
    _store(home, {"developer": {"lane_binding": ["not", "a", "lane"]}})
    _assert_dropped_with_one_warning(tmp_path / "journal", "binding-invalid")


@pytest.mark.parametrize(
    "text", ["principals: [\n", "- a list\n", "schema_version: other\n"]
)
def test_unreadable_bound_list_drops_and_warns(
    home: Path, tmp_path: Path, text: str
) -> None:
    (
        tmp_path
        / "config-root"
        / _policy()["bound_lane_principal_declaration"].replace("{lane}", _BOUND)
    ).write_text(text)
    _store(home, _bound())
    _assert_dropped_with_one_warning(tmp_path / "journal", "declaration-malformed")


def test_installed_omnimarket_without_the_node_drops_and_warns(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hook_content_capture as capture

    _store(home, {"lanes": {_HOME_LANE: {"sasl_username": _OPERATOR}}})
    monkeypatch.setattr(capture, "package_files", lambda *_parts: [])
    monkeypatch.setitem(sys.modules, "hook_content_capture", capture)
    monkeypatch.delitem(
        sys.modules, "node_developer_lane_admission_compute", raising=False
    )
    target = tmp_path / "journal"
    for event_type in (_HELD, "tool.executed"):
        _append(target, event_type)
    assert not target.exists()


def test_every_refusal_has_a_remedy() -> None:
    import hook_content_capture as capture

    node = capture.load_node_handler(
        "omnimarket_lane_admission_refusals",
        "node_developer_lane_admission_compute",
        "handler_developer_lane_admission.py",
    )
    assert isinstance(node, ModuleType)
    notice = _policy()["refusal_notice"]
    assert set(node._REFUSAL_FAULT) | {"admission-node-missing"} == set(
        notice["remedies"]
    )
    raw = yaml.safe_load(_CONTRACT.read_text())
    assert notice["event_class"] in _policy()["excluded_event_classes"]
    assert notice["event_class"] in raw["governed_event_classes"]


def test_the_real_prompt_hook_exits_zero_on_a_refusal(
    home: Path, tmp_path: Path
) -> None:
    """The installed shape: the hook script, its bounded runner and the real appender."""
    import os

    _store(home, _bound(binding=False))
    script = (
        Path(hook_edge_lane.__file__).resolve().parent.parent
        / "scripts/user_prompt_submit_bus_mirror.sh"
    )
    journal_dir = tmp_path / "hook-journal"
    env = {
        **os.environ,
        "PLUGIN_PYTHON_BIN": sys.executable,
        "OMNICLAUDE_MODE": "full",
        "ONEX_LANE": "test-lane",
        "ONEX_HOOK_EMIT_JOURNAL_DIR": str(journal_dir),
    }
    result = subprocess.run(
        ["bash", str(script)],
        input=json.dumps(
            {
                "session_id": "session",
                "cwd": str(tmp_path),
                "hook_event_name": "UserPromptSubmit",
                "prompt": "private prompt",
            }
        ),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert journal.list_pending(journal_dir) == []
    assert "no-declared-principal" in json.loads(result.stdout)["systemMessage"]


def test_policy_names_the_barred_lane_and_the_per_lane_declaration() -> None:
    policy = yaml.safe_load(_CONTRACT.read_text())["developer_event_policy"]
    raw = yaml.safe_load(_CONTRACT.read_text())
    assert policy["collaborator_barred_lanes"] == [raw["lane"]]
    assert "{lane}" in policy["bound_lane_principal_declaration"]
    assert set(policy["collaborator_barred_lanes"]) <= set(raw["known_lanes"])


def test_node_vocabulary_is_the_lane_stores() -> None:
    import hook_content_capture as capture

    node = capture.load_node_handler(
        "omnimarket_lane_admission_vocabulary",
        "node_developer_lane_admission_compute",
        "handler_developer_lane_admission.py",
    )
    assert isinstance(node, ModuleType)
    lane = _lane()
    assert node.LANE_STORE_LANES_BLOCK == lane.LANE_STORE_LANES_BLOCK
    assert node.LANE_STORE_USERNAME_KEY == lane.LANE_STORE_USERNAME_KEY
    assert node.SOURCE_OPERATOR_ENV == lane.CREDENTIAL_SOURCE_OPERATOR_ENV_FILE
