# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Captured secrets become secret-store references (OMN-20926).

The producer offers each secret its scrub finds to omnimarket's captured secret
store effect and puts the returned reference in the record. A fake store
effect proves store-then-reference, dedupe, the marker fallback with its loud
event, and that no secret value ever appears in anything journalled.

Every planted value is built by concatenation and holds ``FAKE``, so no
credential-shaped literal sits in this file.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from omniclaude.hooks.capture_redaction import (
    default_contract_path,
    load_contract,
    plan_content_chunks,
    redact_capture,
)

_LIB_DIR = Path(__file__).resolve().parents[3] / "plugins" / "onex" / "hooks" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

capture_mod = importlib.import_module("hook_content_capture")
health = importlib.import_module("hook_emit_health")
journal = importlib.import_module("hook_emit_journal")

pytestmark = pytest.mark.unit

SESSION = "0f0f0f0f-1111-2222-3333-444444444444"
GITHUB_FAKE = "gh" + "p_" + "FAKE" + "a1b2" * 9
LABELLED_FAKE = "FAKE" + "hunter22value"
REFERENCE_KEY = b"FAKE-reference-key"


def _reference() -> Any:
    reference = load_contract().reference
    assert reference is not None
    return reference


def _digest(value: str) -> str:
    return hmac.new(REFERENCE_KEY, value.encode(), hashlib.sha256).hexdigest()


class FakeStoreEffect:
    """Stands in for omnimarket's HandlerCapturedSecretStore.

    Same contract: ``handle(request)`` returns a result with ``outcome.value``,
    ``reference`` (only when the store holds the value) and ``detail``.
    """

    def __init__(self, refuse: str | None = None) -> None:
        self.refuse = refuse
        self.secrets: dict[str, tuple[str, str]] = {}
        self.calls = 0

    def handle(self, request: dict[str, Any]) -> types.SimpleNamespace:
        self.calls += 1
        if self.refuse is not None:
            return types.SimpleNamespace(
                outcome=types.SimpleNamespace(value=self.refuse),
                reference=None,
                detail=None,
            )
        value = request["value"]
        digest = _digest(value)
        key = _reference().store_key_for(digest)
        outcome = "exists" if key in self.secrets else "stored"
        self.secrets.setdefault(
            key, (value, f"session={request['session_id']} at={request['captured_at']}")
        )
        return types.SimpleNamespace(
            outcome=types.SimpleNamespace(value=outcome),
            reference=_reference().reference_for(digest),
            detail=None,
        )


def _request(**fields: Any) -> dict[str, Any]:
    return fields


@pytest.fixture
def jdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv(capture_mod.OPT_OUT_ENV, raising=False)
    monkeypatch.setattr(capture_mod, "onex_home", lambda: tmp_path / "onex")
    directory = tmp_path / "state" / "hook_emit_journal"
    directory.mkdir(parents=True)
    _status(directory, ("content.captured", "hook.health.error"))
    return directory


def _status(directory: Path, types_: tuple[str, ...]) -> None:
    health.write_status(
        capture_mod.status_path_for(directory),
        health.ModelDrainerStatus(
            last_cycle_at=1.0,
            last_publish_at=None,
            published_total=0,
            pid=1,
            publishable_event_types=types_,
        ),
    )


def _install(monkeypatch: pytest.MonkeyPatch, effect: FakeStoreEffect) -> None:
    monkeypatch.setattr(
        capture_mod, "build_store_handler", lambda _home: (effect, _request)
    )


def _records(jdir: Path, event_type: str = "content.captured") -> list[dict[str, Any]]:
    return [
        dict(entry.record.payload)
        for entry in journal.list_pending(jdir)
        if entry.record.event_type == event_type
    ]


def _assert_no_value_anywhere(jdir: Path, *values: str) -> None:
    written = b"".join(
        path.read_bytes() for path in sorted(jdir.parent.rglob("*")) if path.is_file()
    )
    for value in values:
        assert value.encode() not in written, "a secret value reached the journal"
        plain = hashlib.sha256(value.encode()).hexdigest().encode()
        assert plain not in written, "an unsalted hash of a secret was journalled"


