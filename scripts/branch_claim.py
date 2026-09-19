#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The branch-claim resolution, and the check that records it (OMN-18263).

ONE RESOLUTION, TWO CALLERS. The pull-request check here and the pre-push hook
of OMN-18262 ask the same question, so it is answered in exactly one function
and both callers pass through it. That is the acceptance criterion's own
wording -- "reusing the hook's resolution rather than reimplementing it" -- and
it is not stylistic: a second copy of the comparison is a second place for it to
drift, and drift between a local refusal and a remote check is invisible until
the two disagree about a real push.

THE RESOLUTION, stated once (design of record: the OMN-18259 lane-identity and
claim-index design, section 7):

    from the branch name, the ticket; from the pushed commits' trailers, the
    lane and the fence; from the claim index, the current holder and fence.
    Refuse when the holder is another live lane, or when the commit's fence is
    behind the holder's. Name the holder, the row by file and line, and the
    release path.

NOTHING HERE IMPLEMENTS THAT COMPARISON. The ticket comes from
`claim_index.ticket_from_branch`, the lane from `lane_identity.commit_identity`,
the verdict and its whole refusal text from `claim_index.refusal_for_push`. This
module is the wiring between them plus two modes.

WHY IT RECORDS RATHER THAN REFUSES. Operator ruling, 2026-09-13T09:11:33Z,
durable at `docs/tracking/ROLLING_WORK_LEDGER.md:7178`: the pull-request check
lands FIRST and only records; the hook that refuses lands only after the release
path is shown easy in practice, measured rather than asserted. The two modes are
one flag apart on purpose, so arming the refusal later is a change of caller and
not a change of logic.

WHY THE CLAIM INDEX IS LOADED FROM A PATH rather than imported. It lives beside
the ledger, in the private workspace repository; this repository is public and
may not name it (CLAUDE.md rule 23). The caller supplies the path -- the
workflow from an organization variable, the hook from the workspace root. A path
that does not resolve raises `ResolutionUnavailable` and the run FAILS: a gate
that cannot see its own state has not passed, it has not run.

THE HONEST GAP, named rather than papered over. OMN-18260's stamping hook writes
`Onex-Lane` and `Onex-Session` and NOT the fencing token the design's section 5
describes, because stamping a fence at commit time needs the claim index inside
the commit path. So the fence comparison is live only for commits that carry the
trailer, and an absent fence disables that half of the resolution rather than
defaulting to zero -- a default of zero would refuse every correctly-held push
the moment any ticket reached fence 1. Stamping the fence is follow-up work, and
until it exists this check catches the wrong-lane case and not the preempted-lane
case.

AND THE LIMIT THIS SHARES WITH EVERY GATE AROUND IT. A lane stamps its own
identity and writes its own claim row. This enforces attribution and blast
radius, not authority: no row proves which lane SHOULD hold a ticket. What it
removes is the silent case -- two lanes on one branch and neither knowing.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

# Imported as a package member when the test suite drives it, and as a sibling
# file when a git hook or a workflow step runs it directly -- a hook invokes this
# by absolute path, with no package root anywhere on sys.path.
try:  # pragma: no cover - exercised by whichever caller is running
    from scripts import lane_identity as li
except ImportError:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import lane_identity as li  # type: ignore[no-redef,import-not-found]

__all__ = [
    "FENCE_TRAILER",
    "ResolutionUnavailable",
    "Verdict",
    "load_claim_index",
    "resolve",
    "resolve_store",
    "resolve_with_index",
]

# The third trailer of the OMN-18259 design's section 5. Declared here, and read when
# present, so that the day OMN-18260's hook begins stamping it this resolution
# starts using it with no further change.
FENCE_TRAILER = "Onex-Fence"

# Most severe first. A push can be several things at once -- one commit from a
# foreign lane and another with no trailer at all -- and the label reports the
# worst of them while `findings` carries every one.
_SEVERITY = (
    "held-elsewhere",
    "fence-behind",
    "unidentified",
    "held-by-pusher",
    "unclaimed",
    "no-ticket",
)

