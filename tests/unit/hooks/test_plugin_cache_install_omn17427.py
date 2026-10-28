# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A plugin cache copy has no ``src`` tree, and two hook libs still have to run there (OMN-17427).

``installed_plugins.json`` points ``onex@omninode-tools-dev`` at a cache directory holding a copy of
``plugins/onex`` alone. Measured on that copy (2.4.117) with the registered commands and a realistic
payload on stdin:

* ``ticket_creation_guard.py`` raised ``FileNotFoundError`` for
  ``.../omninode-tools-dev/src/omniclaude/handlers/handler_defect_diagnosis.py``, so the admission
  gate refused every ``save_issue`` call, creates and updates alike, as a guard it could not evaluate.
* ``hook_content_capture.payload_encryption_setting`` could not open the capture contract under the
  absent ``src`` tree, raised ``PayloadSealRefusedError``, and every ``claude_hook_capture.sh`` entry
  (29 of the 56 registered) logged ``skipped <event>: payload encryption refused`` and journalled
  nothing.

Both now fall back to the installed ``omniclaude`` package, found without being imported, which is
what ``hook_emit_append`` already did. These tests run the copied libs the way the hooks run them:
as plain scripts, with no ``src`` beside the copy.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_HOOKS_SRC = _REPO_ROOT / "plugins" / "onex" / "hooks"
_TIMEOUT_S = 120


@pytest.fixture
def cache_hooks(tmp_path: Path) -> Path:
    """``hooks/`` copied to ``<cache>/omninode-tools-dev/onex/9.9.9/hooks``, with no ``src`` above."""
    hooks = tmp_path / "cache" / "omninode-tools-dev" / "onex" / "9.9.9" / "hooks"
    shutil.copytree(
        _HOOKS_SRC,
        hooks,
        ignore=shutil.ignore_patterns("__pycache__", "tests", "*.pyc"),
    )
    assert not (hooks.parents[3] / "src").exists()
    assert not (hooks.parents[3] / "src" / "omniclaude").exists()
    return hooks


def _run(
    argv: list[str], *, stdin: str = "", cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        cwd=cwd,
        check=False,
    )


def test_the_capture_setting_reads_from_the_installed_package(
    cache_hooks: Path, tmp_path: Path
) -> None:
    code = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import hook_content_capture as c; print(c.payload_encryption_setting())"
    )
    done = _run([sys.executable, "-c", code, str(cache_hooks / "lib")], cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "(False, None)"


def test_the_ticket_gate_evaluates_an_update_from_a_cache_copy(
    cache_hooks: Path, tmp_path: Path
) -> None:
    payload = {
        "session_id": "omn17427-cache-copy",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-1", "title": "a title and nothing else"},
    }
    done = _run(
        [sys.executable, str(cache_hooks / "lib" / "ticket_creation_guard.py")],
        stdin=json.dumps(payload),
        cwd=tmp_path,
    )
    assert "Traceback" not in done.stderr, done.stderr
    assert "FileNotFoundError" not in done.stderr, done.stderr
    assert done.returncode == 0, (done.stdout, done.stderr)


def test_the_ticket_gate_still_refuses_an_unbound_create_from_a_cache_copy(
    cache_hooks: Path, tmp_path: Path
) -> None:
    """The fallback must not turn the gate into a pass-through: an unbound create is refused."""
    payload = {
        "session_id": "omn17427-cache-copy",
        "hook_event_name": "PreToolUse",
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {
            "title": "Add a thing",
            "team": "Omninode",
            "description": "do it",
        },
    }
    done = _run(
        [sys.executable, str(cache_hooks / "lib" / "ticket_creation_guard.py")],
        stdin=json.dumps(payload),
        cwd=tmp_path,
    )
    assert "Traceback" not in done.stderr, done.stderr
    # The guard exits 3 with the refusal JSON on stdout; the registered script maps it to exit 2.
    assert done.returncode == 3, (done.stdout, done.stderr)
    assert (
        json.loads(done.stdout)["reason_code"]
        == "issue-create-not-bound-to-a-commitment"
    )
