# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Pre-mutation lane-ownership gate for destructive ``gh`` verbs (OMN-16485, OMN-20685).

Every concurrent lane on a host drives GitHub through ONE shared ``gh`` identity, so
``timeline.actor.login`` is the same account for every lane and per-command
attribution is structurally INDETERMINATE. Nothing mechanically stopped a lane from
closing a peer lane's PR -- observed >=5 times in 48h (omniclaude#2019 was authored
by one account and closed by another), plus a duplicate concurrent
``workflow_dispatch`` fired ~19s after a peer's.

``HandlerPrOwnership.handle`` answers one question:

    "Given this Bash command, may THIS lane perform the GitHub mutation it
     contains?"

It performs NO network I/O. Ownership resolves entirely from the local claims
directory plus a locally-resolvable lane identity, so it is safe to run in the
``PreToolUse`` hot path. Active claims must match the caller's lane and full run
identity; a recorded full session must match too (OMN-19699). A session fallback
may resolve a named claim only when both full session and run match. Shared session
prefixes never prove ownership.

Two mutation classes, deliberately different verdicts:

``ownership`` -- ``gh pr close`` / ``gh pr reopen`` / ``gh api -X PATCH
    .../pulls/<n>`` carrying ``state=closed``. Destroys a peer lane's work.
    FAIL-CLOSED: an absent, expired, unreadable, or lane-less claim REFUSES the
    mutation. "Nobody claimed it" is never read as "therefore anyone may." The
    refusal names the one command that records the claim, so the escape hatch IS
    the act of producing the missing attribution record.

``exclusivity`` -- ``gh workflow run`` / ``gh run cancel``. The hazard is a
    duplicate concurrent actor, not destruction of an owned artifact, so the rule
    is first-writer-wins: an active peer claim refuses; otherwise the mutation is
    allowed AND the claim is recorded, which is what makes the second, racing lane
    refuse.

Where the claims live. The claim registry and the session-id resolver are plugin
hook-library siblings (``pr_claim_registry.py``, ``session_id.py``) that stay in
that directory until the registry has its own node; the process entry takes the
directory as ``--hooks-lib`` and imports them from it.

Fail-open boundary (explicit, not accidental): this handler fails CLOSED on every
ownership question it can pose. Its shell wrapper fails CLOSED when this entry
errors on a command that matched a mutation verb, and never runs it at all for
commands that contain no mutation verb -- so a guard bug cannot brick unrelated
Bash traffic.
"""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from omniclaude.nodes.node_pr_ownership_guard_effect.enums import (
    EnumPrClaimStatus,
    EnumPrMutationClass,
    EnumPrOwnershipReason,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_lane import (
    claim_cli_path,
    resolve_lane_id,
    resolve_run_id,
    resolve_session_id,
    sanitize_lane,
    sibling,
    use_hooks_lib,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_parse import (
    PrMutation,
    canonical_pr_key,
    parse_mutations,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.models import (
    ModelPrOwnershipDecision,
    ModelPrOwnershipRequest,
    ModelPrOwnershipResult,
)
from omniclaude.nodes.node_pr_ownership_guard_effect.protocols import (
    ProtocolPrClaimRegistry,
)

__all__ = [
    "EXIT_ALLOW",
    "EXIT_BLOCK",
    "HandlerPrOwnership",
    "canonical_pr_key",
    "decide",
    "evaluate_command",
    "evaluate_mutations",
    "parse_mutations",
    "read_claim",
    "run_command_file",
    "resolve_lane_id",
    "resolve_run_id",
    "use_hooks_lib",
]


EXIT_ALLOW = 0
EXIT_BLOCK = 3


def _registry() -> ProtocolPrClaimRegistry:
    """The process's claim registry, from the hook library."""
    registry: ProtocolPrClaimRegistry = sibling("pr_claim_registry").get_registry()
    return registry


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


def _claim_command(
    target_key: str, lane_id: str | None = None, run_id: str | None = None
) -> str:
    command = f"python3 {shlex.quote(claim_cli_path())} claim {shlex.quote(target_key)} --action close"
    if lane_id:
        command += f" --lane {shlex.quote(lane_id)}"
    if run_id:
        command += f" --run-id {shlex.quote(run_id)}"
    # The hook can resolve a worktree lane while Bash runs the remedy elsewhere.
    # Bind the CLI to the identity this hook already resolved, without changing
    # the hook's environment or trusting an arbitrary --lane alias.
    bindings = []
    if lane_id:
        bindings.append(shlex.quote(f"ONEX_LANE_ID={lane_id}"))
    if run_id:
        bindings.append(shlex.quote(f"ONEX_RUN_ID={run_id}"))
    if bindings:
        command = "env " + " ".join(bindings) + " " + command
    return command


