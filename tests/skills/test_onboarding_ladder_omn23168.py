# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-23168 AC1: onboarding ends by printing the ladder.

A scripted onboarding on a fresh install with one OpenRouter key and two chosen
models prints a numbered list whose lines end in free or paid.

What runs: a fresh HOME with no delegation state; a stub OpenRouter key server
(it answers the provider's model list only to the bearer key this test minted);
the REAL ``onex secret`` and ``onex models`` commands of the omnimarket this
repository pins, with the model-list read pointed at the stub; and the
entrypoint's OWN ``models_cmd`` and ``print_ladder`` functions, cut out of
``lab-onboarding.sh`` and run by bash. The test also reads phase 3 of the
entrypoint to see that it calls ``print_ladder`` after the models are tested
and before the unpinned delegation.

The falsifier is ``uv run pytest tests/skills/test_onboarding_ladder_omn23168.py``.
The ticket named a shell script for it; the canonical-file-shape ratchet refuses
a new shell script anywhere, so the same test is a pytest.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests.skills.test_onboarding_model_probe_omn21465 import SCRIPT, _function

pytestmark = pytest.mark.unit

KEY = "sk-or-v1-synthetic-omn23168-key-never-printed"
PAID_MODEL = "gpt-4o"
FREE_MODEL = "google/gemma-4-31b-it:free"

# The real onex's command groups, with the provider's model-list read pointed at
# the stub key server named by LADDER_STUB_URL.
ONEX_SHIM = """\
import json, os, sys, urllib.parse, urllib.request
from omnimarket.handlers.routing import byok_model_discovery as discovery
from omnimarket.nodes.node_model_setup_effect.handlers import handler_model_setup as setup


def get_models_json(*, url, timeout_seconds, extra_headers=None):
    target = os.environ["LADDER_STUB_URL"] + urllib.parse.urlparse(url).path
    request = urllib.request.Request(target, headers=dict(extra_headers or {}))
    with urllib.request.urlopen(request, timeout=timeout_seconds) as reply:
        return json.load(reply)


discovery.get_models_json = get_models_json
setup.get_models_json = get_models_json
from omnimarket.cli.cli_secret import models_group, secret_group

group = {"models": models_group, "secret": secret_group}[sys.argv[1]]
group.main(args=sys.argv[2:], prog_name="onex " + sys.argv[1], standalone_mode=True)
"""


@contextmanager
def _key_server() -> Iterator[tuple[str, list[str]]]:
    """A stub OpenRouter: the model list, only for the minted bearer key."""
    reads: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            ok = self.headers.get("Authorization") == f"Bearer {KEY}"
            reads.append(f"{self.path} {'ok' if ok else 'rejected'}")
            body = json.dumps(
                {"data": [{"id": m} for m in (PAID_MODEL, FREE_MODEL)]}
                if ok
                else {"error": "bad key"}
            ).encode()
            self.send_response(200 if ok else 401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", reads
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def ladder_lines_ok(text: str) -> bool:
    """Numbered lines 1. and 2., in the order the key's models were given,
    each ending in its cost class: paid, then free."""
    lines = {
        match.group(1): line
        for line in text.splitlines()
        if (match := re.match(r"^\s*(\d+)\. ", line))
    }
    first, second = lines.get("1"), lines.get("2")
    return bool(
        first
        and second
        and re.search(rf"OpenRouter +{re.escape(PAID_MODEL)} +paid$", first)
        and FREE_MODEL in second
        and second.endswith(" free")
    )


class Install:
    """A fresh HOME and an onex shim over the real command groups."""

    def __init__(self, root: Path, stub_url: str, onex: Path | None = None) -> None:
        self.home = root / "home"
        self.home.mkdir()
        self.workspace = root / "workspace"
        shim = root / "onex_shim.py"
        shim.write_text(ONEX_SHIM)
        self.onex = self.workspace / ".onex-dispatch-venv/bin/onex"
        self.onex.parent.mkdir(parents=True)
        self.onex.write_text(
            "#!/bin/bash\n"
            f'exec env -u PYTHONPATH LADDER_STUB_URL="{stub_url}" '
            f'"{sys.executable}" "{shim}" "$@"\n'
        )
        self.onex.chmod(0o755)
        self.log = root / "run.log"
        self.log.write_text("")

    def run_onex(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.onex), *args],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.home)},
        )

    def print_ladder(self, script_text: str | None = None) -> tuple[int, str]:
        """The entrypoint's own models_cmd and print_ladder, run by bash."""
        body = _function("models_cmd", SCRIPT) + _function("print_ladder", SCRIPT)
        if script_text is not None:
            body = script_text
        done = subprocess.run(
            [
                "/bin/bash",
                "-c",
                "set -uo pipefail\n"
                f'WORKSPACE="{self.workspace}"\n'
                f'LOG="{self.log}"\n'
                "say() { printf '%s\\n' \"$*\"; }\n"
                f"{body}\nprint_ladder\n",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(self.home)},
        )
        return done.returncode, done.stdout


