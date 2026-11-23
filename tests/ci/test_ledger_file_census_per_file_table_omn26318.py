# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-26318: omniclaude's census ratchet carries its per-file table.

``config/ledger_file_census_ratchet.yaml`` holds a shrink-only count row for this
repository and a ``files`` table of the files that hold a reader or writer, each
with its line count. The table is what lets the census node name the file that
grew. These tests pin that the table exists, agrees with the row, and lists only
files that are present. At the merge base the table is absent, so they fail there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
RATCHET_PATH = REPO_ROOT / "config" / "ledger_file_census_ratchet.yaml"
REGISTRATION = "omniclaude"
# The measured count and line total at the base this table was generated from.
# Both may only fall: a bigger number means a reader or writer was added.
MEASURED_FILES = 62
MEASURED_LINES = 243


def _ratchet() -> dict[str, Any]:
    return yaml.safe_load(RATCHET_PATH.read_text(encoding="utf-8"))


def _table(ratchet: dict[str, Any]) -> dict[str, int]:
    assert "files" in ratchet, "the ratchet file has no per-file `files` table"
    files = ratchet["files"]
    assert isinstance(files, dict), "`files` must be a mapping of registration to rows"
    assert REGISTRATION in files, f"`files` has no table for {REGISTRATION!r}"
    return dict(files[REGISTRATION])


def test_per_file_table_is_present() -> None:
    table = _table(_ratchet())
    assert table, "the per-file table must not be empty"


def test_table_rows_are_positive_integers() -> None:
    for path, lines in _table(_ratchet()).items():
        assert isinstance(lines, int) and not isinstance(lines, bool), (
            f"{path}: line count must be an integer, got {lines!r}"
        )
        assert lines >= 1, f"{path}: a row with no lines is dropped, got {lines}"


def test_table_size_equals_the_ratchet_row() -> None:
    ratchet = _ratchet()
    row = ratchet["ratchet"][REGISTRATION]
    assert len(_table(ratchet)) == row, (
        f"the table lists {len(_table(ratchet))} files, the ratchet row says {row}"
    )


def test_row_and_line_total_never_exceed_the_measured_baseline() -> None:
    ratchet = _ratchet()
    row = ratchet["ratchet"][REGISTRATION]
    total = sum(_table(ratchet).values())
    assert row <= MEASURED_FILES, f"row {row} rose above measured {MEASURED_FILES}"
    assert total <= MEASURED_LINES, (
        f"lines {total} rose above measured {MEASURED_LINES}"
    )


def test_every_listed_file_is_present() -> None:
    missing = [p for p in _table(_ratchet()) if not (REPO_ROOT / p).is_file()]
    assert not missing, f"table lists files that are not in the tree: {missing}"


def test_table_without_files_key_fails_the_check() -> None:
    ratchet = _ratchet()
    ratchet.pop("files")
    with pytest.raises(AssertionError, match="no per-file"):
        _table(ratchet)
