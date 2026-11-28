# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Failure-mode tests for the no-DB-in-orchestrator hook docstring skip (OMN-26447)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_no_db_in_orchestrator import check_file  # noqa: E402

PROSE = "Delete the pending rows FROM the cache WHERE the prompt matches."
SQL = "DELETE FROM pending WHERE id = 1"


def _check(tmp_path: Path, source: str | bytes) -> list[str]:
    target = tmp_path / "module.py"
    if isinstance(source, bytes):
        target.write_bytes(source)
    else:
        target.write_text(source, encoding="utf-8")
    return check_file(target)


@pytest.mark.unit
class TestDocstringsPass:
    def test_module_docstring(self, tmp_path: Path) -> None:
        assert _check(tmp_path, f'"""{PROSE}"""\nX = 1\n') == []

    def test_class_docstring(self, tmp_path: Path) -> None:
        assert _check(tmp_path, f'class A:\n    """{PROSE}"""\n') == []

    def test_function_docstring(self, tmp_path: Path) -> None:
        assert _check(tmp_path, f'def f() -> None:\n    """{PROSE}"""\n') == []

    def test_async_function_docstring(self, tmp_path: Path) -> None:
        assert _check(tmp_path, f'async def f() -> None:\n    """{PROSE}"""\n') == []

    def test_nested_function_docstring(self, tmp_path: Path) -> None:
        src = f'def f() -> None:\n    def g() -> None:\n        """{PROSE}"""\n'
        assert _check(tmp_path, src) == []


@pytest.mark.unit
class TestRealSqlStillRefused:
    def test_assigned_to_variable(self, tmp_path: Path) -> None:
        assert len(_check(tmp_path, f'QUERY = "{SQL}"\n')) == 1

    def test_passed_to_cursor_execute(self, tmp_path: Path) -> None:
        assert (
            len(
                _check(
                    tmp_path, f'def f(cursor) -> None:\n    cursor.execute("{SQL}")\n'
                )
            )
            == 1
        )

    def test_second_string_statement_is_not_a_docstring(self, tmp_path: Path) -> None:
        src = f'def f() -> None:\n    """Fine."""\n    "{SQL}"\n'
        assert len(_check(tmp_path, src)) == 1


@pytest.mark.unit
class TestUnchangedBehaviour:
    def test_fstring_literal_part_still_refused(self, tmp_path: Path) -> None:
        # The literal fragment of an f-string is an ast.Constant and was flagged before.
        src = 'x = 1\nQ = f"DELETE FROM t WHERE id = {x}"\n'
        assert len(_check(tmp_path, src)) == 1

    def test_bytes_literal_is_not_flagged(self, tmp_path: Path) -> None:
        assert _check(tmp_path, f'Q = b"{SQL}"\n') == []

    def test_syntax_error_reported(self, tmp_path: Path) -> None:
        result = _check(tmp_path, "def (:\n")
        assert len(result) == 1
        assert "SyntaxError" in result[0]
