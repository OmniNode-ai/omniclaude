# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The ledger test-write guard: a test process never writes the canonical ledger (OMN-19513).

Operator ruling 2026-10-01: "it should be impossible to like fake test like that". A test run on
a lab host published 17 fixture rows to the ledger of record. Test isolation is a convention a
test can forget; this guard sits in the write path itself, so the refusal does not depend on how
a test was set up. Reference design: omnibase_internal#121
(``omnibase_internal.handlers.handler_ledger_write_guard``).

THE RULE. A write is refused when BOTH hold:

1. The process runs under a test runner: ``PYTEST_CURRENT_TEST`` is set, ``pytest`` or
   ``unittest`` is imported, or ``ONEX_TEST_CONTEXT`` is set to any non-empty value. The
   environment signals are inherited by subprocesses (the canary append script is one).
   ``ONEX_TEST_CONTEXT`` only ever adds the signal; no value removes one.
2. The target is canonical:

   - a ledger FILE outside the temporary directory, or inside a ``$OMNI_HOME`` that is not itself
     under the temporary directory (:func:`check_file`, used by ``scripts/hook_canary_ledger_append.sh``);
   - a canonical work-ledger TOPIC name, ``onex.{evt,cmd}.omnimarket.work-ledger-*``
     (:func:`check_topic`);
   - a v2 work-ledger event (``work.ledger.typed.*``) emitted through a daemon socket outside the
     temporary directory: the daemon fans it out to the real ``work-ledger-*.v2`` topics
     (:func:`check_emit_event`, used by the emit client).

A test that needs a ledger uses a ``tmp_path`` file, a socket under ``tmp_path`` or a
non-canonical topic. There is no bypass flag and no allowlist.

The refusal is :class:`LedgerTestWriteRefused`; the command exit is
:data:`EXIT_TEST_WRITE_REFUSED`. The module is stdlib only, so a shell script can run it by path.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

GUARD_NAME = "ledger-test-write-guard"
TEST_CONTEXT_ENV = "ONEX_TEST_CONTEXT"
EXIT_TEST_WRITE_REFUSED = 79
LEDGER_EVENT_PREFIX = "work.ledger.typed."
CANONICAL_TOPIC = re.compile(
    r"^onex\.(?:evt|cmd)\.omnimarket\.work-ledger-[a-z0-9-]+\.v\d+$"
)
_RUNNER_MODULES = ("pytest", "unittest")


class LedgerTestWriteRefused(Exception):
    """A test process tried to write a canonical ledger target. The message names the guard."""

    def __init__(self, signal: str, target_kind: str, target: str) -> None:
        self.signal = signal
        self.target_kind = target_kind
        self.target = target
        super().__init__(
            f"{GUARD_NAME} REFUSED -- a test process ({signal}) tried to write the canonical "
            f"{target_kind} {target}. Nothing was written. A test writes a tmp_path ledger, a "
            "tmp_path emit socket or a non-canonical topic "
            "(omniclaude.handlers.handler_ledger_write_guard, OMN-19513)."
        )


def test_context() -> str | None:
    """The first test-runner signal present, named, or None outside a test."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return "PYTEST_CURRENT_TEST is set"
    if os.environ.get(TEST_CONTEXT_ENV, "").strip():
        return f"{TEST_CONTEXT_ENV} is set"
    for name in _RUNNER_MODULES:
        if name in sys.modules:
            return f"{name} is imported"
    return None


def _temp_root() -> Path:
    return Path(tempfile.gettempdir()).resolve()


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def file_is_canonical(path: Path) -> bool:
    """A ledger file is a test's own only under the temporary directory, and never inside a
    registry root (``OMNI_HOME``) that is not itself a test's scratch directory."""
    resolved = path.expanduser().resolve()
    temp_root = _temp_root()
    registry_root = os.environ.get("OMNI_HOME", "").strip()
    if registry_root:
        home = Path(registry_root).expanduser().resolve()
        if not _inside(home, temp_root) and _inside(resolved, home):
            return True
    return not _inside(resolved, temp_root)


def topic_is_canonical(topic: str) -> bool:
    return CANONICAL_TOPIC.match(topic.strip()) is not None


def _refuse_if_test(target_kind: str, target: str) -> None:
    signal = test_context()
    if signal is not None:
        raise LedgerTestWriteRefused(signal, target_kind, target)


def check_file(path: Path) -> None:
    """Refuse a test's write to a canonical ledger file."""
    if file_is_canonical(path):
        _refuse_if_test("ledger file", str(path))


def check_topic(topic: str) -> None:
    """Refuse a test's publish of a canonical work-ledger topic."""
    if topic_is_canonical(topic):
        _refuse_if_test("ledger topic", topic)


def check_emit_event(event_type: str, socket_path: str) -> None:
    """Refuse a test's v2 work-ledger emit through a daemon socket outside the temp directory."""
    if not event_type.startswith(LEDGER_EVENT_PREFIX):
        return
    if not _inside(Path(socket_path).expanduser().resolve(), _temp_root()):
        _refuse_if_test(
            "ledger topic",
            f"work-ledger v2 topics (event {event_type} via socket {socket_path})",
        )


def main(argv: Sequence[str] | None = None) -> int:
    """The command form, ``--file``, ``--topic``, ``--emit-event`` with ``--socket``.

    For a caller that is not Python: exit 0 when the write may proceed, 79 with the refusal on
    stderr when it may not."""
    parser = argparse.ArgumentParser(
        description="Refuse a test process's canonical ledger write."
    )
    parser.add_argument("--file", type=Path, action="append", default=[])
    parser.add_argument("--topic", action="append", default=[])
    parser.add_argument("--emit-event", action="append", default=[])
    parser.add_argument("--socket", default="")
    args = parser.parse_args(argv)
    try:
        for path in args.file:
            check_file(path)
        for topic in args.topic:
            check_topic(topic)
        for event_type in args.emit_event:
            check_emit_event(event_type, args.socket)
    except LedgerTestWriteRefused as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_TEST_WRITE_REFUSED
    return 0


__all__ = [
    "CANONICAL_TOPIC",
    "EXIT_TEST_WRITE_REFUSED",
    "GUARD_NAME",
    "LEDGER_EVENT_PREFIX",
    "TEST_CONTEXT_ENV",
    "LedgerTestWriteRefused",
    "check_emit_event",
    "check_file",
    "check_topic",
    "file_is_canonical",
    "main",
    "test_context",
    "topic_is_canonical",
]


if __name__ == "__main__":
    raise SystemExit(main())