# What `--mode refuse` actually refuses, and why it is NOT every finding.
#
# OMN-18262's criterion is the wrong-lane case: "a push to a claimed branch from
# a non-holding lane is refused". An `unidentified` push -- commits carrying no
# lane trailer -- is a DIFFERENT and far wider policy, because measured
# 2026-09-13 that is every commit in the fleet. Refusing it by default would turn
# a targeted refusal into a fleet-wide push freeze on the day the hook is
# installed, which is how a gate gets routed around rather than obeyed. It is
# still REPORTED in both modes, so the gap is visible rather than silent; making
# it refusable is `--refuse-outcomes`, and that belongs with the stamping
# rollout, not with this refusal.
_DEFAULT_REFUSE_ON = ("held-elsewhere", "fence-behind")

_REQUIRED_ENTRY_POINTS = (
    "ticket_from_branch",
    "build_index",
    "holder",
    "refusal_for_push",
    # OMN-18791. The claim store is the live ledger AND the rolls it has
    # spilled into; these two are how the resolution reaches the archives. They
    # are REQUIRED rather than probed-for, because a module without them
    # resolves against the live file alone -- and that answers "unclaimed" for
    # every rolled claim, which is indistinguishable from a passing check.
    "window_sources",
    "build_index_from_sources",
    "ClaimStoreIncomplete",
)


class ResolutionUnavailable(RuntimeError):
    """The claim index module could not be loaded.

    Raised rather than degraded. A resolution that fell back to "no holder" when
    it could not read the store would report every branch unclaimed, and an
    unclaimed branch is clean -- so the failure mode is a confident green over
    exactly the corpus the check exists to inspect (CLAUDE.md rule 16).
    """


@dataclass
class Verdict:
    outcome: str
    ticket: str | None
    lanes: list[str] = field(default_factory=list)
    holder: str | None = None
    findings: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings


def load_claim_index(path: Path) -> ModuleType:
    """Import the claim index module from `path`, fail-closed."""
    resolved = Path(path)
    if not resolved.is_file():
        raise ResolutionUnavailable(
            f"the claim index module is not at {resolved}. This check reads the claim "
            "store through that module and refuses to guess without it; point "
            "--claim-index-module (or ONEX_CLAIM_INDEX_MODULE) at it. THE CHECK DID NOT RUN."
        )
    spec = importlib.util.spec_from_file_location("onex_claim_index", resolved)
    if spec is None or spec.loader is None:
        raise ResolutionUnavailable(f"{resolved} is not importable as a Python module")
    module = importlib.util.module_from_spec(spec)
    # Registered in sys.modules BEFORE execution, and not as a convenience.
    # `@dataclass` resolves its own module through `sys.modules[cls.__module__]`
    # while the class body executes, so a module loaded from a path that is not
    # registered fails with an unrelated-looking AttributeError on NoneType --
    # which would read as "the claim index is broken" rather than "it was loaded
    # wrongly". Measured the first time this loaded the real module.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - re-raised as the fail-closed type
        del sys.modules[spec.name]
        raise ResolutionUnavailable(f"{resolved} failed to import: {exc}") from exc
    missing = [name for name in _REQUIRED_ENTRY_POINTS if not hasattr(module, name)]
    if missing:
        # A file that imports but carries none of the entry points is not the
        # claim index; treating it as one would answer with whatever its empty
        # namespace implies, which is "nothing is claimed".
        raise ResolutionUnavailable(
            f"{resolved} imported but is missing {', '.join(missing)}, so it is not the "
            "claim index module"
        )
    return module


def _fence(message: str) -> int | None:
    raw = li.commit_trailers(message).get(FENCE_TRAILER)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        # An unparseable fence is not a zero. Zero would be BEHIND every live
        # claim and would refuse a correct push on a typo.
        return None


