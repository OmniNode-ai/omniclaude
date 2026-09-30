# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Per-call hook work that bought nothing on the operator Mac (OMN-20118).

Measured 2026-09-30 on the operator Mac, one plain Bash tool call:

* ``post_tool_use_output_capture_metadata.sh`` backgrounds one interpreter per
  Bash call that spent 1.13 s of CPU importing ``omnibase_core`` through
  ``omnimarket.nodes.node_emit_daemon.client``, only to find no emit daemon
  socket and drop the event. The socket protocol is newline JSON that the
  stdlib client in ``emit_client_wrapper`` already speaks, so the heavy import
  is pure cost. It stays out of every hook process.
* ``hook_lane_attribution._sidecar_candidates`` globbed every project
  directory under ``~/.claude/projects`` (1,476 of them, 37 ms) for every
  journalled record, even when the first, transcript-derived candidate held
  the sidecar. The glob is a fallback and now only runs when the direct
  candidates did not answer; the answer is unchanged.
* The capture contracts parse through libyaml when PyYAML carries it; the
  parsed value is identical.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
_ROOT = Path(__file__).parents[3]
_HOOKS_LIB = _ROOT / "plugins/onex/hooks/lib"
if str(_HOOKS_LIB) not in sys.path:
    sys.path.insert(0, str(_HOOKS_LIB))


def _run_isolated(code: str, tmp_path: Path) -> dict[str, object]:
    """Run ``code`` in a fresh interpreter so ``sys.modules`` is its own."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["HOME"] = str(tmp_path)
    env["OMNICLAUDE_EMIT_SOCKET"] = str(tmp_path / "absent" / "emit.sock")
    proc = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=_HOOKS_LIB,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_failed_socket_emit_never_imports_the_omnimarket_stack(
    tmp_path: Path,
) -> None:
    result = _run_isolated(
        """
        import json, sys
        sys.path.insert(0, ".")
        import emit_client_wrapper
        ok = emit_client_wrapper.emit_event(
            "tool.executed", {"session_id": "s-1", "tool_name": "Bash"}
        )
        heavy = sorted(
            m for m in sys.modules
            if m.split(".")[0] in {"omnimarket", "omnibase_core", "omnibase_infra"}
        )
        print(json.dumps({"ok": ok, "heavy": heavy[:5], "n": len(heavy)}))
        """,
        tmp_path,
    )
    # The emit still fails, and still reports it: there is no daemon.
    assert result["ok"] is False
    assert result["n"] == 0, result["heavy"]


def test_the_metadata_hook_process_never_imports_the_omnimarket_stack(
    tmp_path: Path,
) -> None:
    result = _run_isolated(
        """
        import io, json, sys
        sys.path.insert(0, ".")
        sys.stdin = io.StringIO(json.dumps({
            "tool_name": "Bash",
            "session_id": "s-1",
            "tool_use_id": "toolu-1",
            "tool_input": {"command": "true"},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
        }))
        import tool_output_capture_metadata as m
        rc = m.main()
        heavy = sorted(
            n for n in sys.modules
            if n.split(".")[0] in {"omnimarket", "omnibase_core", "omnibase_infra"}
        )
        print(json.dumps({"rc": rc, "heavy": heavy[:5], "n": len(heavy)}))
        """,
        tmp_path,
    )
    assert result["rc"] == 0
    assert result["n"] == 0, result["heavy"]


def test_the_socket_client_speaks_the_daemon_protocol() -> None:
    """The stdlib client is what now carries every emit: prove the wire shape."""
    import shutil
    import socket
    import tempfile
    import threading

    import emit_client_wrapper

    # AF_UNIX paths are capped near 104 bytes on macOS; pytest's tmp_path
    # there is longer than that, so the socket gets a short directory of its own.
    short_dir = Path(tempfile.mkdtemp(prefix="emit", dir="/tmp"))  # noqa: S108
    sock_path = short_dir / "e.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    seen: list[dict[str, object]] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            buf = b""
            while not buf.endswith(b"\n"):
                buf += conn.recv(4096)
            seen.append(json.loads(buf))
            conn.sendall(b'{"status": "queued", "event_id": "e-1"}\n')

    t = threading.Thread(target=serve)
    t.start()
    try:
        client = emit_client_wrapper._create_emit_client(str(sock_path), 5.0)
        assert client.emit_sync("tool.executed", {"k": "v"}) == "e-1"
    finally:
        t.join(timeout=10)
        server.close()
        shutil.rmtree(short_dir, ignore_errors=True)
    assert seen == [{"event_type": "tool.executed", "payload": {"k": "v"}}]


def test_the_projects_glob_is_skipped_when_the_transcript_candidate_answers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hook_lane_attribution as la

    projects = tmp_path / "projects"
    session = "11111111-2222-3333-4444-555555555555"
    agent = "a0123456789abcdef"
    subagents = projects / "proj" / session / "subagents"
    subagents.mkdir(parents=True)
    (subagents / f"agent-{agent}.meta.json").write_text(
        json.dumps({"name": "lane-x"}), encoding="utf-8"
    )
    monkeypatch.setenv(la.CLAUDE_PROJECTS_ENV, str(projects))

    globbed: list[str] = []
    real_glob = Path.glob

    def counting_glob(self: Path, pattern: str, *a: object, **k: object):  # type: ignore[no-untyped-def]
        globbed.append(pattern)
        return real_glob(self, pattern, *a, **k)

    monkeypatch.setattr(Path, "glob", counting_glob)
    transcript = projects / "proj" / f"{session}.jsonl"
    assert la.sidecar_lane_name(str(transcript), session, agent) == "lane-x"
    assert globbed == []

    # With no transcript path the glob is the only operand, and still answers.
    assert la.sidecar_lane_name(None, session, agent) == "lane-x"
    assert len(globbed) == 1


def test_the_capture_contracts_parse_through_libyaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pure-Python parser is never reached when libyaml is present.

    Existing contract tests prove the parsed value; this proves the loader.
    """
    yaml = pytest.importorskip("yaml")
    if not getattr(yaml, "__with_libyaml__", False):
        pytest.skip("PyYAML built without libyaml")
    import hook_edge_lane

    from omniclaude.hooks import capture_redaction

    def refuse(*_a: object, **_k: object) -> object:
        raise AssertionError("pure-Python yaml.safe_load on the hook hot path")

    monkeypatch.setattr(yaml, "safe_load", refuse)
    capture_redaction._load.cache_clear()
    try:
        assert capture_redaction.load_contract() is not None
    finally:
        capture_redaction._load.cache_clear()
    edge = _ROOT / "plugins/onex/hooks/contracts/hook_edge_lane.yaml"
    assert hook_edge_lane.load_contract(edge) is not None
