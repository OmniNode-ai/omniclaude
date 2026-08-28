#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Required-Check Skip-Vector Guard (OMN-14854) — shared workflow-parsing model.
#
# Implements the context->job resolution algorithm from the design spec §1:
# every live `required_status_checks` context string is mapped back to the
# GitHub Actions job that produces it, walking through at most one level of
# `uses:` reusable-workflow nesting (Shape A/B/C). This module is imported by
# both the PR-time validator (validate_no_required_check_skip_vectors.py) and
# the privileged reconcile job (reconcile_manifest_vs_live.py) so the
# resolution logic is defined exactly once (DRY).
#
# Deliberately dependency-light: PyYAML only (already an omniclaude runtime
# dependency, see pyproject.toml). No network I/O in this module.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# GitHub Actions events this guard treats as "PR-reachable" — the only events
# `required_status_checks` can ever gate (branch protection cannot see push,
# schedule, or workflow_dispatch runs).
PR_REACHABLE_EVENTS = ("pull_request", "pull_request_target", "merge_group")

# Local-repo `uses:` cross-references to this same org/repo (self-referential
# `OmniNode-ai/omniclaude/.github/workflows/x.yml@ref` form some callers use
# instead of the `./` relative form). Resolved locally exactly like `./`.
_SELF_REPO_USES_RE = re.compile(
    r"^OmniNode-ai/omniclaude/\.github/workflows/(?P<path>[^@]+)@[^/]+$"
)
_LOCAL_USES_RE = re.compile(r"^\./\.github/workflows/(?P<path>[^@]+)$")


class UnresolvedContext(Exception):
    """Raised when a required context cannot be mapped to any local job."""


class UnclassifiableCondition(Exception):
    """Raised internally when `classify()` cannot symbolically evaluate an if:."""


@dataclass
class ParsedJob:
    job_id: str
    raw: dict[str, Any]

    @property
    def name(self) -> str:
        return str(self.raw.get("name") or self.job_id)

    @property
    def if_expr(self) -> str | None:
        expr = self.raw.get("if")
        return str(expr) if expr is not None else None

    @property
    def uses(self) -> str | None:
        uses = self.raw.get("uses")
        return str(uses) if uses is not None else None

    @property
    def needs(self) -> tuple[str, ...]:
        """The job's `needs:` list, normalized to a tuple regardless of the
        YAML source shape (`needs: foo`, `needs: [foo, bar]`). Empty tuple
        when the job declares no `needs:` at all.

        This exists for vector-5 (OMN-15057): GitHub's *implicit* job-level
        `if:` is `success()` evaluated over the job's `needs:` list, not an
        unconditional true. A job with `needs:` and no explicit `if:` is
        NOT provably safe the way a needs-less job is.
        """
        raw_needs = self.raw.get("needs")
        if raw_needs is None:
            return ()
        if isinstance(raw_needs, str):
            return (raw_needs,)
        if isinstance(raw_needs, list):
            return tuple(str(n) for n in raw_needs)
        return ()


@dataclass
class ParsedWorkflow:
    path: Path
    raw: dict[str, Any]
    jobs: dict[str, ParsedJob] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for job_id, job_raw in (self.raw.get("jobs") or {}).items():
            self.jobs[job_id] = ParsedJob(job_id=job_id, raw=job_raw or {})

    @property
    def on_block(self) -> dict[str, Any]:
        """Normalize the `on:` block to a dict, regardless of source shape.

        YAML `on:` may be a bare string (`on: push`), a list
        (`on: [push, pull_request]`), or a mapping (`on: {pull_request: {...}}`).
        PyYAML also parses the bare word `on` as the boolean `True` under
        YAML 1.1 core schema rules in some edge cases — guarded for below.
        """
        # PyYAML's default (non-safe-adjacent) resolver can turn the literal
        # scalar key `on` into the boolean True. safe_load with the standard
        # SafeLoader does this for the *key* `on` under YAML 1.1 bool
        # resolution history; guard both spellings defensively.
        raw_any: dict[Any, Any] = self.raw
        on_val = raw_any.get("on", raw_any.get(True))
        if on_val is None:
            return {}
        if isinstance(on_val, str):
            return {on_val: {}}
        if isinstance(on_val, list):
            return {str(k): {} for k in on_val}
        if isinstance(on_val, dict):
            return {str(k): (v or {}) for k, v in on_val.items()}
        return {}

    def triggers_on_pr_or_merge_group(self) -> bool:
        return any(evt in self.on_block for evt in PR_REACHABLE_EVENTS)

    def path_filtered_pr_events(self) -> list[str]:
        """Return PR-reachable event names whose trigger carries a paths filter."""
        hits: list[str] = []
        for evt in PR_REACHABLE_EVENTS:
            cfg = self.on_block.get(evt)
            if isinstance(cfg, dict) and ("paths" in cfg or "paths-ignore" in cfg):
                hits.append(evt)
        return hits


