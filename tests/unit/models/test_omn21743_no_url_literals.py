# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The OMN-21743 slice holds no URL string literal in code (hosted-runner falsifier for AC1).

The contracts_and_di check lives in omnibase_core and needs a sibling checkout, so this
test applies the same question to the files the slice touched with the standard library
alone: no string constant that opens with ``scheme://host`` outside a docstring.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

# A URL-like constant opens with ``scheme://`` and a host character; a bare ``://`` or
# ``https://`` prefix used to split or test a URL is not a URL.
_URL_START = re.compile(r"^[a-z][a-z0-9+.-]*://[^\s/]")

_ROOT = Path(__file__).resolve().parents[3]

_SLICE_FILES = (
    "src/omniclaude/lib/core/intelligence_cache.py",
    "src/omniclaude/lib/utils/consensus/quorum.py",
    "src/omniclaude/lib/utils/validator_quality.py",
    "src/omniclaude/quirks/classifier.py",
    "plugins/onex/skills/_lib/gather_github_stats/gather_stats.py",
    "plugins/onex/skills/_lib/status/status.py",
    "plugins/onex/skills/changelog_audit/_lib/dispatch.py",
    "plugins/onex/skills/system_status/check_database_health/_lib/execute.py",
)


def _url_literals(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            docstrings.add(id(node.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and _URL_START.match(node.value) is not None
    ]


@pytest.mark.unit
@pytest.mark.parametrize("relative", _SLICE_FILES)
def test_slice_file_holds_no_url_literal(relative: str) -> None:
    source = (_ROOT / relative).read_text(encoding="utf-8")
    assert _url_literals(source) == []


@pytest.mark.unit
def test_scan_sees_a_planted_url_literal() -> None:
    planted = 'ENDPOINT = "http://localhost:6333"\nOTHER = r"https://github\\.com/x"\n'
    assert [line for line, _ in _url_literals(planted)] == [1, 2]
