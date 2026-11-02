# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Seal and open hook capture payloads under a key from the secret store (OMN-19513).

Operator RULING 2026-10-15T04:24:42Z: capture everything raw, and production
should have the option of encrypting the payload. The option is the
``payload_encryption`` block of ``contract_hook_claude_capture.yaml``; the hook
producers read it and, with it on, route every payload they journal through
this handler.

The handler, its models and its enums sit in omniclaude's package-level
``handlers``, ``models`` and ``enums``: the node-home ratchet (OMN-20702)
keeps new node directories out of omniclaude.

What a sealed payload is
------------------------
The routing fields the emit registry needs stay readable (``session_id``,
``event_id``, ``hook_event_name`` and a reduced ``lineage`` for ``hook.event``;
``session_id`` and ``content_kind`` for ``content.captured``). Everything else,
content and lineage detail alike, is one AES-256-GCM ciphertext under the
``payload_encryption`` field. The readable fields ride in the associated data,
so a ciphertext moved onto another session or event is refused when opened.

The key is 32 random bytes held as base64 text in the secret store. It is a
key, not a password, so there is no key derivation: the envelope helper in
omnibase_core (``ModelSecureEventEnvelope.encrypt_payload``) is bound to its
own envelope class and runs PBKDF2 at 600,000 iterations per call, which a
per-hook process should not pay.

Fail closed
-----------
A key that cannot be read, or is not 32 bytes of base64, is a REFUSED outcome;
the producer journals nothing. A reason names a cause or an exception type,
never a key or content. No key is created, moved or printed here.

Reading it back: OPEN with the same key returns the plaintext payload. The
projection that consumes ``onex.evt.omniclaude.hook-event.v1`` does not call it
yet, so it refuses a sealed event; that is why the setting stays off.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import importlib
import json
import os
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from omniclaude.enums.enum_hook_payload_class import EnumHookPayloadClass
from omniclaude.enums.enum_hook_payload_encryption_operation import (
    EnumHookPayloadEncryptionOperation,
)
from omniclaude.enums.enum_hook_payload_encryption_outcome import (
    EnumHookPayloadEncryptionOutcome,
)
from omniclaude.models.model_hook_payload_encryption_request import (
    ModelHookPayloadEncryptionRequest,
)
from omniclaude.models.model_hook_payload_encryption_result import (
    ModelHookPayloadEncryptionResult,
)
from omniclaude.models.model_runtime_paths import runtime_paths

#: The sealed payload's one field: the ciphertext and what a reader needs.
ENVELOPE_FIELD = "payload_encryption"
ALGORITHM = "AES-256-GCM"
ENVELOPE_VERSION = 1
KEY_BYTES = 32
NONCE_BYTES = 12

#: Per class, the top-level fields that stay readable: the emit registry's
#: partition key and required fields (omnimarket
#: ``node_emit_daemon/registries/topics.yaml``).
_CLEAR_FIELDS: dict[EnumHookPayloadClass, tuple[str, ...]] = {
    EnumHookPayloadClass.HOOK_EVENT: ("session_id", "event_id", "hook_event_name"),
    EnumHookPayloadClass.CONTENT_CAPTURED: ("session_id", "content_kind"),
}
#: ``hook.event`` requires ``lineage``; only these ids of it stay readable.
_CLEAR_LINEAGE: tuple[str, ...] = ("session_id", "agent_id", "turn_id")

#: omnimarket's reader for this machine's secret store: ``get_secret(key)`` as
#: the identity ``~/.onex`` names. Imported only when a key is read.
_STORE_READER_MODULE = (
    "omnimarket.nodes.node_captured_secret_resolve_effect.handlers."
    "handler_captured_secret_resolve"
)

if TYPE_CHECKING:
    from pydantic import JsonValue

KeyReader = Callable[[str], "str | None"]


class PayloadEncryptionError(ValueError):
    """The step cannot seal or open. The message never carries a key or content."""


def key_from_text(text: str) -> bytes:
    """The 32 key bytes of a base64 key, or raise. The text is never echoed."""
    try:
        key = base64.b64decode(
            text.strip().replace("-", "+").replace("_", "/"), validate=True
        )
    except (binascii.Error, ValueError):
        msg = "the key is not base64 text"
        raise PayloadEncryptionError(msg) from None
    if len(key) != KEY_BYTES:
        msg = f"the key is not {KEY_BYTES} bytes"
        raise PayloadEncryptionError(msg)
    return key


def resolve_key(key_ref: str | None, reader: KeyReader) -> bytes:
    """Read ``key_ref`` through ``reader`` and return the key bytes, or raise."""
    if not key_ref:
        msg = "key_secret_ref is not set"
        raise PayloadEncryptionError(msg)
    try:
        text = reader(key_ref)
    except Exception as exc:
        msg = f"the secret store refused the key read ({type(exc).__name__})"
        raise PayloadEncryptionError(msg) from exc
    if not text:
        msg = "the secret store holds no key at key_secret_ref"
        raise PayloadEncryptionError(msg)
    return key_from_text(text)


def default_key_reader() -> KeyReader:
    """The secret store reader of this machine, as a plain ``ref -> text`` call."""
    try:
        module = importlib.import_module(_STORE_READER_MODULE)
        reader = module.reader_for_this_machine(runtime_paths().store_reader_home)
    except Exception as exc:
        msg = f"no secret store reader is available ({type(exc).__name__})"
        raise PayloadEncryptionError(msg) from exc

    def read(ref: str) -> str | None:
        value: str | None = asyncio.run(reader.get_secret(ref))
        return value

    return read