@dataclass
class ResolvedJob:
    workflow: ParsedWorkflow
    job_id: str
    # None for Shape A (direct job); set for Shape B/C (caller job that
    # invokes the reusable workflow producing the composed context).
    caller_job_id: str | None = None
    nested_workflow: ParsedWorkflow | None = None
    nested_job_id: str | None = None
    # True when the composed context's second half resolves into a reusable
    # workflow this repo cannot read (cross-org `uses:` ref).
    cross_repo_ref: str | None = None

    @property
    def is_nested(self) -> bool:
        return self.caller_job_id is not None


def load_workflows(workflows_dir: Path) -> dict[str, ParsedWorkflow]:
    """Parse every *.yml/*.yaml file directly under workflows_dir (no recursion:
    GitHub Actions does not read workflows from subdirectories)."""
    workflows: dict[str, ParsedWorkflow] = {}
    for pattern in ("*.yml", "*.yaml"):
        for path in sorted(workflows_dir.glob(pattern)):
            with path.open(encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            if not isinstance(raw, dict):
                continue
            key = path.name
            workflows[key] = ParsedWorkflow(path=path, raw=raw)
    return workflows


def resolve_uses_ref(
    uses_ref: str, workflows: dict[str, ParsedWorkflow]
) -> ParsedWorkflow | None:
    """Resolve a job's `uses:` reference to a locally-parseable ParsedWorkflow,
    or None if the reference points outside this repo (cross-repo reusable —
    e.g. omnibase_core's occ-preflight.yml, onex_change_control's
    pr-title-check-reusable.yml)."""
    local_match = _LOCAL_USES_RE.match(uses_ref)
    if local_match:
        return workflows.get(Path(local_match.group("path")).name)
    self_repo_match = _SELF_REPO_USES_RE.match(uses_ref)
    if self_repo_match:
        return workflows.get(Path(self_repo_match.group("path")).name)
    return None


def resolve_context_to_job(
    context: str,
    workflows: dict[str, ParsedWorkflow],
    preferred_workflow: str | None = None,
) -> ResolvedJob:
    """Implements the design spec §1 mapping algorithm.

    Tries Shape A (plain job name/id match) first, then Shape B/C
    (`<caller_job_id> / <rest>` composed contexts, where `<rest>` is matched
    verbatim against the reusable job's own display name — this handles the
    real "call-reject-skip-token / scan / reject-skip-gate-token" case where
    the reusable job's own `name:` field itself contains a `/`).

    ``preferred_workflow`` (OMN-16878) is the manifest row's own ``workflow:``
    field, and it is consulted FIRST when supplied. Shape-A matching is
    otherwise first-match-wins over a filename-sorted dict, which silently
    mis-resolves whenever two jobs in the repo render the same context name.
    omniclaude has exactly that collision: ``deploy-gate.yml`` carries the
    local ``deploy-gate`` job that produces this repo's required context, and
    ``deploy-gate-reusable.yml`` carries a job *also* named ``deploy-gate``
    (it is the canonical cross-repo reusable that omnibase_core /
    omnibase_infra / omnimarket call by ``uses:``, producing THEIR
    ``deploy-gate / deploy-gate`` context — its job name is load-bearing
    downstream and must not be renamed to break the tie).

    ``"deploy-gate-reusable.yml" < "deploy-gate.yml"`` bytewise, so the
    reusable won the race and the guard reported vector-4-no-pr-trigger
    against a `workflow_call`-only workflow — a false finding about the wrong
    file. The manifest already declares which workflow owns the context; this
    parameter simply stops the resolver from throwing that away. It narrows
    WHICH job a context resolves to; it never suppresses a finding, because
    every vector check still runs against whatever job comes back.

    Deliberately does NOT filter candidate workflows by
    `triggers_on_pr_or_merge_group()` before matching: doing so would make
    vector 4 (missing pull_request/merge_group trigger entirely) unreachable,
    since a workflow lacking that trigger would be skipped during resolution
    and the context would surface as `UnresolvedContext` instead of the more
    specific, more actionable "no PR trigger" finding. The trigger check is
    still applied — just downstream, against the resolved job's own workflow
    — by the caller (see validate_no_required_check_skip_vectors.py).
    """
    if preferred_workflow is not None:
        preferred = workflows.get(preferred_workflow)
        if preferred is not None:
            for job_id, job in preferred.jobs.items():
                if job.name == context:
                    return ResolvedJob(workflow=preferred, job_id=job_id)

    for wf in workflows.values():
        for job_id, job in wf.jobs.items():
            if job.name == context:
                return ResolvedJob(workflow=wf, job_id=job_id)

    for wf in workflows.values():
        for job_id, job in wf.jobs.items():
            if job.uses is None:
                continue
            prefix = f"{job_id} / "
            if not context.startswith(prefix):
                continue
            remainder = context[len(prefix) :]
            reusable_wf = resolve_uses_ref(job.uses, workflows)
            if reusable_wf is None:
                # Cross-repo reusable: caller side resolves, far side does not.
                return ResolvedJob(
                    workflow=wf,
                    job_id=job_id,
                    caller_job_id=job_id,
                    cross_repo_ref=job.uses,
                )
            for r_job_id, r_job in reusable_wf.jobs.items():
                if r_job.name == remainder:
                    return ResolvedJob(
                        workflow=wf,
                        job_id=job_id,
                        caller_job_id=job_id,
                        nested_workflow=reusable_wf,
                        nested_job_id=r_job_id,
                    )

    raise UnresolvedContext(context)


# ---------------------------------------------------------------------------
# Conditional classifier (design spec §2 `classify(if_expr)`)
# ---------------------------------------------------------------------------

ALWAYS_TRUE_FOR_PR = "ALWAYS_TRUE_FOR_PR"
UNGUARDED_CONDITIONAL = "UNGUARDED_CONDITIONAL"

# Anything referencing these is never in the provably-safe set (spec §2), full
# stop — no partial credit, even if combined with a safe event-name check.
_UNSAFE_REFERENCE_RE = re.compile(
    r"github\.actor"
    r"|github\.event\.(?!repository\b|action\b)"  # allow harmless event.* only defensively; still excluded below
    r"|needs\."
    r"|steps\."
    r"|vars\."
    r"|secrets\."
)

_EVENT_NAME_TOKEN_RE = re.compile(r"github\.event_name")


def classify(if_expr: str | None, declared_events: tuple[str, ...]) -> str:
    """Classify a job-level `if:` expression per spec §2.

    - Absent `if:` -> ALWAYS_TRUE_FOR_PR.
    - `always()` -> ALWAYS_TRUE_FOR_PR.
    - An expression referencing ONLY `github.event_name` (via ==, !=, &&, ||,
      parens) is evaluated symbolically for each PR-reachable event declared
      on the workflow's own `on:` block; ALWAYS_TRUE_FOR_PR only if it is true
      for every one of them.
    - Anything referencing github.actor / github.event.* / needs.* / steps.* /
      vars.* / secrets.* (or any other non-event-name predicate) is
      UNGUARDED_CONDITIONAL, unconditionally — this is intentionally stricter
      than "provably safe", per spec §2's explicit no-partial-credit rule.
    """
    if if_expr is None:
        return ALWAYS_TRUE_FOR_PR

    expr = if_expr.strip()
    if expr in ("always()", "${{ always() }}"):
        return ALWAYS_TRUE_FOR_PR

    # Strip the ${{ }} wrapper if present (GHA allows bare or wrapped forms).
    inner = expr
    if inner.startswith("${{") and inner.endswith("}}"):
        inner = inner[3:-2].strip()

    if _UNSAFE_REFERENCE_RE.search(inner):
        return UNGUARDED_CONDITIONAL

    if not _EVENT_NAME_TOKEN_RE.search(inner):
        # References neither event_name nor any known-unsafe token but is not
        # `always()`/absent either (e.g. a bare boolean literal, or something
        # this classifier doesn't recognize) — fail closed, no partial credit.
        return UNGUARDED_CONDITIONAL

    events_to_check = [e for e in declared_events if e in PR_REACHABLE_EVENTS] or list(
        PR_REACHABLE_EVENTS
    )

    py_expr = (
        inner.replace("&&", " and ")
        .replace("||", " or ")
        .replace("github.event_name", "__EVENT_NAME__")
    )
    py_expr = re.sub(r"(?<![=!<>])==(?!=)", "==", py_expr)

    for event in events_to_check:
        candidate = py_expr.replace("__EVENT_NAME__", repr(event))
        try:
            result = eval(candidate, {"__builtins__": {}}, {})  # noqa: S307
        except Exception:
            return UNGUARDED_CONDITIONAL
        if not result:
            return UNGUARDED_CONDITIONAL

    return ALWAYS_TRUE_FOR_PR


# ---------------------------------------------------------------------------
# Result-triage analyzer (vector 6, OMN-15304)
# ---------------------------------------------------------------------------
#
# Vector 5 asks "can this job be SKIPPED?". Vector 6 asks the layer-down
# question vector 5 cannot see: "when this job DOES run, does it fail closed on
# every non-`success` upstream result?".
#
# `needs.<job>.result` has exactly four values — success / failure / cancelled /
# skipped. A gate job that blocks on only some of them renders its required
# context GREEN for the rest. `if: always()` — the very construct that satisfies
# vector 5 — is what guarantees that fail-open path is reached. Live instance:
# omnimarket#1920, run 30298837182 — the `hostile-review` job was CANCELLED at
# 04:13:14Z and `Hostile Review Gate` reported SUCCESS at 04:13:21Z, seven
# seconds later, with no adversarial verdict in existence (OMN-15296, fixed in
# omnimarket#1926; this analyzer hoists that single-workflow test into a
# fleet-wide rule).
#
# The analyzer is deliberately STATIC and FAIL-CLOSED: it recognises a small set
# of provably-hardened shapes and reports everything else. It never executes
# workflow shell — a validator that runs under pre-commit must not run arbitrary
# `run:` blocks.

RESULT_VALUES = ("success", "failure", "cancelled", "skipped")

TRIAGE_ABSENT = "TRIAGE_ABSENT"  # job never consumes a result token
TRIAGE_HARDENED = "TRIAGE_HARDENED"  # provably fails closed on every non-success
TRIAGE_FAIL_OPEN = "TRIAGE_FAIL_OPEN"  # positively recognised partial triage
TRIAGE_UNVERIFIABLE = "TRIAGE_UNVERIFIABLE"  # consumes a result, shape unparseable

# The GHA expression tokens whose value space is the four result values.
_NEEDS_RESULT_RE = re.compile(r"needs\.(?P<job>[A-Za-z0-9_\-]+)\.(?:result|outcome)")
_STEPS_OUTCOME_RE = re.compile(
    r"steps\.(?P<step>[A-Za-z0-9_\-]+)\.(?:outcome|conclusion)"
)
_JOB_STATUS_RE = re.compile(r"job\.status")

# Sentinel a result-bearing expression / shell variable is normalized to before
# structural matching, so `${{ needs.x.result }}`, `$RESULT`, `"${RESULT}"` and
# `${{ steps.y.outcome }}` all reduce to one token.
#
# The analysis is per-UPSTREAM (OMN-15304 remediation round 1): exactly one
# upstream's token is normalized to `_RESULT_SENTINEL` per pass, and every
# OTHER result-bearing token is normalized to `_OTHER_SENTINEL` so it can
# neither harden nor weaken the verdict for the upstream under analysis. A
# single shared sentinel made the analysis per-JOB, and because the shape scan
# returns on the FIRST hardened shape it finds, a hardened check on upstream A
# certified the whole job while upstream B's triage was fail-open. That masked
# omniclaude's own `Hostile Review Gate` — a live REQUIRED context whose
# `occ-preflight` guard hardened while `hostile-review` blocked only on
# `failure` (the pre-#1926 omnimarket shape verbatim, and the very incident
# this vector exists to catch).
_RESULT_SENTINEL = "\x00RESULT\x00"
_OTHER_SENTINEL = "\x00OTHERRESULT\x00"

# One result-bearing upstream, identified by kind + name:
# ("needs", <job_id>) | ("steps", <step_id>) | ("job", "status").
ResultSource = tuple[str, str]

_GHA_EXPR_RE = re.compile(r"\$\{\{(?P<inner>[^}]*)\}\}")
_ASSIGN_RE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?(?P<var>[A-Za-z_][A-Za-z0-9_]*)="
    r"[\"']?" + re.escape(_RESULT_SENTINEL) + r"[\"']?[ \t]*$"
)
_ASSIGN_OTHER_RE = re.compile(
    r"(?m)^[ \t]*(?:export[ \t]+)?(?P<var>[A-Za-z_][A-Za-z0-9_]*)="
    r"[\"']?" + re.escape(_OTHER_SENTINEL) + r"[\"']?[ \t]*$"
)
_EXIT_NONZERO_RE = re.compile(r"\bexit[ \t]+([1-9][0-9]*)\b")
_NOT_SUCCESS_RE = re.compile(
    re.escape(_RESULT_SENTINEL) + r"[ \t]*!=[ \t]*[\"']?success[\"']?"
)
_NOT_EQ_VALUE_RE = re.compile(
    re.escape(_RESULT_SENTINEL) + r"[ \t]*!=[ \t]*[\"']?(?P<value>[a-z_]+)[\"']?"
)
_EQ_VALUE_RE = re.compile(
    re.escape(_RESULT_SENTINEL) + r"[ \t]*==?[ \t]*[\"']?(?P<value>[a-z_]+)[\"']?"
)
# `if <cond over the result>; then <pass> else <fail> fi` — the positive-test
# form. Hardened iff the condition admits ONLY `success`; a disjunction like
# `== success || == skipped` is the fail-open shape (a skipped upstream is the
# absence of a verdict exactly like a cancelled one).
_IF_THEN_ELSE_RE = re.compile(
    # The condition may span lines via backslash continuations — omnibase_core's
    # `quality-gate` conjoins ~40 `[[ "$x" == "success" ]] && \` clauses that
    # way, and a single-line cond pattern misread it as unhardened.
    r"\bif\b(?P<cond>(?:[^\n]|\\\n)*?)(?:;[ \t]*)?\n?[ \t]*then\b"
    r"(?P<body>.*?)\belse\b(?P<els>.*?)\bfi\b",
    re.DOTALL,
)
_CASE_RE = re.compile(
    r"\bcase[ \t]+[\"']?"
    + re.escape(_RESULT_SENTINEL)
    + r"[\"']?[ \t]+in\b(?P<body>.*?)\besac\b",
    re.DOTALL,
)


