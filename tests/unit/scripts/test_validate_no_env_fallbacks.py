# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.validate_no_env_fallbacks import scan_python_file

pytestmark = pytest.mark.unit


def test_embedded_triple_quotes_do_not_start_docstring(tmp_path: Path) -> None:
    path = tmp_path / "module.py"
    path.write_text(
        'marker = """not a docstring opener"""\nurl = os.getenv("X", "localhost")\n',
        encoding="utf-8",
    )
    assert scan_python_file(path) == [(2, 'url = os.getenv("X", "localhost")')]


def test_embedded_triple_quotes_on_fallback_line_still_scans(
    tmp_path: Path,
) -> None:
    path = tmp_path / "module.py"
    path.write_text(
        'url = os.getenv("X", "localhost") + """suffix"""\n',
        encoding="utf-8",
    )
    assert scan_python_file(path) == [
        (1, 'url = os.getenv("X", "localhost") + """suffix"""')
    ]


def test_same_line_triple_quoted_literal_with_executable_fallback_scans(
    tmp_path: Path,
) -> None:
    path = tmp_path / "module.py"
    path.write_text(
        '"""not a standalone docstring"""; url = os.getenv("X", "localhost")\n',
        encoding="utf-8",
    )
    assert scan_python_file(path) == [
        (1, '"""not a standalone docstring"""; url = os.getenv("X", "localhost")')
    ]
