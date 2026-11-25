# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""A ledger reader that does not answer once must not read as no CLAIM (OMN-24562).

OMN-26641 (#3325) narrowed the gate's CLAIM read to the lanes it resolves. Act lane
``integration:act300`` was still refused ``lane_identity_missing`` at 2026-11-25T12:20Z with
its CLAIM (12:18:53Z) open on the ledger: the work-ledger reader's bus session was timing out
that day (``bus FAILED: TimeoutError`` in the host-drift rows of 11:22Z to 11:37Z; the recorded
reading of ``integration_act_lane_2026_11_24`` is exit 69, no rows, reason
``bus-session-failed-timeouterror``). The gate made one attempt and read exit 69 as no rows.

The stand-in reader answers exit 69 for its first ``fail_first`` starts and then the lane's
rows. A reader that never answers still refuses: nothing is admitted on an unread ledger.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.hooks.test_ticket_creation_guard_integration_act_lane import (
    _CLAIM,
    _LANE,
    _mint,
)
from tests.hooks.test_ticket_creation_guard_lane_intake import (
    _AGENT,
    _admitted,
    _reason,
    _run,
    _workflow_subagent,
)

pytestmark = pytest.mark.unit

_STAND_IN = """#!{python}
import pathlib, sys
count = pathlib.Path({count!r})
seen = int(count.read_text()) if count.exists() else 0
count.write_text(str(seen + 1))
if seen < {fail_first}:
    sys.stderr.write("READER reader=hook-refusal-lane query=rows status=unreadable "
                     "source=none reason=node-read-failed-bus-session-failed-timeouterror\\n")
    sys.exit(69)
print({row!r})
sys.stderr.write("READER reader=hook-refusal-lane query=rows status=ok source=node\\n")
"""


def _unreliable_reader(tmp_path: Path, fail_first: int) -> Path:
    count = tmp_path / "starts.count"
    reader = tmp_path / "reader-python"
    reader.write_text(
        _STAND_IN.format(
            python=sys.executable, count=str(count), fail_first=fail_first, row=_CLAIM
        ),
        encoding="utf-8",
    )
    reader.chmod(0o755)
    return count


def _mint_as_act_lane(
    tmp_path: Path, fail_first: int
) -> tuple[subprocess.CompletedProcess[str], Path]:
    env, payload = _workflow_subagent(
        tmp_path, sidecar_lane=_LANE, sidecar_description=_LANE
    )
    count = _unreliable_reader(tmp_path, fail_first)
    result = _run(
        _mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    return result, count


def test_one_unreadable_answer_is_retried_and_the_open_claim_admits(
    tmp_path: Path,
) -> None:
    result, count = _mint_as_act_lane(tmp_path, fail_first=1)
    _admitted(result)
    assert count.read_text() == "2"


def test_a_reader_that_never_answers_still_refuses(tmp_path: Path) -> None:
    result, count = _mint_as_act_lane(tmp_path, fail_first=99)
    assert result.returncode == 3, result.stdout + result.stderr
    assert "lane_identity_missing" in _reason(result)
    assert count.read_text() == "2"
