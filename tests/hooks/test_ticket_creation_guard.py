# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Ticket-creation admission gate: the checker and the registered hook (OMN-17942).

Two layers, both load-bearing, for the reasons OMN-17499's suite states.

The **checker** cases pin the admission rules themselves — which field is
missing, whether the binding line is a real line or an incidental substring,
and which shapes are refused rather than assumed clean.

The **hook** cases run the registered script end to end as a subprocess. That
is not redundant with the checker cases: OMN-8928 is the counterexample this
plugin's canary harness exists for — its Python returned a correct
``{"decision": "block"}`` and the registered hook still exited 0, because
``error-guard.sh`` installs an EXIT trap that converts a non-zero exit to 0 and
that script never called ``trap - EXIT``. A unit test on the decision core
would have passed. Only running the command the harness runs tells the two
apart.

Why the gate exists at all, measured over Linear 2026-08-22 → 2026-09-04:
1553 tickets created in 14 days (~111/day) against ~35/day closed; 1537 of them
under the single API identity every lane writes as; 398 never touched again;
779 never left Backlog; 343 unclassifiable by title. The control in place was
prose in CLAUDE.md and in the dispatch briefs. It is the same memory-class
control that failed 41 times in one session in OMN-17499, and here it failed
about 1500 times in a fortnight.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
import yaml

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOKS_DIR = _REPO_ROOT / "plugins" / "onex" / "hooks"
_GUARD_PY = _HOOKS_DIR / "lib" / "ticket_creation_guard.py"
_HOOK_SCRIPT = _HOOKS_DIR / "scripts" / "pre_tool_use_ticket_creation_gate.sh"
_HOOKS_JSON = _HOOKS_DIR / "hooks.json"
_INVENTORY = _HOOKS_DIR / "contracts" / "hook_inventory.yaml"
_POLICY_JSON = _HOOKS_DIR / "config" / "ticket_creation_policy.json"

#: The borrowed mask bit. Its namesake script must stay unregistered — see
#: test_the_borrowed_mask_bit_gates_only_this_guard.
_GATE_BIT_NAME: Final[str] = "LINEAR_DONE_VERIFY"
_GATE_BIT: Final[int] = 0x80000000000

_TIMEOUT_S = 120


def _load_guard() -> ModuleType:
    """Load the decision core by path, not by package name.

    The hook runs the file as a plain script from the plugin cache, where no
    ``plugins`` package exists (the OMN-16983 lesson). Loading it the same way
    keeps the test honest about what actually runs.
    """
    spec = importlib.util.spec_from_file_location("ticket_creation_guard", _GUARD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_GUARD = _load_guard()
POLICY = _GUARD.load_policy()


def _check(tool_input: dict[str, Any]) -> list[Any]:
    return list(_GUARD.check_save_issue(tool_input, POLICY))


def _codes(tool_input: dict[str, Any]) -> set[str]:
    return {f.code for f in _check(tool_input)}


_GOOD_DESCRIPTION = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "The board grows faster than any projection can classify it, so the manual\n"
    "sweep cannot be retired until admission is controlled.\n"
)


def _create(**overrides: Any) -> dict[str, Any]:
    """A well-formed CREATE payload, with named fields overridden."""
    payload: dict[str, Any] = {
        "team": "Omninode",
        "title": "Refuse a Linear create with no binding",
        "parentId": "OMN-16729",
        "project": "7ab68a44-653e-40e1-a770-b5e6a964b159",
        "description": _GOOD_DESCRIPTION,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The shipped policy is config, not a Python literal
# ---------------------------------------------------------------------------


def test_policy_ships_as_json_next_to_the_model_guards_allowlist() -> None:
    assert _POLICY_JSON.is_file(), (
        f"{_POLICY_JSON} is missing. The vocabulary is config so that changing "
        "admission policy is a config edit reviewable in one place, not a "
        "Python literal a reader has to infer the rule from."
    )
    json.loads(_POLICY_JSON.read_text(encoding="utf-8"))


def test_policy_is_read_from_config_not_hardcoded(tmp_path: Path) -> None:
    override = tmp_path / "policy.json"
    override.write_text(
        json.dumps(
            {
                "criterion_ids": ["C1"],
                "invariant_ids": ["INV-001"],
                "epic_markers": ["issue_class: epic"],
                "residual_title_terms": ["nit"],
                "in_progress_state_names": ["in progress"],
                "falsifier_markers": ["falsifier:"],
                "acceptance_criteria_headings": ["acceptance criteria"],
                "state_criterion_markers": [r"\bread back\b"],
                "behaviour_criterion_markers": [r"\brefuses?\b"],
                "merge_state_falsifier_markers": [r"\bgh pr\b"],
                "behaviour_runner_words": ["pytest"],
                "unstarted_children_cap": 3,
                "unstarted_state_types": ["backlog"],
                "override_ledger_paths": ["docs/tracking/ROLLING_WORK_LEDGER.md"],
                "override_ledger_path_prefixes": ["docs/tracking/archive/"],
            }
        ),
        encoding="utf-8",
    )
    policy = _GUARD.load_policy(override)
    assert policy.unstarted_children_cap == 3
    assert policy.unstarted_state_types == frozenset({"backlog"})
    assert policy.criterion_ids == frozenset({"C1"})
    assert policy.invariant_ids == frozenset({"INV-001"})
    assert policy.residual_title_terms == ("nit",)
    assert policy.in_progress_state_names == frozenset({"in progress"})
    assert policy.falsifier_markers == ("falsifier:",)
    assert policy.behaviour_runner_words == ("pytest",)


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ("{}", "no keys at all"),
        ('{"criterion_ids": []}', "missing epic_markers and residual terms"),
        (
            '{"criterion_ids": ["C1"], "invariant_ids": ["INV-001"], '
            '"epic_markers": [], "residual_title_terms": ["nit"]}',
            "an empty epic_markers list makes the epic escape unreachable, "
            "which is a policy change disguised as a blank",
        ),
        (
            '{"criterion_ids": "C1", "invariant_ids": ["INV-001"], '
            '"epic_markers": ["e"], "residual_title_terms": ["nit"]}',
            "criterion_ids is not a list",
        ),
        (
            '{"criterion_ids": ["C1"], "epic_markers": ["e"], '
            '"residual_title_terms": ["nit"]}',
            "invariant_ids is absent -- half the vocabulary silently missing "
            "would refuse every INV binding while the gate reported healthy",
        ),
        (
            '{"criterion_ids": ["C1"], "invariant_ids": ["INV-103", "103"], '
            '"epic_markers": ["e"], "residual_title_terms": ["nit"]}',
            "an invariant id that is not of the form INV-<nnn>",
        ),
        (
            '{"criterion_ids": ["C1"], "invariant_ids": ["INV-12"], '
            '"epic_markers": ["e"], "residual_title_terms": ["nit"]}',
            "the registry spells invariants zero-padded to three digits, so a "
            "two-digit id is a typo and is refused rather than guessed at",
        ),
        ("not json at all", "unparseable"),
    ],
)
def test_malformed_policy_raises_rather_than_defaulting(
    tmp_path: Path, payload: str, why: str
) -> None:
    """A policy that cannot be read must not silently become a permissive one.

    The failure mode this refuses is the one that makes a gate report green
    while enforcing nothing.
    """
    bad = tmp_path / "policy.json"
    bad.write_text(payload, encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)


def test_shipped_residual_vocabulary_covers_the_named_terms() -> None:
    terms = set(POLICY.residual_title_terms)
    for expected in ("follow-up", "residual", "nit", "minor", "cleanup", "noted"):
        assert expected in terms, f"{expected!r} missing from the shipped vocabulary"


# ---------------------------------------------------------------------------
# The admission vocabulary is sourced from the beta PRD, not the charter
# ---------------------------------------------------------------------------
#
# The gate shipped bound to C1..C6 from
# beta/plans/customer-plane-validation-charter-plan.md, because at the time the
# guard landed the beta PRD existed only on a draft PR and no C-id enumeration
# was reachable at origin/main. That PR merged
# (knowledge-base-internal#125 -> main cac690c3), so the citable set is now the
# PRD's own, and the charter is no longer a source: INV-109 rules the
# customer-plane validation probes tests rather than ship conditions, so a
# charter probe id is not a commitment a ticket can bind to.
#
# No charter id had to be DROPPED. The PRD's section 6 table spells C1..C27,
# which covers the six charter spellings; what changed is what each id resolves
# to, not whether the string is admitted.


_PRD_REPO: Final[str] = "OmniNode-ai/knowledge-base-internal"
_PRD_PATH: Final[str] = "beta/requirements/2026-09-04-beta-prd.md"

#: Section 6 release-criteria table rows: ``| **C9** | ... |``.
_PRD_CRITERION_ROW: Final[re.Pattern[str]] = re.compile(
    r"^\|\s*\*\*(C\d+)\*\*\s*\|", re.MULTILINE
)
#: The machine-readable coverage block in the PRD front matter.
_PRD_COVERAGE_BLOCK: Final[re.Pattern[str]] = re.compile(
    r"<!--\s*invariant-coverage:start\s*-->(?P<body>.*?)<!--\s*invariant-coverage:end\s*-->",
    re.DOTALL,
)
_PRD_COVERAGE_ENTRY: Final[re.Pattern[str]] = re.compile(
    r"^-\s*(INV-\d+)\s*$", re.MULTILINE
)


def _prd_source() -> dict[str, Any]:
    """The ``prd_source`` pin shipped alongside the vocabulary."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    source = raw.get("prd_source")
    assert isinstance(source, dict), (
        f"{_POLICY_JSON} carries no 'prd_source' object. The vocabulary is "
        "sourced from a document in another repository, so the exact revision "
        "it was read from has to ship with it -- otherwise 'the ids come from "
        "the PRD' is a claim no one can check."
    )
    return source


def _ids_in_prd(text: str) -> tuple[list[str], list[str]]:
    """Extract the criterion and invariant ids the PRD actually carries.

    Two different surfaces on purpose. The criteria are the rows of the
    section 6 release table, so a C-id mentioned in prose elsewhere is not
    admitted by accident. The invariants are the ``invariant-coverage`` block,
    NOT every ``INV-`` token in the document: the PRD cites deploy- and
    security-scope invariants by reference while explicitly declining to carry
    those scopes, and section 9.2 names INV-108 as process-scoped and carried
    by a different document. Binding a ticket to an id the PRD only mentions
    would be a binding to a commitment this document does not make.
    """
    criteria = _PRD_CRITERION_ROW.findall(text)
    block = _PRD_COVERAGE_BLOCK.search(text)
    invariants = _PRD_COVERAGE_ENTRY.findall(block.group("body")) if block else []
    return criteria, invariants


def _kb_checkout() -> Path | None:
    """A local clone of the PRD's repository, or ``None``.

    Fail-fast on the variable is the omni_home rule for a lane WRITING to that
    repo. Here the checkout is test input, not a destination, and CI runners
    for this repo have no clone of a private sibling -- so the absence is a
    skip with a stated reason, never a silent pass.
    """
    raw = os.environ.get("KNOWLEDGE_BASE_INTERNAL_PATH")
    candidates = [Path(raw)] if raw else []
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        candidates.append(Path(omni_home) / "knowledge-base-internal")
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    return None


def _prd_at(checkout: Path, revision: str) -> str | None:
    """``git show <revision>:<path>``, or ``None`` when the revision is absent."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{_PRD_PATH}"],
        cwd=checkout,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def test_the_shipped_vocabulary_pins_the_revision_it_was_read_from() -> None:
    source = _prd_source()
    assert source.get("repo") == _PRD_REPO
    assert source.get("path") == _PRD_PATH
    commit = source.get("commit")
    assert isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit), (
        f"'prd_source.commit' must be a full 40-character sha, got {commit!r}. "
        "An abbreviated or absent sha cannot be resolved back to one document "
        "state, so the drift check below has nothing to compare against."
    )


