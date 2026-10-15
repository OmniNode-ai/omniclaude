# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""HandlerClaudeCodeHookAdapter and the onex-claude-code-hook entry (OMN-18531, T0.3 AC1, AC10, AC11)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import yaml

from omniclaude.hooks.topics import TopicBase
from omniclaude.nodes.node_claude_code_hook_adapter_effect.enums import (
    EnumClientMaxMode,
    EnumClientVerdictAction,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers.handler_claude_code_hook_adapter import (
    HandlerClaudeCodeHookAdapter,
    build_command_payload,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers.handler_claude_code_hook_cli import (
    EXIT_BAD_INPUT,
    EXIT_NO_CLIENT,
    main,
    watch_parent,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers.handler_client_bindings_loader import (
    load_client_section,
)
from omniclaude.nodes.node_claude_code_hook_adapter_effect.models import (
    ModelClientSection,
    ModelHookAdapterRequest,
    ModelReceiptEvent,
)

from .conftest import make_binding

if TYPE_CHECKING:
    from pydantic import JsonValue

pytestmark = pytest.mark.unit

TESTS_DIR = Path(__file__).parent
REPO = Path(__file__).resolve().parents[4]
EVENT = TopicBase.CLAUDE_CODE_HOOK_ADAPTED.value
HOOK_INPUT: dict[str, JsonValue] = {
    "session": {"id": "s-1"},
    "input": {"prompt": "do the thing", "extra": "never copied"},
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class RecordingClient:
    def __init__(self, *payloads: dict[str, JsonValue]) -> None:
        self.payloads = payloads
        self.calls: list[dict[str, object]] = []

    def publish_and_await(self, **kwargs: object) -> tuple[ModelReceiptEvent, ...]:
        self.calls.append(kwargs)
        return tuple(ModelReceiptEvent(topic=EVENT, payload=p) for p in self.payloads)


def _handle(binding, *payloads):
    client = RecordingClient(*payloads)
    out = HandlerClaudeCodeHookAdapter(client).handle(
        ModelHookAdapterRequest(binding=binding, hook_input=HOOK_INPUT)
    )
    return out, client


def test_ac1_payload_is_drawn_only_from_the_hook_input(replacing_binding) -> None:
    assert build_command_payload(replacing_binding, HOOK_INPUT) == {
        "session_id": "s-1",
        "prompt": "do the thing",
    }
    _, client = _handle(replacing_binding, {"action": "proceed_native"})
    (call,) = client.calls
    assert call["payload"] == {"session_id": "s-1", "prompt": "do the thing"}
    assert call["topic"] == replacing_binding.command_topic


def test_an_absent_source_is_null_not_an_error(replacing_binding) -> None:
    assert build_command_payload(replacing_binding, {}) == {
        "session_id": None,
        "prompt": None,
    }


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ({"action": "answer", "text": "hi"}, {"result": "hi"}),
        ({"action": "refuse", "text": "no"}, {"deny": "no"}),
        ({"action": "proceed_native"}, None),
        ({"action": "native"}, None),
        ({"action": "none"}, None),
    ],
)
def test_ac1_output_is_only_the_hooks_shape(replacing_binding, reply, expected) -> None:
    out, _ = _handle(replacing_binding, reply)
    assert out.hook_output == expected


def test_install_maps_to_messages_only_when_the_hash_matches(replacing_binding) -> None:
    text = json.dumps([{"role": "user", "content": "x"}])
    ok, _ = _handle(
        replacing_binding,
        {"action": "install", "text": text, "package_sha256": sha(text)},
    )
    assert ok.hook_output == {"messages": [{"role": "user", "content": "x"}]}
    bad, _ = _handle(
        replacing_binding,
        {"action": "install", "text": text, "package_sha256": "0" * 64},
    )
    assert bad.hook_output is None
    assert bad.client_verdict.action is EnumClientVerdictAction.NATIVE


def test_ac11_inject_is_additional_context_only_on_a_hash_match(
    additive_binding,
) -> None:
    ok, _ = _handle(
        additive_binding,
        {"action": "inject", "text": "ctx", "package_sha256": sha("ctx")},
    )
    assert ok.hook_output == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "ctx",
        }
    }
    mismatch, _ = _handle(
        additive_binding,
        {"action": "inject", "text": "ctx", "package_sha256": sha("other")},
    )
    assert mismatch.hook_output is None


def _chunks(text: str, record_id: str = "rec-1") -> list[dict[str, JsonValue]]:
    parts = [text[i : i + 4] for i in range(0, len(text), 4)]
    return [
        {"record_id": record_id, "chunk_index": i, "chunk_total": len(parts), "data": p}
        for i, p in enumerate(parts)
    ]


