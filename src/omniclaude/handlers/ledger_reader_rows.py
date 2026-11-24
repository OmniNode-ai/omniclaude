# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Rows of the work ledger from the work-ledger reader node, never from a file (OMN-26508).

One place for the call every hook, gate and script of this repository makes when it needs ledger
rows: it runs the node's history read (``read_history_rows``) in the dispatch venv interpreter, which
holds the node, and returns the rows it answered. The read is unbounded in size (the CLI form of the
reader truncates a large answer, and a dropped row would be a ruling never shown or a claim never
seen). A reader that is not named in the overlay's ``moved_readers``, that did not answer, or that has
no interpreter is :class:`LedgerReaderUnreadableError`: a failed read is never an empty list and the
file is never read in its place.

Standard library only. The caller supplies the bound on the read (``timeout_s``): no number lives here.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

#: Run by the dispatch venv interpreter. argv: reader, since (UTC ISO), lane term (or empty), then the
#: row kinds. Exit 0 answered (rows on stdout, possibly none); exit 2 the node did not answer.
_PROGRAM = (
    "import sys\n"
    "from datetime import datetime\n"
    "from omnimarket.nodes.node_work_ledger_reader_effect.adapters.rows_read import "
    "LedgerRowsUnreadableError, read_history_rows\n"
    "reader, since, term = sys.argv[1:4]\n"
    "try:\n"
    "    rows = read_history_rows(reader, datetime.fromisoformat(since.replace('Z', '+00:00')), "
    "kinds=tuple(sys.argv[4:]), term=term or None)\n"
    "except LedgerRowsUnreadableError as exc:\n"
    "    sys.stderr.write(str(exc) + '\\n')\n"
    "    sys.exit(2)\n"
    "sys.stdout.write('\\n'.join(rows) + '\\n' if rows else '')\n"
)

_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class LedgerReaderUnreadableError(RuntimeError):
    """The reader node did not answer; no row was read and none is assumed."""


def read_history_rows(
    reader: str,
    since: datetime,
    kinds: Sequence[str],
    *,
    timeout_s: float,
    term: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """The rows of ``kinds`` the reader node holds since ``since``, oldest first, at any age."""
    env = os.environ if environ is None else environ
    home = env.get("OMNI_HOME", "").strip()
    python = env.get("ONEX_LEDGER_READER_PYTHON") or (
        f"{home}/.onex-dispatch-venv/bin/python" if home else ""
    )
    if not python:
        raise LedgerReaderUnreadableError(
            "no interpreter for the work-ledger reader node: set ONEX_LEDGER_READER_PYTHON or OMNI_HOME"
        )
    stamp = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        done = subprocess.run(
            [python, "-I", "-c", _PROGRAM, reader, stamp, term or "", *kinds],
            capture_output=True,
            text=True,
            env=dict(env),
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise LedgerReaderUnreadableError(
            f"the work-ledger reader node did not answer ({exc})"
        ) from exc
    if done.returncode != 0:
        raise LedgerReaderUnreadableError(
            f"the work-ledger reader node exited {done.returncode}: {done.stderr.strip()[:200]}"
        )
    rows = [line for line in done.stdout.splitlines() if line.strip()]
    rows.sort(key=lambda line: line.split("|", 1)[0])
    return rows


def read_parsed_rows(
    reader: str,
    since: datetime,
    kinds: Sequence[str],
    *,
    timeout_s: float,
    term: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> list[tuple[str, str, dict[str, str], str]]:
    """``(stamp, kind, fields, raw)`` of each row :func:`read_history_rows` answers that is a row."""
    parsed = []
    for raw in read_history_rows(
        reader, since, kinds, timeout_s=timeout_s, term=term, environ=environ
    ):
        cells = [cell.strip() for cell in raw.split(" | ")]
        if len(cells) > 1 and _STAMP.fullmatch(cells[0].removeprefix("- ").strip()):
            fields = dict(c.split("=", 1) for c in cells[2:] if "=" in c)
            parsed.append((cells[0].removeprefix("- ").strip(), cells[1], fields, raw))
    return parsed


def read_lane_claims(
    reader: str,
    lane: str,
    since: datetime,
    *,
    timeout_s: float,
    environ: Mapping[str, str] | None = None,
) -> list[str]:
    """The stamps of the CLAIM rows of ``lane`` the reader node holds since ``since``."""
    rows = read_parsed_rows(
        reader,
        since,
        ("CLAIM",),
        timeout_s=timeout_s,
        term=f"lane={lane}",
        environ=environ,
    )
    return [stamp for stamp, _, fields, _ in rows if fields.get("lane") == lane]