@dataclass
class ResultTriageVerdict:
    """Verdict of the vector-6 analysis for one job.

    `status` is one of the TRIAGE_* constants. `consumed_jobs` is every
    `needs.<job>` whose `.result`/`.outcome` the job reads — the raw material
    for the OMN-15304 §4 sibling-dependency observation. `uncovered_values` is
    populated only for TRIAGE_FAIL_OPEN and names the result values that reach
    the pass path.
    """

    status: str
    consumed_jobs: tuple[str, ...] = ()
    uncovered_values: tuple[str, ...] = ()
    detail: str = ""


def _is_result_expr(inner: str, soft_step_ids: frozenset[str] | None = None) -> bool:
    if _NEEDS_RESULT_RE.search(inner) or _JOB_STATUS_RE.search(inner):
        return True
    for m in _STEPS_OUTCOME_RE.finditer(inner):
        if soft_step_ids is None or m.group("step") in soft_step_ids:
            return True
    return False


def _strip_sentinel_quotes(text: str) -> str:
    for sentinel in (_RESULT_SENTINEL, _OTHER_SENTINEL):
        text = re.sub(r"[\"']" + re.escape(sentinel) + r"[\"']", sentinel, text)
    return text


def _normalize_result_tokens(text: str, focus: ResultSource | None = None) -> str:
    """Replace every result-bearing token — `needs.<job>.result`,
    `steps.<id>.outcome`, `job.status` — then every shell variable bound to one,
    then the quotes around them, with `_RESULT_SENTINEL`.

    Tokens are substituted GLOBALLY rather than only inside `${{ }}`: a step's
    `if:` is a bare GHA expression with no `${{ }}` wrapper
    (`if: needs.lint.result != 'success'`), and missing those was a live false
    positive on omnibase_spi `detect-changes` / omnibase_core `receipt-honesty`.
    Quote stripping matters for the same reason — `"${{ needs.test.result }}"`
    normalizes to `"<SENT>"`, and the comparison matchers anchor on the bare
    sentinel (live false positive on omnidash `ci-summary`).

    Variable binding is a bounded fixpoint over `VAR=<SENT>` assignments, which
    covers the `RESULT="${{ ... }}"` preamble every real gate script opens with.
    A variable later rebound to something else is NOT unbound — deliberate:
    over-normalizing can only make the analyzer see MORE result consumption,
    never less, and the fail-closed default covers the rest.

    When `focus` is given, ONLY that source becomes `_RESULT_SENTINEL`; every
    other result-bearing token becomes `_OTHER_SENTINEL`, which no shape
    matcher recognises. That is what makes the vector-6 verdict per-upstream
    instead of per-job. `focus=None` (all sources collapse to one sentinel) is
    retained for the source-enumeration pass only — never for a hardening
    decision.

    The two sentinels are unbound in OTHER-first order: if a shell variable is
    assigned from both a focused and an unfocused token, resolving it to
    `_OTHER_SENTINEL` costs at most a TRIAGE_UNVERIFIABLE finding, whereas
    resolving it to `_RESULT_SENTINEL` could manufacture a false HARDENED.
    Fail-closed on the ambiguity.
    """

    def _sub(sentinel_if_focused: str, source: ResultSource) -> str:
        if focus is None or focus == source:
            return sentinel_if_focused
        return _OTHER_SENTINEL

    normalized = _NEEDS_RESULT_RE.sub(
        lambda m: _sub(_RESULT_SENTINEL, ("needs", m.group("job"))), text
    )
    normalized = _STEPS_OUTCOME_RE.sub(
        lambda m: _sub(_RESULT_SENTINEL, ("steps", m.group("step"))), normalized
    )
    normalized = _JOB_STATUS_RE.sub(
        lambda m: _sub(_RESULT_SENTINEL, ("job", "status")), normalized
    )
    # Collapse a `${{ <SENT> }}` wrapper that now contains nothing else.
    for sentinel in (_RESULT_SENTINEL, _OTHER_SENTINEL):
        normalized = re.sub(
            r"\$\{\{[ \t]*" + re.escape(sentinel) + r"[ \t]*\}\}",
            sentinel,
            normalized,
        )
    normalized = _strip_sentinel_quotes(normalized)
    normalized = _rebind_aggregator_loop(normalized)
    for _ in range(4):  # bounded fixpoint: VAR2="$VAR1" chains
        before = normalized
        for assign_re, sentinel in (
            (_ASSIGN_OTHER_RE, _OTHER_SENTINEL),
            (_ASSIGN_RE, _RESULT_SENTINEL),
        ):
            for var in {m.group("var") for m in assign_re.finditer(normalized)}:
                normalized = re.sub(
                    r"\$\{" + re.escape(var) + r"(?::-[^}]*)?\}"
                    r"|\$" + re.escape(var) + r"\b",
                    sentinel,
                    normalized,
                )
        normalized = _strip_sentinel_quotes(normalized)
        if normalized == before:
            break
    return normalized


