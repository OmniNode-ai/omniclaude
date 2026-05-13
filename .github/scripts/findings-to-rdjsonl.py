#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Convert ONEX sweep/review finding formats to reviewdog rdjsonl."""

import json
import sys

HOSTILE_SEVERITY = {
    "critical": "ERROR",
    "major": "ERROR",
    "minor": "WARNING",
    "nit": "INFO",
}
SWEEP_SEVERITY = {
    "CRITICAL": "ERROR",
    "ERROR": "ERROR",
    "WARNING": "WARNING",
    "INFO": "INFO",
}
CONTRACT_SEVERITY = {
    "critical": "ERROR",
    "major": "ERROR",
    "minor": "WARNING",
    "info": "INFO",
}


def _hostile_reviewer(f: dict) -> dict:
    evidence = f.get("evidence", {})
    lr = evidence.get("line_range", {})
    msg = f"{f['title']}: {f['description']}"
    if f.get("suggestion"):
        msg += f"\n\nSuggested fix: {f['suggestion']}"
    return {
        "message": msg,
        "location": {
            "path": evidence.get("file_path", "unknown"),
            "range": {
                "start": {"line": lr.get("start", 1)},
                "end": {"line": lr.get("end", lr.get("start", 1))},
            },
        },
        "severity": HOSTILE_SEVERITY.get(f.get("severity", "minor"), "WARNING"),
        "source": {"name": "hostile-reviewer"},
        "code": {"value": f.get("category", "unknown")},
    }


def _aislop_sweep(f: dict) -> dict:
    return {
        "message": f"[{f['check']}] {f['message']}",
        "location": {
            "path": f.get("path", "unknown"),
            "range": {"start": {"line": f.get("line", 1)}},
        },
        "severity": SWEEP_SEVERITY.get(f.get("severity", "WARNING"), "WARNING"),
        "source": {"name": "aislop-sweep"},
        "code": {"value": f.get("check", "unknown")},
    }


def _contract_sweep(f: dict) -> dict:
    return {
        "message": f"[{f['node_name']}] {f['violation_type']}: {f['message']}",
        "location": {
            "path": f.get("field", "contract.yaml"),
            "range": {"start": {"line": 1}},
        },
        "severity": CONTRACT_SEVERITY.get(f.get("severity", "minor"), "WARNING"),
        "source": {"name": "contract-sweep"},
        "code": {"value": f.get("violation_type", "unknown")},
    }


CONVERTERS = {
    "hostile_reviewer": _hostile_reviewer,
    "aislop_sweep": _aislop_sweep,
    "contract_sweep": _contract_sweep,
}

if __name__ == "__main__":
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON input: {exc}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    if not isinstance(data, dict):
        print("Input must be a JSON object", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    fmt = data.get("format")
    if not isinstance(fmt, str):
        print("Missing or invalid required field: format", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    findings = data.get("findings")
    if not isinstance(findings, list):
        print("Missing or invalid required field: findings", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    if fmt not in CONVERTERS:
        print(f"Unknown format: {fmt}", file=sys.stderr)  # noqa: T201
        sys.exit(1)
    converter = CONVERTERS[fmt]
    for finding in findings:
        print(json.dumps(converter(finding)))  # noqa: T201
