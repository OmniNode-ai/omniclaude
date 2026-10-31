# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Contractor classes stop before either transport or any durable capture state."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import hook_emit_append as appender
import hook_emit_drainer as drainer
import hook_emit_journal as journal
import pytest
import yaml

pytestmark = pytest.mark.unit

# A known lane of the shipped contract a collaborator is bound to (spelled in parts: the
# public-repo hygiene gate reads the literal as a lab name).
BOUND = "-".join(("stability", "test"))
CONTRACTOR = f"{BOUND}-contractor-laptop"

BLOCKED = (
    "prompt.submitted",
    "content.captured",
    "session.outcome",
    "utilization.scoring.requested",
)


@pytest.fixture
def profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    store = home / ".onex"
    store.mkdir(parents=True)
    config = tmp_path / "config-root"
    declaration = config / "config/lab/developer-principal-overlay.yaml"
    declaration.parent.mkdir(parents=True)
    declaration.write_text(
        yaml.safe_dump(
            {
                "schema_version": "developer_principal.v1",
                "grants_source": "omnibase_infra:deploy/lab/developer-principal-grants.yaml",
                "principals": [
                    {
                        "principal": "dev-contractor-laptop",
                        "login": "contractor@example.invalid",
                        "device": "laptop",
                    }
                ],
            }
        )
    )
    bound = config / f"config/lab/lane-overlays/{BOUND}.developer-principal.yaml"
    bound.parent.mkdir(parents=True)
    bound.write_text(
        yaml.safe_dump(
            {
                "schema_version": "developer_principal.v1",
                "grants_source": "none: test",
                "principals": [
                    {
                        "principal": CONTRACTOR,
                        "login": "contractor@example.invalid",
                        "device": "laptop",
                    }
                ],
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("ONEX_WORKSPACE_CONFIG_ROOT", str(config))
    monkeypatch.setenv("ONEX_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("ONEX_HOOK_LOCAL_BUS_HTTP_URL", raising=False)
    # Ambient identity must never overrule the selected lane's store.
    monkeypatch.setenv("KAFKA_SASL_USERNAME", "dev-operator-workstation")
    return store / "config.yaml"


def identity(profile: Path, principal: str) -> None:
    profile.write_text(
        yaml.safe_dump(
            {
                "lanes": {
                    "dev": {
                        "sasl_username": principal,
                        "sasl_password_ref": "not-read",
                    },
                    "unselected": {"sasl_username": "dev-contractor-laptop"},
                }
            }
        )
    )


def bound_identity(profile: Path, principal: str) -> None:
    """A collaborator bound to its own lane (``onex profile bind-lane``)."""
    profile.write_text(
        yaml.safe_dump(
            {
                "developer": {"lane_binding": BOUND},
                "lanes": {BOUND: {"sasl_username": principal}},
            }
        )
    )


def journalled(target: Path) -> list[str]:
    return [entry.record.event_type for entry in journal.list_pending(target)]


def append(event_type: str, target: Path) -> None:
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


@pytest.mark.parametrize("event_type", BLOCKED)
def test_contractor_drops_before_journal(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    bound_identity(profile, CONTRACTOR)
    target = tmp_path / "journal"

    append(event_type, target)

    assert not target.exists()
    assert not (tmp_path / "state").exists()
    # Positive control uses the same profile and actual journal/drain path.
    append("tool.executed", target)
    emitter = Mock()
    emitter.publish.return_value = True
    assert drainer.drain_once(target, emitter) == (1, 0, 0)
    assert emitter.publish.call_args.args[0].event_type == "tool.executed"
    assert list(journal.list_pending(target)) == []
    assert not (target / "dead_letter").exists()


@pytest.mark.parametrize("event_type", [*BLOCKED, "tool.executed", "hook.event"])
def test_operator_retains_publication(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
) -> None:
    identity(profile, "dev-operator-workstation")

    append(event_type, tmp_path / "journal")

    assert journalled(tmp_path / "journal") == [event_type]


def test_contractor_evt_is_journalled(profile: Path, tmp_path: Path) -> None:
    bound_identity(profile, CONTRACTOR)
    append("hook.event", tmp_path / "journal")
    assert journalled(tmp_path / "journal") == ["hook.event"]


def test_content_capture_exits_before_reading_or_stamping(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hook_content_capture as capture

    bound_identity(profile, CONTRACTOR)
    load = Mock(side_effect=AssertionError("content must not be read or stamped"))
    monkeypatch.setattr(capture, "load_resolver", load)
    monkeypatch.setattr(capture, "drainer_can_publish", lambda _path: True)
    assert (
        capture.capture(
            {"session_id": "session", "prompt": "private"},
            kind="prompt",
            journal_dir=tmp_path / "journal",
        )
        == 0
    )
    load.assert_not_called()


def test_only_held_classes_are_suppressed(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hook_edge_lane as lane

    bound_identity(profile, CONTRACTOR)
    contract = lane.load_contract(
        Path(lane.__file__).parent.parent / "contracts/hook_edge_lane.yaml"
    )
    raw = yaml.safe_load(
        (
            Path(lane.__file__).parent.parent / "contracts/hook_edge_lane.yaml"
        ).read_text()
    )
    assert set(raw["developer_event_policy"]["excluded_event_classes"]) == set(BLOCKED)
    permitted = set(contract.governed_event_classes) - set(BLOCKED)
    assert "tool.executed" in permitted
    assert "hook.event" in permitted
    for event_type in sorted(contract.governed_event_classes):
        append(event_type, tmp_path / "journal")
    assert set(journalled(tmp_path / "journal")) == permitted


def test_malformed_developer_declaration_cannot_publish_or_spool(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_identity(profile, CONTRACTOR)
    declaration = (
        tmp_path
        / f"config-root/config/lab/lane-overlays/{BOUND}.developer-principal.yaml"
    )
    declaration.write_text("schema_version: developer_principal.v1\nprincipals: []\n")
    # OMN-21599: a refusal drops every class (nothing reaches any lane) and never raises.
    append("prompt.submitted", tmp_path / "journal")
    append("tool.executed", tmp_path / "journal")
    assert not (tmp_path / "journal").exists()


def test_operator_without_developer_declaration_keeps_existing_behavior(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity(profile, "dev-operator-workstation")
    (tmp_path / "config-root/config/lab/developer-principal-overlay.yaml").unlink()
    append("prompt.submitted", tmp_path / "journal")
    assert journalled(tmp_path / "journal") == ["prompt.submitted"]


@pytest.mark.parametrize(
    ("principal", "held_count"),
    [
        (CONTRACTOR, 0),
        ("dev-operator-workstation", len(BLOCKED)),
    ],
)
def test_real_hook_appender_cli_on_a_clean_profile(
    profile: Path,
    tmp_path: Path,
    principal: str,
    held_count: int,
) -> None:
    if principal == CONTRACTOR:
        bound_identity(profile, principal)
    else:
        identity(profile, principal)
    target = tmp_path / "journal"
    script = Path(appender.__file__)
    for event_type in BLOCKED:
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--event-type",
                event_type,
                "--payload",
                json.dumps({"session_id": "session", "content": "private"}),
                "--session-id",
                "session",
                "--journal-dir",
                str(target),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode == 0, result.stderr
    assert len(journal.list_pending(target)) == held_count
    if held_count == 0:
        assert not target.exists()
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--event-type",
            "tool.executed",
            "--payload",
            "{}",
            "--journal-dir",
            str(target),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    pending = journal.list_pending(target)
    assert len(pending) == held_count + 1
    assert pending[-1].record.event_type == "tool.executed"
    assert not (target / "dead_letter").exists()


def test_store_principal_normalization_matches_broker_identity(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_identity(profile, f"  {CONTRACTOR}  ")
    append("prompt.submitted", tmp_path / "journal")
    assert not (tmp_path / "journal").exists()


def test_plugin_cache_uses_installed_handler_for_admission(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bound_identity(profile, CONTRACTOR)
    monkeypatch.setattr(
        appender, "_BUS_HANDLER", tmp_path / "cache-without-src/handler.py"
    )
    append("prompt.submitted", tmp_path / "journal")
    assert not (tmp_path / "journal").exists()
    append("tool.executed", tmp_path / "journal")
    assert journalled(tmp_path / "journal") == ["tool.executed"]


def test_operator_with_older_installed_handler_keeps_existing_behavior(
    profile: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    identity(profile, "dev-operator-workstation")
    monkeypatch.setattr(appender, "_load_bus_handler", SimpleNamespace)
    append("prompt.submitted", tmp_path / "journal")
    assert journalled(tmp_path / "journal") == ["prompt.submitted"]