_FOR_LOOP_RE = re.compile(
    r"\bfor[ \t]+(?P<var>[A-Za-z_][A-Za-z0-9_]*)[ \t]+in\b(?P<list>(?:[^\n]|\\\n)*?)(?:;[ \t]*)?\n?[ \t]*do\b",
    re.DOTALL,
)


def _rebind_aggregator_loop(text: str) -> str:
    """Model the `for check in "<name>=<result>" ...; do ... "${check##*=}"` shape.

    This is the dominant real aggregator idiom in the fleet (omniclaude
    `quality-gate`/`tests-gate`/`omni-standards-gate`, omnimarket and omnidash
    `omni-standards-gate`). The result reaches the triage through a loop
    variable and a suffix expansion, so without this rebinding every one of
    those jobs lands in TRIAGE_UNVERIFIABLE — correct as a fail-closed default,
    but it cannot distinguish the ones that DO fail closed (omnidash) from the
    ones that let `skipped` through (omniclaude, omnimarket).

    Only `${var##*=}` / `${var#*=}` (value side) are rebound. `${var%%=*}` is
    the label side and is deliberately left alone.
    """
    for m in _FOR_LOOP_RE.finditer(text):
        if _RESULT_SENTINEL not in m.group("list"):
            continue
        var = m.group("var")
        text = re.sub(
            r"\$\{" + re.escape(var) + r"##?\*=\}",
            _RESULT_SENTINEL,
            text,
        )
    return text


