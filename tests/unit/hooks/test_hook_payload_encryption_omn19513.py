# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Payload encryption of the hook capture (OMN-19513).

Operator RULING 2026-10-15T04:24:42Z: capture everything raw, and production
should have the option of encrypting the payload. The option is one contract
setting, ``payload_encryption`` in ``contract_hook_claude_capture.yaml``, off
by default. These tests hold the step behind it: with the setting on, the
journalled payload of both capture classes is encrypted with a key read from
the secret store by ``key_secret_ref`` and a reader holding the same key gets
the plaintext payload back; with it off, nothing changes.

Every key here is generated per test (``os.urandom``); none is a real key and
none is printed.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from omniclaude.nodes.node_hook_payload_encryption_effect.enums import (
    EnumHookPayloadClass,
    EnumHookPayloadEncryptionOperation,
    EnumHookPayloadEncryptionOutcome,
)
from omniclaude.nodes.node_hook_payload_encryption_effect.handlers import (
    handler_hook_payload_encryption as enc,
)
from omniclaude.nodes.node_hook_payload_encryption_effect.models import (
    ModelHookPayloadEncryptionRequest,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"))
claude_capture = importlib.import_module("hook_claude_capture")
content_capture = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("hook_lane_overlay")]

_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "hooks" / "claude_hook_capture"
SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
KEY_REF = "capture/payload-key-throwaway"
MARKER = "PLAINTEXT-MARKER-FAKE-0001"
HOOK_EVENT = EnumHookPayloadClass.HOOK_EVENT
CONTENT = EnumHookPayloadClass.CONTENT_CAPTURED
OP = EnumHookPayloadEncryptionOperation
OUTCOME = EnumHookPayloadEncryptionOutcome


def _throwaway_key() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")


class FakeStore:
    """A secret store reader: records the references it was asked for."""

    def __init__(self, value: str | None) -> None:
        self.value = value
        self.seen: list[str] = []

    def __call__(self, ref: str) -> str | None:
        self.seen.append(ref)
        return self.value


def _contract(tmp_path: Path, *, enabled: str, ref: str) -> Path:
    path = tmp_path / "contract.yaml"
    path.write_text(
        "name: x\n"
        "payload_encryption:\n"
        f"  enabled: {enabled}   # a comment\n"
        f"  key_secret_ref: {ref}\n"
        "coverage: []\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _capture_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(claude_capture.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(claude_capture, "lane_grant_pending", lambda: False)


def _journal_dir(root: Path) -> Path:
    directory = root / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    health.write_status(
        directory.parent / health.STATUS_FILENAME,
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=("hook.event", "content.captured"),
        ),
    )
    return directory


@pytest.fixture
def jdir(tmp_path: Path) -> Path:
    return _journal_dir(tmp_path)


@pytest.fixture
def encryption_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        content_capture,
        "CAPTURE_CONTRACT_YAML",
        _contract(tmp_path, enabled="true", ref=KEY_REF),
    )


def _journalled(journal_dir: Path, event_type: str) -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(journal_dir)
        if entry.record.event_type == event_type
    ]


def _stdin_with_marker() -> dict[str, Any]:
    stdin: dict[str, Any] = json.loads(
        (_FIXTURES / "stdin" / "UserPromptSubmit.json").read_text(encoding="utf-8")
    )
    stdin["prompt"] = MARKER
    return stdin


def _open(
    sealed: dict[str, Any], key_text: str, payload_class: EnumHookPayloadClass
) -> dict[str, Any]:
    result = enc.HandlerHookPayloadEncryption(key_ref=KEY_REF).handle(
        ModelHookPayloadEncryptionRequest(
            operation=OP.OPEN,
            payload_class=payload_class,
            payload=sealed,
            key=SecretStr(key_text),
        )
    )
    assert result.outcome is OUTCOME.OPENED
    assert result.payload is not None
    return result.payload


# ---------------------------------------------------------------------------
# the setting
# ---------------------------------------------------------------------------


def test_the_shipped_contract_is_off_with_no_key_reference() -> None:
    assert content_capture.payload_encryption_setting() == (False, None)


def test_the_setting_reads_enabled_and_the_key_reference(tmp_path: Path) -> None:
    read = content_capture.payload_encryption_setting
    assert read(_contract(tmp_path, enabled="true", ref=KEY_REF)) == (True, KEY_REF)
    assert read(_contract(tmp_path, enabled="true", ref=f'"{KEY_REF}"')) == (
        True,
        KEY_REF,
    )
    assert read(_contract(tmp_path, enabled="false", ref="null")) == (False, None)


def test_an_unreadable_contract_is_off(tmp_path: Path) -> None:
    assert content_capture.payload_encryption_setting(tmp_path / "none.yaml") == (
        False,
        None,
    )


def test_the_hook_event_module_keeps_its_setting_reader(tmp_path: Path) -> None:
    assert claude_capture.payload_encryption_enabled() is False
    on = _contract(tmp_path, enabled="true", ref=KEY_REF)
    assert claude_capture.payload_encryption_enabled(on) is True