def test_the_shipped_criterion_ids_are_the_prd_release_criteria() -> None:
    """C1..C28, contiguous, with no gap and nothing outside the table.

    Offline half of the drift check: it pins the SHAPE of the set on every
    runner, including the ones with no clone of the PRD's repository.

    Was C1..C27 until 2026-09-13. The PRD grew a C28 row and the pin lagged it,
    so a ticket binding to a commitment the document does make was refused --
    found by the origin/main half of this check and repaired under OMN-18331
    rather than carried forward as a red test nobody owns.
    """
    expected = {f"C{n}" for n in range(1, 29)}
    assert set(POLICY.criterion_ids) == expected, (
        "the shipped criterion ids are not the PRD's section 6 table "
        f"(C1..C28); difference: {set(POLICY.criterion_ids) ^ expected}"
    )


def test_the_shipped_invariant_ids_are_the_prd_coverage_block() -> None:
    """43 ids, and the ones the PRD declines to carry are not among them.

    42 until 2026-09-13, when the coverage block gained INV-115; see the
    criterion-id check above for why the bump landed under OMN-18331.
    """
    assert len(POLICY.invariant_ids) == 43, (
        f"expected the PRD's 43-entry invariant-coverage block, got "
        f"{len(POLICY.invariant_ids)} ids"
    )
    for carried in ("INV-012", "INV-103", "INV-109", "INV-113", "INV-115"):
        assert carried in POLICY.invariant_ids
    for not_carried, why in (
        ("INV-108", "process-scoped; section 9.2 says it is carried elsewhere"),
        ("INV-032", "deploy scope, cited by reference only"),
        ("INV-071", "deploy scope, cited by reference only"),
        ("INV-086", "security scope, cited by reference only"),
    ):
        assert not_carried not in POLICY.invariant_ids, (
            f"{not_carried} must not be bindable: {why}"
        )


def test_a_prd_criterion_id_binds() -> None:
    """The whole point of the repoint: C7..C27 did not exist in the charter."""
    for cid in ("C7", "C9", "C17", "C27"):
        assert "missing_gate_line" not in _codes(
            _create(description=f"Gate: {cid}\n\nbody\n")
        ), f"Gate: {cid} is a PRD release criterion and must bind"


def test_a_prd_invariant_id_binds() -> None:
    for inv in ("INV-103", "INV-109", "INV-113", "INV-012"):
        assert "missing_gate_line" not in _codes(
            _create(description=f"Gate: {inv}\n\nbody\n")
        ), f"Gate: {inv} is carried by the PRD and must bind"


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Gate: C29", "one past the end of the PRD table"),
        ("Gate: C0", "the table starts at C1"),
        ("Gate: INV-108", "mentioned by the PRD but deliberately not carried"),
        ("Gate: INV-032", "cited by reference from a scope the PRD does not claim"),
        ("Gate: INV-999", "not an invariant at all"),
        ("Gate: INV-12", "not the registry's zero-padded spelling"),
    ],
)
def test_an_id_the_prd_does_not_carry_is_refused(line: str, why: str) -> None:
    assert "missing_gate_line" in _codes(_create(description=f"{line}\n\nbody\n")), (
        f"expected a refusal for {why}"
    )


def test_the_charter_spellings_survive_because_the_prd_spells_them_too() -> None:
    """C1..C6 stay admitted -- what changed is what they resolve to.

    The charter is no longer a source (INV-109), so if the PRD table had
    started at C7 these six would have been dropped. It does not; the note in
    the policy records that this is why they stand.
    """
    for cid in ("C1", "C2", "C3", "C4", "C5", "C6"):
        assert cid in POLICY.criterion_ids


def test_the_pinned_revision_carries_the_shipped_ids() -> None:
    """Drift check, against the exact revision the policy names."""
    checkout = _kb_checkout()
    if checkout is None:
        pytest.skip(
            "no local checkout of "
            f"{_PRD_REPO}: neither KNOWLEDGE_BASE_INTERNAL_PATH nor "
            "$OMNI_HOME/knowledge-base-internal resolves to a git clone. The "
            "PRD lives in a private sibling repository that this repo's CI "
            "runners do not clone, so the drift check is a local-lane check; "
            "the offline shape assertions above still run everywhere."
        )
    source = _prd_source()
    commit = source["commit"]
    text = _prd_at(checkout, commit)
    if text is None:
        pytest.skip(
            f"commit {commit} is not present in {checkout}; run "
            "'git fetch origin' in that clone to make the pinned revision "
            "resolvable, then re-run this check."
        )
    criteria, invariants = _ids_in_prd(text)
    assert set(criteria) == set(POLICY.criterion_ids), (
        f"criterion ids drifted from {_PRD_PATH} at {commit[:8]}: "
        f"{set(criteria) ^ set(POLICY.criterion_ids)}"
    )
    assert set(invariants) == set(POLICY.invariant_ids), (
        f"invariant ids drifted from {_PRD_PATH} at {commit[:8]}: "
        f"{set(invariants) ^ set(POLICY.invariant_ids)}"
    )


def test_the_pin_is_still_current_with_the_prd_on_origin_main() -> None:
    """The PRD moved and the pin did not: bump both in one change.

    Distinct from the check above, which only proves the pin is honest about
    the revision it names. This one is the reason the pin does not quietly rot
    into a description of a document state nobody has read for months.
    """
    checkout = _kb_checkout()
    if checkout is None:
        pytest.skip(
            f"no local checkout of {_PRD_REPO} (see the pinned-revision check "
            "for why this is a skip and not a pass)"
        )
    text = _prd_at(checkout, "origin/main")
    if text is None:
        pytest.skip(
            f"{checkout} has no origin/main ref carrying {_PRD_PATH}; run "
            "'git fetch origin' in that clone."
        )
    criteria, invariants = _ids_in_prd(text)
    source = _prd_source()
    assert set(criteria) == set(POLICY.criterion_ids) and set(invariants) == set(
        POLICY.invariant_ids
    ), (
        f"{_PRD_PATH} at origin/main no longer matches the ids pinned at "
        f"{source['commit'][:8]}. Criterion delta: "
        f"{set(criteria) ^ set(POLICY.criterion_ids)}; invariant delta: "
        f"{set(invariants) ^ set(POLICY.invariant_ids)}. Update "
        "criterion_ids, invariant_ids and prd_source.commit together -- a "
        "vocabulary that lags its source admits bindings to commitments the "
        "document no longer makes, and refuses the ones it does."
    )


# ---------------------------------------------------------------------------
# Updates are never gated
# ---------------------------------------------------------------------------


def test_an_update_is_never_gated() -> None:
    """`save_issue` with an `id` edits an existing row and creates nothing.

    Gating it would block every state flip, every description repair and every
    parent re-link the board-truth work depends on.
    """
    assert (
        _check(
            {
                "id": "OMN-17942",
                "state": "In Progress",
                "description": "no Gate line, no parent, no project",
            }
        )
        == []
    )


def test_an_update_that_removes_the_parent_is_still_not_gated() -> None:
    assert _check({"id": "OMN-17942", "parentId": None}) == []


# ---------------------------------------------------------------------------
# The four admission rules
# ---------------------------------------------------------------------------


def test_a_well_formed_create_is_allowed() -> None:
    assert _check(_create()) == []


def test_create_without_a_parent_is_refused() -> None:
    assert "missing_parent" in _codes(_create(parentId=None))


def test_create_with_no_parent_key_at_all_is_refused() -> None:
    payload = _create()
    del payload["parentId"]
    assert "missing_parent" in _codes(payload)


def test_create_with_a_blank_parent_is_refused() -> None:
    assert "missing_parent" in _codes(_create(parentId="   "))


def test_an_epic_marker_in_the_description_substitutes_for_a_parent() -> None:
    payload = _create()
    del payload["parentId"]
    payload["description"] = "issue_class: epic\n\n" + _GOOD_DESCRIPTION
    assert "missing_parent" not in _codes(payload)


def test_the_epic_marker_must_be_its_own_line() -> None:
    """Rule 15 of the workspace doctrine, applied here.

    A gate that substring-matches fires on prose that merely mentions the
    trigger — and, the direction that matters, PASSES on prose that mentions
    it while meaning nothing. "this is not an issue_class: epic, it is a
    child" would otherwise open the parent escape.
    """
    payload = _create()
    del payload["parentId"]
    payload["description"] = (
        "This row is not an issue_class: epic, it is a child of the epic.\n\n"
        + _GOOD_DESCRIPTION
    )
    assert "missing_parent" in _codes(payload)


def test_create_without_a_project_is_refused() -> None:
    payload = _create()
    del payload["project"]
    assert "missing_project" in _codes(payload)


def test_create_with_a_null_project_is_refused() -> None:
    assert "missing_project" in _codes(_create(project=None))


def test_the_projectid_spelling_is_accepted_too() -> None:
    """The MCP surface's field is `project`; `projectId` is what the REST API
    and half the internal prose call it. Both name the same requirement, and a
    guard that refuses one spelling teaches lanes to work around it rather than
    to name a project."""
    payload = _create()
    del payload["project"]
    payload["projectId"] = "7ab68a44-653e-40e1-a770-b5e6a964b159"
    assert "missing_project" not in _codes(payload)


def test_create_without_a_gate_line_is_refused() -> None:
    assert "missing_gate_line" in _codes(
        _create(description="Some work that should happen.\n")
    )


def test_create_with_no_description_at_all_is_refused() -> None:
    payload = _create()
    del payload["description"]
    assert "missing_gate_line" in _codes(payload)


