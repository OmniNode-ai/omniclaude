#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Fail-closed Done-flip and acceptance-box guard.

Done, or an edit ticking an acceptance box, needs repo evidence: a merged PR's
``contracts/<TICKET>.yaml`` binding every labelled criterion and a green
``repo-evidence / dod-verify`` run on the contract that merged (or, for a
docs-only ticket, its merged docs PR). Cited PRs merged, no box unchecked.
The hook's readers read no GitHub through gh (OMN-20368). Exit 0 allows; 2 blocks.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Sibling module (same lib/ dir). The shell wrapper runs this file directly, so
# its directory is on sys.path[0] and the import resolves without packaging.
from linear_done_verify import (
    PRStatus,
    augment_description_with_attachments,
    fetch_pr_status,
    is_cancel_state,
    is_done_state,
    parse_deploy_readback_marker,
    verify,
    verify_implementing,
)
from no_pr_bound_evidence import (
    RepoEvidenceOutcome,
    RepoEvidenceVerdict,
    evaluate_repo_evidence,
)

_LINEAR_TOOLS = frozenset(
    {"mcp__linear-server__save_issue", "mcp__linear-server__update_issue"}
)

# An unchecked acceptance box is the ticket author's admission that work
# remains, even when the product PR merged and its evidence checks passed.
_UNCHECKED_BOX_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[ \][ \t]+\S.*$", re.MULTILINE
)
_MAX_UNCHECKED_BOX_SNIPPET_CHARS = 240


def find_unchecked_acceptance_boxes(description: str) -> list[str]:
    """Every unchecked list-item box with text (``- [ ] x``, ``1. [ ] x``). Pure."""
    return [
        line.strip()[:_MAX_UNCHECKED_BOX_SNIPPET_CHARS]
        for line in _UNCHECKED_BOX_RE.findall(description or "")
    ]


@dataclass(frozen=True)
class Decision:
    """Result of the guard: allow (exit 0) or block (exit 2)."""

    allowed: bool
    reason: str


# ---------------------------------------------------------------------------
# Live Linear read (for status-only updates that omit the description)
# ---------------------------------------------------------------------------


def _default_linear_fetcher(ticket_id: str) -> dict[str, Any] | None:
    """The issue dict via ``_fetch_linear_issue``; ``{}`` with no key, None on failure."""
    from linear_done_verify import _fetch_linear_issue

    result = _fetch_linear_issue(ticket_id)
    return result if isinstance(result, dict) or result is None else None


# ---------------------------------------------------------------------------
# Core decision
# ---------------------------------------------------------------------------

# OMN-20368: a CHECKED task-list box. Every box counts, as for the unchecked
# gate above: a lane that ticks a box is asserting a criterion was met.
_CHECKED_BOX_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[xX]\][ \t]+(\S.*)$", re.MULTILINE
)
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def _normalise_box_text(text: str) -> str:
    """Box text compared across edits: Linear's backslash escapes and spacing removed."""
    return " ".join(text.replace("\\", "").split()).casefold()


def checked_acceptance_boxes(description: str) -> set[str]:
    """The normalised text of every checked (``[x]``) task-list item. Pure."""
    return {_normalise_box_text(m) for m in _CHECKED_BOX_RE.findall(description or "")}


def newly_ticked_boxes(before: str | None, after: str) -> list[str]:
    """Checked boxes in ``after`` that were not checked in ``before``.

    ``before`` is None when the current description could not be read; every
    checked box in ``after`` then counts as newly ticked (fail closed: an edit
    whose effect cannot be compared is treated as the edit that ticks).
    """
    previously = checked_acceptance_boxes(before) if before is not None else set()
    return sorted(checked_acceptance_boxes(after) - previously)