def resolve_with_index(
    claim_index: ModuleType,
    index: dict[str, Any],
    *,
    branch: str,
    commits: list[tuple[str, str]],
    ledger_name: str,
    now: datetime,
) -> Verdict:
    """The resolution, against an already-built index."""
    ticket = claim_index.ticket_from_branch(branch)
    if ticket is None:
        # Not every branch is ticket-shaped, and a branch with no ticket has no
        # claim to compare against. Silence is the correct answer, not a finding.
        return Verdict(outcome="no-ticket", ticket=None)

    held = claim_index.holder(index, ticket)
    holder_text = None
    if held is not None and held.state == "held":
        # The HOLDER's own source file, which after a roll is an archive rather
        # than the live ledger (OMN-18791). Falling back to `ledger_name` keeps
        # this readable against an index built before that field existed.
        source = getattr(held, "source", None) or ledger_name
        holder_text = f"{held.lane} ({source}:{held.claim_line}, fence {held.fence})"

    findings: list[str] = []
    outcomes: set[str] = set()
    lanes: list[str] = []

    for sha, message in commits:
        identity = li.commit_identity(message)
        if identity is None:
            outcomes.add("unidentified")
            findings.append(
                f"{sha[:12]} carries no resolvable lane identity, so this push cannot be "
                f"compared against the claim on {ticket}. An absent identifier and a wrong "
                "one are indistinguishable downstream, which is why this reports rather "
                "than passing.\n"
                "    Register the worktree once, then amend or re-commit:\n"
                "      python3 scripts/lane_identity.py register --lane <slug> "
                f"--ticket {ticket}"
            )
            continue

        lane = identity[0]
        if lane not in lanes:
            lanes.append(lane)

        reason = claim_index.refusal_for_push(
            index, ticket, lane, fence=_fence(message), now=now
        )
        if reason is None:
            outcomes.add(
                "held-by-pusher"
                if held is not None and held.state == "held"
                else "unclaimed"
            )
            continue

        # The refusal text -- holder, citable row, release path -- comes entirely
        # from the claim index. The only thing decided here is which LABEL to put
        # on it, and that is a comparison of two values the index already
        # returned, not a second copy of the refusal rule.
        kind = (
            "held-elsewhere"
            if held is not None and held.lane != lane
            else "fence-behind"
        )
        outcomes.add(kind)
        findings.append(f"{sha[:12]}: {reason}")

    if not commits:
        outcomes.add("held-by-pusher" if holder_text else "unclaimed")

    outcome = next((name for name in _SEVERITY if name in outcomes), "unclaimed")
    return Verdict(
        outcome=outcome,
        ticket=ticket,
        lanes=lanes,
        holder=holder_text,
        findings=findings,
    )


def resolve(
    claim_index: ModuleType,
    *,
    branch: str,
    commits: list[tuple[str, str]],
    ledger_text: str,
    ledger_name: str,
    now: datetime,
) -> Verdict:
    """The resolution against ONE text.

    This is the shape for a caller that already holds the text and is asking
    about that text alone. A caller resolving the real store wants
    `resolve_store`: the store is the live ledger plus the rolls it has spilled
    into, and this form cannot see them (OMN-18791).
    """
    index = claim_index.build_index(ledger_text, ledger_name, now=now)
    return resolve_with_index(
        claim_index,
        index,
        branch=branch,
        commits=commits,
        ledger_name=ledger_name,
        now=now,
    )