def _verdict(text: str, action: str = "answer") -> dict[str, JsonValue]:
    return {
        "action": action,
        "record_id": "rec-1",
        "package_sha256": sha(text),
    }


def test_ac10_chunks_are_reassembled_by_record_id_in_index_order(
    replacing_binding,
) -> None:
    text = "the full reply that did not fit in one message"
    shuffled = list(reversed(_chunks(text)))
    out, _ = _handle(replacing_binding, *shuffled, _verdict(text))
    assert out.hook_output == {"result": text}


def test_ac10_a_missing_chunk_is_never_a_reply(replacing_binding) -> None:
    text = "the full reply that did not fit in one message"
    chunks = _chunks(text)
    del chunks[2]
    out, _ = _handle(replacing_binding, *chunks, _verdict(text))
    assert out.hook_output is None
    assert out.client_verdict.action is EnumClientVerdictAction.NATIVE


def test_ac10_a_missing_chunk_is_deny_when_the_binding_refuses(
    replacing_binding,
) -> None:
    refusing = make_binding(unverified_action=EnumClientVerdictAction.REFUSE)
    text = "the full reply that did not fit in one message"
    chunks = _chunks(text)[:-1]
    out, _ = _handle(refusing, *chunks, _verdict(text))
    assert out.hook_output == {"deny": ""}


def test_ac10_chunks_of_another_record_do_not_mix_in(replacing_binding) -> None:
    text = "the full reply that did not fit in one message"
    out, _ = _handle(
        replacing_binding, *_chunks(text), *_chunks("poison", "rec-2"), _verdict(text)
    )
    assert out.hook_output == {"result": text}


def test_ac10_a_hash_mismatch_on_reassembly_is_native(replacing_binding) -> None:
    text = "the full reply that did not fit in one message"
    verdict = _verdict(text)
    verdict["package_sha256"] = sha("different")
    out, _ = _handle(replacing_binding, *_chunks(text), verdict)
    assert out.hook_output is None


def test_a_reply_with_no_verdict_is_the_bindings_fallback(replacing_binding) -> None:
    out, _ = _handle(replacing_binding)
    assert out.client_verdict.action is EnumClientVerdictAction.NATIVE


# --- the console entry -------------------------------------------------------------


def _section(*bindings) -> ModelClientSection:
    return ModelClientSection(
        default_max_mode=EnumClientMaxMode.OBSERVE,
        host_max_modes={"lab": EnumClientMaxMode.REQUIRED},
        bindings=bindings,
    )


def test_entry_prints_the_max_mode_first_then_only_the_hook_shape(
    replacing_binding, monkeypatch
) -> None:
    monkeypatch.setenv("ONEX_CLIENT_HOST", "lab")
    out, err = io.StringIO(), io.StringIO()
    code = main(
        ["--binding", "delegation"],
        client=RecordingClient({"action": "refuse", "text": "no"}),
        stdin=io.StringIO(json.dumps(HOOK_INPUT)),
        stdout=out,
        stderr=err,
        section=_section(replacing_binding),
    )
    assert code == 0
    assert out.getvalue() == '{"deny": "no"}'
    assert err.getvalue().splitlines()[0] == "onex-claude-code-hook max_mode=required"


def test_entry_prints_nothing_for_a_native_verdict(replacing_binding) -> None:
    out = io.StringIO()
    code = main(
        ["--binding", "delegation"],
        client=RecordingClient({"action": "proceed_native"}),
        stdin=io.StringIO("{}"),
        stdout=out,
        stderr=io.StringIO(),
        section=_section(replacing_binding),
    )
    assert (code, out.getvalue()) == (0, "")


def test_entry_exits_nonzero_with_empty_stdout_on_garbage_input(
    replacing_binding,
) -> None:
    out = io.StringIO()
    code = main(
        ["--binding", "delegation"],
        client=RecordingClient(),
        stdin=io.StringIO("not json"),
        stdout=out,
        stderr=io.StringIO(),
        section=_section(replacing_binding),
    )
    assert (code, out.getvalue()) == (EXIT_BAD_INPUT, "")


def test_entry_exits_nonzero_when_the_client_is_unavailable(
    replacing_binding, monkeypatch
) -> None:
    monkeypatch.setenv("ONEX_HOOK_RECEIPT_CLIENT", "no_such_module_omn18531:Client")
    out = io.StringIO()
    code = main(
        ["--binding", "delegation"],
        stdin=io.StringIO("{}"),
        stdout=out,
        stderr=io.StringIO(),
        section=_section(replacing_binding),
    )
    assert (code, out.getvalue()) == (EXIT_NO_CLIENT, "")


