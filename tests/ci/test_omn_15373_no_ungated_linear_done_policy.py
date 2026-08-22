# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CI guard: no committed recipe may mint a Linear Done (OMN-15373/OMN-15523).

Why this gate exists
--------------------
OMN-15373 catalogued four false-Done mechanisms, all of them Linear-side config.
Auditing that ticket surfaced in-repo ones that no ticket had named:
``.github/workflows/linear-close-on-merge.yml`` (OMN-3262). On every merged PR
it extracted an ``OMN-XXXX`` id **from the head branch name**, resolved the
team's ``completed``-type workflow state, and issued
``issueUpdate(stateId: <Done>)`` by raw ``curl``.

That path:

* required no closing keyword — branch-name extraction was the primary signal;
* never executed ``close_evidence_gate`` / ``enforce_close_evidence``
  (OMN-13817), because it is shell in YAML, not the node;
* never consulted a ``dod_verify`` receipt.

omniclaude's copy was the **widest exposure of the three**: the OMN-14641
hardening extended its trigger to ``dev`` — the everyday merge target — while
leaving the Done-write itself ungated. Hardening the *signal* does not make the
*target* legitimate.

It was latent, not safe. The identical omnimarket copy reached its close step on
run ``30232689862`` (2026-07-27T02:39:24Z, branch
``promotion/omn-14812-omnimarket-dev-to-main``), logging
``Extracted ticket ID: OMN-14812``; the ONLY thing that stopped the flip was
``LINEAR_API_KEY is not set``. Provisioning that secret for an unrelated
reason — including arming the OMN-15373 drift guard, which needs exactly this
key — would silently have converted the workflow into an evidence-less Done
writer on every merge.

The rule
--------
A file is a violation when it does BOTH of:

1. issue a Linear workflow-state mutation (``issueUpdate`` / ``issueBatchUpdate``
   carrying a ``stateId``); AND
2. resolve or name a ``completed``-type target for it.

The conjunction is deliberate. Signal 1 alone is legitimate — the sanctioned
evidence-gated callers issue exactly that mutation and resolve states by NAME,
never selecting on ``type == completed``. Signal 2 alone is noise (unrelated
``status="completed"`` literals). Only a recipe that deliberately seeks out the
completed-type state AND writes it is a Done minter.

This runs in the normal pytest suite, so it is pre-merge enforcement on every PR
rather than an advisory sweep (CLAUDE.md rule 5: enforcement, not detection).
It lives under ``tests/ci/`` because this repo's change-aware selector maps the
``.github/workflows/`` and ``tests/ci/`` path prefixes onto ``tests/ci/``
(``scripts/ci/test_selection_adjacency.yaml`` ``path_triggers``, OMN-15393), so
both a re-add of the workflow and an edit to this guard select it.

Escape hatch: ``# linear-done-write-ok: <reason>`` anywhere in the file, reserved
for forensic/illustrative quotes. Free-text justification does not count.