@pytest.mark.parametrize(
    "line",
    [
        "Gate: C1",
        "Gate: C27",
        "Gate: INV-103",
        "Gate: OMN-16729 AC-5",
        "Gate: OMN-16106 AC-12",
        "Gate: live-gate defect: kb-doc-gate",
        "Gate: live-gate defect: deploy-gate / deploy-gate",
        "  Gate: OMN-16729 AC-5",
    ],
)
def test_every_accepted_binding_form_passes(line: str) -> None:
    assert "missing_gate_line" not in _codes(
        _create(description=f"{line}\n\nWhy this is the binding.\n")
    )


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("Gate: C99", "a criterion id that is not in the shipped set"),
        ("Gate: OMN-16729", "a parent with no acceptance-criterion ordinal"),
        ("Gate: OMN-16729 AC-", "an empty ordinal"),
        ("Gate: AC-5", "an ordinal with no parent"),
        ("Gate: live-gate defect:", "a defect with no check named"),
        ("Gate: because it seemed useful", "free text"),
        ("Gate:", "the keyword alone"),
    ],
)
def test_a_gate_line_that_binds_to_nothing_is_refused(line: str, why: str) -> None:
    assert "missing_gate_line" in _codes(_create(description=f"{line}\n\nbody\n")), (
        f"expected a refusal for {why}"
    )


def test_the_gate_line_must_be_a_line_not_a_substring() -> None:
    """The same rule-15 failure, on the binding half.

    "the ticket carries no Gate: OMN-1 AC-1 line" would otherwise satisfy the
    gate by describing its own absence — a gate firing green on documentation
    about the gate, which is exactly the OCC#7213 shape.
    """
    assert "missing_gate_line" in _codes(
        _create(description="This row carries no Gate: OMN-16729 AC-5 binding yet.\n")
    )


def test_a_bulleted_gate_line_is_refused() -> None:
    """The OCC `Evidence-Ticket:` convention is unbulleted for the same reason:
    a bullet is how a line ends up inside a checklist that nothing binds."""
    assert "missing_gate_line" in _codes(
        _create(description="- Gate: OMN-16729 AC-5\n\nbody\n")
    )


# ---------------------------------------------------------------------------
# Residual-shaped titles
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "Follow-up: tighten the selector",
        "follow up on the review thread",
        "Residual from OMN-17499: the fork case",
        "nit: rename the fixture",
        "Minor cleanup in the hooks dir",
        "Cleanup: delete the dead branch",
        "Noted during review — the log line is duplicated",
    ],
)
def test_a_residual_shaped_title_is_refused(title: str) -> None:
    assert "residual_title" in _codes(_create(title=title))


def test_a_residual_shaped_title_is_allowed_when_it_binds_to_a_live_gate_defect() -> (
    None
):
    """The one exemption, and the reason it exists.

    A live gate that is broken is not a residual — it is a control reporting
    green while enforcing nothing, and the standing rule to comment on the
    parent instead of filing would bury it. The exemption is deliberately
    narrow: a criterion id or a parent AC does NOT unlock a residual title.
    """
    assert "residual_title" not in _codes(
        _create(
            title="Follow-up: kb-doc-gate passes a renamed file",
            description="Gate: live-gate defect: kb-doc-gate\n\nbody\n",
        )
    )


def test_a_criterion_binding_does_not_unlock_a_residual_title() -> None:
    assert "residual_title" in _codes(
        _create(
            title="nit: rename the fixture",
            description="Gate: C1\n\nbody\n",
        )
    )


def test_a_parent_ac_binding_does_not_unlock_a_residual_title() -> None:
    assert "residual_title" in _codes(
        _create(
            title="Residual: the fork case",
            description="Gate: OMN-16729 AC-5\n\nbody\n",
        )
    )


def test_residual_terms_match_on_word_boundaries_not_inside_other_words() -> None:
    """`minor` must not fire on `minority`, and `nit` must not fire on
    `initialise` or `monitor`. A gate that refuses correct work teaches lanes
    to route around it, which costs more than the tickets it stops."""
    for title in (
        "Monitor the queue depth for the delegation lane",
        "Initialise the tenant credential chain",
        "Report the minority-class routing split",
    ):
        assert "residual_title" not in _codes(_create(title=title)), title


# ---------------------------------------------------------------------------
# Fail-closed on a malformed call
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tool_input", "why"),
    [
        ({}, "no fields at all"),
        ({"title": "x"}, "a create with nothing but a title"),
        ({"id": "", "title": "x"}, "an id that is present but blank"),
        ({"id": 17942, "title": "x"}, "an id that is not a string"),
        ({"title": None, "parentId": "OMN-1", "project": "p"}, "a null title"),
        ({"title": 3, "parentId": "OMN-1", "project": "p"}, "a non-string title"),
        (
            {"title": "x", "parentId": "OMN-1", "project": "p", "description": 7},
            "a non-string description",
        ),
    ],
)
def test_an_unevaluable_create_is_refused(tool_input: dict[str, Any], why: str) -> None:
    assert _check(tool_input), f"expected a refusal for {why}"


def test_a_template_create_with_no_description_is_refused() -> None:
    """A `template` fills the body server-side, so the guard cannot see whether
    a binding line is in it. Refusing is the fail-closed reading: a create
    whose text the guard never sees is unverified, not clean."""
    codes = _codes(
        {
            "team": "Omninode",
            "title": "From a template",
            "parentId": "OMN-16729",
            "project": "7ab68a44",
            "template": "Bug report",
        }
    )
    assert "missing_gate_line" in codes


def test_the_block_reason_names_the_missing_field_and_the_fix() -> None:
    reason = _GUARD.render_block_reason(_check(_create(parentId=None)), POLICY)
    assert "parentId" in reason
    assert "OMN-17942" in reason
    assert _GATE_BIT_NAME in reason, (
        "the refusal must name its own disable switch, or a lane blocked by a "
        "guard it thinks is wrong has no route except to work around it"
    )


def test_the_block_reason_lists_every_failing_rule_at_once() -> None:
    """One refusal per call, naming everything wrong with it.

    A guard that reports one missing field per attempt turns a single fix into
    four round trips, and each round trip is a chance for the lane to give up
    and file the ticket from somewhere the gate does not see.
    """
    reason = _GUARD.render_block_reason(
        _check({"title": "nit: a thing", "team": "Omninode"}), POLICY
    )
    for expected in ("parentId", "project", "Gate:"):
        assert expected in reason


# ---------------------------------------------------------------------------
# The registered hook, end to end
# ---------------------------------------------------------------------------


def _registered_command() -> str:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    commands = [
        hook["command"]
        for group in data["hooks"]["PreToolUse"]
        for hook in group["hooks"]
    ]
    matching = [c for c in commands if c.endswith("/" + _HOOK_SCRIPT.name)]
    assert matching, (
        f"hooks.json does not register {_HOOK_SCRIPT.name}. This test FAILS "
        "rather than skips on purpose: an unregistered enforcement hook is "
        "exactly the OMN-13244 defect, and a skipped check reports it as green."
    )
    return str(matching[0])


def _matcher_for_registered_hook() -> str:
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    for group in data["hooks"]["PreToolUse"]:
        for hook in group["hooks"]:
            if hook["command"].endswith("/" + _HOOK_SCRIPT.name):
                return str(group["matcher"])
    raise AssertionError(f"{_HOOK_SCRIPT.name} is not registered")


def _hook_ledger(tmp_path: Path) -> Path:
    """Where the guard's log lines actually land.

    `onex-paths.sh` *exports* ONEX_HOOK_LOG unconditionally as
    ``$ONEX_STATE_DIR/logs/hooks.log``, overwriting whatever the caller set. So
    a caller-supplied ONEX_HOOK_LOG is not honoured, and asserting against one
    would test a file no hook on this machine ever writes. The state-dir path is
    the shared hook ledger every sibling guard logs to; that is the surface
    these tests read.
    """
    return tmp_path / "state" / "logs" / "hooks.log"


def _run_hook(
    payload: dict[str, Any], tmp_path: Path, *, mask: str | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
        "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
        "ONEX_STATE_DIR": str(tmp_path / "state"),
        # Pinned, not inherited: mode.sh resolves "lite" for some cwds, and the
        # question here is whether the hook enforces, not what mode the host is
        # in.
        "OMNICLAUDE_MODE": "full",
    }
    if mask is not None:
        env["ONEX_HOOKS_MASK"] = mask
    return subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=_TIMEOUT_S,
        check=False,
    )


def test_hook_script_is_registered_and_executable() -> None:
    assert _registered_command().endswith("/" + _HOOK_SCRIPT.name)
    assert os.access(_HOOK_SCRIPT, os.X_OK), f"{_HOOK_SCRIPT} is not executable"


def test_the_matcher_covers_the_linear_write_surface() -> None:
    matcher = _matcher_for_registered_hook()
    assert "save_issue" in matcher, (
        "mcp__linear-server__save_issue is the create path every lane writes "
        f"through; the registered matcher {matcher!r} does not cover it"
    )


def test_jq_is_available() -> None:
    """The hook renders its decision with ``jq -n``, as every sibling guard
    does. Asserted rather than skipped around: without jq the block payload
    never reaches stdout, the script exits non-zero, and ``error-guard.sh``
    converts that to exit 0 — a silent fail-OPEN."""
    assert shutil.which("jq") is not None


def test_the_borrowed_mask_bit_gates_only_this_guard() -> None:
    """`LINEAR_DONE_VERIFY` must remain a one-control switch.

    This guard borrows that bit because a dedicated one is not mintable here:
    `EnumHookBit` lives in omnibase_core, all 60 default-mask ordinals are
    allocated, 60-62 are the disabled-by-default trio, and
    knowledge-base-internal `reference/hook-bitmask-bit-governance.md` rule 7
    forbids ordinal 63 outright.

    The borrow is only honest while the bit's namesake script stays
    unregistered. `pre_tool_use_linear_done_verify.sh` is on disk and dark
    under the OMN-13244 baseline — its merged-PR semantics were folded into
    `pre_tool_use_done_flip_guard.sh` by OMN-13856 — so today
    `onex hooks disable LINEAR_DONE_VERIFY` disables exactly this guard. If
    someone re-registers it, that one command silently turns off two controls,
    which is the quiet switch-mismatch the OMN-17020 inventory exists to
    refuse.
    """
    data = json.loads(_HOOKS_JSON.read_text(encoding="utf-8"))
    registered = {
        hook["command"].rsplit("/", 1)[-1]
        for group in data["hooks"].get("PreToolUse", [])
        for hook in group["hooks"]
    }
    assert "pre_tool_use_linear_done_verify.sh" not in registered, (
        "pre_tool_use_linear_done_verify.sh has been registered, so "
        "LINEAR_DONE_VERIFY now gates two controls. Either mint this guard its "
        "own EnumHookBit (an omnibase_core change plus the architecture review "
        "knowledge-base-internal reference/hook-bitmask-bit-governance.md rule "
        "7 requires), or move one of the two to a different bit. Do not leave "
        "two guards behind one switch."
    )


def test_the_hook_is_declared_in_the_typed_inventory() -> None:
    """OMN-17020: a registration hooks.json carries and the inventory does not
    is exactly the drift the hook-inventory gate fails closed on."""
    inventory = yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))
    entries = [
        h for h in inventory["expected_hooks"] if h["script"] == _HOOK_SCRIPT.name
    ]
    assert entries, f"{_HOOK_SCRIPT.name} is not declared in {_INVENTORY}"
    entry = entries[0]
    assert entry["ticket"] == "OMN-17942"
    assert entry["event"] == "PreToolUse"
    assert entry["enforcement"] is True
    assert entry["mask"]["gate_call"] == _GATE_BIT_NAME
    assert entry["mask"]["bit_defined"] is True
    assert entry["canary"]["kind"] == "block"


