#!/usr/bin/env python3
"""Convert ruff check --output-format=json to reviewdog rdjsonl."""

import json
import sys

SEVERITY_MAP = {
    "E": "ERROR",
    "F": "ERROR",
    "S": "ERROR",
    "B": "ERROR",
    "W": "WARNING",
    "U": "WARNING",
    "N": "WARNING",
    "D": "WARNING",
    "C": "WARNING",
    "T": "WARNING",
    "I": "INFO",
}


def convert(findings: list[dict]) -> None:
    for f in findings:
        loc = f["location"]
        end = f.get("end_location", loc)
        diag: dict = {
            "message": f"{f['code']}: {f['message']}",
            "location": {
                "path": f["filename"],
                "range": {
                    "start": {"line": loc["row"], "column": loc["column"]},
                    "end": {"line": end["row"], "column": end["column"]},
                },
            },
            "severity": SEVERITY_MAP.get(f["code"][0], "WARNING"),
            "source": {"name": "ruff", "url": "https://docs.astral.sh/ruff/rules/"},
            "code": {"value": f["code"]},
        }
        fix = f.get("fix")
        if fix and fix.get("edits"):
            suggestions = []
            for edit in fix["edits"]:
                suggestions.append(
                    {
                        "range": {
                            "start": {
                                "line": edit["location"]["row"],
                                "column": edit["location"]["column"],
                            },
                            "end": {
                                "line": edit["end_location"]["row"],
                                "column": edit["end_location"]["column"],
                            },
                        },
                        "text": edit["content"],
                    }
                )
            diag["suggestions"] = suggestions
        print(json.dumps(diag))  # noqa: T201


if __name__ == "__main__":
    convert(json.load(sys.stdin))