def resolve_store(
    claim_index: ModuleType,
    *,
    branch: str,
    commits: list[tuple[str, str]],
    ledger: Path,
    ledger_name: str,
    now: datetime,
) -> Verdict:
    """The resolution against the whole claim store.

    The ledger ROLLS: a post-merge hook moves rows out of the live file into
    `<ledger dir>/archive/`, daily. Reading the live file alone therefore lost
    every claim the last roll carried away, and a lost claim reads as an
    UNCLAIMED branch -- which is clean. Both callers of this resolution passed
    exactly the case they exist to catch, once a day, silently (OMN-18791).

    Which files that is, and the bound that keeps it cheap, are the claim
    index's decision and not re-implemented here -- the same reason nothing in
    this module re-implements the comparison.
    """
    sources = claim_index.window_sources(ledger, ledger_name, now=now)
    index = claim_index.build_index_from_sources(sources, now=now)
    return resolve_with_index(
        claim_index,
        index,
        branch=branch,
        commits=commits,
        ledger_name=ledger_name,
        now=now,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _commits_from_args(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.messages_from:
        path = Path(args.messages_from)
        if not path.is_file():
            raise ResolutionUnavailable(f"no commit message file at {path}")
        return [("(local)", path.read_text(encoding="utf-8"))]
    if not args.rev_range:
        raise ResolutionUnavailable("one of --range or --messages-from is required")
    revs: list[str] = [args.rev_range]
    if args.not_on_remote:
        revs += ["--not", f"--remotes={args.not_on_remote}"]
    try:
        return [
            (sha, message)
            for sha, _subject, message in li.commits_in_range(Path(args.repo), revs)
        ]
    except li.BadRange as exc:
        # An unresolvable range yields no commits, and no commits reads exactly
        # like "every commit is fine". Error instead.
        raise ResolutionUnavailable(str(exc)) from exc


def _install_hook(repo: Path) -> int:
    """Install the pre-push hook into `repo`'s OWN hooks directory.

    The shared-directory refusal is `lane_identity.own_hooks_dir`, imported
    rather than re-implemented. A second, weaker copy of the one check that
    stopped the 2026-09-13 fleet incident is exactly the drift this phase is
    about -- and a pre-push hook installed into a shared directory would arm
    every repository that shares it, which is a worse version of the incident
    that check was written for.
    """
    try:
        target, reason = li.install_hook(
            repo,
            source=Path(__file__).resolve().parent / "hooks" / "pre-push-branch-claim",
            hook_name="pre-push",
            placeholder="@BRANCH_CLAIM_PATH@",
            module=Path(__file__),
        )
    except li.SharedHooksDirectory as exc:
        print(f"branch_claim: {exc}", file=sys.stderr)
        return 2
    print(f"branch_claim: installed {target}")
    print(
        "  It refuses NOTHING until a worktree is registered as a lane:\n"
        "    python3 scripts/lane_identity.py register --lane <slug> --ticket OMN-XXXX"
    )
    reachable, _ = li.hooks_reachable(repo, "pre-push")
    if not reachable:
        # OMN-18273: a hook file git will never dispatch is not an installation.
        # Reported nonzero rather than printed over, because the whole defect
        # this closes is a mechanism that reported Done and never ran.
        print(f"branch_claim: NOT REACHABLE -- {reason}", file=sys.stderr)
        return 4
    print(f"branch_claim: reachable -- {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="resolve a branch against the claim store")
    check.add_argument("--branch", required=True)
    check.add_argument("--repo", default=".")
    check.add_argument("--range", dest="rev_range", help="e.g. origin/dev..HEAD")
    check.add_argument(
        "--not-on-remote",
        help=(
            "exclude commits already on this remote's branches. For a NEW branch "
            "there is no remote tip to diff against, and reading the branch's whole "
            "history instead would attribute somebody else's commits to this push."
        ),
    )
    check.add_argument("--messages-from", help="a file holding one commit message")
    check.add_argument("--ledger", required=True)
    check.add_argument(
        "--ledger-name",
        required=True,
        help="how the ledger is cited in a refusal, e.g. docs/tracking/<file>.md",
    )
    check.add_argument("--claim-index-module", required=True)
    check.add_argument("--index", help="optional cache path for the resolved index")
    check.add_argument("--mode", choices=("record", "refuse"), default="record")
    check.add_argument(
        "--refuse-outcomes",
        default=",".join(_DEFAULT_REFUSE_ON),
        help=(
            "comma-separated outcomes that make 'refuse' mode exit non-zero "
            f"(default: {','.join(_DEFAULT_REFUSE_ON)}). Findings outside the set "
            "are still printed."
        ),
    )
    check.add_argument(
        "--annotate",
        action="store_true",
        help="emit findings as workflow-command annotations as well as text",
    )

    install = sub.add_parser(
        "install-hook",
        help="install the pre-push branch-claim hook in a clone",
        description=(
            "Arms one CLONE. Separate from the lane-identity installer on purpose: "
            "a refusing pre-push hook is a decision somebody makes, never a side "
            "effect of installing the stamping hook. Even once installed it does "
            "nothing for a worktree that is not registered as a lane."
        ),
    )
    install.add_argument("--repo", default=".")

    args = parser.parse_args(argv)

    if args.command == "install-hook":
        return _install_hook(Path(args.repo))

    try:
        claim_index = load_claim_index(Path(args.claim_index_module))
    except ResolutionUnavailable as exc:
        # Loaded before the resolution below, and separately, because that
        # block catches an exception type the module itself declares -- naming
        # it while the module is unbound would raise from the handler.
        print(f"branch-claim: {exc}", file=sys.stderr)
        return 2

    try:
        ledger = Path(args.ledger)
        if not ledger.is_file():
            raise ResolutionUnavailable(
                f"the claim store is not readable at {ledger}. The check refuses rather "
                "than resolving against an empty store: no holders reads exactly like "
                "every branch being unclaimed, which is a clean bill of health over the "
                "whole corpus. THE CHECK DID NOT RUN."
            )
        commits = _commits_from_args(args)
        now = datetime.now(UTC)
        if args.index:
            index = claim_index.resolve_index(
                ledger, Path(args.index), args.ledger_name, now=now
            )
            verdict = resolve_with_index(
                claim_index,
                index,
                branch=args.branch,
                commits=commits,
                ledger_name=args.ledger_name,
                now=now,
            )
        else:
            verdict = resolve_store(
                claim_index,
                branch=args.branch,
                commits=commits,
                ledger=ledger,
                ledger_name=args.ledger_name,
                now=now,
            )
    except claim_index.ClaimStoreIncomplete as exc:
        # The store itself says a file exists that this cannot read. Reported
        # with the same exit code as any other could-not-run, because that is
        # what it is: resolving the readable half would report every rolled
        # claim as unclaimed, which is a clean bill of health over exactly the
        # rows nobody can see.
        print(f"branch-claim: {exc}\nTHE CHECK DID NOT RUN.", file=sys.stderr)
        return 2
    except ResolutionUnavailable as exc:
        # Exit 2 in BOTH modes. Record mode tolerates a finding; it does not
        # tolerate a gate that could not run, and the two must not share an exit
        # code or the distinction is unreadable from the outside.
        print(f"branch-claim: {exc}", file=sys.stderr)
        return 2

    header = (
        f"branch-claim: {verdict.outcome} "
        f"branch={args.branch} ticket={verdict.ticket or '-'} "
        f"lanes={','.join(verdict.lanes) or '-'} holder={verdict.holder or '-'}"
    )
    print(header)

    if verdict.clean:
        return 0

    for finding in verdict.findings:
        print(finding, file=sys.stderr)
        if args.annotate:
            print(f"::warning title=branch-claim::{finding.splitlines()[0]}")

    refusable = {
        name.strip() for name in args.refuse_outcomes.split(",") if name.strip()
    }
    if args.mode == "refuse":
        if verdict.outcome in refusable:
            return 1
        print(
            f"branch-claim: {verdict.outcome} is reported but not refused "
            f"(refusing on: {', '.join(sorted(refusable))})."
        )
        return 0
    print(
        "branch-claim: recorded, not refused. The pull-request check reports; the "
        "pre-push refusal is the separate, later half (operator ruling 2026-09-13)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
