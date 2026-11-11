# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21465: onboarding probes each model on the developer's key before the menu.

A name in the provider's model list is not proof the key can call it: a
deprecated or non-chat model is listed too, and the developer picks it and fails
at phase 3. The picker now sends one one-token completion per listed model and
offers, and recommends, only those that answered. A 429 means busy, not unusable
(OMN-21464), so it stays. The provider is stubbed; no real provider is called.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
HANDLER = (
    REPO / "src/omniclaude/nodes/node_skill_omninode_dev_setup_orchestrator"
    "/handler_onboarding_preflight.sh"
)
KEY = "sk-proj-omn21465-test"
SCRIPT = REPO / "plugins/onex/skills/_bin/lab-onboarding.sh"
FUNCTIONS = [
    "omnimarket_file",
    "catalogue_row",
    "to_ere",
    "recommended_order",
    "recommended_basis",
    "list_in_order",
    "offered_models",
    "list_recommended_first",
    "probe_model",
    "probe_listed",
    "key_models",
    "drop_unlisted",
    "choose_models",
    "parse_ordered_choice",
    "comma_list",
    "set_chosen_models",
]

DEPRECATED = {
    "error": {"message": "The model `gpt-4.1-nano` has been deprecated", "code": 404}
}
NOT_FOUND = {"error": {"message": "The model does not exist", "code": 404}}


def _function(name: str, source: Path = HANDLER) -> str:
    lines = source.read_text().splitlines(keepends=True)
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}() {{"))
    if lines[start].rstrip().endswith("}"):
        return lines[start]
    end = next(i for i in range(start, len(lines)) if lines[i].rstrip() == "}")
    return "".join(lines[start : end + 1])


def _start(
    models: list[str], chat: dict[str, tuple[int, Any]]
) -> tuple[ThreadingHTTPServer, dict[str, Any]]:
    seen: dict[str, Any] = {"auth": [], "bodies": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a: object) -> None:
            pass

        def _send(self, code: int, body: object) -> None:
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            self._send(200, {"data": [{"id": m} for m in models]})

        def do_POST(self) -> None:
            body = json.loads(
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
            )
            seen["auth"].append(self.headers.get("Authorization"))
            seen["bodies"].append(body)
            code, payload = chat.get(body["model"], (200, {"choices": []}))
            if isinstance(payload, dict) and payload.get("_needs") not in (
                None,
                *body,
            ):
                code, payload = (
                    400,
                    {"error": {"message": f"use {payload['_needs']} instead"}},
                )
            self._send(code, payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    seen["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    return server, seen


@contextmanager
def _provider(
    models: list[str], chat: dict[str, tuple[int, Any]]
) -> Iterator[dict[str, Any]]:
    server, seen = _start(models, chat)
    try:
        yield seen
    finally:
        server.shutdown()
        server.server_close()


def _catalogue(
    tmp_path: Path, base: str, defaults: list[str], endpoint: str | None = None
) -> Path:
    path = tmp_path / "catalogue.yaml"
    listing = "".join(f'      - "{m}"\n' for m in defaults)
    path.write_text(
        "providers:\n"
        "  - provider: openai\n"
        f'    endpoint_url: "{endpoint or base + "/chat"}"\n'
        f'    models_url: "{base}/models"\n'
        "    default_models:\n"
        f"{listing}"
        "recommended_order:\n"
        "  onboarding: baseline\n"
        "  orders:\n"
        "    baseline:\n"
        "      models: default_models\n"
        '      basis: "OMN-21215"\n'
    )
    return path


def _run(tmp_path: Path, catalogue: Path, script: str) -> str:
    funcs = "\n".join(_function(f) for f in FUNCTIONS)
    prelude = (
        "set -uo pipefail\n"
        + _function("in_list", SCRIPT)
        + _function("drop_model", SCRIPT)
        + "LOG=/dev/null; TAB=$(printf '\\t'); MODELS='openai gemini'; SKIPPED=''\n"
        "say() { printf '%s\\n' \"$*\"; }\n"
        "ram_gb() { echo 16; }\n"
        'provider_label() { case "$1" in openai) echo OpenAI ;; *) echo "$1" ;; esac; }\n'
        'set_result() { RESULT="$2"; }\n'
        "CHOSEN_OPENAI=''; CHOSEN_GEMINI=''; CHOSEN_OPENROUTER=''; CHOSEN_OLLAMA=''\n"
        "MODEL_LIST=''; MODEL_LIST_ERR=''; RECOMMENDED=''; REC_BASIS=''\n"
        "WORKSPACE=/nonexistent; CATALOGUE_REL=omnimarket/x.yaml\n"
    )
    done = subprocess.run(
        ["/bin/bash", "-c", f"{prelude}{funcs}\n{script}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
            "ONBOARD_TEST_CATALOGUE": str(catalogue),
        },
    )
    assert done.returncode == 0, done.stderr
    return done.stdout


MENU = f'key_models openai "{KEY}"; rc=$?; echo "rc=$rc"; echo "---"\n'


def test_the_key_is_sent_by_header_on_stdin_never_as_an_argument() -> None:
    body = _function("probe_model")
    assert "| curl -sS -m 20 -H @- " in body
    assert "Authorization: Bearer %s" in body