def _register_key_and_two_models(install: Install, reads: list[str]) -> None:
    stored = install.run_onex(
        "secret",
        "set",
        "llm.openrouter.api_key",
        "--model",
        PAID_MODEL,
        stdin=f"{KEY}\n",
    )
    assert stored.returncode == 0, stored.stdout + stored.stderr
    added = install.run_onex("models", "add-model", "openrouter", "--model", FREE_MODEL)
    assert added.returncode == 0, added.stdout + added.stderr
    assert any(r.endswith(" ok") for r in reads), "the stub was never read with the key"
    assert not any(r.endswith("rejected") for r in reads), reads


def test_the_assertion_has_teeth() -> None:
    """Control: the check itself goes red on a list that is not the ladder."""
    good = f"1. OpenRouter  {PAID_MODEL}  paid\n2. OpenRouter  {FREE_MODEL}  free\n"
    assert ladder_lines_ok(good)
    assert not ladder_lines_ok(f"1. OpenRouter  {PAID_MODEL}  paid\n")
    assert not ladder_lines_ok(good.replace("  paid", "  unknown"))
    assert not ladder_lines_ok(good.replace("  free", ""))
    assert not ladder_lines_ok(re.sub(r"(?m)^\d\. ", "", good))
    assert not ladder_lines_ok(good.replace("1. ", "2. ", 1))


def test_a_fresh_install_with_one_key_and_two_models_prints_the_numbered_ladder(
    tmp_path: Path,
) -> None:
    """AC1: the entrypoint's print_ladder, over the real onex, prints a numbered
    list of the two models whose lines end in paid and free."""
    with _key_server() as (url, reads):
        install = Install(tmp_path, url)
        assert not (install.home / ".omninode").exists(), "the install is not fresh"
        _register_key_and_two_models(install, reads)

        status, out = install.print_ladder()

    assert status == 0, out
    assert ladder_lines_ok(out), out
    assert KEY not in out and KEY not in install.log.read_text()


def test_an_onex_that_lists_no_ladder_prints_no_ladder(tmp_path: Path) -> None:
    """Failing control: the same functions over an onex with no --ladder (an
    onboarding that predates the release) print no list, say so, and fail."""
    with _key_server() as (url, _reads):
        install = Install(tmp_path, url)
        install.onex.write_text(
            '#!/bin/bash\necho "Error: No such option: --ladder" >&2\nexit 2\n'
        )
        status, out = install.print_ladder()

    assert status != 0
    assert not ladder_lines_ok(out)
    assert "could not be listed" in out


def test_injected_break_the_cost_class_is_dropped(tmp_path: Path) -> None:
    """Failing control: the printer drops each line's last word, and the
    assertion that passes on the real printer goes red."""
    with _key_server() as (url, reads):
        install = Install(tmp_path, url)
        _register_key_and_two_models(install, reads)
        real = _function("models_cmd", SCRIPT) + _function("print_ladder", SCRIPT)
        broken = real.replace(
            "printf '%s\\n' \"$out\" |",
            "printf '%s\\n' \"$out\" | sed 's/ *[a-z]*$//' |",
        )
        assert broken != real, "the break did not apply"
        _status, out = install.print_ladder(script_text=broken)

    assert not ladder_lines_ok(out), out


def test_phase_3_calls_print_ladder_after_the_models_are_tested() -> None:
    """The entrypoint reaches it: phase 3 calls print_ladder once, after the
    models are tested and placed and before the unpinned delegation."""
    phase3 = _function("phase3", SCRIPT).splitlines()
    calls = [i for i, line in enumerate(phase3) if line == "  print_ladder"]
    assert len(calls) == 1, "phase 3 must call print_ladder exactly once"

    def at(needle: str) -> int:
        return next(i for i, line in enumerate(phase3) if needle in line)

    assert at("passed_models") < at("place_local_url_on_ladder") < calls[0]
    assert calls[0] < at("retry_capture") < at("stamp_proven_floor")