def test_registered_hook_blocks_a_create_with_no_binding(tmp_path: Path) -> None:
    """The OMN-8928 shape: a correct verdict whose exit code is swallowed
    enforces nothing. Assert the exit code and the payload, from the command
    the harness actually runs."""
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {
                "team": "Omninode",
                "title": "Some work that occurred to a lane",
                "description": "It would be good to do this.\n",
            },
        },
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, (
        f"expected a block (exit 2), got {result.returncode}.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert '"decision": "block"' in combined
    assert "parentId" in combined
    assert "project" in combined
    assert "Gate:" in combined
    assert _GATE_BIT_NAME in combined


def test_registered_hook_blocks_a_residual_title(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {
                "team": "Omninode",
                "title": "Follow-up: tighten the selector",
                "parentId": "OMN-16729",
                "project": "7ab68a44",
                "description": "Gate: OMN-16729 AC-5\n\nbody\n",
            },
        },
        tmp_path,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2, combined
    assert "residual" in combined.lower()


def test_registered_hook_allows_a_well_formed_create(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": _create(),
        },
        tmp_path,
    )
    assert result.returncode == 0, (
        f"a well-formed create was refused.\nstdout: {result.stdout!r}\n"
        f"stderr: {result.stderr!r}"
    )


def test_registered_hook_allows_an_update(tmp_path: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"id": "OMN-17942", "state": "In Progress"},
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_registered_hook_blocks_an_unparseable_payload(tmp_path: Path) -> None:
    """Only the Linear write surface reaches this hook, so refusing an
    unreadable payload cannot strand any other tool."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input="{not json",
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(home),
            "CLAUDE_PLUGIN_ROOT": str(_HOOKS_DIR.parent),
            "CLAUDE_PROJECT_DIR": str(_REPO_ROOT),
            "ONEX_STATE_DIR": str(tmp_path / "state"),
            "OMNICLAUDE_MODE": "full",
        },
        timeout=_TIMEOUT_S,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_registered_hook_passes_through_another_tool(tmp_path: Path) -> None:
    """A tool other than the Linear write surface is passed through untouched,
    so a bug in this guard can never brick unrelated traffic."""
    result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_disable_switch_allows_and_logs_a_notice(tmp_path: Path) -> None:
    """`onex hooks disable LINEAR_DONE_VERIFY` clears the bit in the mask.

    A disabled guard must still leave a trace. The OMN-13244 history is a hook
    going dark with no repo-visible signal for months; a silent `exit 0` here
    would reproduce it one mask edit at a time.
    """
    disabled = hex(0xFFFFFFFFFFFFFFF & ~_GATE_BIT)
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"team": "Omninode", "title": "no binding at all"},
        },
        tmp_path,
        mask=disabled,
    )
    assert result.returncode == 0, (
        "the mask bit is cleared, so the guard must not refuse.\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    log = _hook_ledger(tmp_path).read_text(encoding="utf-8")
    assert _GATE_BIT_NAME in log
    assert "DISABLED" in log


def test_a_refusal_is_recorded_in_the_hook_log(tmp_path: Path) -> None:
    """The model gate logs its refusals; so does this one. A refusal nobody can
    count is a control nobody can measure, and the measurement is the whole
    reason this gate exists."""
    _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": {"team": "Omninode", "title": "no binding at all"},
        },
        tmp_path,
    )
    log = _hook_ledger(tmp_path).read_text(encoding="utf-8")
    assert "BLOCKED" in log
    assert "ticket-creation-gate" in log


# ---------------------------------------------------------------------------
# Rule 5 — a create that STARTS In Progress needs an executable probe
# ---------------------------------------------------------------------------
#
# Why: the scheduled evidence closer (OMN-16106) re-runs `onex skill dod_verify`
# against the checks a ticket's OCC contract declares. A ticket whose definition
# of done is prose declares no check it can run, so it is structurally
# unreachable by every closing mechanism and can only ever be closed by a person
# reading it — four such tickets sit In Progress in the 2026-08-31 sprint. The
# probe line is the one thing that must exist at the START for a ticket to be
# mechanically closeable at the end.

_PROBE = "Probe: uv run pytest tests/hooks/test_ticket_creation_guard.py -q => exits 0"


def _in_progress(**overrides: Any) -> dict[str, Any]:
    payload = _create(state="In Progress")
    payload.update(overrides)
    return payload


def test_in_progress_create_without_a_probe_is_refused() -> None:
    codes = {finding.code for finding in _check(_in_progress())}
    assert "missing_probe_line" in codes


def test_in_progress_create_with_a_probe_is_admitted() -> None:
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\n{_PROBE}\n")
    assert _check(payload) == []


@pytest.mark.parametrize(
    "state_value",
    ["In Progress", "in progress", "  IN-PROGRESS  ", "started", "inprogress"],
)
def test_every_configured_in_progress_spelling_fires(state_value: str) -> None:
    codes = {finding.code for finding in _check(_create(state=state_value))}
    assert "missing_probe_line" in codes


@pytest.mark.parametrize("field", ["state", "stateId", "status", "statusType"])
def test_the_rule_reads_every_state_spelling_the_write_surface_accepts(
    field: str,
) -> None:
    codes = {finding.code for finding in _check(_create(**{field: "In Progress"}))}
    assert "missing_probe_line" in codes


def test_a_backlog_create_needs_no_probe() -> None:
    """Rule 5 is scoped to work claimed to be in flight, not to every create.

    A probe demanded at filing time for work nobody has scoped yet is a field a
    lane fills in with something plausible to get past the check.
    """
    assert _check(_create(state="Backlog")) == []
    assert _check(_create()) == []


def test_a_state_uuid_is_not_classified_and_not_refused() -> None:
    """The one fail-OPEN direction, bounded to rule 5 and stated on purpose.

    This module has no workspace lookup, so it cannot resolve a state uuid.
    Refusing on one would make every id-shaped create unfileable; the refusal
    it does make is on a create that says, in words, that it starts In Progress.
    """
    payload = _create(stateId="f1a2b3c4-0000-4d5e-8f90-abcdefabcdef")
    assert _check(payload) == []


def test_a_probe_missing_its_expected_observation_is_refused() -> None:
    """A command with no expected observation is adjudicated by a human read."""
    payload = _in_progress(
        description=f"{_GOOD_DESCRIPTION}\nProbe: uv run pytest tests/unit -q\n"
    )
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes


@pytest.mark.parametrize(
    "probe_body",
    ["=> exits 0", "uv run pytest -q =>", "   =>   "],
)
def test_a_probe_with_a_blank_half_is_refused(probe_body: str) -> None:
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\nProbe: {probe_body}\n")
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes


def test_a_bulleted_probe_does_not_count() -> None:
    """CLAUDE.md rule 15: a bullet is how a line lands inside a checklist.

    The line must bind, not appear in a list of things someone might do.
    """
    payload = _in_progress(description=f"{_GOOD_DESCRIPTION}\n- {_PROBE}\n")
    codes = {finding.code for finding in _check(payload)}
    assert "missing_probe_line" in codes


def test_prose_mentioning_a_probe_does_not_satisfy_the_rule() -> None:
    """The direction that matters for an admission gate.

    A substring rule *passes* on prose that mentions the trigger while meaning
    the opposite — "this ticket has no Probe: line yet" would satisfy it.
    """
    payload = _in_progress(
        description=(
            f"{_GOOD_DESCRIPTION}\n"
            "This ticket has no Probe: line yet because the deliverable is prose.\n"
        )
    )
    codes = {finding.code for finding in _check(payload)}
    assert "malformed_probe_line" in codes or "missing_probe_line" in codes


def test_one_well_formed_probe_among_several_lines_satisfies_the_rule() -> None:
    """Matches how several `Gate:` lines are treated — the strongest one wins."""
    payload = _in_progress(
        description=f"{_GOOD_DESCRIPTION}\nProbe: an example with no arrow\n{_PROBE}\n"
    )
    assert _check(payload) == []


def test_an_update_that_moves_a_ticket_to_in_progress_is_still_not_gated() -> None:
    """The transition surface this module deliberately does not cover.

    A ticket created in Backlog and moved to In Progress later moves by an
    UPDATE, and updates are never gated here. Recording it as a test so the
    scope of rule 5 is a pinned fact rather than a claim in a docstring — if a
    later change starts gating updates, this test is the one that has to be
    deliberately rewritten.
    """
    assert _check({"id": "OMN-16106", "state": "In Progress"}) == []


def test_the_shipped_policy_configures_the_in_progress_vocabulary() -> None:
    assert POLICY.in_progress_state_names
    assert "in progress" in POLICY.in_progress_state_names


def test_a_policy_missing_the_in_progress_vocabulary_is_refused(
    tmp_path: Path,
) -> None:
    """No default in code: an unreadable policy refuses, never widens."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    del raw["in_progress_state_names"]
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)


# ---------------------------------------------------------------------------
# Rules 6 and 7 — a named falsifier per acceptance criterion (OMN-18331)
# ---------------------------------------------------------------------------
#
# The plan these two rules implement puts the criterion-to-check binding at
# ticket-creation time for one reason: it is the only point in the lifecycle
# where the binding is declared BEFORE the evidence exists, BY the party that
# knows the intent, and ATTRIBUTABLY. Every case below is written against that
# claim rather than against the regexes, so a later refactor that keeps the
# rules and moves the machinery leaves these green.

_FALSIFIED_BODY = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "## Acceptance criteria\n"
    "\n"
    "* **AC1 — the guard refuses an unfalsified create.** RED first. "
    "— falsifier: a guard test feeding a create with one unfalsified "
    "criterion asserts a non-zero refusal\n"
    "* **AC2 — the shipped policy carries the vocabulary.** "
    "— falsifier: uv run pytest tests/hooks/test_ticket_creation_guard.py -q\n"
)

_UNFALSIFIED_CRITERION = "AC3 — the refusal names the criterion it refused."


def _with_criteria(*criteria: str, gate: str = "Gate: OMN-16729 AC-5") -> str:
    body = [gate, "", "## Acceptance criteria", ""]
    body.extend(f"* {criterion}" for criterion in criteria)
    body.append("")
    return "\n".join(body)


def _reason(payload: dict[str, Any]) -> str:
    return _GUARD.render_block_reason(_check(payload), POLICY)


# -- AC1: an unfalsified criterion is refused, and the refusal names it ------


def test_a_criterion_naming_no_check_is_refused() -> None:
    """The rule itself. RED before OMN-18331: this create is admitted today."""
    payload = _create(description=_FALSIFIED_BODY + f"* {_UNFALSIFIED_CRITERION}\n")
    assert "unfalsified_criterion" in _codes(payload)


