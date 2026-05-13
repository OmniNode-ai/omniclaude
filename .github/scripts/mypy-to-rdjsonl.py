#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Convert mypy text output to reviewdog rdjsonl."""

import json
import re
import sys

PATTERN = re.compile(
    r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<column>\d+))?: (?P<severity>\w+): (?P<message>.+?)(?:\s+\[(?P<code>[\w-]+)\])?$"
)
SEVERITY_MAP = {"error": "ERROR", "warning": "WARNING", "note": "INFO"}

for line in sys.stdin:
    m = PATTERN.match(line.strip())
    if not m:
        continue
    start: dict = {"line": int(m.group("line"))}
    if m.group("column"):
        start["column"] = int(m.group("column"))
    diag: dict = {
        "message": m.group("message"),
        "location": {
            "path": m.group("path"),
            "range": {"start": start},
        },
        "severity": SEVERITY_MAP.get(m.group("severity"), "WARNING"),
        "source": {"name": "mypy", "url": "https://mypy.readthedocs.io/"},
    }
    code = m.group("code")
    if code:
        diag["code"] = {
            "value": code,
            "url": f"https://mypy.readthedocs.io/en/stable/error_code_list.html#{code}",
        }
    print(json.dumps(diag))  # noqa: T201
