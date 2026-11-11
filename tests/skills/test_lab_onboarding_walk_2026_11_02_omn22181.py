# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-22181 AC4: the 2026-11-02 clean-VM walk, replayed against the script.

The walk pinned script ee8797af on a 4 vCPU, 8 GB Tart VM cloned from
ghcr.io/cirruslabs/macos-tahoe-vanilla and read 17 GB free disk. Preflight
(``--preflight-only --provider local``, no override of the disk reading) refused
it with "17 GB free disk (needs 20)", exit 3. The readings of that walk are the
fixture; they must pass preflight for the local-model path.
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

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "plugins" / "onex" / "skills" / "_bin" / "lab-onboarding.sh"
FIXTURE = REPO / "tests" / "fixtures" / "onboarding_walk_2026_11_02" / "walk.json"

pytestmark = pytest.mark.unit


class _Answers(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b'{"status": "ok"}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


@contextmanager
def _local_model_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Answers)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _m1_disk_gb() -> int:
    match = re.search(r"^M1_DISK_GB=(\d+)", SCRIPT.read_text(encoding="utf-8"), re.M)
    assert match, "M1_DISK_GB is not declared in the script"
    return int(match.group(1))


def _walk() -> dict[str, object]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _preflight(
    tmp_path: Path, readings: dict[str, object]
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir()
    run = tmp_path / "run"
    run.mkdir()
    with _local_model_server() as url:
        return subprocess.run(
            [
                "/bin/bash",
                str(SCRIPT),
                "--preflight-only",
                "--provider",
                "local",
                "--local-url",
                url,
                "--local-model",
                "onboarding-stub",
            ],
            env={
                "HOME": str(home),
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "TMPDIR": f"{run}/",
                "ONBOARD_NOTIFY": "0",
                "ONBOARD_TEST_OS": "Darwin",
                "ONBOARD_TEST_MACOS": str(readings["macos"]),
                "ONBOARD_TEST_PORTS_BUSY": "",
                "ONBOARD_TEST_DISK_GB": str(readings["disk_free_gb"]),
                "ONBOARD_TEST_RAM_GB": str(readings["ram_gb"]),
                "ONBOARD_TEST_CPUS": str(readings["cpus"]),
                "ONBOARD_TEST_VM": "1" if readings["vm"] else "0",
                "ONBOARD_TEST_ADMIN": "1",
                "ONBOARD_TEST_NEEDS_ADMIN": "0",
            },
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )


def test_the_fixture_is_the_walks_recorded_data() -> None:
    walk = _walk()
    assert walk["pinned_script"] == "ee8797af"
    assert walk["image"] == "ghcr.io/cirruslabs/macos-tahoe-vanilla"
    readings = walk["readings"]
    assert isinstance(readings, dict)
    assert readings["disk_total_gb"] == 41
    assert readings["disk_free_gb"] == 17
