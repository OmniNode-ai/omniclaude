# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The publish-time ruling re-read reads narrowly, so its read answers inside the bound (OMN-26330).

The unfiltered read of the CLAIM, RULING and ACK rows of every lane over 720 hours matched 61565 rows
and took 263.3 s on a lab host on 2026-11-24 (past the 150 s bound of the call). The stand-in
reader below models that cost: it exits 69, the node's unreadable code, for a read of CLAIM or ACK
rows that is not narrowed by lane or by a window of at most 24 hours (the RULING rows alone answered in
6.3 s over 720 hours on the same host). The guard must still judge the same rows.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from omniclaude.handlers.ruling_reread_rows import (
    MAX_WINDOW_HOURS,
    newest_claim_stamp,
    ruling_reread_rows,
)
from omniclaude.handlers.work_ledger_rows import LedgerRowsUnavailable
from omniclaude.nodes.node_git_effect.handlers import handler_git_admission as guard

pytestmark = pytest.mark.unit

LANE = "worker"
CLAIM = f"2026-11-24T10:00:00Z | CLAIM | lane={LANE} | ticket=OMN-1 | actor=x | worktree=none | c"
OTHER_CLAIM = "2026-11-24T10:01:00Z | CLAIM | lane=peer | ticket=OMN-2 | actor=x | c"
RULING = (
    '2026-11-24T10:30:00Z | RULING | lane=operator | ticket=OMN-1 | "Use the model."'
)
NOW = datetime(2026, 11, 24, 11, 30, tzinfo=UTC)

FAKE = """\
import os, sys
argv = sys.argv[1:]
open(os.environ["FAKE_READER_LOG"], "a").write(" ".join(argv) + chr(10))
def values(flag):
    return [argv[i + 1] for i, a in enumerate(argv) if a == flag]
kinds, lanes = values("--kind"), values("--row-lane")
hours = int(values("--window-hours")[0])
if not lanes and hours > 24 and set(kinds or ["CLAIM"]) - {"RULING"}:
    sys.exit(69)  # unfiltered CLAIM or ACK rows of 30 days: past the bound on the real ledger
for raw in open(os.environ["FAKE_LEDGER_ROWS"]).read().splitlines():
    cells = [c.strip() for c in raw.split(" | ")]
    fields = dict(c.split("=", 1) for c in cells[2:] if "=" in c)
    if kinds and cells[1] not in kinds:
        continue
    if lanes and not ({fields.get("lane"), fields.get("from")} & set(lanes)):
        continue
    print(raw)
"""


@pytest.fixture
def reader_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    script = tmp_path / "fake_reader.py"
    script.write_text(FAKE, encoding="utf-8")
    wrapper = tmp_path / "reader"
    wrapper.write_text(
        f'#!/bin/sh\nexec {sys.executable} {script} "$@"\n', encoding="utf-8"
    )
    wrapper.chmod(0o755)
    rows = tmp_path / "rows.txt"
    rows.write_text("\n".join([CLAIM, OTHER_CLAIM, RULING]) + "\n", encoding="utf-8")
    env = {
        "ONEX_LANE": LANE,
        "FAKE_LEDGER_ROWS": str(rows),
        "FAKE_READER_LOG": str(tmp_path / "reader.log"),
        "ONEX_LEDGER_READER_PYTHON": str(wrapper),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
    }
    monkeypatch.delenv("ONEX_LANE_ID", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


def calls(env: dict[str, str]) -> list[str]:
    return Path(env["FAKE_READER_LOG"]).read_text(encoding="utf-8").splitlines()


def test_the_lanes_claim_and_ack_rows_are_read_by_lane_then_the_rulings_since_its_claim(
    reader_env: dict[str, str],
) -> None:
    rows = ruling_reread_rows("r", LANE, environ=os.environ, now=NOW)
    assert rows == [CLAIM, RULING]  # the peer's CLAIM is never read
    first, second = calls(reader_env)
    assert (
        f"--window-hours {MAX_WINDOW_HOURS} --kind CLAIM --kind ACK --row-lane {LANE}"
        in first
    )
    # The CLAIM is 90 minutes old: two hours rounded up, one more of margin.
    assert "--window-hours 3 --kind RULING" in second
    assert "--row-lane" not in second


def test_a_claim_older_than_the_ceiling_reads_the_ceiling(
    reader_env: dict[str, str],
) -> None:
    ruling_reread_rows(
        "r", LANE, environ=os.environ, now=datetime(2027, 3, 1, tzinfo=UTC)
    )
    assert f"--window-hours {MAX_WINDOW_HOURS} --kind RULING" in calls(reader_env)[1]


def test_a_lane_with_no_claim_makes_one_read_and_gets_no_rows(
    reader_env: dict[str, str],
) -> None:
    Path(reader_env["FAKE_LEDGER_ROWS"]).write_text(
        OTHER_CLAIM + "\n", encoding="utf-8"
    )
    assert ruling_reread_rows("r", LANE, environ=os.environ, now=NOW) == []
    assert len(calls(reader_env)) == 1


def test_a_second_read_that_does_not_answer_is_unavailable(
    reader_env: dict[str, str],
) -> None:
    wrapper = Path(reader_env["ONEX_LEDGER_READER_PYTHON"])
    wrapper.write_text(
        f"#!/bin/sh\ncase \"$*\" in *RULING*) exit 69;; esac\necho '{CLAIM}'\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerRowsUnavailable):
        ruling_reread_rows("r", LANE, environ=os.environ, now=NOW)


def test_the_newest_claim_of_the_lane_is_the_one_kept() -> None:
    newer = CLAIM.replace("10:00:00Z", "11:00:00Z")
    assert (
        newest_claim_stamp([CLAIM, newer, OTHER_CLAIM], LANE) == "2026-11-24T11:00:00Z"
    )
    assert newest_claim_stamp([OTHER_CLAIM], LANE) == ""


def _ack(ruling: str) -> str:
    import hashlib

    digest = hashlib.sha256(ruling.encode()).hexdigest()
    return (
        f"2026-11-24T10:40:00Z | ACK | lane={LANE} | from={LANE} | to=operator | "
        f"id=2026-11-24T10:40:00Z-{LANE} | re=2026-11-24T10:30:00Z | "
        f"ruling=2026-11-24T10:30:00Z | ruling-sha256={digest} | read and applied"
    )


def test_the_guard_answers_when_only_narrow_reads_answer(
    reader_env: dict[str, str],
) -> None:
    # Without the narrowing the guard's one 720 hour read exits 69 here and the lane cannot publish.
    rows = Path(reader_env["FAKE_LEDGER_ROWS"])
    assert guard.ruling_reread_refusal(os.environ)  # the RULING is not acknowledged
    with rows.open("a", encoding="utf-8") as file:
        file.write(_ack(RULING) + "\n")
    assert guard.ruling_reread_refusal(os.environ) is None


def test_the_guard_still_names_a_pending_ruling_when_the_reads_answer(
    reader_env: dict[str, str],
) -> None:
    reason = guard.ruling_reread_refusal(os.environ)
    assert reason and "ACK requires" in reason and "could not be verified" not in reason


def test_the_stand_in_refuses_the_unfiltered_read(reader_env: dict[str, str]) -> None:
    # Positive control: the stand-in does fail the old read, so the passes above are the narrowing.
    done = subprocess.run(
        [
            reader_env["ONEX_LEDGER_READER_PYTHON"],
            "-m",
            "m",
            "--reader",
            "r",
            "--window-hours",
            "720",
            "--kind",
            "CLAIM",
            "--kind",
            "RULING",
            "--kind",
            "ACK",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 69
