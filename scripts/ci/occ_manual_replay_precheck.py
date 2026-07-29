#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Precheck for the OCC born-path manual replay entrypoint (OMN-14993).

`call-occ-autobind.yml` and `call-occ-companion-effect.yml` gained a
`workflow_dispatch` trigger so an operator can manually re-request a
machine mint for a PR whose original `pull_request` event was swallowed
(live incident: the pre-fix 422 bug in `node_occ_companion_effect`,
OMN-14981/OMN-14939). That entrypoint only works for a PR that is
currently OPEN and non-draft.

The downstream `node_occ_companion_compute` handler
(`handler_occ_companion_compute.py`, F-17 guard,
`_SUPPRESS_PR_STATES = {"closed", "merged"}` plus a separate draft check)
DELIBERATELY refuses to author a companion for a closed/merged/draft PR --
this guard was added after incident occ#4333 (a companion generated for a
closed draft). It is not a missing trigger type; it is intentional business
logic several hops downstream of this workflow, on the other side of a Kafka
publish. If the manual-dispatch entrypoint published for a merged PR anyway,
the request would be silently absorbed by that guard with `no_op_reason`
logged deep in the compute node and zero visible signal on the GitHub side --
exactly the vacuous-green failure class OMN-14993 exists to avoid.

This script is the fail-loud precheck: it runs BEFORE the publish step, reads
the same live PR state (`state`, `isDraft`) the operator would otherwise have
to know to check by hand, and refuses with an explicit, actionable message
instead of letting the request travel to the bus only to vanish.

Merged/closed-PR replay is explicitly OUT OF SCOPE for this entrypoint (see
OMN-14993, OMN-14991 Recommendation 4) -- making it work would require a new,
deliberately-scoped override of F-17 in `handler_occ_companion_compute.py`,
which is real design work, not a workflow trigger change.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

#: PR states for which the downstream F-17 guard in
#: `handler_occ_companion_compute.py` will refuse to author a companion.
#: Mirrors `_SUPPRESS_PR_STATES` there (kept as a local literal -- this
#: script runs in a GHA step with no omnimarket checkout available at this
#: point in the job; the two-repo duplication is the same trade already made
#: by the caller-workflow-owns-its-trigger design, not a new drift risk this
#: script introduces).
_DOWNSTREAM_SUPPRESSED_STATES = frozenset({"closed", "merged"})


class ManualReplayRefusedError(Exception):
    """Raised when the target PR cannot be mint-replayed via this entrypoint."""


def check_replay_eligible(pr_state: dict[str, Any]) -> None:
    """Raise :class:`ManualReplayRefusedError` if ``pr_state`` cannot be replayed.

    ``pr_state`` is the parsed JSON of
    ``gh pr view <n> --json number,state,isDraft,headRefOid,headRefName,title``.
    Refuses (does not silently pass) on:

    * ``state`` in ``{"closed", "merged"}`` (GitHub's `gh pr view --json state`
      returns exactly one of ``OPEN``/``CLOSED``/``MERGED``, compared
      case-insensitively here).
    * ``isDraft`` true.

    Both mirror the F-17 guard in `handler_occ_companion_compute.py` so this
    entrypoint refuses at the cheapest possible point (before publish) rather
    than let the request silently no-op several hops downstream.
    """
    number = pr_state.get("number")
    state = str(pr_state.get("state", "")).strip().lower()
    is_draft = bool(pr_state.get("isDraft", False))

    if state in _DOWNSTREAM_SUPPRESSED_STATES:
        raise ManualReplayRefusedError(
            f"PR #{number} is {state!r} -- the OCC born-path manual replay "
            f"entrypoint cannot mint a companion for a closed/merged PR. "
            f"This is not a missing trigger: the downstream F-17 guard in "
            f"omnimarket's handler_occ_companion_compute.py "
            f"(_SUPPRESS_PR_STATES = {{'closed', 'merged'}}) deliberately "
            f"refuses to author a companion for a PR in this state (added "
            f"after incident occ#4333). Publishing anyway would silently "
            f"no-op downstream with no visible signal here -- refusing "
            f"before publish instead. See OMN-14993 / OMN-14991 for the "
            f"design question of a scoped backfill override; none exists "
            f"today."
        )

    if is_draft:
        raise ManualReplayRefusedError(
            f"PR #{number} is a draft -- the OCC born-path manual replay "
            f"entrypoint cannot mint a companion for a draft PR (same F-17 "
            f"guard, draft-suppression branch, in handler_occ_companion_"
            f"compute.py). Mark the PR ready for review first, or wait for "
            f"the automatic ready_for_review trigger (OMN-14987) once it "
            f"lands, then retry."
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            "usage: occ_manual_replay_precheck.py <pr_state.json>",
            file=sys.stderr,
        )
        return 2

    pr_state_path = Path(argv[1])
    try:
        pr_state = json.loads(pr_state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read/parse {pr_state_path}: {exc}", file=sys.stderr)
        return 2

    try:
        check_replay_eligible(pr_state)
    except ManualReplayRefusedError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(
        f"PR #{pr_state.get('number')} is OPEN and non-draft -- "
        f"manual replay eligible.",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