def _patch_texts(ops: list[Any]) -> str:
    parts: list[str] = []
    for op in ops:
        if isinstance(op, dict):
            for key in ("new_string", "text"):
                value = op.get(key)
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def apply_description_patch(current: str, ops: list[Any]) -> str | None:
    """Apply the Linear MCP ``patch`` operations to ``current``; None if any fails.

    Mirrors the MCP's documented semantics (every anchor must match exactly
    once, unless ``replace_all``). A None result is not an error to the caller:
    it means the guard cannot predict the edit, and it fails closed on it.
    """
    text = current
    for op in ops:
        if not isinstance(op, dict):
            return None
        kind = op.get("op")
        if kind == "replace":
            old, new = op.get("old_string"), op.get("new_string")
            if not isinstance(old, str) or not isinstance(new, str) or not old:
                return None
            if op.get("replace_all"):
                if old not in text:
                    return None
                text = text.replace(old, new)
            else:
                if text.count(old) != 1:
                    return None
                text = text.replace(old, new, 1)
        elif kind in ("insert_before", "insert_after"):
            anchor, add = op.get("anchor"), op.get("text")
            if not isinstance(anchor, str) or not isinstance(add, str):
                return None
            if text.count(anchor) != 1:
                return None
            joined = add + anchor if kind == "insert_before" else anchor + add
            text = text.replace(anchor, joined, 1)
        elif kind == "prepend":
            add = op.get("text")
            if not isinstance(add, str):
                return None
            text = add + text
        elif kind == "append":
            add = op.get("text")
            if not isinstance(add, str):
                return None
            text = text + add
        elif kind == "replace_range":
            start, end, new = op.get("from"), op.get("to"), op.get("new_string")
            if not all(isinstance(x, str) for x in (start, end, new)):
                return None
            assert isinstance(start, str) and isinstance(end, str)
            assert isinstance(new, str)
            if text.count(start) != 1:
                return None
            i = text.index(start)
            j = text.find(end, i + len(start))
            if j < 0 or text.count(end, i + len(start)) != 1:
                return None
            text = text[:i] + new + text[j:]
        else:
            return None
    return text


def _refuse(reason: str) -> Decision:
    return Decision(False, reason)


def _repo_evidence_refusal(ticket_id: str, detail: str, *, why: str) -> Decision:
    return _refuse(
        f"no_bound_dod_receipt for {ticket_id}: {why}. The repo-evidence bar is "
        f"the product repository's contracts/{ticket_id}.yaml binding EVERY "
        "labelled acceptance criterion through `binds_ac`, plus a green "
        '"repo-evidence / dod-verify" GitHub Actions check run on the merged '
        "head verifying the same contract that merged. What is missing: "
        f"{detail} Land the bindings and a passing check in the product repository."
    )