def decide(
    mutation: PrMutation,
    lane_id: str | None,
    claim_status: EnumPrClaimStatus,
    claim_lane: str | None,
    *,
    run_id: str | None = None,
    claim_run: str | None = None,
    session_id: str | None = None,
    claim_session: str | None = None,
) -> ModelPrOwnershipDecision:
    """Return the verdict for one mutation. Pure; no I/O."""
    verb = mutation.verb
    target = mutation.target_key

    if lane_id is None:
        return ModelPrOwnershipDecision(
            allowed=False,
            reason_code=EnumPrOwnershipReason.INDETERMINATE_LANE,
            verb=verb,
            target_key=target,
            message=(
                f"REFUSED ({verb}): this lane has no resolvable identity, so the "
                "mutation cannot be attributed. Attribution that cannot be "
                "established fails closed — it is never assumed. Export "
                "ONEX_LANE_ID=<your-lane-handle> or ONEX_LANE (the handle you registered in "
                "the rolling work ledger) and retry."
            ),
        )

    if target is None:
        reason = mutation.unresolved_reason or "target could not be resolved"
        return ModelPrOwnershipDecision(
            allowed=False,
            reason_code=EnumPrOwnershipReason.INDETERMINATE_TARGET,
            verb=verb,
            target_key=None,
            message=(
                f"REFUSED ({verb}): {reason}. Ownership cannot be checked against "
                "an unresolved target, so this fails closed. Re-run with an "
                "explicit --repo <owner>/<repo> and an explicit id."
            ),
        )

    if claim_status == EnumPrClaimStatus.UNREADABLE:
        return ModelPrOwnershipDecision(
            allowed=False,
            reason_code=EnumPrOwnershipReason.INDETERMINATE_CLAIM,
            verb=verb,
            target_key=target,
            message=(
                f"REFUSED ({verb}) on {mutation.detail}: the ownership claim for "
                f"'{target}' exists but is unreadable or malformed. An "
                "unreadable claim is INDETERMINATE, not absent, and fails closed. "
                f"Inspect it with: python3 {claim_cli_path()} list"
            ),
        )

    if claim_status == EnumPrClaimStatus.ACTIVE:
        if claim_lane is None:
            return ModelPrOwnershipDecision(
                allowed=False,
                reason_code=EnumPrOwnershipReason.INDETERMINATE_CLAIM,
                verb=verb,
                target_key=target,
                message=(
                    f"REFUSED ({verb}) on {mutation.detail}: an active claim exists "
                    f"on '{target}' but it records no lane, so it cannot prove this "
                    "lane owns the work. Re-claim it with: "
                    + _claim_command(target, lane_id, run_id)
                ),
            )
        session_owns_claim = bool(
            session_id
            and run_id
            and lane_id == sanitize_lane(f"session:{session_id[:16]}")
            and claim_session == session_id
            and claim_run == run_id
        )
        if claim_lane != lane_id and not session_owns_claim:
            return ModelPrOwnershipDecision(
                allowed=False,
                reason_code=EnumPrOwnershipReason.CROSS_LANE,
                verb=verb,
                target_key=target,
                message=(
                    f"REFUSED ({verb}) on {mutation.detail}: owned by lane "
                    f"'{claim_lane}', and you are lane '{lane_id}'. A lane may not "
                    "mutate a peer lane's work. Coordinate with that lane in the "
                    "rolling work ledger; if it is finished, it releases the claim "
                    f"with: python3 {claim_cli_path()} "
                    f"release '{target}' <run-id>"
                ),
            )
        if (claim_session and claim_session != session_id) or (
            run_id is not None and claim_run != run_id
        ):
            return ModelPrOwnershipDecision(
                allowed=False,
                reason_code=EnumPrOwnershipReason.CROSS_RUN,
                verb=verb,
                target_key=target,
                message=(
                    f"REFUSED ({verb}) on {mutation.detail}: owned by lane "
                    f"'{claim_lane}' in run '{claim_run}', session '{claim_session}', "
                    f"and you are run '{run_id}', session '{session_id}'. "
                    "A matching lane name cannot authorize another run or session. "
                    "Coordinate with the holder in the rolling work ledger."
                ),
            )
        return ModelPrOwnershipDecision(
            allowed=True,
            reason_code=EnumPrOwnershipReason.OWNED_BY_SELF,
            verb=verb,
            target_key=target,
            message=f"allowed: lane '{claim_lane}' holds an active claim on {target}",
        )

    # claim_status is "absent" or "expired" from here on.
    if mutation.mutation_class == EnumPrMutationClass.EXCLUSIVITY:
        return ModelPrOwnershipDecision(
            allowed=True,
            reason_code=EnumPrOwnershipReason.FIRST_WRITER,
            verb=verb,
            target_key=target,
            record_claim=True,
            message=(
                f"allowed: lane '{lane_id}' is the first writer for {target}; "
                "claim recorded so a racing peer refuses"
            ),
        )

    return ModelPrOwnershipDecision(
        allowed=False,
        reason_code=EnumPrOwnershipReason.UNCLAIMED,
        verb=verb,
        target_key=target,
        message=(
            f"Missing PR claim: '{target}' has no active ownership claim. "
            f"REFUSED ({verb}) on {mutation.detail}.\n"
            f"    {_claim_command(target, lane_id, run_id)}\n"
            "Run the command above only if this work is yours, before closing. An "
            "unclaimed target is INDETERMINATE, not free — >=5 green PRs were "
            "closed unmerged this way in 48h under the shared gh identity "
            "(OMN-16485). "
            "Recording the claim IS the attribution record that is otherwise "
            "missing; it is not a formality to route around."
        ),
    )