Ported from ``omnimarket`` ``tests/test_omn_15373_no_ungated_linear_done_policy.py``
(omnimarket#1977) under OMN-15523.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Directories that can carry an executable recipe. Source is scanned too: a
# handler that resolves a completed state and calls issueUpdate is the same
# defect written in Python. ``plugins`` is included because this repo's nested
# script roots (``plugins/onex/scripts/``, ``plugins/onex/hooks/scripts/``) are
# invoked from the repo root by ci.yml and are executable recipes in every sense
# that matters here.
_SCAN_DIRS: tuple[str, ...] = (".github", "scripts", "src", "plugins")
_SCAN_SUFFIXES: frozenset[str] = frozenset({".yml", ".yaml", ".sh", ".py"})

# This file quotes the shapes it forbids. Exempt by path rather than by
# littering annotations through the test that proves the patterns work.
_SELF_EXEMPT: frozenset[str] = frozenset(
    {"tests/ci/test_omn_15373_no_ungated_linear_done_policy.py"}
)

_ALLOW_ANNOTATION = "linear-done-write-ok:"

# Directory names that never carry first-party committed recipes.
_EXCLUDED_PARTS: frozenset[str] = frozenset(
    {"__pycache__", ".venv", "node_modules", "site-packages"}
)

# Signal 1 — a Linear workflow-state mutation. Matched across the whole file
# (not per line) because the GraphQL document is usually a multi-line string.
_STATE_MUTATION = re.compile(
    r"(issueUpdate|issueBatchUpdate)\b[\s\S]{0,200}?stateId",
    re.IGNORECASE,
)

# Signal 2 — selecting the completed-type state. Covers the shell/Python idiom
# used by the deleted workflow (`s.get("type", "").upper() == "COMPLETED"`), the
# GraphQL/JSON form (`"type": "completed"`), and a direct constant comparison.
_COMPLETED_TARGET = re.compile(
    r"""["']?\btype\b["']?[^\n]{0,60}?(?:==|!=|=~|:)\s*["']completed["']""",
    re.IGNORECASE,
)


def _iter_candidate_files() -> list[Path]:
    files: list[Path] = []
    for d in _SCAN_DIRS:
        root = _REPO_ROOT / d
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in _SCAN_SUFFIXES:
                continue
            if _EXCLUDED_PARTS & set(path.parts):
                continue
            files.append(path)
    return files


def _violations() -> list[tuple[str, str]]:
    """Return (relative_path, matched_completed_target) for each Done minter."""
    found: list[tuple[str, str]] = []
    for path in _iter_candidate_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _SELF_EXEMPT:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - binary stragglers
            continue
        if _ALLOW_ANNOTATION in text:
            continue
        if not _STATE_MUTATION.search(text):
            continue
        target = _COMPLETED_TARGET.search(text)
        if target is None:
            continue
        found.append((rel, target.group(0).strip()))
    return found


def test_no_committed_recipe_mints_a_linear_done() -> None:
    """No file in this repo may write a Linear completed-type state.

    A merge is ``code-only``/``receipt-bound`` at best. ``Done`` is reachable
    only through ``dod_verify`` with durable evidence, so a recipe that resolves
    the completed-type state AND issues a ``stateId`` mutation is a false-Done
    producer unless it routes through ``close_evidence_gate``.
    """
    violations = _violations()
    assert not violations, (
        "Ungated Linear Done minter(s) found — these write `Done` with no "
        "dod_verify receipt and no closing keyword (OMN-15373):\n"
        + "\n".join(f"  {p}  (completed target: {m})" for p, m in violations)
        + "\n\nFix: route the transition through close_evidence_gate, retarget it "
        "to a non-completed state, or delete the writer. If the match is a "
        f"forensic/illustrative quote, annotate the file with `{_ALLOW_ANNOTATION} "
        "<reason>`."
    )


def test_the_original_offending_workflow_is_gone() -> None:
    """``linear-close-on-merge.yml`` must not come back.

    Pinned by name because a regex gate only catches the shapes it knows: the
    durable fix for OMN-3262's workflow was deletion, and a re-add under the
    same name (even rewritten) should force a re-read of this ticket rather than
    a silent revival. Linear's own git integration already performs the
    merge->state transition for every repo, so this workflow was a duplicate
    producer as well as an ungated one.
    """
    offender = _REPO_ROOT / ".github/workflows/linear-close-on-merge.yml"
    assert not offender.exists(), (
        "`.github/workflows/linear-close-on-merge.yml` was re-added. It flipped "
        "Linear tickets to Done from a branch-name match on PR merge, with no "
        "closing keyword, no evidence gate and no dod_verify receipt "
        "(OMN-15373/OMN-15523). Linear's native git integration already owns the "
        "merge->state transition; do not reintroduce a second, ungated producer."
    )


# ---------------------------------------------------------------------------
# Anti-vacuity: prove the patterns match the real thing they were written for.
# A policy gate whose regex matches nothing passes forever and proves nothing.
# ---------------------------------------------------------------------------

# Verbatim from the deleted `.github/workflows/linear-close-on-merge.yml`
# (omniclaude@dev blob 02fcbb628f5025ba7befe281b223052f77ab39d6).
_DELETED_WORKFLOW_MUTATION = (
    'mutation { issueUpdate(id: \\"$ISSUE_ID\\", '
    'input: { stateId: \\"$DONE_STATE_ID\\" }) { success issue { id state { name } } } }'
)
_DELETED_WORKFLOW_TARGET = (
    "completed = [s for s in states if s.get('type', '').upper() == 'COMPLETED']"
)


def test_mutation_pattern_matches_the_deleted_workflow() -> None:
    assert _STATE_MUTATION.search(_DELETED_WORKFLOW_MUTATION)


@pytest.mark.parametrize(
    "sample",
    [
        _DELETED_WORKFLOW_TARGET,
        'completed = [s for s in states if s.get("type", "").upper() == "COMPLETED"]',
        '{"type": "completed"}',
        'if state["type"] == "completed":',
    ],
)
def test_completed_target_pattern_matches_real_shapes(sample: str) -> None:
    assert _COMPLETED_TARGET.search(sample), sample


@pytest.mark.parametrize(
    "sample",
    [
        # Unrelated completion status literals that must NOT trip the gate.
        'status="completed",',
        'COMPLETED = "completed"',
        'if state in {"completed", "queued", "in_progress"}:',
    ],
)
def test_completed_target_pattern_ignores_unrelated_status_literals(
    sample: str,
) -> None:
    assert not _COMPLETED_TARGET.search(sample), sample


def test_by_name_state_resolution_is_not_flagged() -> None:
    """The sanctioned shape issues the same mutation and must stay clean.

    An evidence-gated caller resolves the target state by NAME and never selects
    on ``type == completed``, so the conjunction excludes it. Unlike omnimarket
    — where this assertion is pinned to the live ``LinearHttpClient.save_issue``
    — omniclaude has NO ``issueUpdate`` call site at all outside the workflow
    this PR deletes (verified at ``omniclaude@dev`` 005a2db4:
    ``git grep -lE 'issueUpdate|issueBatchUpdate'`` returned only
    ``.github/workflows/linear-close-on-merge.yml``). Pinning to a file that does
    not exist would be a vacuous assertion, so the sanctioned shape is asserted
    directly. If a by-name writer is later added here, this sample is the shape
    it must keep.
    """
    sanctioned = (
        "mutation { issueUpdate(id: $id, input: { stateId: $stateId }) { success } }\n"
        'target = next(s for s in states if s["name"] == desired_state_name)'
    )
    assert _STATE_MUTATION.search(sanctioned), "expected the mutation signal to fire"
    assert not _COMPLETED_TARGET.search(sanctioned)