def test_the_refusal_quotes_the_offending_criterion() -> None:
    """A refusal naming a count and not a criterion is one a lane cannot act on.

    The whole design constraint on this gate is that the remedy must be cheaper
    than the workaround. "one of your criteria is unfalsified" fails that; the
    author has to re-read all of them to find which.
    """
    payload = _create(description=_FALSIFIED_BODY + f"* {_UNFALSIFIED_CRITERION}\n")
    reason = _reason(payload)
    assert "the refusal names the criterion it refused" in reason
    assert "AC1" not in reason.split("unfalsified_criterion")[1].split("fix:")[0], (
        "the falsified criteria must not be quoted as offenders — quoting all "
        "of them is the same as quoting none"
    )


def test_the_refusal_counts_the_criteria_it_read() -> None:
    """So an author can tell a rule that read three criteria from one that read
    thirty because a stray bullet list landed inside the section."""
    payload = _create(description=_FALSIFIED_BODY + f"* {_UNFALSIFIED_CRITERION}\n")
    assert "1 of 3 acceptance criteria" in _reason(payload)


def test_many_unfalsified_criteria_are_named_up_to_a_cap() -> None:
    """An unbounded splice is how a refusal hits a transport limit."""
    payload = _create(
        description=_with_criteria(*[f"AC{n} — a criterion." for n in range(1, 21)])
    )
    reason = _reason(payload)
    assert "and 12 more" in reason, reason


# -- AC2: the positive control ----------------------------------------------


def test_a_create_whose_every_criterion_is_falsified_is_admitted() -> None:
    """The control that proves the rule does not simply refuse everything.

    Without this, a guard that blocked every create carrying a criteria section
    would pass every other case in this file.
    """
    assert _check(_create(description=_FALSIFIED_BODY)) == []


def test_the_second_falsifier_spelling_is_admitted() -> None:
    """`Falsified by` is the form already in the corpus (OMN-18135's own
    criteria are written with it). Refusing it would refuse tickets written the
    way the minting lanes already write them."""
    payload = _create(
        description=_with_criteria(
            "AC1 — the guard refuses an unfalsified create. "
            "**Falsified by** a guard test green at the parent commit."
        )
    )
    assert _check(payload) == []


def test_a_falsifier_marker_with_nothing_after_it_does_not_count() -> None:
    """A field filled in to get past a check is the failure mode, not a typo."""
    payload = _create(description=_with_criteria("AC1 — a criterion. — falsifier:"))
    assert "unfalsified_criterion" in _codes(payload)


# -- AC3: a merge-state falsifier on a behaviour criterion ------------------


def test_a_behaviour_criterion_falsified_by_a_merge_state_read_is_refused() -> None:
    """A merged pull request says a change landed. It does not say the
    behaviour the criterion claims actually happens."""
    payload = _create(
        description=_with_criteria(
            "AC1 — the guard refuses a create whose criterion names no check. "
            "— falsifier: gh pr view 2150 --json merged --jq .merged"
        )
    )
    assert "merge_state_falsifier_on_behaviour_criterion" in _codes(payload)


def test_the_same_falsifier_on_a_merge_shaped_criterion_is_admitted() -> None:
    """The control that separates rule 7 from "refuse every gh command".

    A criterion ABOUT merge state is settled by a merge-state read. Refusing
    that would be the gate being wrong, and a lane meeting it would be right.
    """
    payload = _create(
        description=_with_criteria(
            "AC1 — the companion is merged to `main` and read back. "
            "— falsifier: gh pr view 2150 --json merged --jq .merged"
        )
    )
    assert _check(payload) == []


def test_a_falsifier_carrying_both_a_merge_read_and_a_runner_is_admitted() -> None:
    """OMN-18135's measured finding, pinned.

    The repo-qualified `gh api repos/<owner>/<repo>/...` anchor is what receipt
    hardening asks for, and the proof-class module classifies the combined form
    as behaviour because the walk continues past the merge-state segment. A
    rule refusing any falsifier that mentions `gh` would refuse the one shape
    that clears both gates.
    """
    payload = _create(
        description=_with_criteria(
            "AC1 — the guard refuses an unfalsified create. — falsifier: "
            "gh api repos/OmniNode-ai/omniclaude/commits/$SHA --jq .sha && "
            "uv run pytest tests/hooks/test_ticket_creation_guard.py -q"
        )
    )
    assert _check(payload) == []


def test_the_refusal_names_both_the_criterion_and_its_falsifier() -> None:
    """Rule 7's refusal has to say which half to change, because either half
    is a legitimate edit: reword the criterion, or name a real check."""
    payload = _create(
        description=_with_criteria(
            "AC1 — the guard refuses an unfalsified create. "
            "— falsifier: gh pr view 2150 --json merged"
        )
    )
    reason = _reason(payload)
    assert "the guard refuses an unfalsified create" in reason
    assert "gh pr view 2150 --json merged" in reason


def test_an_ambiguous_criterion_is_admitted_rather_than_refused() -> None:
    """The inverted tie-break, pinned as behaviour rather than left in prose.

    The source classifier resolves a criterion carrying BOTH marker classes to
    "not state-shaped", because there a tie holds a flip. Here a tie must be
    ADMITTED, because here it refuses a create. Same wordlist, opposite
    default — if a later change makes this file's classifier agree with its
    source's tie-break, this test is the one that goes red.
    """
    payload = _create(
        description=_with_criteria(
            "AC1 — the handler refuses the write and the row is read back "
            "from the live database. — falsifier: gh pr view 2150 --json merged"
        )
    )
    assert _check(payload) == []


def test_a_criterion_with_no_marker_either_way_is_admitted() -> None:
    payload = _create(
        description=_with_criteria(
            "AC1 — the document records the ruling. "
            "— falsifier: gh pr view 2150 --json merged"
        )
    )
    assert _check(payload) == []


# -- the item boundary does the anchoring work ------------------------------


def test_a_falsifier_on_one_criterion_does_not_discharge_the_next() -> None:
    """Rules 3 and 5 anchor to a whole line; this rule anchors to an ITEM.

    That is the one departure from whole-line matching in this module, so the
    property it trades for has to be a pinned fact: a body-wide substring rule
    would let one falsifier satisfy every criterion in the list, which is the
    exact shape CLAUDE.md rule 15 exists to refuse.
    """
    payload = _create(
        description=_with_criteria(
            "AC1 — a criterion. — falsifier: uv run pytest tests/x.py -q",
            "AC2 — a second criterion with no check of its own.",
        )
    )
    reason = _reason(payload)
    assert "unfalsified_criterion" in _codes(payload)
    assert "a second criterion with no check of its own" in reason


def test_a_wrapped_falsifier_on_a_continuation_line_is_read() -> None:
    """Markdown wraps. A rule that only read the first physical line of an item
    would refuse correctly-written tickets, which is design constraint 5."""
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n"
            "\n"
            "## Acceptance criteria\n"
            "\n"
            "* **AC1 — the guard refuses an unfalsified create.**\n"
            "  RED first, then green.\n"
            "  — falsifier: uv run pytest tests/hooks/test_x.py -q\n"
        )
    )
    assert _check(payload) == []


def test_criteria_stop_at_the_next_markdown_heading() -> None:
    """An `## Out of scope` list is not a list of acceptance criteria."""
    payload = _create(
        description=(
            _FALSIFIED_BODY
            + "\n## Out of scope\n\n"
            + "* Judging whether a declared falsifier is a good one.\n"
        )
    )
    assert _check(payload) == []


def test_an_unbulleted_ac_line_is_read_as_a_criterion() -> None:
    """`**AC1** — ...` with no bullet is a shape that exists in this corpus and
    that a list-item-only parser silently counts as zero."""
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n\n## Acceptance criteria\n\n"
            "**AC1** — a criterion with no named check.\n"
        )
    )
    assert "unfalsified_criterion" in _codes(payload)


# -- the stated fail-open direction, bounded to rule 6 ----------------------


def test_a_description_with_no_criteria_heading_is_not_gated() -> None:
    """The deliberate divergence from the closer's parser, pinned.

    That parser reads the WHOLE BODY when it finds no heading, because there an
    over-count HOLDS a flip. Here an over-count REFUSES a create, so the
    fallback is dropped: a bullet list in a Why section is not a criterion
    list, and refusing on one is how a gate teaches lanes to route around it.

    This is a fail-OPEN direction and it is bounded to rule 6. Such a ticket
    declares no map, the autobinder transcribes nothing, and the closer holds
    it on an unbound criterion — today's behaviour for the whole corpus.
    """
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n\n"
            "## Why\n\n"
            "* the board grows faster than any projection can classify it\n"
            "* the manual sweep cannot be retired until admission is controlled\n"
        )
    )
    assert _check(payload) == []


def test_a_criteria_heading_under_its_other_standing_name_is_read() -> None:
    """`Definition of done` makes the identical statement, and reading only one
    spelling is the formatting-dependence the closer's parser already removed."""
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n\n## Definition of done\n\n"
            "* AC1 — a criterion with no named check.\n"
        )
    )
    assert "unfalsified_criterion" in _codes(payload)


def test_a_heading_with_a_trailing_qualifier_still_opens_the_section() -> None:
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n\n## Acceptance criteria (falsifiable)\n\n"
            "* AC1 — a criterion with no named check.\n"
        )
    )
    assert "unfalsified_criterion" in _codes(payload)


def test_a_heading_that_merely_mentions_the_section_does_not_open_it() -> None:
    """Closed-set membership, not a prefix match — the same reason rule 1
    refuses a prefix rule on the epic marker."""
    payload = _create(
        description=(
            "Gate: OMN-16729 AC-5\n\n## Acceptance criteria coverage report\n\n"
            "* a bullet that is not a criterion\n"
        )
    )
    assert _check(payload) == []


def test_an_update_is_never_gated_on_falsifiers() -> None:
    """Only creation is gated, so history is untouched.

    Gating updates would refuse every repair of a pre-OMN-18331 ticket, which
    would make the remedy for the whole existing corpus impossible — the
    opposite of design constraint 5.
    """
    assert (
        _check(
            {
                "id": "OMN-16106",
                "description": _with_criteria("AC1 — a criterion with no check."),
            }
        )
        == []
    )


# -- AC5: the refusal is legible enough that the remedy is the cheaper path --


def test_the_refusal_shows_an_example_falsifier_line() -> None:
    """A refusal that names a problem without naming its remedy is one a lane
    routes around. The grammar and a worked example both have to be in it."""
    payload = _create(description=_with_criteria("AC1 — a criterion with no check."))
    reason = _reason(payload)
    assert "falsifier:" in reason
    assert "check name or a command shape" in reason
    assert "never a result" in reason


def test_the_merge_state_refusal_names_the_shape_that_clears_both_gates() -> None:
    """The combined form is the thing an author most needs told, because the
    two gates look mutually exclusive and are not."""
    payload = _create(
        description=_with_criteria(
            "AC1 — the guard refuses an unfalsified create. "
            "— falsifier: gh pr view 2150 --json merged"
        )
    )
    reason = _reason(payload)
    assert "gh api repos/<owner>/<repo>/commits/<sha>" in reason
    assert "uv run pytest" in reason


# -- AC4: wired as the hook, with no exemption ------------------------------


