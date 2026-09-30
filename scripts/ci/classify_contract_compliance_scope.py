# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Decide the one declared case in which Contract Compliance evaluates nothing.

OMN-20138 (ported from omnibase_infra OMN-20135). The Contract Compliance Check now fails closed when the PR's ticket
has no contract at its evidence commit, or when no ticket resolves at all. One
kind of pull request carries no ticket by design: a dependency-bot bump, which
doctrine's PR-title rule exempts from carrying a ticket token. Such a PR has no
contract and no evidence reference, so evaluating it could only fail.

This module is that exemption, stated once and narrowly. It is the same
predicate ``ci_summary_gate`` already applies to the change-control caller jobs
(``_declared_ticketless_dependency_bot_skip``, OMN-19167), composed from the
same public helpers so the two cannot drift:

1. the event is ``pull_request`` (push and merge_group carry no author or title,
   and admit nothing);
2. the author is one of the dependency bots (``DEPENDENCY_BOT_AUTHORS``);
3. the mirrored PR-title rule exempts the PR from carrying a ticket (its
   bot-author arm already does for both bots);
4. neither the title nor the head ref carries a ticket token.

Anything else is evaluated. A bot PR that a lane retitled with a ticket is
judged against that ticket's contract; a human PR with a bump-shaped title must
carry a ticket like any other.

Writes ``exempt=true`` or ``exempt=false`` to ``--github-output``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scripts.ci.ci_summary_gate import (
    DEPENDENCY_BOT_AUTHORS,
    PullRequestContext,
    title_rule_exempts_ticket,
)


def is_declared_exemption(*, event_name: str, ctx: PullRequestContext) -> bool:
    """True only for a ticketless dependency-bot bump on a pull_request event."""

    if event_name != "pull_request" or not ctx.is_resolved:
        return False
    if ctx.author not in DEPENDENCY_BOT_AUTHORS:
        return False
    if not title_rule_exempts_ticket(author=ctx.author, title=ctx.title):
        return False
    return not ctx.carries_ticket_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--pr-author", default="")
    parser.add_argument("--pr-title", default="")
    parser.add_argument("--pr-head-ref", default="")
    parser.add_argument("--github-output", required=True, type=Path)
    args = parser.parse_args(argv)

    ctx = PullRequestContext(
        author=args.pr_author, title=args.pr_title, head_ref=args.pr_head_ref
    )
    exempt = is_declared_exemption(event_name=args.event_name, ctx=ctx)
    with args.github_output.open("a", encoding="utf-8") as out:
        out.write(f"exempt={'true' if exempt else 'false'}\n")
    if exempt:
        sys.stdout.write(
            f"Declared exemption: ticketless dependency-bot bump by {ctx.author} "
            "(PR-title rule); no ticket contract applies, so no DoD item is run.\n"
        )
    else:
        sys.stdout.write(
            "Not exempt: the PR's ticket contract is resolved and evaluated.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
