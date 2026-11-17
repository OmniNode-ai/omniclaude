# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Installed E2E probe for native delegation and its counted fallback provider.

Run from a built installation with --python, --canonical-installer, --local-url,
--local-model and --fallback-history. Only private HOME/profile/store paths are
used. The JSON artifact preserves native inference and fallback observations.
"""

import argparse
import json
import os
import subprocess
import threading
import time
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", type=Path)
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--python")
    parser.add_argument("--prompt", default="Render the isolated feasibility answer.")
    parser.add_argument("--fallback-history", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--canonical-installer", type=Path)
    parser.add_argument("--local-url")
    parser.add_argument("--local-model")
    args = parser.parse_args()
    root = args.artifact_dir.resolve() / ("probe-" + str(time.time_ns()))
    home = root / "home"
    config = home / ".claude"
    config.mkdir(parents=True)
    requests = []
    provider_payloads = []

    class Refuse(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if self.path != "/instrument-control":
                provider_payloads.append(json.loads(body))
            if self.path == "/instrument-control":
                self.send_response(401)
                self.end_headers()
                return
            if "count_tokens" in self.path:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"input_tokens":1}')
                return
            events = [
                (
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": "msg_probe",
                            "type": "message",
                            "role": "assistant",
                            "model": "claude-sonnet-4-20250514",
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 1, "output_tokens": 0},
                        },
                    },
                ),
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "text", "text": ""},
                    },
                ),
                (
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {
                            "type": "text_delta",
                            "text": "BASELINE_ENGINE_CALLED",
                        },
                    },
                ),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                        "usage": {"output_tokens": 1},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
            body = "".join(
                f"event: {name}\ndata: {json.dumps(event)}\n\n"
                for name, event in events
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Refuse)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    evidence = {"status": "failed"}
    try:
        control = HTTPConnection("127.0.0.1", server.server_port, timeout=2)
        control.request("POST", "/instrument-control", body=b"{}")
        assert control.getresponse().status == 401
        control.close()
        assert requests == ["/instrument-control"], requests
        requests.clear()
        env = {
            key: os.environ[key]
            for key in (
                "PATH",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE",
            )
            if key in os.environ
        }
        env.update(
            HOME=str(home),
            CLAUDE_CONFIG_DIR=str(config),
            ANTHROPIC_API_KEY="sk-ant-probe-invalid-not-a-secret",
            ANTHROPIC_BASE_URL=base,
            CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
            DISABLE_AUTOUPDATER="1",
        )
        if args.python:
            env["PLUGIN_PYTHON_BIN"] = args.python
            env["ONEX_HOOKS_MASK"] = "0x800"
            env["CLAUDE_PROJECT_DIR"] = str(Path.cwd())
            env["OMNICLAUDE_MODE"] = "full"
            env["ONEX_STATE_DIR"] = str(root / "state")
        if args.canonical_installer:
            assert args.python and args.local_url and args.local_model
            onex = str(Path(args.python).with_name("onex"))
            setup = []
            commands = [
                [onex, "local", "init", "--json"],
                [
                    onex,
                    "models",
                    "connect",
                    "isolated-native",
                    "--url",
                    args.local_url,
                    "--model",
                    args.local_model,
                    "--no-test",
                    "--json",
                ],
                [
                    onex,
                    "models",
                    "select-connection",
                    "isolated-native",
                    args.local_model,
                    "--json",
                ],
                [
                    "bash",
                    str(args.canonical_installer.resolve()),
                    "--apply",
                    "--skip-pip",
                    "--skip-smoke",
                    "--python",
                    args.python,
                ],
            ]
            for argv in commands:
                step = subprocess.run(
                    argv,
                    cwd=home,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=90,
                )
                setup.append(
                    {
                        "argv": argv,
                        "exit_code": step.returncode,
                        "stdout": step.stdout,
                        "stderr": step.stderr,
                    }
                )
                (root / "setup.json").write_text(json.dumps(setup, indent=2) + "\n")
                assert step.returncode == 0, (step.stdout + step.stderr)[-3000:]
            # Test the installed interpreter binding and customer opt-in; do
            # not lend the plugin an environment-only interpreter/full mode.
            env.pop("PLUGIN_PYTHON_BIN", None)
            env["OMNICLAUDE_MODE"] = "lite"
        if args.install:
            assert args.plugin
            name = json.loads((args.plugin / ".claude-plugin/plugin.json").read_text())[
                "name"
            ]
            installed = subprocess.run(
                [
                    "claude",
                    "plugin",
                    "install",
                    name,
                    "--marketplace",
                    str(args.plugin.resolve().parent),
                    "--scope",
                    "user",
                    "--json",
                ],
                cwd=home,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
            (root / "plugin-install.json").write_text(
                json.dumps(
                    {
                        "exit_code": installed.returncode,
                        "stdout": installed.stdout,
                        "stderr": installed.stderr,
                    },
                    indent=2,
                )
            )
            assert installed.returncode == 0, installed.stderr
        command = [
            "claude",
            "-p",
            args.prompt,
            "--debug-file",
            str(root / "claude-debug.log"),
            "--setting-sources",
            "user" if args.install or args.canonical_installer else "",
            "--output-format",
            "json",
            "--max-turns",
            "1",
            "--tools",
            "",
            "--strict-mcp-config",
        ]
        if args.plugin and not args.install and not args.canonical_installer:
            command += ["--plugin-dir", str(args.plugin.resolve())]
        try:
            process = subprocess.run(
                command,
                cwd=home,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=150,
            )
            result = json.loads(process.stdout)
            code = process.returncode
            (root / "stderr.txt").write_text(process.stderr)
        except subprocess.TimeoutExpired:
            result = {"is_error": True, "result": "CLI exceeded 150 seconds"}
            code = None
        except json.JSONDecodeError:
            result = {
                "is_error": True,
                "result": "CLI did not emit JSON",
                "stderr": process.stderr[-1500:],
            }
            code = process.returncode
        evidence = {
            "plugin": str(args.plugin) if args.plugin else None,
            "exit_code": code,
            "provider_requests": list(requests),
            "native_provider_requests": list(requests),
            "instrument_control_passed": True,
            "result": result,
        }
        (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
        print(
            json.dumps(
                {
                    "evidence": str(root / "evidence.json"),
                    "exit_code": code,
                    "provider_request_count": len(requests),
                    "answer": result.get("result"),
                    "is_error": result.get("is_error"),
                }
            )
        )
        assert code == 0, f"CLI failed: {result.get('result')}"
        assert result.get("is_error") is False, result
        assert "ONEX_MOD_FEASIBILITY" in result.get("result", ""), (
            "No normal assistant answer"
        )
        assert "blocked by hook" not in result.get("result", ""), (
            "Answer is still a warning"
        )
        assert not requests, f"Unexpected provider requests: {requests}"
        if args.history or args.fallback_history:
            resumed = command.copy()
            resumed[2] = (
                "@claude check retained assistant history."
                if args.fallback_history
                else "Check retained assistant history."
            )
            resumed += ["--resume", result["session_id"]]
            process = subprocess.run(
                resumed,
                cwd=home,
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=150,
            )
            history = json.loads(process.stdout)
            evidence["fallback_provider_requests"] = list(requests)
            evidence["history_result"] = history
            evidence["provider_requests"] = list(requests)
            (root / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
            print(
                json.dumps(
                    {
                        "history_answer": history.get("result"),
                        "provider_request_count": len(requests),
                    }
                )
            )
            assert process.returncode == 0 and history.get("is_error") is False
            if args.fallback_history:
                assert "BASELINE_ENGINE_CALLED" in history.get("result", "")
                assert len(requests) == 1, requests
                assert any(
                    message.get("role") == "assistant"
                    and "ONEX_MOD_FEASIBILITY" in json.dumps(message.get("content"))
                    for payload in provider_payloads
                    for message in payload.get("messages", [])
                ), "Delegated assistant answer did not reach the fallback model"
                evidence["fallback_received_assistant_history"] = True
                (root / "evidence.json").write_text(
                    json.dumps(evidence, indent=2) + "\n"
                )
            else:
                assert "ONEX_HISTORY_PRESENT" in history.get("result", ""), (
                    "Assistant history was not retained"
                )
                assert not requests, requests
    finally:
        try:
            if (
                args.canonical_installer
                and (home / ".omninode/delegation/rollback-manifest.json").is_file()
            ):
                stopped = subprocess.run(
                    [
                        "bash",
                        str(args.canonical_installer.resolve()),
                        "--uninstall",
                        "--python",
                        args.python,
                    ],
                    cwd=home,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=60,
                )
                assert stopped.returncode == 0, stopped.stdout + stopped.stderr
                settings = json.loads((config / "settings.json").read_text())
                assert (
                    settings.get("enabledPlugins", {}).get(
                        "onex-delegation@onex-delegation-local"
                    )
                    is not True
                )
                evidence["off_verified"] = True
                evidence["private_store"] = str(
                    home / ".omninode/delegation/delegation.sqlite"
                )
                (root / "evidence.json").write_text(
                    json.dumps(evidence, indent=2) + "\n"
                )
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