def test_the_registered_hook_blocks_an_unfalsified_create(tmp_path: Path) -> None:
    """The rule ships wired into the pre-tool-use path, not as a sweep.

    Not redundant with the checker cases: OMN-8928 is the counterexample this
    harness exists for — correct Python, and the registered hook still exited
    0 because an EXIT trap converted the non-zero exit.
    """
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": _create(
                description=_with_criteria("AC1 — a criterion with no named check.")
            ),
        },
        tmp_path,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert '"decision": "block"' in result.stdout
    assert "a criterion with no named check" in result.stdout


def test_the_registered_hook_admits_a_fully_falsified_create(tmp_path: Path) -> None:
    """The end-to-end positive control. Without it, a hook that blocked every
    create would satisfy the case above."""
    result = _run_hook(
        {
            "tool_name": "mcp__linear-server__save_issue",
            "tool_input": _create(description=_FALSIFIED_BODY),
        },
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_new_rules_have_no_exemption_or_allowlist_key() -> None:
    """There is no sanctioned spelling for an unfalsified criterion.

    A create that cannot be evaluated is refused; a create that declares no
    criteria section is out of rule 6's scope by a stated boundary, which is
    not the same thing as an exemption an author can write into a ticket.
    """
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    forbidden = {
        "falsifier_exempt",
        "falsifier_allowlist",
        "skip_falsifier",
        "unfalsified_allowed",
        "criteria_exempt",
    }
    assert not forbidden & set(raw), (
        f"an escape hatch was added: {forbidden & set(raw)}"
    )
    source = _GUARD_PY.read_text(encoding="utf-8")
    for token in ("ONEX_SKIP_FALSIFIER", "allow_unfalsified", "FALSIFIER_OPT_IN"):
        assert token not in source, f"{token} is an opt-in; rule 6 has none"


def test_the_inventory_contract_records_the_new_rules() -> None:
    """The guard's own inventory contract is what a reader consults to learn
    what this hook enforces. A rule absent from it is a rule nobody finds."""
    inventory = yaml.safe_load(_INVENTORY.read_text(encoding="utf-8"))
    entry = next(
        item
        for group in inventory.values()
        if isinstance(group, list)
        for item in group
        if isinstance(item, dict) and item.get("script") == _HOOK_SCRIPT.name
    )
    purpose = entry["purpose"]
    assert "falsifier" in purpose.lower(), purpose
    assert "OMN-18331" in purpose, purpose


# -- the vocabulary is config, and it is pinned to its source ---------------


def test_the_shipped_policy_configures_the_falsifier_vocabulary() -> None:
    assert POLICY.falsifier_markers[0] == "falsifier:"
    assert "falsified by" in POLICY.falsifier_markers
    assert POLICY.acceptance_criteria_headings
    assert POLICY.state_criterion_markers
    assert POLICY.behaviour_criterion_markers
    assert POLICY.merge_state_falsifier_markers
    assert "pytest" in POLICY.behaviour_runner_words


@pytest.mark.parametrize(
    "key",
    [
        "falsifier_markers",
        "acceptance_criteria_headings",
        "state_criterion_markers",
        "behaviour_criterion_markers",
        "merge_state_falsifier_markers",
        "behaviour_runner_words",
    ],
)
def test_a_policy_missing_a_falsifier_key_is_refused(tmp_path: Path, key: str) -> None:
    """No default in code, for the new vocabulary as for the old: a policy that
    cannot be read must not silently become a permissive one."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    del raw[key]
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)


def test_a_marker_that_is_not_a_regex_is_refused_at_load(tmp_path: Path) -> None:
    """A regex error raised from inside a rule would surface as an unhandled
    exception, which the wrapper treats as a block — every Linear create on the
    machine failing with a traceback instead of a policy error naming the
    pattern."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    raw["state_criterion_markers"] = [r"\bunbalanced("]
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(bad)


def _sibling_clone(repo: str) -> Path | None:
    """A sibling clone of ``repo``, or ``None`` when none is present.

    Resolved from OMNI_HOME, falling back to this repo's own parent directory.
    No default path and no guess: an absent clone SKIPS with a stated reason
    (this repo's CI runners clone neither source repository), and a wrong path
    would compare against a file that is not the source.
    """
    roots = []
    workspace_root = os.environ.get("OMNI_HOME")
    if workspace_root:
        roots.append(Path(workspace_root))
    roots.append(_REPO_ROOT.parent)
    for root in roots:
        candidate = root / repo
        if candidate.is_dir():
            return candidate
    return None


def _verbose_alternatives(source: str, symbol: str) -> list[str]:
    """The alternation branches of a verbose regex literal in ``source``.

    Reads the branches the way ``re.VERBOSE`` does — one per line, trailing
    comments and whitespace dropped — so a drift in either direction shows up
    as a list difference naming the branch rather than as an opaque mismatch.
    """
    start = source.index(f"{symbol}: re.Pattern[str] = re.compile(")
    body = source[
        source.index('r"""', start) + 4 : source.index(
            '"""', source.index('r"""', start) + 4
        )
    ]
    branches: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("(?") or stripped.startswith("#"):
            continue
        stripped = re.split(r"\s+#", stripped, maxsplit=1)[0].strip()
        if not stripped:
            continue
        branches.append(stripped.lstrip("|").strip())
    return branches


def test_the_criterion_vocabulary_has_not_drifted_from_its_source() -> None:
    """Transcribed, not imported — so the transcription is tested.

    This guard parses its own policy with the standard library alone and can
    take no dependency on another repository's package, which is why the
    marker sets live in config. The cost of that is drift: a vocabulary that
    lags its source classifies criteria the authoring repo no longer would, in
    BOTH directions. So the pin is checked against the live file when a clone
    is present and skipped, with the reason stated, when one is not.
    """
    pinned = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))["proof_class_source"]
    classifier = pinned["criterion_classifier"]
    clone = _sibling_clone(classifier["repo"].split("/")[-1])
    if clone is None:
        pytest.skip(
            f"no clone of {classifier['repo']} is present; this repo's CI "
            "runners do not clone it, so the pin is checked where one exists"
        )
    source_path = clone / classifier["path"]
    if not source_path.is_file():
        pytest.skip(f"{source_path} is absent from the clone")
    source = source_path.read_text(encoding="utf-8")
    policy_raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    for symbol, key in (
        ("_STATE_MARKER_RE", "state_criterion_markers"),
        ("_BEHAVIOUR_MARKER_RE", "behaviour_criterion_markers"),
    ):
        assert _verbose_alternatives(source, symbol) == policy_raw[key], (
            f"{key} has drifted from {classifier['repo']} {symbol}. Bump the "
            "commit in proof_class_source and the markers in ONE change."
        )


def test_the_runner_allowlist_has_not_drifted_from_its_source() -> None:
    """The same pin, for the tight positive runner allowlist rule 7 conjoins on."""
    pinned = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))["proof_class_source"]
    allowlist = pinned["runner_allowlist"]
    clone = _sibling_clone(allowlist["repo"].split("/")[-1])
    if clone is None:
        pytest.skip(
            f"no clone of {allowlist['repo']} is present; this repo's CI "
            "runners do not clone it"
        )
    source_path = clone / allowlist["path"]
    if not source_path.is_file():
        pytest.skip(f"{source_path} is absent from the clone")
    source = source_path.read_text(encoding="utf-8")
    block = source[source.index("_BEHAVIOR_WORDS") :]
    block = block[block.index("{") : block.index("}")]
    words = sorted(re.findall(r'"([^"]+)"', block))
    assert words == sorted(POLICY.behaviour_runner_words), (
        "behaviour_runner_words has drifted from the proof-class module's "
        "_BEHAVIOR_WORDS. Bump the commit in proof_class_source and the words "
        "in ONE change."
    )


# ---------------------------------------------------------------------------
# AC6 — each criterion is one independently hashable unit (OMN-18331)
# ---------------------------------------------------------------------------
#
# The plan's next step transcribes each criterion's declared falsifier into a
# companion contract as an ACCEPTED binding, pinning `criterion_hash` to the
# criterion text as it read when the binding was accepted. That only works if
# editing one criterion cannot disturb another's hash, so independence is a
# pinned property here rather than an incidental one downstream.


def test_each_criterion_round_trips_to_a_label_a_falsifier_and_a_hash() -> None:
    units = _GUARD.criterion_units(_FALSIFIED_BODY, POLICY)
    assert [unit.label for unit in units] == ["AC1", "AC2"]
    assert all(unit.falsifier for unit in units)
    assert all(len(unit.criterion_hash) == 64 for unit in units)
    assert len({unit.criterion_hash for unit in units}) == 2


def test_the_hash_is_the_sha256_of_the_canonical_text() -> None:
    """Stated as an equation, not as "some hash", so a consumer in another
    repository can compute it without importing this module."""
    import hashlib

    unit = _GUARD.criterion_units(_FALSIFIED_BODY, POLICY)[0]
    assert unit.criterion_hash == hashlib.sha256(unit.text.encode("utf-8")).hexdigest()


def test_editing_one_criterion_leaves_every_other_hash_byte_identical() -> None:
    """The independence property the whole unit exists for.

    A shared hash over the section would invalidate every accepted binding on
    a ticket whenever any one criterion was reworded, which would make the
    acceptance worthless the first time an author fixed a typo.
    """
    before = _GUARD.criterion_units(
        _with_criteria(
            "AC1 — first. — falsifier: uv run pytest tests/a.py -q",
            "AC2 — second. — falsifier: uv run pytest tests/b.py -q",
            "AC3 — third. — falsifier: uv run pytest tests/c.py -q",
        ),
        POLICY,
    )
    after = _GUARD.criterion_units(
        _with_criteria(
            "AC1 — first. — falsifier: uv run pytest tests/a.py -q",
            "AC2 — second, reworded entirely. — falsifier: uv run pytest tests/z.py -q",
            "AC3 — third. — falsifier: uv run pytest tests/c.py -q",
        ),
        POLICY,
    )
    assert before[0].criterion_hash == after[0].criterion_hash
    assert before[2].criterion_hash == after[2].criterion_hash
    assert before[1].criterion_hash != after[1].criterion_hash


def test_rewrapping_a_criterion_does_not_change_its_hash() -> None:
    """The one edit that changes the bytes without changing what the criterion
    says. Markdown re-wraps; a hash that moved on a re-wrap would report a
    rewrite that never happened."""
    one_line = _with_criteria(
        "AC1 — the guard reads a wrapped criterion. "
        "— falsifier: uv run pytest tests/hooks/test_x.py -q"
    )
    wrapped = (
        "Gate: OMN-16729 AC-5\n\n## Acceptance criteria\n\n"
        "* AC1 — the guard reads a wrapped\n"
        "  criterion.\n"
        "  — falsifier: uv run pytest tests/hooks/test_x.py -q\n"
    )
    assert (
        _GUARD.criterion_units(one_line, POLICY)[0].criterion_hash
        == _GUARD.criterion_units(wrapped, POLICY)[0].criterion_hash
    )


