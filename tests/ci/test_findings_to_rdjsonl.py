# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import json
import subprocess
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "scripts"
    / "findings-to-rdjsonl.py"
)


def test_hostile_reviewer_finding():
    payload = {
        "format": "hostile_reviewer",
        "findings": [
            {
                "category": "logic_error",
                "severity": "major",
                "title": "Unchecked None return",
                "description": "get_user() can return None but caller does not check",
                "evidence": {
                    "file_path": "src/auth.py",
                    "line_range": {"start": 42, "end": 45},
                    "code_snippet": "user = get_user(id)",
                },
                "suggestion": "Add None check: if user is None: raise ValueError(...)",
            }
        ],
    }
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["location"]["path"] == "src/auth.py"
    assert diag["location"]["range"]["start"]["line"] == 42
    assert diag["location"]["range"]["end"]["line"] == 45
    assert diag["severity"] == "ERROR"
    assert "Unchecked None return" in diag["message"]
    assert "Suggested fix:" in diag["message"]


def test_aislop_sweep_finding():
    payload = {
        "format": "aislop_sweep",
        "findings": [
            {
                "repo": "omniclaude",
                "path": "src/omniclaude/hooks/schemas.py",
                "line": 15,
                "check": "hardcoded_path",
                "message": "Hardcoded absolute path detected",
                "severity": "ERROR",
                "autofixable": False,
            }
        ],
    }
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["location"]["path"] == "src/omniclaude/hooks/schemas.py"
    assert diag["location"]["range"]["start"]["line"] == 15
    assert diag["severity"] == "ERROR"
    assert diag["source"]["name"] == "aislop-sweep"


def test_contract_sweep_finding():
    payload = {
        "format": "contract_sweep",
        "findings": [
            {
                "node_name": "node_foo",
                "violation_type": "missing_handler",
                "severity": "critical",
                "message": "Handler module not found",
                "field": "handler_module",
            }
        ],
    }
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert diag["severity"] == "ERROR"
    assert diag["source"]["name"] == "contract-sweep"
    assert "node_foo" in diag["message"]


def test_unknown_format_fails():
    payload = {"format": "unknown_format", "findings": [{}]}
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0


def test_malformed_json_reports_clear_error():
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input="{not-json",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Invalid JSON input:" in result.stderr


def test_missing_findings_reports_clear_error():
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps({"format": "hostile_reviewer"}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Missing or invalid required field: findings" in result.stderr


def test_output_conforms_to_reviewdog_diagnostic_schema():
    """Validate rdjsonl output has required fields per reviewdog Diagnostic spec."""
    payload = {
        "format": "hostile_reviewer",
        "findings": [
            {
                "category": "logic_error",
                "severity": "major",
                "title": "Test finding",
                "description": "Test description",
                "evidence": {
                    "file_path": "src/test.py",
                    "line_range": {"start": 1, "end": 2},
                },
            }
        ],
    }
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    diag = json.loads(result.stdout.strip())
    assert "message" in diag
    assert "location" in diag
    assert "path" in diag["location"]
    assert "range" in diag["location"]
    assert "start" in diag["location"]["range"]
    assert "line" in diag["location"]["range"]["start"]
    assert diag["severity"] in ("ERROR", "WARNING", "INFO")
