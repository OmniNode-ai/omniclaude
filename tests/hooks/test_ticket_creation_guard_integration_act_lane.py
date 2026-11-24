# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The integration pass's act lane passes the Linear create gate's lane identity (OMN-26641).

The hourly integration pass names its act step ``integration:act<pass>`` (passes 281 to 285)
and the create gate refused every create it made with ``lane_identity_missing`` although the
lane's CLAIM was on the ledger. Recorded under ``tests/fixtures/integration_act_lane_2026_11_24``:
the lane's CLAIM and TERMINAL rows, and the recorded readings of the gate's own claim-reader
argv. The unfiltered 6-hour read of every lane's CLAIM and TERMINAL rows (627 of 6102 rows)
timed out at the reader's 120 s route bound (exit 69, no rows) while the same read with
``--row-lane integration:act283`` answered its rows in 46.7 s. The gate reads a read that
does not answer as no CLAIM.

The stand-in reader below replays those readings: it answers only a read that names a lane,
as the recorded run did, and answers nothing to an unfiltered window read.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.hooks.test_ticket_creation_guard_lane_intake import (
    _AGENT,
    _LABEL,
    _admitted,
    _create,
    _reason,
    _run,
    _stamped,
    _workflow_subagent,
)

pytestmark = pytest.mark.unit

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/integration_act_lane_2026_11_24/recorded.json"
)
_RECORDED: dict[str, Any] = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_LANE: str = _RECORDED["lane"]
_PARENT = "orchestrator-31d9-swarm"

#: A reader that behaves as the recorded runs did. ``argv.log`` receives every argv it was
#: started with. A read naming no lane never answers within the bound (the recorded exit 69).
_STAND_IN = """#!{python}
import json, sys
recorded = json.load(open({fixture!r}))
with open({log!r}, "a") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
lanes = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--row-lane"]
if not lanes:
    sys.stderr.write(recorded["reader_readings"][0]["stderr"] + "\\n")
    sys.exit(69)
rows = {rows!r}
for row in rows:
    if any(("| lane=" + lane + " |") in row for lane in lanes):
        print(row)
sys.stderr.write(recorded["reader_readings"][1]["stderr"] + "\\n")
"""


def _reader(tmp_path: Path, rows: tuple[str, ...]) -> Path:
    """Install the stand-in as the hook's reader interpreter; return its argv log."""
    log = tmp_path / "argv.log"
    stand_in = tmp_path / "reader-python"
    stand_in.write_text(
        _STAND_IN.format(
            python=sys.executable,
            fixture=str(_FIXTURE),
            log=str(log),
            rows=list(rows),
        ),
        encoding="utf-8",
    )
    stand_in.chmod(0o755)
    return log


def _act_lane(
    tmp_path: Path, rows: tuple[str, ...]
) -> tuple[dict[str, str], dict[str, Any], Path]:
    env, payload = _workflow_subagent(
        tmp_path, sidecar_lane=_LANE, sidecar_description=_LANE
    )
    return env, payload, _reader(tmp_path, rows)


def _mint(lane: str = _LANE) -> dict[str, Any]:
    return _create(description=_stamped(lane), labels=[_LABEL])


_CLAIM: str = _RECORDED["claim_row"]
_TERMINAL: str = _RECORDED["terminal_row"]


@pytest.mark.parametrize("hook", [False, True], ids=["core", "registered-hook"])
def test_the_recorded_act_lane_with_its_open_claim_mints(
    tmp_path: Path, hook: bool
) -> None:
    """AC1: the recorded CLAIM, the recorded reader that answers only a lane-named read."""
    env, payload, _log = _act_lane(tmp_path, (_CLAIM,))
    result = _run(
        _mint(),
        tmp_path,
        agent_id=_AGENT,
        extra_env=env,
        extra_payload=payload,
        hook=hook,
    )
    _admitted(result)


def test_the_gate_asks_the_reader_for_the_one_lane_it_resolves(tmp_path: Path) -> None:
    """The claim read names the lane, so the answer is two rows and not 627 of the window."""
    env, payload, log = _act_lane(tmp_path, (_CLAIM,))
    _run(_mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload)
    argvs = log.read_text(encoding="utf-8").splitlines()
    assert len(argvs) == 1, argvs
    assert argvs[0].endswith(f"--row-lane {_LANE}"), argvs[0]
    assert "--window-hours 6" in argvs[0]
    assert "--kind CLAIM" in argvs[0]
    assert "--kind TERMINAL" in argvs[0]


def test_colon_alias_and_claim_lookup_are_not_the_cause(tmp_path: Path) -> None:
    """Control: a reader that answers the whole window admits the same lane, at any code."""
    env, payload = _workflow_subagent(
        tmp_path, sidecar_lane=_LANE, sidecar_description=_LANE
    )
    reader = tmp_path / "reader-python"
    ledger = tmp_path / "window.md"
    ledger.write_text(f"{_CLAIM}\n", encoding="utf-8")
    reader.write_text(f'#!/bin/sh\ncat "{ledger}"\n', encoding="utf-8")
    reader.chmod(0o755)
    result = _run(
        _mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    _admitted(result)


def test_a_lane_with_no_claim_is_still_refused(tmp_path: Path) -> None:
    """The gate is not widened: the reader answers, and holds no CLAIM of this lane."""
    other = _CLAIM.replace(f"lane={_LANE}", "lane=integration:act999")
    env, payload, _log = _act_lane(tmp_path, (other,))
    result = _run(
        _mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "lane_identity_missing" in _reason(result)
    assert f"no open CLAIM for lane '{_LANE}'" in _reason(result)


def test_a_lane_whose_claim_is_closed_is_still_refused(tmp_path: Path) -> None:
    """The recorded TERMINAL closes the CLAIM: no open CLAIM, no identity."""
    env, payload, _log = _act_lane(tmp_path, (_CLAIM, _TERMINAL))
    result = _run(
        _mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    assert result.returncode == 3, result.stdout + result.stderr
    assert "lane_identity_missing" in _reason(result)


def test_a_prompt_named_act_lane_reads_its_own_claim(tmp_path: Path) -> None:
    """The dispatch prompt names the lane and its parent; the sidecar holds only a label."""
    prompt = (
        f"You are lane {_LANE} (parent {_PARENT}, ticket OMN-26641) for the act step."
    )
    env, payload = _workflow_subagent(
        tmp_path,
        sidecar_lane="act-step",
        sidecar_description="integration act step",
        prompt=prompt,
    )
    log = _reader(tmp_path, (_CLAIM,))
    result = _run(
        _mint(), tmp_path, agent_id=_AGENT, extra_env=env, extra_payload=payload
    )
    _admitted(result)
    argvs = log.read_text(encoding="utf-8").splitlines()
    assert len(argvs) == 1, argvs
    assert f"--row-lane {_LANE}" in argvs[0], argvs[0]