def test_rewording_a_criterion_does_change_its_hash() -> None:
    """The control for the case above. A normalisation broad enough to absorb a
    rewrite would make the pin unable to detect the thing it exists for."""
    first = _GUARD.criterion_units(
        _with_criteria("AC1 — the guard refuses. — falsifier: uv run pytest a.py"),
        POLICY,
    )[0]
    second = _GUARD.criterion_units(
        _with_criteria("AC1 — the guard admits. — falsifier: uv run pytest a.py"),
        POLICY,
    )[0]
    assert first.criterion_hash != second.criterion_hash


def test_swapping_the_falsifier_changes_the_hash() -> None:
    """The falsifier is inside the hash on purpose.

    What an author accepts is the PAIR — this criterion, settled by this check.
    A hash covering only the criterion half would let the check change silently
    under a binding already accepted.
    """
    first = _GUARD.criterion_units(
        _with_criteria("AC1 — the guard refuses. — falsifier: uv run pytest a.py"),
        POLICY,
    )[0]
    second = _GUARD.criterion_units(
        _with_criteria("AC1 — the guard refuses. — falsifier: uv run pytest b.py"),
        POLICY,
    )[0]
    assert first.criterion_hash != second.criterion_hash


def test_a_malformed_criterion_is_reported_not_silently_hashed() -> None:
    """A unit with no falsifier is surfaced as such.

    Handing a consumer a hash with no falsifier and no signal would let the
    transcriber mint a binding to a criterion that named no check — the exact
    thing rule 6 refuses, laundered one repository over.
    """
    units = _GUARD.criterion_units(
        _with_criteria(
            "AC1 — falsified. — falsifier: uv run pytest a.py",
            "AC2 — this one names no check at all.",
        ),
        POLICY,
    )
    assert units[0].falsifier is not None
    assert units[1].falsifier is None
    assert units[1].criterion_hash  # still hashable; it is the falsifier that is absent


def test_an_unlabelled_criterion_yields_no_label_rather_than_a_positional_one() -> None:
    """An ordinal derived from parse position renumbers every binding below it
    the moment a bullet is inserted, which is worse than having none."""
    units = _GUARD.criterion_units(
        _with_criteria("a criterion with no ordinal. — falsifier: uv run pytest a.py"),
        POLICY,
    )
    assert units[0].label is None


def test_the_gate_and_the_exported_unit_share_one_parse() -> None:
    """Two parsers would be two places to disagree about where one criterion
    ends, and a disagreement there binds a criterion to its neighbour's check."""
    body = _with_criteria(
        "AC1 — falsified. — falsifier: uv run pytest a.py",
        "AC2 — unfalsified.",
    )
    units = _GUARD.criterion_units(body, POLICY)
    reason = _reason(_create(description=body))
    assert f"1 of {len(units)} acceptance criteria" in reason


# ---------------------------------------------------------------------------
# A suffixed ordinal (AC2b, AC10a) binds as its own unit, not UNLABELLED
# ---------------------------------------------------------------------------
#
# OMN-18356. `_CRITERION_LABEL` required a word boundary directly after the
# ordinal digits. A suffix letter sits immediately after the digits with no
# boundary between them (both are word characters), so the whole match failed
# and the criterion came back with label=None -- the same shape as a criterion
# carrying no ordinal at all. Found live transcribing OMN-18332: 6 of its 12
# criteria (AC2b/c/d/e/f/g) parsed unlabelled and were silently skipped by the
# autobinder rather than bound.


def test_a_suffixed_ordinal_binds_as_its_own_labelled_unit() -> None:
    units = _GUARD.criterion_units(
        _with_criteria(
            "AC2 — the base criterion.  — falsifier: uv run pytest a.py",
            "AC2b — NEGATIVE CONTROL, must not close the ticket. "
            "— falsifier: uv run pytest b.py",
            "AC10a — a double-digit ordinal with a suffix. "
            "— falsifier: uv run pytest c.py",
        ),
        POLICY,
    )
    assert [unit.label for unit in units] == ["AC2", "AC2b", "AC10a"]
    # Never merged into the base ordinal's unit: three units, three hashes.
    assert len({unit.criterion_hash for unit in units}) == 3


def test_a_suffixed_label_is_not_merged_into_its_base_ordinal_neighbour() -> None:
    """The dangerous failure mode this fixes: a suffixed criterion silently
    absorbed into (or dropped alongside) its numeric neighbour rather than
    surfacing as its own bindable unit."""
    units = _GUARD.criterion_units(
        _with_criteria(
            "AC2 — the base criterion. — falsifier: uv run pytest a.py",
            "AC2b — a distinct sibling criterion. — falsifier: uv run pytest b.py",
        ),
        POLICY,
    )
    assert len(units) == 2
    assert units[0].label == "AC2"
    assert units[1].label == "AC2b"
    assert units[0].text != units[1].text
    assert units[0].criterion_hash != units[1].criterion_hash


def test_an_uppercase_suffix_is_preserved_as_written() -> None:
    """The suffix is part of the stable label an external binding points at,
    so it is read verbatim rather than case-normalised away."""
    units = _GUARD.criterion_units(
        _with_criteria("AC2B — an uppercase suffix. — falsifier: uv run pytest a.py"),
        POLICY,
    )
    assert units[0].label == "AC2B"


def test_a_criterion_with_no_parseable_ordinal_is_reported_unlabelled_not_dropped() -> (
    None
):
    """The population this defect could have hidden a second way: an
    unparsable label must still surface as an explicit unlabelled unit in the
    returned list, never silently absent from it."""
    body = _with_criteria(
        "AC1 — falsified. — falsifier: uv run pytest a.py",
        "this criterion names no ordinal at all. — falsifier: uv run pytest b.py",
    )
    units = _GUARD.criterion_units(body, POLICY)
    assert len(units) == 2
    assert units[0].label == "AC1"
    assert units[1].label is None
    assert units[1].criterion_hash


# ---------------------------------------------------------------------------
# Rule 8 — a parent may not carry more than N children nobody has started
# ---------------------------------------------------------------------------
#
# Why: rules 1-7 bound the SHAPE of a ticket and say nothing about VOLUME. A
# parent can accumulate an unbounded queue of correctly-bound tickets nobody
# will ever start, and every one of them passes. The friction trend report
# (knowledge-base-internal, 2026-09-13, sections 4 and 7) measured created
# against Done at 3.1 : 1 over fifteen days -- a net +815 -- with 31 of 58 new
# friction tickets never started, across a window that lies ENTIRELY AFTER this
# guard shipped. The guard was green on every one of those creates.
#
# The cap is a single declared constant in the shipped policy, not a literal in
# the checker, so raising it is a config edit an operator can see in one place.

_UNSTARTED_NODE_STATE: Final[dict[str, str]] = {"name": "Backlog", "type": "backlog"}
_STARTED_NODE_STATE: Final[dict[str, str]] = {"name": "In Progress", "type": "started"}

_RULING_ROWS: Final[str] = "\n".join(
    [
        "2026-09-13T00:00:00Z | NOTE | lane=other | filler row",
        "2026-09-13T01:00:00Z | RULING | lane=orchestrator | OMN-16729 may carry a "
        "deliberate queue through the end of the sprint; the cap is waived for it "
        "and for nothing else.",
        "2026-09-13T02:00:00Z | CLAIM | lane=other | this row mentions a RULING for "
        "OMN-16729 in its free text and authorises nothing",
        "2026-09-13T03:00:00Z | RULING | lane=orchestrator | a ruling about some "
        "other subject entirely",
    ]
)

#: Line numbers inside :data:`_RULING_ROWS`, 1-based.
_RULING_LINE: Final[int] = 2
_CLAIM_LINE: Final[int] = 3
_RULING_OTHER_SUBJECT_LINE: Final[int] = 4

_LEDGER_REL: Final[str] = "docs/tracking/ROLLING_WORK_LEDGER.md"


def _cap() -> int:
    return POLICY.unstarted_children_cap


def _nodes(count: int, started: int = 0) -> list[dict[str, Any]]:
    """``count`` children, ``started`` of which are In Progress.

    ``createdAt`` increases with the index, so the child at index 0 is the
    oldest and the refusal's "oldest unstarted child" is deterministic.
    """
    out: list[dict[str, Any]] = []
    for index in range(count):
        state = _STARTED_NODE_STATE if index < started else _UNSTARTED_NODE_STATE
        out.append(
            {
                "identifier": f"OMN-9{index:03d}",
                "title": f"child number {index}",
                "createdAt": f"2026-08-{(index % 28) + 1:02d}T00:00:00.000Z",
                "state": dict(state),
            }
        )
    return out


def _census(count: int, started: int = 0, parent: str = "OMN-16729") -> Any:
    return _GUARD.build_census(parent, _nodes(count, started), POLICY)


def _lookup_for(census: Any) -> Any:
    def lookup(_parent_ref: str) -> Any:
        return census

    return lookup


def _check_capped(
    tool_input: dict[str, Any],
    lookup: Any,
    ledger_root: Path | None = None,
    policy: Any = None,
) -> list[Any]:
    return list(
        _GUARD.check_save_issue(
            tool_input,
            policy or POLICY,
            children_lookup=lookup,
            ledger_root=ledger_root,
        )
    )


def _cap_codes(tool_input: dict[str, Any], lookup: Any, **kwargs: Any) -> set[str]:
    return {finding.code for finding in _check_capped(tool_input, lookup, **kwargs)}


# --- the cap itself --------------------------------------------------------


def test_the_shipped_policy_declares_one_cap_constant() -> None:
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    assert isinstance(raw["unstarted_children_cap"], int)
    assert raw["unstarted_children_cap"] >= 1
    assert POLICY.unstarted_children_cap == raw["unstarted_children_cap"]
    rationale = "\n".join(raw["$comment"])
    assert "unstarted_children_cap" in rationale, (
        "the cap's rationale belongs beside it in the policy, not in a commit "
        "message nobody reads when they change the number"
    )


def test_the_shipped_policy_declares_the_unstarted_state_vocabulary() -> None:
    assert "backlog" in POLICY.unstarted_state_types
    assert "unstarted" in POLICY.unstarted_state_types
    assert "started" not in POLICY.unstarted_state_types
    assert "completed" not in POLICY.unstarted_state_types


def test_a_parent_exactly_at_the_cap_is_admitted() -> None:
    assert _check_capped(_create(), _lookup_for(_census(_cap()))) == []


def test_a_parent_one_over_the_cap_is_refused() -> None:
    codes = _cap_codes(_create(), _lookup_for(_census(_cap() + 1)))
    assert "unstarted_children_cap" in codes


def test_a_started_child_does_not_count_toward_the_cap() -> None:
    """N+1 children, one of them In Progress, is N unstarted and is admitted.

    This is the case that distinguishes a cap on *work nobody has started* from
    a cap on children, which would refuse a parent whose queue is being worked.
    """
    census = _census(_cap() + 1, started=1)
    assert len(census.unstarted) == _cap()
    assert _check_capped(_create(), _lookup_for(census)) == []