def _capture(jdir: Path, prompt: str) -> int:
    return capture_mod.capture(
        {"session_id": SESSION, "prompt": prompt}, kind="prompt", journal_dir=jdir
    )


# ---------------------------------------------------------------------------
# store-then-reference
# ---------------------------------------------------------------------------


def test_a_detected_secret_is_stored_and_its_reference_crosses(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effect = FakeStoreEffect()
    _install(monkeypatch, effect)
    _capture(jdir, "push with " + GITHUB_FAKE + " now")

    (record,) = _records(jdir)
    minted = _reference().reference_for(_digest(GITHUB_FAKE))
    assert record["content"] == "push with " + minted + " now"
    assert record["stored_refs"] == {"stored": 1, "fallback": 0, "reason": None}
    assert record["producer_redaction"] == {"github_token": 1}
    ((value, comment),) = effect.secrets.values()
    assert value == GITHUB_FAKE
    assert f"session={SESSION}" in comment
    assert "push" not in comment, "surrounding text reached the store"
    assert _records(jdir, "hook.health.error") == []
    _assert_no_value_anywhere(jdir, GITHUB_FAKE)


def test_a_labelled_secret_keeps_its_label_and_stores_only_the_value(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effect = FakeStoreEffect()
    _install(monkeypatch, effect)
    _capture(jdir, "export password=" + LABELLED_FAKE + "\nthen run")

    (record,) = _records(jdir)
    minted = _reference().reference_for(_digest(LABELLED_FAKE))
    assert record["content"] == "export password=" + minted + "\nthen run"
    assert [value for value, _ in effect.secrets.values()] == [LABELLED_FAKE]
    _assert_no_value_anywhere(jdir, LABELLED_FAKE)


def test_the_reference_survives_the_fan_out_scrub(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install(monkeypatch, FakeStoreEffect())
    _capture(jdir, "token=" + LABELLED_FAKE + " and " + GITHUB_FAKE)

    (record,) = _records(jdir)
    topic = capture_mod.content_topic(capture_mod.load_resolver())
    fanned = redact_capture(record, topic=topic)
    assert fanned["content"] == record["content"]
    assert fanned["stored_refs"] == record["stored_refs"]
    assert len(_reference().pattern.findall(fanned["content"])) == 2


def test_the_same_secret_is_one_stored_value_and_one_reference(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    effect = FakeStoreEffect()
    _install(monkeypatch, effect)
    _capture(jdir, GITHUB_FAKE + " and again " + GITHUB_FAKE)
    _capture(jdir, "later: " + GITHUB_FAKE)

    assert len(effect.secrets) == 1
    references = {
        ref
        for record in _records(jdir)
        for ref in _reference().pattern.findall(record["content"])
    }
    assert len(references) == 1


def test_a_capture_with_no_secret_never_loads_the_store(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        capture_mod,
        "build_store_handler",
        lambda _home: pytest.fail("the store effect loaded with no secret found"),
    )
    _capture(jdir, "nothing sensitive here")
    (record,) = _records(jdir)
    assert "stored_refs" not in record


# ---------------------------------------------------------------------------
# fallback: today's marker, a reason, and a loud event
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reason", ["write_refused", "store_unreachable", "login_refused", "misconfigured"]
)
def test_a_store_failure_falls_back_to_the_marker_loudly(
    jdir: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    effect = FakeStoreEffect(refuse=reason)
    _install(monkeypatch, effect)
    _capture(jdir, "use " + GITHUB_FAKE + " and password=" + LABELLED_FAKE)

    (record,) = _records(jdir)
    assert "[REDACTED:github_token]" in record["content"]
    assert _reference().pattern.search(record["content"]) is None
    assert record["stored_refs"] == {"stored": 0, "fallback": 2, "reason": reason}
    assert effect.calls == 1, "a refused store was asked again in one capture"

    (alarm,) = _records(jdir, "hook.health.error")
    assert alarm["hook_name"] == "hook_content_capture"
    assert alarm["error_tier"] == "degraded"
    assert f"reason={reason}" in alarm["error_message"]
    assert "2 secret span(s)" in alarm["error_message"]
    assert alarm["session_id"] == SESSION
    _assert_no_value_anywhere(jdir, GITHUB_FAKE, LABELLED_FAKE)


@pytest.mark.parametrize("quiet", ["not_configured", "writer_unavailable"])
def test_a_machine_that_does_not_take_part_falls_back_quietly(
    jdir: Path, monkeypatch: pytest.MonkeyPatch, quiet: str
) -> None:
    if quiet == "writer_unavailable":

        def _missing(_home: Path) -> tuple[Any, Any]:
            raise ModuleNotFoundError("no captured secret store effect")

        monkeypatch.setattr(capture_mod, "build_store_handler", _missing)
    else:
        _install(monkeypatch, FakeStoreEffect(refuse=quiet))
    _capture(jdir, "use " + GITHUB_FAKE)

    (record,) = _records(jdir)
    assert record["content"] == "use [REDACTED:github_token]"
    assert record["stored_refs"] == {"stored": 0, "fallback": 1, "reason": quiet}
    assert _records(jdir, "hook.health.error") == []
    _assert_no_value_anywhere(jdir, GITHUB_FAKE)


def test_the_alarm_is_skipped_when_the_drainer_cannot_publish_it(
    jdir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _status(jdir, ("content.captured",))
    _install(monkeypatch, FakeStoreEffect(refuse="write_refused"))
    _capture(jdir, "use " + GITHUB_FAKE)
    assert _records(jdir)[0]["stored_refs"]["reason"] == "write_refused"
    assert _records(jdir, "hook.health.error") == []


# ---------------------------------------------------------------------------
# wiring and chunking
# ---------------------------------------------------------------------------


def test_build_store_handler_names_omnimarkets_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    class _Handler:
        def __init__(self, *, onex_home: Path) -> None:
            seen["onex_home"] = onex_home

    handler_module = types.ModuleType(capture_mod._STORE_HANDLER_MODULE)
    setattr(handler_module, "HandlerCapturedSecretStore", _Handler)
    request_module = types.ModuleType(capture_mod._STORE_REQUEST_MODULE)
    setattr(request_module, "ModelCapturedSecretStoreRequest", dict)
    monkeypatch.setitem(sys.modules, capture_mod._STORE_HANDLER_MODULE, handler_module)
    monkeypatch.setitem(sys.modules, capture_mod._STORE_REQUEST_MODULE, request_module)

    handler, request = capture_mod.build_store_handler(tmp_path)
    assert isinstance(handler, _Handler)
    assert seen["onex_home"] == tmp_path
    assert request is dict


def test_chunking_never_cuts_a_reference(tmp_path: Path) -> None:
    import yaml

    raw = yaml.safe_load(default_contract_path().read_text(encoding="utf-8"))
    topic = next(t for t, p in raw["topics"].items() if p.get("content_policy"))
    raw["topics"][topic]["content_policy"]["chunk_chars"] = 100
    raw["topics"][topic]["content_policy"]["max_content_chars"] = 250
    path = tmp_path / "capture_redaction.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    ref = _reference().reference_for(_digest(GITHUB_FAKE))
    text = "a" * 60 + " " + ref + " " + "b" * 70 + " " + ref + " " + "c" * 50
    plan = plan_content_chunks(text, topic, contract_path=path)
    joined = "".join(plan.chunks)
    assert all(len(chunk) <= 100 for chunk in plan.chunks)
    assert joined == text[: len(joined)]
    assert plan.truncated is True
    assert sum(chunk.count(ref) for chunk in plan.chunks) == 1
    assert joined.count("secret:") == 1
