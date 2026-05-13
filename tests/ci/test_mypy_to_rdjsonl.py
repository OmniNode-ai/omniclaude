# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "mypy-to-rdjsonl.py"
)


def test_mypy_error_converts_to_rdjsonl():
    mypy_output = (
        "src/foo.py:10: error: Incompatible types in assignment "
        '(expression has type "str", variable has type "int")  [assignment]\n'
    )
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=mypy_output,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["location"]["path"] == "src/foo.py"
    assert diag["location"]["range"]["start"]["line"] == 10
    assert diag["severity"] == "ERROR"
    assert "Incompatible types" in diag["message"]
    assert diag["code"]["value"] == "assignment"


def test_mypy_note_converts_to_info():
    mypy_output = 'src/foo.py:5: note: Revealed type is "builtins.int"\n'
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=mypy_output,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["severity"] == "INFO"


def test_column_aware_message():
    mypy_output = "src/foo.py:10:5: error: Incompatible types  [assignment]\n"
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=mypy_output,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["location"]["range"]["start"]["line"] == 10
    assert diag["location"]["range"]["start"]["column"] == 5


def test_summary_lines_are_skipped():
    mypy_output = "Found 3 errors in 2 files (checked 15 source files)\n"
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=mypy_output,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