def _case_is_hardened(body: str) -> bool:
    """True iff a `case` over the result sentinel fails closed on every
    non-`success` branch AND carries a `*` catch-all that also fails closed.

    Default-deny on the catch-all is required, not optional: GitHub may add a
    fifth result value, and an unrecognised value must never open the merge
    path (the OMN-15296 `*)` branch).
    """
    segments = body.split(";;")
    saw_catch_all = False
    for segment in segments:
        if ")" not in segment:
            continue
        label_part, _, action = segment.partition(")")
        labels = [
            lbl.strip().strip("\"'")
            for lbl in label_part.replace("(", "").split("|")
            if lbl.strip()
        ]
        if not labels:
            continue
        fails_closed = bool(_EXIT_NONZERO_RE.search(action))
        if "*" in labels:
            saw_catch_all = True
            if not fails_closed:
                return False
            continue
        if labels == ["success"]:
            continue
        # Any branch naming a non-success value (alone or mixed with success)
        # must fail closed.
        if not fails_closed:
            return False
    return saw_catch_all


def _triage_step_can_harden(step: dict[str, Any]) -> bool:
    """False when the step's own non-zero exit cannot fail the JOB.

    `continue-on-error: true` makes `exit 1` a no-op for the job conclusion, so
    such a step can never be the thing that proves fail-closed. The analyzer
    already modelled `continue-on-error` for the CONSUMED side
    (`soft_step_ids`); modelling only that side was asymmetric — a triage step
    running `exit 1` under `continue-on-error: true` certified TRIAGE_HARDENED
    while hardening nothing. An expression-valued `continue-on-error`
    (`${{ ... }}`) cannot be proven false statically, so it fails closed the
    same way.
    """
    soft_flag = step.get("continue-on-error")
    if soft_flag is True:
        return False
    return not isinstance(soft_flag, str)


