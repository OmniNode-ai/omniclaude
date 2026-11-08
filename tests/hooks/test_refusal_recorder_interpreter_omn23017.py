# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The hook refusal recorder finds an interpreter that can import its row module (OMN-23017).

On the lab hosts every guard refusal of a landing worker was written by the
OMN-20883 fallback writer as ``reason=recorder-import-failure``. The guard
runner's first interpreter (``PYTHON_CMD``, the plugin data venv) held an
omnimarket older than the row module the recorder imports, so the recorder
died with ``No module named 'omnimarket.models.error_normalizer'`` while the
registry clone's venv, further down the same resolution order, imports it.
The recorder tried the first interpreter only.

Each test drives the real seam (``hook_record_refusal`` in a bash process that
sources ``error-guard.sh`` from a copy of the hooks tree whose root holds no
venv) with only the ledger writer and the failing interpreters replaced.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.hooks.test_refusal_recorder_delivery_omn20883 import Box, _cell

pytestmark = pytest.mark.unit

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "hook_refusal_recorder_import_failure_rows.jsonl"
)

#: What the lab host's recorder printed, from its hooks.log, for each fallback row.
_STALE_STDERR = (
    "hook refusal recorder: No module named 'omnimarket.models.error_normalizer'"
)


def _stale_python(path: Path, stderr: str = _STALE_STDERR) -> Path:
    """An interpreter whose installed omnimarket predates the row module.

    It fails the recorder (``-m``) as a stale venv does and still runs the
    standard-library redactor (``-c``), as the same venv can.
    """
    path.write_text(
        "#!/bin/sh\n"
        'case " $* " in\n'
        f'  *" -m "*) echo "{stderr}" >&2; exit 1;;\n'
        "esac\n"
        f'exec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _working_clone_python(box: Box) -> Path:
    """``$OMNI_HOME/omniclaude/.venv/bin/python3``: the registry clone's venv."""
    path = box.home / "omniclaude" / ".venv" / "bin" / "python3"
    path.parent.mkdir(parents=True)
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    path.chmod(0o755)
    return path


def test_hook_refusal_recorder_imports_row_module(tmp_path: Path) -> None:
    """AC1: the stale first interpreter is passed over for one that imports the row module."""
    box = Box(tmp_path)
    stale = _stale_python(tmp_path / "data-venv-python3")
    _working_clone_python(box)

    rows = box.refuse({"PYTHON_CMD": str(stale), "ONEX_LANE": "landing-L29761"})

    assert len(rows) == 1
    row = rows[0]
    assert _cell(row, "reason") != "recorder-import-failure"
    assert "worktree-path-outside-canonical-root" in _cell(row, "reason")
    assert _cell(row, "guard") == "pre_tool_use_worktree_guard.sh"
    assert _cell(row, "lane") == "landing-L29761"
    assert _cell(row, "lane_source") == "env"
    assert "BLOCKED: test refusal" in row


def test_hook_refusal_recorder_runs_the_first_working_interpreter_once(
    tmp_path: Path,
) -> None:
    """A recorder that imports and then refuses to write is not retried under the next interpreter."""
    box = Box(tmp_path)
    clone = _working_clone_python(box)
    ran = tmp_path / "ran"
    counting = tmp_path / "counting-python3"
    counting.write_text(
        f'#!/bin/sh\necho x >> "{ran}"\nexec "{sys.executable}" "$@"\n',
        encoding="utf-8",
    )
    counting.chmod(0o755)

    rows = box.refuse(
        {
            "PYTHON_CMD": str(counting),
            "PLUGIN_PYTHON_BIN": str(clone),
            "ONEX_LANE": "landing-L29761",
        }
    )

    assert len(rows) == 1
    assert _cell(rows[0], "reason") != "recorder-import-failure"
    assert ran.read_text(encoding="utf-8").count("x") == 1


@pytest.fixture
def short_root() -> Iterator[Path]:
    """A scratch root with a short path.

    The fallback row's interpreter cell is cut at 400 characters. A lab host
    that keeps pytest's temp root under a long run directory puts the three
    interpreter paths past that cut, so the last one is cut off the row.
    """
    root = Path(tempfile.mkdtemp(prefix="hr", dir="/tmp"))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_hook_refusal_fallback_row_carries_reason_and_interpreter(
    short_root: Path,
) -> None:
    """AC2: when no interpreter can import the row module the row names the refusal and the failures."""
    tmp_path = short_root
    box = Box(tmp_path)
    first = _stale_python(tmp_path / "data-venv-python3")
    second = _stale_python(
        tmp_path / "plugin-python3", "python3: Error while finding module specification"
    )

    rows = box.refuse(
        {
            "PYTHON_CMD": str(first),
            "PLUGIN_PYTHON_BIN": str(second),
            "ONEX_LANE": "landing-L29761",
        }
    )

    assert len(rows) == 1
    row = rows[0]
    assert _cell(row, "reason") == "recorder-import-failure"
    assert _cell(row, "guard") == "pre_tool_use_worktree_guard.sh"
    assert "BLOCKED: test refusal" in _cell(row, "detail")
    interpreters = _cell(row, "interpreter").split(",")
    assert interpreters[:2] == [str(first), str(second)]
    # the last interpreter tried is the system python3 on PATH, which is broken too
    assert str(tmp_path / "python3") in interpreters
    assert "Error while finding module specification" in _cell(row, "import_error")


def test_hook_refusal_fallback_row_carries_reason_redacts_credentials(
    tmp_path: Path,
) -> None:
    """The refusal text in the fallback row is redacted by the shared secret redactor."""
    box = Box(tmp_path)
    stale = _stale_python(tmp_path / "data-venv-python3")
    token = (
        "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"
    )  # shaped like a PAT, not one

    rows = box.refuse(
        {"PYTHON_CMD": str(stale), "ONEX_LANE": "landing-L29761"},
        detail=f"BLOCKED: pushed with token {token} | and a cell separator",
    )

    assert len(rows) == 1
    detail = _cell(rows[0], "detail")
    assert token not in rows[0]
    assert "BLOCKED: pushed with token" in detail
    assert " | " not in detail


def _fixture_rows() -> list[dict[str, str]]:
    return [
        json.loads(line)
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_hook_refusal_recorder_import_failure_fixture_is_the_recorded_shape() -> None:
    rows = _fixture_rows()
    assert len(rows) >= 6
    assert {r["guard"] for r in rows} == {
        "pre_tool_use_shared_tree_git_guard.sh",
        "pre_tool_use_worktree_guard.sh",
    }
    assert all(r["reason"] == "recorder-import-failure" for r in rows)
    assert all(r["ts"].startswith("2026-11-07T") for r in rows)


@pytest.mark.parametrize(
    "recorded",
    _fixture_rows(),
    ids=lambda r: f"{r['lane']}-{r['guard'].removesuffix('.sh')}-{r['ts']}",
)
def test_hook_refusal_recorder_import_failure_fixture(
    tmp_path: Path, recorded: dict[str, str]
) -> None:
    """AC3: each recorded fallback row, replayed, now reaches the ledger with its real reason.

    The interpreter fails with the line the lab host's hooks.log holds for that
    row; the registry clone's venv imports the row module.
    """
    box = Box(tmp_path)
    stale = _stale_python(tmp_path / "data-venv-python3", recorded["recorder_stderr"])
    _working_clone_python(box)

    rows = box.refuse(
        {
            "PYTHON_CMD": str(stale),
            "ONEX_LANE": recorded["lane"],
            "TEST_HOOK_NAME": recorded["guard"],
        }
    )

    assert len(rows) == 1
    assert _cell(rows[0], "reason") != recorded["reason"]
    assert _cell(rows[0], "guard") == recorded["guard"]
    assert _cell(rows[0], "lane") == recorded["lane"]