def _clear_view(
    payload_class: EnumHookPayloadClass, payload: Mapping[str, JsonValue]
) -> dict[str, JsonValue]:
    clear: dict[str, JsonValue] = {
        name: payload.get(name) for name in _CLEAR_FIELDS[payload_class]
    }
    if payload_class is EnumHookPayloadClass.HOOK_EVENT:
        lineage = payload.get("lineage")
        source = lineage if isinstance(lineage, Mapping) else {}
        clear["lineage"] = {name: source.get(name) for name in _CLEAR_LINEAGE}
    return clear


def _aad(payload_class: EnumHookPayloadClass, clear: Mapping[str, JsonValue]) -> bytes:
    return json.dumps(
        {"payload_class": payload_class.value, "clear": clear},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def seal_payload(
    payload: Mapping[str, JsonValue],
    *,
    payload_class: EnumHookPayloadClass,
    key: bytes,
    key_ref: str,
) -> dict[str, JsonValue]:
    """The sealed form of ``payload``: readable routing fields plus one ciphertext."""
    clear = _clear_view(payload_class, payload)
    plaintext = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _aad(payload_class, clear))
    return {
        **clear,
        ENVELOPE_FIELD: {
            "v": ENVELOPE_VERSION,
            "alg": ALGORITHM,
            "key_ref": key_ref,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        },
    }


def open_payload(
    sealed: Mapping[str, JsonValue], *, payload_class: EnumHookPayloadClass, key: bytes
) -> dict[str, JsonValue]:
    """The plaintext payload of a sealed one, or raise.

    Fields the sealed payload gained after sealing (the journal appender stamps
    actor, turn and lane) are outside the associated data and ignored.
    """
    block = sealed.get(ENVELOPE_FIELD)
    if not isinstance(block, Mapping) or block.get("alg") != ALGORITHM:
        msg = "the payload is not sealed"
        raise PayloadEncryptionError(msg)
    nonce_text = block.get("nonce")
    cipher_text = block.get("ciphertext")
    if not isinstance(nonce_text, str) or not isinstance(cipher_text, str):
        msg = "the sealed payload is malformed"
        raise PayloadEncryptionError(msg)
    try:
        nonce = base64.b64decode(nonce_text, validate=True)
        ciphertext = base64.b64decode(cipher_text, validate=True)
    except (binascii.Error, ValueError):
        msg = "the sealed payload is malformed"
        raise PayloadEncryptionError(msg) from None
    clear = _clear_view(payload_class, sealed)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, _aad(payload_class, clear))
    except (InvalidTag, ValueError):
        msg = "the payload did not open (wrong key, or altered)"
        raise PayloadEncryptionError(msg) from None
    opened: dict[str, JsonValue] = json.loads(plaintext.decode("utf-8"))
    return opened


class HandlerHookPayloadEncryption:
    """``handle(request) -> result``: check the key, seal a payload, or open one.

    One instance serves one capture process: the key is read from the secret
    store once, on first need, and held for the instance's life.
    """

    def __init__(
        self, *, key_ref: str | None, key_reader: KeyReader | None = None
    ) -> None:
        self._key_ref = key_ref
        self._key_reader = key_reader
        self._key: bytes | None = None

    def _store_key(self) -> bytes:
        if self._key is None:
            reader = self._key_reader or default_key_reader()
            self._key = resolve_key(self._key_ref, reader)
        return self._key

    def handle(
        self, request: ModelHookPayloadEncryptionRequest
    ) -> ModelHookPayloadEncryptionResult:
        outcome = EnumHookPayloadEncryptionOutcome
        try:
            if request.operation is EnumHookPayloadEncryptionOperation.OPEN:
                key = (
                    key_from_text(request.key.get_secret_value())
                    if request.key is not None
                    else self._store_key()
                )
                return ModelHookPayloadEncryptionResult(
                    outcome=outcome.OPENED,
                    payload=open_payload(
                        request.payload, payload_class=request.payload_class, key=key
                    ),
                )
            key = self._store_key()
            if request.operation is EnumHookPayloadEncryptionOperation.CHECK:
                return ModelHookPayloadEncryptionResult(outcome=outcome.READY)
            return ModelHookPayloadEncryptionResult(
                outcome=outcome.SEALED,
                payload=seal_payload(
                    request.payload,
                    payload_class=request.payload_class,
                    key=key,
                    key_ref=self._key_ref or "",
                ),
            )
        except PayloadEncryptionError as exc:
            return ModelHookPayloadEncryptionResult(
                outcome=outcome.REFUSED, reason=str(exc)
            )


__all__ = [
    "ALGORITHM",
    "ENVELOPE_FIELD",
    "EnumHookPayloadClass",
    "EnumHookPayloadEncryptionOperation",
    "EnumHookPayloadEncryptionOutcome",
    "HandlerHookPayloadEncryption",
    "KeyReader",
    "ModelHookPayloadEncryptionRequest",
    "ModelHookPayloadEncryptionResult",
    "PayloadEncryptionError",
    "default_key_reader",
    "key_from_text",
    "open_payload",
    "resolve_key",
    "seal_payload",
]