def decide(
    call: dict[str, Any],
    *,
    repo_evidence_probe: Callable[
        [str, list[str], list[PRStatus]], RepoEvidenceVerdict | None
    ]
    | None = None,
    pr_fetcher: Callable[[Any], Any] = fetch_pr_status,
    linear_fetcher: Callable[[str], dict[str, Any] | None] = _default_linear_fetcher,
) -> Decision:
    """Decide a tool call using repo evidence, GitHub PRs and live Linear text.

    I/O boundaries are injectable: ``repo_evidence_probe(ticket_id,
    descriptions, merged_statuses)``, ``pr_fetcher(PRRef)``, and
    ``linear_fetcher(ticket_id)``. Repo evidence is the only sufficient bar
    for Done transitions and acceptance-box ticks.
    """
    tool_name = call.get("tool_name", "")
    if tool_name not in _LINEAR_TOOLS:
        return Decision(True, "not_linear_tool")

    params = call.get("tool_input") or {}
    if not isinstance(params, dict):
        return Decision(True, "no_tool_input")

    ticket_id = str(params.get("id") or params.get("issueId") or "")
    state_value = str(params.get("state") or params.get("status") or "").strip()

    # A state passed by id (the MCP accepts "type, name, or ID") cannot be
    # classified without a network read, and an unclassified Done would slip
    # past every check below. Refused: pass the state by name.
    if state_value and _UUID_RE.match(state_value):
        return _refuse(
            f"state_by_id: state {state_value} was passed by id, so the guard "
            "cannot tell whether this is a Done transition. Pass the state by "
            "name (Done, In Progress, ...)."
        )

    if is_cancel_state(state_value):
        return Decision(True, "carve_out:cancel_state")
    is_done = is_done_state(state_value)

    # ---- the live description, read once ---------------------------------
    issue: dict[str, Any] | None = None
    live_read = False

    def _live() -> dict[str, Any] | None:
        nonlocal issue, live_read
        if not live_read:
            live_read = True
            fetched = linear_fetcher(ticket_id) if ticket_id else None
            issue = fetched if isinstance(fetched, dict) and fetched else None
        return issue

    # ---- the repo-evidence bar --------------------------------------------
    def _repo_verdict(
        descriptions: list[str], statuses: list[PRStatus] | None
    ) -> RepoEvidenceVerdict | None:
        if not ticket_id:
            return None
        if statuses is None:
            live = _live()
            description = (
                new_description
                if new_description is not None
                else str(live.get("description") or "")
                if live
                else ""
            )
            labels = [str(x) for x in (params.get("labels") or [])]
            if live is not None and not labels:
                labels = [str(x) for x in (live.get("labels") or [])]
            attachment_urls = (
                [str(x) for x in (live.get("attachment_urls") or [])] if live else []
            )
            pr_description = augment_description_with_attachments(
                description, attachment_urls
            )
            statuses = verify(
                pr_description,
                labels,
                default_repo=os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None,
                fetcher=pr_fetcher,
                ticket_id=ticket_id or None,
            ).pr_statuses
        merged_statuses = [s for s in statuses if s.state == "MERGED"]
        return (repo_evidence_probe or evaluate_repo_evidence)(
            ticket_id, descriptions, merged_statuses
        )

    def _bar(
        descriptions: list[str],
        *,
        why: str,
        statuses: list[PRStatus] | None = None,
    ) -> Decision | None:
        """None when every description's criteria are bound; else the refusal."""
        if not ticket_id:
            return _refuse(
                "no_ticket_id: a Done transition or an acceptance-box tick needs "
                "the issue id so its repo evidence can be read. Pass 'id'."
            )
        repo_verdict = _repo_verdict(descriptions, statuses)
        if (
            repo_verdict is not None
            and repo_verdict.outcome is RepoEvidenceOutcome.PASSED
        ):
            return None
        detail = (
            repo_verdict.detail
            if repo_verdict is not None
            else "repo evidence verdict unavailable"
        )
        return _repo_evidence_refusal(ticket_id, detail, why=why)

    # ---- the description this call would leave behind ----------------------
    has_description = isinstance(params.get("description"), str)
    patch_ops = params.get("patch")
    new_description: str | None = None
    current_description: str | None = None
    if has_description or isinstance(patch_ops, list):
        live = _live() if ticket_id else None
        current_description = (
            str(live.get("description") or "") if live is not None else None
        )
        if not ticket_id:
            current_description = ""  # a create: nothing was checked before it
        if has_description:
            new_description = str(params["description"])
        elif isinstance(patch_ops, list):
            applied = (
                apply_description_patch(current_description, patch_ops)
                if current_description is not None
                else None
            )
            # An edit the guard cannot predict is judged by what it inserts.
            new_description = (
                applied if applied is not None else _patch_texts(patch_ops)
            )
            if applied is None:
                current_description = None

    # ---- (T) acceptance-box tick gate (OMN-20368) -------------------------
    # A Done call is held to the full bar below on the description it writes,
    # which is strictly stronger, so the tick gate serves every other edit.
    if new_description is not None and not is_done:
        ticked = newly_ticked_boxes(current_description, new_description)
        if ticked:
            if not ticket_id:
                return _refuse(
                    "ac_tick_without_receipt: a new ticket cannot be created with "
                    f"checked acceptance boxes ({'; '.join(ticked[:3])}). Create "
                    "it with every box unchecked; boxes are ticked only once a "
                    "passing repo-evidence check exists (OMN-20368)."
                )
            preview = "; ".join(t[:120] for t in ticked[:3])
            refused = _bar(
                [new_description],
                why=(
                    f"this edit ticks {len(ticked)} acceptance box(es) ({preview}) "
                    "and no passing repo evidence covers the criteria"
                ),
            )
            if refused is not None:
                return Decision(
                    False,
                    refused.reason.replace(
                        "no_bound_dod_receipt", "ac_tick_without_receipt", 1
                    ),
                )

    if not is_done:
        return Decision(True, "not_done_state")

    # ---- Done transition -------------------------------------------------
    labels: list[str] = [str(x) for x in (params.get("labels") or [])]
    live = _live() if ticket_id else None
    live_description = str(live.get("description") or "") if live else ""
    if live is not None and not labels:
        labels = [str(x) for x in (live.get("labels") or [])]
    attachment_urls = (
        [str(x) for x in (live.get("attachment_urls") or [])] if live else []
    )
    # The criteria a Done must satisfy: today's, and whatever this call writes.
    # Evaluating only the proposed text would let a Done call drop a criterion.
    descriptions = [d for d in (live_description, new_description) if d]
    description = new_description if new_description is not None else live_description
    pr_description = augment_description_with_attachments(description, attachment_urls)

    # (U) an unchecked box is the ticket's own admission it is not done
    # (OMN-15030). Checked against every description in play.
    for desc in descriptions or [""]:
        unchecked_boxes = find_unchecked_acceptance_boxes(desc)
        if unchecked_boxes:
            preview = "; ".join(unchecked_boxes[:5])
            more = (
                f" (+{len(unchecked_boxes) - 5} more)"
                if len(unchecked_boxes) > 5
                else ""
            )
            return _refuse(
                f"unchecked_acceptance_criteria: {len(unchecked_boxes)} unchecked "
                f"box(es) remain in the ticket description: {preview}{more}. "
                "Ticking them is not the remedy: a box is ticked only once a "
                "passing repo-evidence check covers it (OMN-15030 / OMN-20368)."
            )

    default_repo = os.environ.get("LINEAR_DONE_VERIFY_DEFAULT_REPO") or None

    # (P) every cited / linked product PR must be merged. A further condition,
    # never a sufficient one (OMN-20368).
    merged_pr = False
    merged_statuses: list[PRStatus] = []
    if parse_deploy_readback_marker(pr_description) is not None:
        impl_result = verify_implementing(
            pr_description, labels, default_repo=default_repo, fetcher=pr_fetcher
        )
        if not impl_result.allowed:
            return _refuse(f"pr_not_merged\n{impl_result.reason}")
        merged_statuses = [s for s in impl_result.pr_statuses if s.state == "MERGED"]
    else:
        pr_result = verify(
            pr_description,
            labels,
            default_repo=default_repo,
            fetcher=pr_fetcher,
            ticket_id=ticket_id or None,
        )
        merged_statuses = [s for s in pr_result.pr_statuses if s.state == "MERGED"]
        if not pr_result.allowed:
            return _refuse(f"pr_not_merged\n{pr_result.reason}")
        merged_pr = pr_result.reason == "all_prs_merged"

    # (B) the repo-evidence bar. The one sufficient condition, on every path.
    refused = _bar(
        descriptions or [description],
        statuses=merged_statuses,
        why=(
            "a Done transition needs a passing definition-of-done check for "
            "every acceptance criterion"
        ),
    )
    if refused is not None:
        return refused
    return Decision(
        True,
        "durable_evidence:repo_bound_checks" + (":all_prs_merged" if merged_pr else ""),
    )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def _load_stdin_call() -> dict[str, Any]:
    try:
        parsed = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _lane_readers() -> dict[str, Callable[..., Any]]:
    """``decide``'s readers from the node_linear_effect handler, imported on first use."""

    def reader(name: str) -> Callable[..., Any]:
        def read(*args: Any) -> Any:
            os.environ.setdefault("ONEX_PLUGIN_HOOK_LIB", os.path.dirname(__file__))
            from omniclaude.nodes.node_linear_effect.handlers import (
                handler_lane_repo_evidence as handler,
            )

            return getattr(handler.hook_evidence_readers(), name)(*args)

        return read

    return {
        "repo_evidence_probe": reader("repo_evidence"),
        "pr_fetcher": reader("pr_status"),
    }


def main() -> int:
    """Read a PreToolUse call on stdin; exit 0 or 2. Fail CLOSED (OMN-20368)."""
    call = _load_stdin_call()
    try:
        decision = decide(call, **_lane_readers())
    except (
        ArithmeticError,
        AttributeError,
        ImportError,
        LookupError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        decision = Decision(
            False,
            f"guard_error: the done-flip guard could not decide "
            f"({type(exc).__name__}: {exc}). Refusing the Linear write rather "
            "than letting it through unchecked (OMN-20368).",
        )
    if decision.allowed:
        return 0
    payload = {
        "decision": "block",
        "reason": f"[OMN-20368 done-flip repo-evidence gate] {decision.reason}",
    }
    sys.stderr.write(json.dumps(payload) + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
