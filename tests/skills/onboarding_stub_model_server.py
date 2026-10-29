# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A keyless OpenAI-compatible model server for the onboarding verification (OMN-20700).

The onboarding verification workflow runs ``lab-onboarding.sh --provider local`` on a
fresh macOS runner. Phase 3 then sets the local model up and runs real ``onex
delegate`` calls against it, so the run proves delegation end to end with no
provider key and no private repository. This server is that local model: it
answers every chat completion with ``hello``, the one word the onboarding's test
delegation asks for, and appends one line per completion to ``--log`` so the
workflow can show the delegations reached a model.

Standard library only: it runs on the runner's system python before the
onboarding has installed anything.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANSWER = "hello"


class Handler(BaseHTTPRequestHandler):
    model = "onboarding-stub"
    log_path: Path

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"stub-model: {self.command} {self.path} -> {fmt % args}", flush=True)

    def _json(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(
                200,
                {
                    "object": "list",
                    "data": [{"id": self.model, "object": "model", "owned_by": "ci"}],
                },
            )
        else:
            self._json(200, {"status": "ok", "model": self.model})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": {"message": "request body is not JSON"}})
            return
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": {"message": f"no route {self.path}"}})
            return
        model = req.get("model") or self.model
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "path": self.path,
                        "model": model,
                        "stream": bool(req.get("stream")),
                    }
                )
                + "\n"
            )
        created = int(time.time())
        if req.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in (
                ({"role": "assistant", "content": ANSWER}, None),
                ({}, "stop"),
            ):
                chunk = {
                    "id": "chatcmpl-stub",
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            return
        self._json(
            200,
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ANSWER},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 1,
                    "total_tokens": 13,
                },
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--model", default=Handler.model)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    Handler.model = args.model
    Handler.log_path = args.log
    args.log.touch()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