def _result_sources(steps: list[Any], soft: frozenset[str]) -> list[ResultSource]:
    """Every distinct result-bearing upstream the job's steps read, in source
    order. This is the unit of vector-6 analysis: the job is hardened only if
    EVERY one of these is individually hardened.

    `steps.<id>.outcome` counts only when step `<id>` is soft
    (`continue-on-error: true`) — otherwise its failure already failed the job
    and reading `.outcome` is cosmetic.
    """
    sources: list[ResultSource] = []

    def _add(source: ResultSource) -> None:
        if source not in sources:
            sources.append(source)

    for step in steps:
        if not isinstance(step, dict):
            continue
        for key in ("run", "if"):
            blob = step.get(key)
            if not isinstance(blob, str):
                continue
            for m in _NEEDS_RESULT_RE.finditer(blob):
                _add(("needs", m.group("job")))
            for m in _STEPS_OUTCOME_RE.finditer(blob):
                if m.group("step") in soft:
                    _add(("steps", m.group("step")))
            if _JOB_STATUS_RE.search(blob):
                _add(("job", "status"))
    return sources


def _analyze_one_source(
    steps: list[Any], soft: frozenset[str], focus: ResultSource
) -> tuple[str, tuple[str, ...], str]:
    """Run the shape scan against ONE upstream.

    Returns `(status, uncovered_values, detail)`. Every other result-bearing
    token in the job is normalized to `_OTHER_SENTINEL`, so a guard on a
    DIFFERENT upstream can neither harden nor weaken this verdict — the fix for
    the per-job masking bug (a hardened `occ-preflight` check certifying a job
    whose `hostile-review` triage blocked only on `failure`).
    """
    # Shape 3 (pure-GHA): a step gated on `<result> != 'success'` whose body
    # fails the job. Checked first — it needs no shell parsing at all.
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_if = step.get("if")
        step_run = step.get("run")
        if not isinstance(step_if, str) or not isinstance(step_run, str):
            continue
        if not _triage_step_can_harden(step):
            continue
        if _NOT_SUCCESS_RE.search(_normalize_result_tokens(step_if, focus)) and (
            _EXIT_NONZERO_RE.search(step_run)
        ):
            return (
                TRIAGE_HARDENED,
                (),
                "step-level `if: <result> != success` guarding a non-zero exit",
            )

    covered_values: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if not isinstance(run, str) or not _is_result_expr(run, soft):
            continue
        norm = _normalize_result_tokens(run, focus)
        if _RESULT_SENTINEL not in norm:
            continue  # this step does not read the upstream under analysis
        can_harden = _triage_step_can_harden(step)

        # Shape 1: explicit `case` with default-deny catch-all.
        for case_match in _CASE_RE.finditer(norm):
            if _case_is_hardened(case_match.group("body")) and can_harden:
                return (
                    TRIAGE_HARDENED,
                    (),
                    "`case` over the result with default-deny `*` branch",
                )

        # Shape 2: `if [ <result> != success ]; then ... exit N`.
        #
        # Guarded against the conjunction weakening
        # `[ $R != "success" ] && [ $R != "skipped" ]` — that shape reads as
        # "!= success" locally while letting `skipped` through, so a single
        # `!= <non-success>` anywhere in the script disqualifies Shape 2 and
        # the job falls through to a finding. Fail-closed on ambiguity.
        weakened = any(
            m.group("value") != "success" for m in _NOT_EQ_VALUE_RE.finditer(norm)
        )
        if weakened and _NOT_SUCCESS_RE.search(norm):
            leaked = tuple(
                sorted(
                    {
                        m.group("value")
                        for m in _NOT_EQ_VALUE_RE.finditer(norm)
                        if m.group("value") != "success"
                    }
                )
            )
            return (
                TRIAGE_FAIL_OPEN,
                leaked,
                "`!= success` is conjoined with `!= "
                + ", != ".join(leaked)
                + "`, so "
                + ", ".join(leaked)
                + " reaches the pass path — the absence of a verdict, not a passing one",
            )
        for m in _NOT_SUCCESS_RE.finditer(norm) if not weakened else ():
            if _EXIT_NONZERO_RE.search(norm[m.end() : m.end() + 400]) and can_harden:
                return (
                    TRIAGE_HARDENED,
                    (),
                    "`<result> != success` guarding a non-zero exit",
                )

        # Shape 4: `if <cond>; then ...pass... else ...exit N... fi`.
        for m in _IF_THEN_ELSE_RE.finditer(norm):
            cond = m.group("cond")
            if _RESULT_SENTINEL not in cond:
                continue
            if not _EXIT_NONZERO_RE.search(m.group("els")):
                continue
            if _NOT_EQ_VALUE_RE.search(cond):
                continue  # negative form — Shape 2's territory, not this one
            cond_values = {mm.group("value") for mm in _EQ_VALUE_RE.finditer(cond)}
            if not cond_values:
                continue
            if cond_values == {"success"}:
                if not can_harden:
                    continue
                return (
                    TRIAGE_HARDENED,
                    (),
                    "`if <result> = success ... else <non-zero exit>` positive test",
                )
            leaked = tuple(sorted(cond_values - {"success"}))
            return (
                TRIAGE_FAIL_OPEN,
                leaked,
                "the pass condition admits "
                + ", ".join(sorted(cond_values))
                + " — "
                + ", ".join(leaked)
                + " is the ABSENCE of a verdict, not a passing one",
            )

        # Not hardened — record which specific values ARE blocked, so the
        # finding can name the ones that fall through to the pass path.
        for m in _EQ_VALUE_RE.finditer(norm):
            if _EXIT_NONZERO_RE.search(norm[m.end() : m.end() + 400]):
                covered_values.add(m.group("value"))

    blocked = covered_values & set(RESULT_VALUES)
    if blocked:
        uncovered = tuple(
            v for v in RESULT_VALUES if v != "success" and v not in blocked
        )
        return (
            TRIAGE_FAIL_OPEN,
            uncovered,
            "blocks only on "
            + ", ".join(sorted(blocked))
            + "; "
            + ", ".join(uncovered)
            + " (and any future result value) fall through to the pass path",
        )

    return (
        TRIAGE_UNVERIFIABLE,
        (),
        "reads a `needs.*.result` / `steps.*.outcome` / `job.status` token but "
        "no provably fail-closed triage shape was found",
    )