# ---------------------------------------------------------------------------
# Registry-backed evaluation
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Registry-backed evaluation
# ---------------------------------------------------------------------------


def read_claim(
    claims_dir: Path, target_key: str
) -> tuple[EnumPrClaimStatus, str | None, str | None, str | None]:
    """Read a claim, distinguishing absent from unreadable (fail-closed input)."""
    registry = sibling("pr_claim_registry")

    claim_file = claims_dir / f"{registry.filesystem_key(target_key)}.json"
    if not claim_file.exists():
        return EnumPrClaimStatus.ABSENT, None, None, None
    try:
        data = json.loads(claim_file.read_text())
    except (json.JSONDecodeError, OSError):
        return EnumPrClaimStatus.UNREADABLE, None, None, None
    if not isinstance(data, dict):
        return EnumPrClaimStatus.UNREADABLE, None, None, None

    lane = data.get("lane_id")
    lane_value = lane if isinstance(lane, str) and lane.strip() else None
    run = data.get("claimed_by_run")
    session = data.get("claimed_by_session")
    if (run is not None and (not isinstance(run, str) or not run.strip())) or (
        session is not None and (not isinstance(session, str) or not session.strip())
    ):
        return EnumPrClaimStatus.UNREADABLE, lane_value, None, None
    try:
        active = registry.is_active(data)
    except (TypeError, ValueError):
        return EnumPrClaimStatus.UNREADABLE, lane_value, run, session
    status = EnumPrClaimStatus.ACTIVE if active else EnumPrClaimStatus.EXPIRED
    return status, lane_value, run, session


def evaluate_command(
    command: str,
    *,
    claims_dir: Path,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
    default_repo: str | None = None,
) -> list[ModelPrOwnershipDecision]:
    """Evaluate every guarded mutation in ``command``.

    Returns one decision per detected mutation; an empty list means the command
    contains nothing this guard governs.
    """
    mutations = parse_mutations(command, default_repo=default_repo)
    if not mutations:
        return []
    return evaluate_mutations(mutations, claims_dir=claims_dir, env=env, cwd=cwd)