# ---------------------------------------------------------------------------
# the cipher
# ---------------------------------------------------------------------------

_PAYLOAD = {
    "session_id": SESSION,
    "event_id": "evt-1",
    "hook_event_name": "PostToolUse",
    "lineage": {"session_id": SESSION, "agent_id": None, "turn_id": "t-1", "x": "y"},
    "content_refs": [{"field": "tool_input", "value": MARKER}],
}


def _seal(key_text: str) -> dict[str, Any]:
    return enc.seal_payload(
        _PAYLOAD,
        payload_class=HOOK_EVENT,
        key=enc.key_from_text(key_text),
        key_ref=KEY_REF,
    )


def test_seal_then_open_returns_the_payload() -> None:
    key_text = _throwaway_key()
    assert _open(_seal(key_text), key_text, HOOK_EVENT) == _PAYLOAD


def test_the_sealed_payload_holds_no_plaintext_and_keeps_routing_fields() -> None:
    sealed = _seal(_throwaway_key())
    assert MARKER not in json.dumps(sealed)
    assert sealed["session_id"] == SESSION
    assert sealed["event_id"] == "evt-1"
    assert sealed["hook_event_name"] == "PostToolUse"
    assert sealed["lineage"] == {
        "session_id": SESSION,
        "agent_id": None,
        "turn_id": "t-1",
    }
    block = sealed[enc.ENVELOPE_FIELD]
    assert block["alg"] == "AES-256-GCM"
    assert block["key_ref"] == KEY_REF


def test_each_seal_uses_a_fresh_nonce() -> None:
    key_text = _throwaway_key()
    first = _seal(key_text)[enc.ENVELOPE_FIELD]
    second = _seal(key_text)[enc.ENVELOPE_FIELD]
    assert first["nonce"] != second["nonce"]
    assert first["ciphertext"] != second["ciphertext"]


def test_the_wrong_key_does_not_open_it() -> None:
    sealed = _seal(_throwaway_key())
    with pytest.raises(enc.PayloadEncryptionError):
        enc.open_payload(
            sealed,
            payload_class=HOOK_EVENT,
            key=enc.key_from_text(_throwaway_key()),
        )


def test_moving_the_ciphertext_to_another_session_is_refused() -> None:
    key_text = _throwaway_key()
    moved = {**_seal(key_text), "session_id": "another-session"}
    with pytest.raises(enc.PayloadEncryptionError):
        enc.open_payload(
            moved, payload_class=HOOK_EVENT, key=enc.key_from_text(key_text)
        )


def test_a_payload_that_is_not_sealed_is_refused_on_open() -> None:
    with pytest.raises(enc.PayloadEncryptionError):
        enc.open_payload(
            dict(_PAYLOAD),
            payload_class=HOOK_EVENT,
            key=enc.key_from_text(_throwaway_key()),
        )


@pytest.mark.parametrize(
    "text", ["", "not base64 !!", base64.b64encode(b"short").decode()]
)
def test_a_key_that_is_not_32_bytes_of_base64_is_refused(text: str) -> None:
    with pytest.raises(enc.PayloadEncryptionError) as raised:
        enc.key_from_text(text)
    assert not text or text not in str(raised.value)


def test_resolve_key_reads_the_reference_and_fails_closed() -> None:
    key_text = _throwaway_key()
    store = FakeStore(key_text)
    assert enc.resolve_key(KEY_REF, store) == enc.key_from_text(key_text)
    assert store.seen == [KEY_REF]
    with pytest.raises(enc.PayloadEncryptionError):
        enc.resolve_key(KEY_REF, FakeStore(None))
    with pytest.raises(enc.PayloadEncryptionError):
        enc.resolve_key(None, store)

    def failing(_ref: str) -> str | None:
        raise RuntimeError(key_text)

    with pytest.raises(enc.PayloadEncryptionError) as raised:
        enc.resolve_key(KEY_REF, failing)
    assert key_text not in str(raised.value)


# ---------------------------------------------------------------------------
# the handler
# ---------------------------------------------------------------------------


def test_the_handler_seals_opens_and_reads_the_store_once() -> None:
    key_text = _throwaway_key()
    store = FakeStore(key_text)
    handler = enc.HandlerHookPayloadEncryption(key_ref=KEY_REF, key_reader=store)
    sealed = handler.handle(
        ModelHookPayloadEncryptionRequest(
            operation=OP.SEAL, payload_class=HOOK_EVENT, payload=dict(_PAYLOAD)
        )
    )
    assert sealed.outcome is OUTCOME.SEALED
    assert sealed.payload is not None
    assert MARKER not in json.dumps(sealed.payload)
    opened = handler.handle(
        ModelHookPayloadEncryptionRequest(
            operation=OP.OPEN, payload_class=HOOK_EVENT, payload=sealed.payload
        )
    )
    assert opened.payload == _PAYLOAD
    assert store.seen == [KEY_REF]  # read once, held for the instance