def _source_label(source: ResultSource) -> str:
    kind, name = source
    if kind == "needs":
        return f"needs.{name}.result"
    if kind == "steps":
        return f"steps.{name}.outcome"
    return "job.status"


def analyze_result_triage(job: ParsedJob) -> ResultTriageVerdict:
    """Vector-6 analysis of one job's `steps:` (OMN-15304).

    Returns TRIAGE_ABSENT when the job never reads a result token — vector 6
    simply does not apply. Otherwise EVERY result-bearing upstream the job
    reads must independently PROVE it fails closed; an inline `run:` this
    analyzer cannot interpret returns TRIAGE_UNVERIFIABLE, which the validator
    treats as a finding (ticket scope item 2: unparseable triage must not read
    as hardened).

    The analysis is per-UPSTREAM, not per-job. A job that hardens on upstream A
    and is fail-open on upstream B is FAIL_OPEN — the single-sentinel,
    first-hardened-shape-wins version of this function reported it HARDENED and
    masked a live fail-open on omniclaude's own `Hostile Review Gate`.
    """
    steps_raw = job.raw.get("steps")
    steps: list[Any] = steps_raw if isinstance(steps_raw, list) else []

    # A `steps.<id>.outcome` read is only a fail-open surface when step <id>
    # can fail WITHOUT failing the job — i.e. it carries
    # `continue-on-error: true`. Otherwise the step's own failure already
    # fails the job before the reader runs, and reading `.outcome` is
    # cosmetic (live false positive on omnibase_core `docs-validation`).
    soft = frozenset(
        str(st["id"])
        for st in steps
        if isinstance(st, dict) and st.get("id") and st.get("continue-on-error") is True
    )

    # The JOB-level `if:` is deliberately out of scope. A result read there
    # decides whether the job RUNS (vectors 2/3/5 own that: a skipped job
    # satisfies branch protection); vector 6 is only about how a job that DID
    # run triages the result. Including it double-reported every
    # `if: needs.x.result == 'success'` job under the wrong vector.
    sources = _result_sources(steps, soft)
    if not sources:
        return ResultTriageVerdict(status=TRIAGE_ABSENT)

    consumed_t = tuple(name for kind, name in sources if kind == "needs")

    fail_open: list[tuple[ResultSource, tuple[str, ...], str]] = []
    unverifiable: list[tuple[ResultSource, str]] = []
    for source in sources:
        status, uncovered, detail = _analyze_one_source(steps, soft, source)
        if status == TRIAGE_FAIL_OPEN:
            fail_open.append((source, uncovered, detail))
        elif status == TRIAGE_UNVERIFIABLE:
            unverifiable.append((source, detail))

    if fail_open:
        uncovered_union = tuple(
            v for v in RESULT_VALUES if any(v in unc for _, unc, _ in fail_open)
        )
        return ResultTriageVerdict(
            status=TRIAGE_FAIL_OPEN,
            consumed_jobs=consumed_t,
            uncovered_values=uncovered_union,
            detail="; ".join(
                f"for `{_source_label(src)}`, {detail}" for src, _, detail in fail_open
            ),
        )
    if unverifiable:
        return ResultTriageVerdict(
            status=TRIAGE_UNVERIFIABLE,
            consumed_jobs=consumed_t,
            detail="; ".join(
                f"for `{_source_label(src)}`, {detail}" for src, detail in unverifiable
            ),
        )
    return ResultTriageVerdict(
        status=TRIAGE_HARDENED,
        consumed_jobs=consumed_t,
        detail="every consumed upstream result is triaged fail-closed",
    )