def test_entry_exits_nonzero_when_the_client_raises(replacing_binding) -> None:
    class Boom:
        def publish_and_await(self, **kwargs: object) -> tuple[ModelReceiptEvent, ...]:
            raise TimeoutError("deadline")

    out = io.StringIO()
    code = main(
        ["--binding", "delegation"],
        client=Boom(),
        stdin=io.StringIO("{}"),
        stdout=out,
        stderr=io.StringIO(),
        section=_section(replacing_binding),
    )
    assert code != 0
    assert out.getvalue() == ""


def _write_fixture_contract(tmp_path: Path, binding) -> Path:
    contract = tmp_path / "adapter-contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "client_bindings": {
                    "claude_code": json.loads(_section(binding).model_dump_json())
                }
            }
        )
    )
    return contract


def _env(contract: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        ONEX_CLAUDE_CODE_ADAPTER_CONTRACT=str(contract),
        ONEX_HOOK_RECEIPT_CLIENT="fake_receipt_client:FakeClient",
        PYTHONPATH=os.pathsep.join([str(TESTS_DIR), env.get("PYTHONPATH", "")]),
    )
    env.update(extra)
    return env


def test_ac1_the_real_command_hosts_no_node_handler(
    replacing_binding, tmp_path
) -> None:
    contract = _write_fixture_contract(tmp_path, replacing_binding)
    probe = (
        "import json, sys\n"
        "from omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers."
        "handler_claude_code_hook_cli import main\n"
        "code = main(['--binding', 'delegation'])\n"
        "loaded = sorted(m for m in sys.modules if '.nodes.node_' in m and "
        "'node_claude_code_hook_adapter_effect' not in m)\n"
        "sys.stderr.write('LOADED=' + json.dumps(loaded))\n"
        "raise SystemExit(code)\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe],
        input=json.dumps(HOOK_INPUT),
        capture_output=True,
        text=True,
        env=_env(contract, FAKE_REPLY=json.dumps([{"action": "answer", "text": "hi"}])),
        timeout=60,
        cwd=REPO,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout == '{"result": "hi"}'
    assert "LOADED=[]" in done.stderr, done.stderr


def test_the_entry_exits_when_its_parent_goes_away(replacing_binding, tmp_path) -> None:
    contract = _write_fixture_contract(tmp_path, replacing_binding)
    env = _env(contract, FAKE_SLEEP="1")
    stdin_file = tmp_path / "stdin.json"
    stdin_file.write_text(json.dumps(HOOK_INPUT))
    ready = tmp_path / "stderr.txt"
    parent = (
        "import subprocess, sys, time\n"
        f"fh = open({str(stdin_file)!r})\n"
        "p = subprocess.Popen([sys.executable, '-m', "
        "'omniclaude.nodes.node_claude_code_hook_adapter_effect.handlers."
        "handler_claude_code_hook_cli', '--binding', 'delegation'], stdin=fh, "
        f"stdout=subprocess.DEVNULL, stderr=open({str(ready)!r}, 'w'))\n"
        "end = time.monotonic() + 30\n"
        f"while 'max_mode' not in open({str(ready)!r}).read() and time.monotonic() < end:\n"
        "    time.sleep(0.1)\n"
        "print(p.pid, flush=True)\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", parent],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        cwd=REPO,
        check=True,
    )
    pid = int(out.stdout.strip())
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.25)
    os.kill(pid, 9)
    pytest.fail("the adapter outlived its parent")


class _FakeEvent(threading.Event):
    """An Event whose wait is recorded, to prove the watcher blocks and never spins."""

    def __init__(self, returns: list[bool]) -> None:
        super().__init__()
        self.returns = returns
        self.waits: list[float] = []

    def wait(self, timeout: float | None = None) -> bool:
        assert timeout is not None
        self.waits.append(timeout)
        return self.returns.pop(0)


def test_the_parent_watch_blocks_between_polls_and_fires_once_on_orphaning() -> None:
    pids = iter([100, 100, 100, 1])
    fired: list[int] = []
    event = _FakeEvent([False, False, False])
    watch_parent(
        event,
        get_ppid=lambda: next(pids),
        on_orphaned=lambda: fired.append(1),
        poll_seconds=0.5,
    )
    assert fired == [1]
    assert event.waits == [0.5, 0.5, 0.5]


def test_the_parent_watch_returns_when_stopped() -> None:
    stop = threading.Event()
    stop.set()
    watch_parent(stop, get_ppid=lambda: 100, on_orphaned=lambda: pytest.fail("fired"))


def test_the_shipped_contract_loads_an_empty_inventory_until_a_binding_ticket_adds_rows() -> (
    None
):
    section = load_client_section()
    assert section.bindings == ()
