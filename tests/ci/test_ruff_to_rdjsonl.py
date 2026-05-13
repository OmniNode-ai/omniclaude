# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2] / ".github" / "scripts" / "ruff-to-rdjsonl.py"
)


def test_fixable_violation_includes_suggestion():
    ruff_json = json.dumps(
        [
            {
                "code": "UP007",
                "message": "Use `X | Y` instead of `Optional[X]`",
                "filename": "src/foo.py",
                "location": {"row": 10, "column": 5},
                "end_location": {"row": 10, "column": 25},
                "fix": {
                    "applicability": "safe",
                    "message": "Convert to `X | Y`",
                    "edits": [
                        {
                            "content": "int | None",
                            "location": {"row": 10, "column": 5},
                            "end_location": {"row": 10, "column": 25},
                        }
                    ],
                },
            }
        ]
    )
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=ruff_json,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["message"] == "UP007: Use `X | Y` instead of `Optional[X]`"
    assert diag["location"]["path"] == "src/foo.py"
    assert diag["location"]["range"]["start"]["line"] == 10
    assert diag["location"]["range"]["start"]["column"] == 5
    assert diag["severity"] == "WARNING"
    assert len(diag["suggestions"]) == 1
    assert diag["suggestions"][0]["text"] == "int | None"


def test_non_fixable_violation_has_no_suggestions():
    ruff_json = json.dumps(
        [
            {
                "code": "E501",
                "message": "Line too long (120 > 88)",
                "filename": "src/bar.py",
                "location": {"row": 5, "column": 1},
                "end_location": {"row": 5, "column": 120},
                "fix": None,
            }
        ]
    )
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=ruff_json,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert "suggestions" not in diag
    assert diag["severity"] == "ERROR"


def test_empty_input_produces_no_output():
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input="[]",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == ""
