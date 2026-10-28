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
import re
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


def test_a_listed_model_that_404s_on_completion_is_not_offered(tmp_path: Path) -> None:
    """AC1: gpt-4.1-nano is listed but deprecated, gpt-4o-2024-05-13 is gone; both are
    marked unavailable with the provider's reason. A 429 model is kept, busy."""
    models = ["gpt-4.1", "gpt-4.1-nano", "gpt-4o-2024-05-13", "gpt-4o-mini"]
    chat = {
        "gpt-4.1-nano": (404, DEPRECATED),
        "gpt-4o-2024-05-13": (404, NOT_FOUND),
        "gpt-4o-mini": (429, {"error": {"message": "Rate limit reached"}}),
    }
    with _provider(models, chat) as served:
        cat = _catalogue(tmp_path, served["url"], [])
        out = _run(
            tmp_path,
            cat,
            MENU + 'choose_models openai <<< "1,2"\necho "chosen=$CHOSEN_OPENAI"',
        )
    menu = out.split("---")[1]
    assert "rc=0" in out
    assert " 1) gpt-4.1" in menu and "gpt-4o-mini  (busy just now, HTTP 429)" in menu
    numbered = re.findall(r"^\s+\d+\) (\S+)", menu, re.M)
    assert numbered == ["gpt-4.1", "gpt-4o-mini"]
    assert "Not offered, your key could not call these:" in menu
    assert (
        "✗ gpt-4.1-nano: HTTP 404: The model `gpt-4.1-nano` has been deprecated" in menu
    )
    assert "✗ gpt-4o-2024-05-13: HTTP 404: The model does not exist" in menu
    assert set(served["auth"]) == {
        f"Bearer {KEY}"
    }  # the probe used the developer's key
    assert all(b.get("max_completion_tokens") == 1 for b in served["bodies"])


def test_a_recommendation_naming_a_404_model_is_dropped_with_the_reason(
    tmp_path: Path,
) -> None:
    """AC2: the routing contract recommends gpt-4.1-nano first; it 404s, so the
    recommendation is dropped, the reason is recorded, and Enter takes the next."""
    models = ["gpt-4.1", "gpt-4.1-nano", "gpt-4o"]
    chat = {"gpt-4.1-nano": (404, DEPRECATED)}
    with _provider(models, chat) as served:
        cat = _catalogue(tmp_path, served["url"], ["gpt-4.1-nano", "gpt-4o"])
        out = _run(
            tmp_path,
            cat,
            MENU
            + 'echo "recommended=$RECOMMENDED"; echo "list=$(echo $MODEL_LIST)"\n'
            + 'echo "unavailable=$MODEL_UNAVAILABLE"\n'
            + 'choose_models openai <<< ""\necho "chosen=$CHOSEN_OPENAI"',
        )
    assert "list=gpt-4o gpt-4.1" in out
    assert "recommended=1" in out  # gpt-4o, renumbered; the 404 recommendation is gone
    assert "unavailable=gpt-4.1-nano: HTTP 404" in out and "deprecated" in out
    assert "chosen=gpt-4o" in out
    assert "gpt-4.1-nano  (recommended)" not in out


def test_a_provider_whose_every_model_fails_is_unusable_at_the_menu(
    tmp_path: Path,
) -> None:
    """AC3: preflight drops the provider with the reason; it is no longer in
    MODELS, so phase 3 (which loops over MODELS) never sets it up."""
    models = ["gpt-4.1-nano", "gpt-4o-2024-05-13", "o4-mini-2025-04-16"]
    chat = dict.fromkeys(models, (404, NOT_FOUND))
    with _provider(models, chat) as served:
        cat = _catalogue(tmp_path, served["url"], [])
        out = _run(
            tmp_path,
            cat,
            'if key_models openai "' + KEY + '"; then echo OFFERED; else\n'
            "  drop_unlisted openai; fi\n"
            'echo "models=[$MODELS] skipped=[$SKIPPED] result=$RESULT"',
        )
    assert "OFFERED" not in out
    assert (
        "✗ OpenAI: none of the 3 models it lists answered a test call on your key"
        in out
    )
    assert "Nothing was stored for it" in out
    assert "models=[gemini] skipped=[openai] result=fail:none of the 3 models" in out


def test_a_probe_that_cannot_connect_leaves_no_model_offered(tmp_path: Path) -> None:
    """A provider that does not answer the test call at all is unusable, not offered."""
    with _provider(["gpt-4.1"], {}) as served:
        cat = _catalogue(
            tmp_path, served["url"], [], endpoint="http://127.0.0.1:9/chat"
        )
        out = _run(tmp_path, cat, MENU + 'echo "unavailable=$MODEL_UNAVAILABLE"')
    assert "rc=1" in out
    assert "gpt-4.1: it did not answer" in out


def test_a_model_that_wants_max_tokens_is_retried_and_offered(tmp_path: Path) -> None:
    """A 400 naming the token-limit parameter is retried with the other spelling."""
    chat = {"gpt-3.5": (200, {"_needs": "max_tokens"})}
    with _provider(["gpt-3.5"], chat) as served:
        cat = _catalogue(tmp_path, served["url"], [])
        out = _run(tmp_path, cat, MENU + 'echo "list=$MODEL_LIST"')
    assert "rc=0" in out and "list=gpt-3.5" in out
    assert [("max_tokens" in b) for b in served["bodies"]] == [False, True]


def test_the_key_is_sent_by_header_on_stdin_never_as_an_argument() -> None:
    body = _function("probe_model")
    assert "| curl -sS -m 20 -H @- " in body
    assert "Authorization: Bearer %s" in body