def test_the_handler_refuses_without_a_key_and_says_why_without_the_key() -> None:
    handler = enc.HandlerHookPayloadEncryption(
        key_ref=KEY_REF, key_reader=FakeStore("not-a-key")
    )
    result = handler.handle(
        ModelHookPayloadEncryptionRequest(operation=OP.CHECK, payload_class=HOOK_EVENT)
    )
    assert result.outcome is OUTCOME.REFUSED
    assert result.reason is not None
    assert "not-a-key" not in result.reason


def test_the_default_reader_without_a_configured_store_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``~/.onex`` overlay, no key: the seal is refused, not skipped."""
    monkeypatch.setenv("HOME", str(tmp_path))
    contract = _contract(tmp_path, enabled="true", ref=KEY_REF)
    with pytest.raises(content_capture.PayloadSealRefusedError):
        content_capture.payload_sealer(contract_path=contract)


# ---------------------------------------------------------------------------
# hook.event
# ---------------------------------------------------------------------------


def test_off_changes_nothing(jdir: Path) -> None:
    assert claude_capture.capture(_stdin_with_marker(), journal_dir=jdir) == 1
    (payload,) = _journalled(jdir, "hook.event")
    assert enc.ENVELOPE_FIELD not in payload
    assert MARKER in json.dumps(payload)


@pytest.mark.usefixtures("encryption_on")
def test_hook_event_is_journalled_encrypted_and_opens_with_the_same_key(
    jdir: Path,
) -> None:
    key_text = _throwaway_key()
    store = FakeStore(key_text)
    wrote = claude_capture.capture(
        _stdin_with_marker(), journal_dir=jdir, key_reader=store
    )
    assert wrote == 1
    assert store.seen == [KEY_REF]
    (sealed,) = _journalled(jdir, "hook.event")
    assert MARKER not in json.dumps(sealed)
    for required in ("session_id", "event_id", "hook_event_name", "lineage"):
        assert required in sealed
    assert MARKER in json.dumps(_open(sealed, key_text, HOOK_EVENT))


@pytest.mark.usefixtures("encryption_on")
def test_hook_event_opens_to_what_the_off_path_journals(
    tmp_path: Path, jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
    key_text = _throwaway_key()
    claude_capture.capture(
        _stdin_with_marker(),
        journal_dir=jdir,
        now=now,
        key_reader=FakeStore(key_text),
    )
    (sealed,) = _journalled(jdir, "hook.event")

    monkeypatch.setattr(
        content_capture,
        "CAPTURE_CONTRACT_YAML",
        _contract(tmp_path, enabled="false", ref="null"),
    )
    plain_dir = _journal_dir(tmp_path / "plain")
    claude_capture.capture(_stdin_with_marker(), journal_dir=plain_dir, now=now)
    (plain,) = _journalled(plain_dir, "hook.event")

    opened = _open(sealed, key_text, HOOK_EVENT)
    for name in ("event_id", "hook_event_name", "content_refs", "lineage"):
        assert opened[name] == plain[name]


@pytest.mark.usefixtures("encryption_on")
@pytest.mark.parametrize("key_text", [None, "", "not-a-key"])
def test_hook_event_with_no_usable_key_journals_nothing_and_says_why(
    jdir: Path, key_text: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    wrote = claude_capture.capture(
        _stdin_with_marker(), journal_dir=jdir, key_reader=FakeStore(key_text)
    )
    assert wrote == 0
    assert _journalled(jdir, "hook.event") == []
    assert MARKER not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# content.captured
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("encryption_on")
def test_content_record_is_journalled_encrypted_and_opens_with_the_same_key(
    jdir: Path,
) -> None:
    key_text = _throwaway_key()
    written = content_capture.capture(
        {"session_id": SESSION, "prompt": MARKER},
        kind="prompt",
        journal_dir=jdir,
        key_reader=FakeStore(key_text),
    )
    assert written == 1
    (sealed,) = _journalled(jdir, "content.captured")
    assert MARKER not in json.dumps(sealed)
    assert sealed["session_id"] == SESSION
    assert sealed["content_kind"] == "prompt"
    opened = _open(sealed, key_text, CONTENT)
    assert opened["content"] == MARKER
    assert opened["chunk_index"] == 0


@pytest.mark.usefixtures("encryption_on")
def test_content_record_with_no_usable_key_journals_nothing(jdir: Path) -> None:
    written = content_capture.capture(
        {"session_id": SESSION, "prompt": MARKER},
        kind="prompt",
        journal_dir=jdir,
        key_reader=FakeStore(None),
    )
    assert written == 0
    assert _journalled(jdir, "content.captured") == []


def test_content_record_off_changes_nothing(jdir: Path) -> None:
    written = content_capture.capture(
        {"session_id": SESSION, "prompt": MARKER}, kind="prompt", journal_dir=jdir
    )
    assert written == 1
    (record,) = _journalled(jdir, "content.captured")
    assert record["content"] == MARKER
    assert enc.ENVELOPE_FIELD not in record