def evaluate_mutations(
    mutations: list[PrMutation],
    *,
    claims_dir: Path,
    env: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> list[ModelPrOwnershipDecision]:
    """Decide already-parsed mutations against the on-disk claims directory.

    Split out from :func:`evaluate_command` so the process entry can parse FIRST
    and skip every ownership surface -- registry import included -- when the
    command holds no guarded mutation (OMN-16983).
    """
    lane_id = resolve_lane_id(env=env, cwd=cwd)
    run_id = resolve_run_id(env=env) or lane_id
    session_id = resolve_session_id(env)
    decisions: list[ModelPrOwnershipDecision] = []
    for mutation in mutations:
        if mutation.target_key is None:
            decisions.append(decide(mutation, lane_id, EnumPrClaimStatus.ABSENT, None))
            continue
        status, claim_lane, claim_run, claim_session = read_claim(
            claims_dir, mutation.target_key
        )
        decisions.append(
            decide(
                mutation,
                lane_id,
                status,
                claim_lane,
                run_id=run_id,
                claim_run=claim_run,
                session_id=session_id,
                claim_session=claim_session,
            )
        )
    return decisions


class HandlerPrOwnership:
    """Judge one Bash command's GitHub mutations against the lane-ownership claims."""

    def __init__(self, *, defer_claims: bool = False) -> None:
        """``defer_claims`` leaves first-writer claims to :meth:`record_claims`.

        The process entry prints the verdict before the claims are written, as the
        standalone guard did: the registry can print a line while it reaps an
        expired claim, and that line must follow the verdict.
        """
        self._defer_claims = defer_claims

    def handle(self, request: ModelPrOwnershipRequest) -> ModelPrOwnershipResult:
        """Decide every guarded mutation in the command; record first-writer claims.

        The shell pre-filter is a cheap, deliberately over-matching grep: it fires
        on a bare ``gh api`` for ANY HTTP method, and on quoted text that merely
        names a guarded verb. THIS parser is the authority. A command carrying no
        guarded mutation -- a read-only ``gh api <path> --jq``, a ``printf 'gh api
        ...'`` -- is decided right here, before any ownership surface is touched: no
        registry import, no claims directory, no state directory. That ordering is
        the fix, not an optimization (OMN-16983): it is what stops a defect in the
        ownership path from converting read-only GitHub traffic into a refusal.
        Genuine mutation verbs fall through and keep the OMN-16485 fail-closed
        contract.
        """
        if request.hooks_lib:
            use_hooks_lib(request.hooks_lib)
        mutations = parse_mutations(request.command, default_repo=request.default_repo)
        if not mutations:
            return ModelPrOwnershipResult(blocked=False, decisions=[], reason="")

        claims_dir = _registry().claims_dir
        decisions = evaluate_mutations(
            mutations, claims_dir=claims_dir, env=request.env, cwd=request.cwd
        )
        blocked = [decision for decision in decisions if not decision.allowed]
        if blocked:
            return ModelPrOwnershipResult(
                blocked=True,
                decisions=decisions,
                reason="\n\n".join(decision.message for decision in blocked),
            )
        result = ModelPrOwnershipResult(blocked=False, decisions=decisions, reason="")
        if self._defer_claims:
            return result
        return result.model_copy(
            update={"recorded_claims": self.record_claims(request, result)}
        )

    def record_claims(
        self, request: ModelPrOwnershipRequest, result: ModelPrOwnershipResult
    ) -> list[str]:
        """Record a claim for each allowed first-writer (exclusivity) mutation.

        This is what makes the next racing lane see a live claim rather than an
        empty registry. A blocked verdict records nothing.
        """
        if result.blocked or not any(d.record_claim for d in result.decisions):
            return []
        lane_id = resolve_lane_id(env=request.env, cwd=request.cwd)
        registry = _registry()
        recorded: list[str] = []
        for decision in result.decisions:
            if decision.record_claim and decision.target_key and lane_id:
                registry.acquire(
                    pr_key=decision.target_key,
                    run_id=resolve_run_id(env=request.env) or lane_id,
                    action=decision.verb,
                    lane_id=lane_id,
                    session_id=resolve_session_id(request.env),
                )
                recorded.append(decision.target_key)
        return recorded


def run_command_file(command: str, *, cwd: str | None, default_repo: str | None) -> int:
    """Judge one command for the process entry: print the verdict, then record claims.

    Exit codes: 0 allow, 3 block. The verdict is printed before the claims are
    written, as the standalone guard did: the registry can print a line while it
    reaps an expired claim, and that line must follow the verdict.
    """
    request = ModelPrOwnershipRequest(
        command=command, cwd=cwd, default_repo=default_repo
    )
    handler = HandlerPrOwnership(defer_claims=True)
    result = handler.handle(request)
    sys.stdout.write(json.dumps(result.verdict_payload()) + "\n")
    if result.blocked:
        return EXIT_BLOCK
    handler.record_claims(request, result)
    return EXIT_ALLOW