def test_the_cap_comes_from_config_and_not_from_a_literal(tmp_path: Path) -> None:
    """Lower the configured cap and the same census now refuses."""
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    raw["unstarted_children_cap"] = 2
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    tightened = _GUARD.load_policy(path)
    census = _GUARD.build_census("OMN-16729", _nodes(3), tightened)
    codes = {
        finding.code
        for finding in _GUARD.check_save_issue(
            _create(), tightened, children_lookup=_lookup_for(census)
        )
    }
    assert "unstarted_children_cap" in codes


@pytest.mark.parametrize(
    ("mutation", "why"),
    [
        ({"unstarted_children_cap": 0}, "a cap of zero refuses every create"),
        ({"unstarted_children_cap": -1}, "a negative cap is meaningless"),
        ({"unstarted_children_cap": "10"}, "a string is not a count"),
        ({"unstarted_children_cap": None}, "absent is not a default"),
    ],
)
def test_a_policy_with_an_unusable_cap_is_refused(
    tmp_path: Path, mutation: dict[str, Any], why: str
) -> None:
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    raw.update(mutation)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(_GUARD.PolicyError):
        _GUARD.load_policy(path)


# --- what the refusal has to say -------------------------------------------


def test_the_refusal_names_the_parent_the_count_and_the_oldest_child() -> None:
    findings = _check_capped(_create(), _lookup_for(_census(_cap() + 1)))
    rendered = _GUARD.render_block_reason(findings, POLICY)
    assert "OMN-16729" in rendered, "the refusal must name the parent"
    assert str(_cap() + 1) in rendered, "the refusal must name the count"
    assert str(_cap()) in rendered, "the refusal must name the cap it applied"
    assert "OMN-9000" in rendered, "the refusal must name the oldest unstarted child"
    assert "2026-08-01" in rendered, "and when that child was filed"


def test_the_refusal_states_every_route_that_unblocks_it() -> None:
    findings = _check_capped(_create(), _lookup_for(_census(_cap() + 1)))
    rendered = _GUARD.render_block_reason(findings, POLICY).lower()
    assert "start" in rendered
    assert "cancel" in rendered
    assert "ruling" in rendered
    assert _GUARD.OVERRIDE_CITATION_GRAMMAR.split(":")[0].lower() in rendered


def test_there_is_no_environment_variable_bypass() -> None:
    """The only environment this guard reads is where to find things, never whether to run.

    A gate with an env-var off switch is a gate every lane turns off. The
    documented disable is the mask bit, which is logged.
    """
    source = _GUARD_PY.read_text(encoding="utf-8")
    named = set(re.findall(r"environ(?:\.get)?[\[(]\s*\"([A-Z0-9_]+)\"", source))
    assert named <= {"LINEAR_API_KEY", "OMNI_HOME"}, (
        f"the guard reads {sorted(named)}; anything beyond locating the read "
        "credential and the ledger is a bypass surface"
    )
    assert "SKIP" not in source.upper().replace("SKIPPING", "")


# --- the override ----------------------------------------------------------


def _with_override(line: int, path: str = _LEDGER_REL) -> dict[str, Any]:
    return _create(
        description=f"{_GOOD_DESCRIPTION}\nAdmission-Override: {path}:{line}\n"
    )


def _ledger_at(tmp_path: Path) -> Path:
    ledger = tmp_path / _LEDGER_REL
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(_RULING_ROWS + "\n", encoding="utf-8")
    return tmp_path


def test_a_ruling_row_naming_the_parent_admits_an_over_cap_create(
    tmp_path: Path,
) -> None:
    home = _ledger_at(tmp_path)
    assert (
        _check_capped(
            _with_override(_RULING_LINE),
            _lookup_for(_census(_cap() + 1)),
            ledger_root=home,
        )
        == []
    )


def test_a_claim_row_is_not_a_ruling(tmp_path: Path) -> None:
    home = _ledger_at(tmp_path)
    codes = _cap_codes(
        _with_override(_CLAIM_LINE),
        _lookup_for(_census(_cap() + 1)),
        ledger_root=home,
    )
    assert "override_row_not_ruling" in codes


def test_a_ruling_about_another_subject_does_not_waive_this_parent(
    tmp_path: Path,
) -> None:
    home = _ledger_at(tmp_path)
    codes = _cap_codes(
        _with_override(_RULING_OTHER_SUBJECT_LINE),
        _lookup_for(_census(_cap() + 1)),
        ledger_root=home,
    )
    assert "override_row_does_not_name_parent" in codes


def test_a_citation_past_the_end_of_the_ledger_is_refused(tmp_path: Path) -> None:
    home = _ledger_at(tmp_path)
    codes = _cap_codes(
        _with_override(9999), _lookup_for(_census(_cap() + 1)), ledger_root=home
    )
    assert "override_line_absent" in codes


@pytest.mark.parametrize(
    "path",
    ["docs/notes/my-own-file.md", "/etc/passwd", "../elsewhere/ledger.md"],
)
def test_a_citation_to_a_file_the_lane_can_write_is_refused(
    tmp_path: Path, path: str
) -> None:
    home = _ledger_at(tmp_path)
    codes = _cap_codes(
        _with_override(_RULING_LINE, path=path),
        _lookup_for(_census(_cap() + 1)),
        ledger_root=home,
    )
    assert "override_path_not_canonical" in codes


def test_an_override_with_no_resolvable_ledger_root_is_refused() -> None:
    codes = _cap_codes(
        _with_override(_RULING_LINE), _lookup_for(_census(_cap() + 1)), ledger_root=None
    )
    assert "override_ledger_unreadable" in codes


def test_prose_mentioning_the_override_does_not_waive_the_cap(tmp_path: Path) -> None:
    """Rule 15, the direction that matters for an admission gate.

    A substring rule passes on prose that names the trigger while meaning the
    opposite -- "this create carries no Admission-Override: ... citation" would
    satisfy it by describing its own absence.
    """
    home = _ledger_at(tmp_path)
    payload = _create(
        description=(
            f"{_GOOD_DESCRIPTION}\n"
            f"This create carries no Admission-Override: {_LEDGER_REL}:"
            f"{_RULING_LINE} citation, deliberately.\n"
        )
    )
    codes = _cap_codes(payload, _lookup_for(_census(_cap() + 1)), ledger_root=home)
    assert "unstarted_children_cap" in codes


def test_a_bulleted_override_does_not_count(tmp_path: Path) -> None:
    home = _ledger_at(tmp_path)
    payload = _create(
        description=(
            f"{_GOOD_DESCRIPTION}\n- Admission-Override: {_LEDGER_REL}:{_RULING_LINE}\n"
        )
    )
    codes = _cap_codes(payload, _lookup_for(_census(_cap() + 1)), ledger_root=home)
    assert "unstarted_children_cap" in codes


def test_an_override_does_not_waive_the_other_rules(tmp_path: Path) -> None:
    """The override waives the CAP, never the binding."""
    home = _ledger_at(tmp_path)
    payload = _with_override(_RULING_LINE)
    payload["description"] = payload["description"].replace("Gate: OMN-16729 AC-5", "")
    codes = _cap_codes(payload, _lookup_for(_census(_cap() + 1)), ledger_root=home)
    assert "missing_gate_line" in codes


# --- the fail direction, stated and pinned ---------------------------------


def test_without_a_lookup_the_rule_is_not_evaluated() -> None:
    """The one bounded fail-open: a machine with no Linear read credential.

    Refusing every create there would make rules 1-5 -- which are payload-only
    and always enforceable -- collateral damage of a missing key, and the guard
    would be disabled wholesale rather than repaired.
    """
    assert _check_capped(_create(), None) == []


def test_a_lookup_that_cannot_resolve_the_parent_refuses() -> None:
    """A network or API failure refuses: the create could not have succeeded anyway."""
    codes = _cap_codes(_create(), _lookup_for(None))
    assert "unstarted_cap_unresolved" in codes


def test_a_truncated_census_below_the_cap_refuses() -> None:
    """A lower bound is not a count, and this guard does not guess."""
    census = _GUARD.ParentCensus(
        parent="OMN-16729",
        unstarted=_census(2).unstarted,
        complete=False,
    )
    codes = _cap_codes(_create(), _lookup_for(census))
    assert "unstarted_cap_unresolved" in codes


def test_a_truncated_census_over_the_cap_still_refuses_on_the_cap() -> None:
    census = _GUARD.ParentCensus(
        parent="OMN-16729",
        unstarted=_census(_cap() + 1).unstarted,
        complete=False,
    )
    codes = _cap_codes(_create(), _lookup_for(census))
    assert "unstarted_children_cap" in codes


def test_an_epic_create_with_no_parent_is_not_capped() -> None:
    """Rule 6 counts a parent's queue. A create declaring itself an epic has none."""

    def explode(_parent_ref: str) -> Any:  # pragma: no cover - must not be called
        raise AssertionError("rule 6 looked up a parent that was never named")

    payload = _create(
        parentId=None, description=f"issue_class: epic\n{_GOOD_DESCRIPTION}"
    )
    assert _check_capped(payload, explode) == []


def test_an_update_is_not_capped() -> None:
    def explode(_parent_ref: str) -> Any:  # pragma: no cover - must not be called
        raise AssertionError("rule 6 ran on an update")

    assert _check_capped(_create(id="OMN-1234"), explode) == []


def test_the_census_classifies_by_state_type_not_by_state_name() -> None:
    """A team that renames Backlog keeps the same Linear state TYPE."""
    nodes = _nodes(2)
    nodes[0]["state"] = {"name": "Icebox", "type": "backlog"}
    nodes[1]["state"] = {"name": "Backlog", "type": "completed"}
    census = _GUARD.build_census("OMN-16729", nodes, POLICY)
    assert [child.identifier for child in census.unstarted] == ["OMN-9000"]


def test_the_census_names_the_parent_linear_resolved_not_the_payload_spelling() -> None:
    """A payload may carry a uuid; the refusal has to name something a human can open."""
    census = _GUARD.build_census("OMN-16729", _nodes(1), POLICY)
    assert census.parent == "OMN-16729"


# --- end to end through the registered hook --------------------------------


def test_registered_hook_allows_a_create_when_no_read_credential_is_present(
    tmp_path: Path,
) -> None:
    """The absent-credential fail-open, proven through the command the harness runs.

    Also proves the hook does not hang waiting on a network call it cannot make.
    """
    payload = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": _create(),
    }
    env = dict(os.environ)
    env.pop("LINEAR_API_KEY", None)
    env["ONEX_HOOK_LOG"] = str(tmp_path / "hooks.log")
    env["HOME"] = str(tmp_path)
    result = subprocess.run(
        ["bash", str(_HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_main_wires_the_real_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default lookup is not optional in production -- main() supplies it."""
    monkeypatch.setenv("LINEAR_API_KEY", "lin_api_test")
    monkeypatch.setattr(
        _GUARD,
        "_fetch_children_nodes",
        lambda parent_ref, api_key: ("OMN-16729", _nodes(_cap() + 1), True),
    )
    payload = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": _create(),
    }
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(payload)))
    assert _GUARD.main([]) == 3
