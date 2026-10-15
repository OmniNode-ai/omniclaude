# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""onex-claude-code-hook: the adapter's own console entry point (OMN-18531, T0.3).

Reads one hook JSON document from stdin, publishes through the receipt-mode client
(no handler hosted here) and writes exactly the hook's output shape to stdout:
never a ModelSkillResult. Its first stderr line is the resolved max mode.

Failure posture (P5c/P5d/P5f): no thread spins (every wait blocks on an Event with
a timeout); the process exits when its parent goes away; it starts no child of its
own, so there is no group to leak. Any failure prints nothing on stdout and exits
non-zero, which the rendered binding maps through its fixed failure table.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, TextIO, cast

from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers.handler_claude_code_hook_adapter import (
    HandlerClaudeCodeHookAdapter,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers.handler_client_bindings_loader import (
    CONTRACT_PATH,
    load_client_section,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientSection,
    ModelHookAdapterRequest,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.protocols import (
    ProtocolReceiptModeClient,
)

if TYPE_CHECKING:
    from pydantic import JsonValue

CLIENT_ENV = "ONEX_HOOK_RECEIPT_CLIENT"
HOST_ENV = "ONEX_CLIENT_HOST"
CONTRACT_ENV = "ONEX_CLAUDE_CODE_ADAPTER_CONTRACT"
DEFAULT_CLIENT = "omnibase_infra.cli.receipt_mode_client:ReceiptModeClient"
PARENT_POLL_SECONDS = 1.0

EXIT_BAD_ARGS = 2
EXIT_BAD_INPUT = 3
EXIT_NO_CLIENT = 4
EXIT_FAILED = 5


def resolve_max_mode(section: ModelClientSection, host: str) -> EnumClientMaxMode:
    return section.host_max_modes.get(host, section.default_max_mode)


def watch_parent(
    stop: threading.Event,
    *,
    get_ppid: Callable[[], int] = os.getppid,
    on_orphaned: Callable[[], None] = lambda: os._exit(EXIT_FAILED),
    poll_seconds: float = PARENT_POLL_SECONDS,
    parent_pid: int | None = None,
) -> None:
    """Block-poll the parent pid; exit when it changes (P5f). Waits on the event, never spins.

    parent_pid is the pid read at process start: a parent that died before this thread's first
    read would otherwise be taken for the original one.
    """
    started_with = get_ppid() if parent_pid is None else parent_pid
    while not stop.wait(poll_seconds):
        if get_ppid() != started_with:
            on_orphaned()
            return


def _load_client() -> ProtocolReceiptModeClient:
    module_name, _, attr = os.environ.get(CLIENT_ENV, DEFAULT_CLIENT).partition(":")
    factory = cast(
        "Callable[[], ProtocolReceiptModeClient]",
        getattr(importlib.import_module(module_name), attr),
    )
    return factory()


def main(
    argv: list[str] | None = None,
    *,
    client: ProtocolReceiptModeClient | None = None,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    section: ModelClientSection | None = None,
) -> int:
    parent_pid = os.getppid()
    out, err, inp = stdout or sys.stdout, stderr or sys.stderr, stdin or sys.stdin
    parser = argparse.ArgumentParser(prog="onex-claude-code-hook")
    parser.add_argument("--binding", required=True)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_BAD_ARGS
    try:
        loaded = (
            section
            if section is not None
            else load_client_section(Path(os.environ.get(CONTRACT_ENV, CONTRACT_PATH)))
        )
        max_mode = resolve_max_mode(loaded, os.environ.get(HOST_ENV, ""))
        err.write(f"onex-claude-code-hook max_mode={max_mode.value}\n")
        err.flush()
        binding = next((b for b in loaded.bindings if b.name == args.binding), None)
        if binding is None:
            err.write(f"unknown binding {args.binding!r}\n")
            return EXIT_BAD_ARGS
        hook_input: dict[str, JsonValue] = json.loads(inp.read())
        if not isinstance(hook_input, dict):
            raise ValueError("hook input is not a JSON object")
    except (ValueError, OSError) as exc:
        err.write(f"bad hook input: {exc}\n")
        return EXIT_BAD_INPUT
    try:
        receipt_client = client if client is not None else _load_client()
    except (ImportError, AttributeError) as exc:
        err.write(f"receipt-mode client unavailable: {exc}\n")
        return EXIT_NO_CLIENT
    stop = threading.Event()
    if client is None:
        threading.Thread(
            target=watch_parent,
            args=(stop,),
            kwargs={"parent_pid": parent_pid},
            daemon=True,
        ).start()
    try:
        result = HandlerClaudeCodeHookAdapter(receipt_client).handle(
            ModelHookAdapterRequest(binding=binding, hook_input=hook_input)
        )
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        err.write(f"adapter failed: {type(exc).__name__}: {exc}\n")
        return EXIT_FAILED
    finally:
        stop.set()
    if result.hook_output is not None:
        out.write(json.dumps(result.hook_output))
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
