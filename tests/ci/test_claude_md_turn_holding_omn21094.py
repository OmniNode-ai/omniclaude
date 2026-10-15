# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""CLAUDE.md records the turn-holding ruling and the true content-topic list (OMN-21094).

Plan task T0.5 of the context service plan. Each test is one acceptance
criterion's falsifier, read off the checked-in ``CLAUDE.md``:

* AC1  the "never block on Kafka" rule stays; the turn-holding section cites the
  2026-10-02 ruling verbatim, lets a replacing hook hold the turn for the
  replaced operation's contracted deadline with a fixed fallback, and says an
  observing hook never waits on Kafka.
* AC2  the bounded journal-failure rule is stated elsewhere and the
  turn-holding text does not cite it as authority.
* AC3  the emit-daemon description (the ``emit.sock`` paragraph) is gone.
* AC4  the additive-binding rule cites the 2026-10-02T14:58:44Z row, bounds every
  additive profile, and does not cite the replacement decision as its authority.
* AC5  the "full prompts" rule names every other command topic the T0.6 audit
  lists as carrying full prompts, each with the access control it read.

Every check runs against a text, so each one is also run against a synthetic
violating text (the positive control for a zero).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

CLAUDE_MD = Path(__file__).resolve().parents[2] / "CLAUDE.md"

TURN_HOLDING_HEADING = "### Turn-holding"
CONTENT_TOPICS_HEADING = "### Command topics that carry full prompts"

REPLACEMENT_RULING_STAMP = "2026-10-02T11:28:23Z"
REPLACEMENT_RULING_WORDS = (
    "yes, for compact absolutely. the current compact already does this."
)
ADDITIVE_RULING_STAMP = "2026-10-02T14:58:44Z"

# Every command topic that the T0.6 content transport audit
# (knowledge-base beta/deep-dives/2026-10-15-content-transport-audit.md,
# sections 4.1 to 4.3 and 11.4) lists as carrying a prompt, a request text or a
# full ledger row today. "content-captured" is the one the old rule named.
CONTENT_COMMAND_TOPICS = (
    "onex.cmd.omniintelligence.content-captured.v1",
    "onex.cmd.omniintelligence.tool-content.v1",
    "onex.cmd.omniintelligence.compliance-evaluate.v1",
    "onex.cmd.omnimarket.delegate-skill.v1",
    "onex.cmd.omnibase-infra.delegation-request.v1",
    "onex.cmd.omnibase-infra.delegation-routing-request.v1",
    "onex.cmd.omnibase-infra.delegation-inference-request.v1",
    "onex.cmd.omnibase-infra.delegation-quality-gate-request.v1",
    "onex.cmd.omnimarket.delegation-acceptance-judge-requested.v1",
    "onex.cmd.omnimarket.delegation-execute.v1",
    "onex.cmd.omnimarket.delegation-fanout-requested.v1",
    "onex.cmd.omnibase-infra.llm-inference-request.v1",
    "onex.cmd.omnibase-infra.remote-agent-invoke.v1",
    "onex.cmd.omninode.routing-requested.v1",
    "onex.cmd.omnimarket.operator-capture-decision-requested.v1",
    "onex.cmd.omnimarket.work-ledger-append-requested.v1",
    "onex.cmd.omnimarket.work-ledger-emit.v1",
    "onex.cmd.omniclaude.delegate-task.v1",
)


def _read() -> str:
    return CLAUDE_MD.read_text(encoding="utf-8")


def _section(text: str, heading: str) -> str:
    """The body under ``heading`` up to the next heading of the same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.find(heading)
    if start == -1:
        return ""
    body = text[start + len(heading) :]
    stop = re.search(rf"^#{{1,{level}}} ", body, flags=re.MULTILINE)
    return body[: stop.start()] if stop else body


def _paragraph(section: str, lead: str) -> str:
    """The paragraph of ``section`` that opens with the bold lead-in ``lead``."""
    for block in section.split("\n\n"):
        if block.strip().startswith(lead):
            return " ".join(block.split())
    return ""


def ac1_failures(text: str) -> list[str]:
    found: list[str] = []
    if "never block** on Kafka" not in text:
        found.append("the never-block-on-Kafka invariant row is gone")
    section = _section(text, TURN_HOLDING_HEADING)
    if not section:
        return [*found, "the turn-holding section is absent"]
    replacing = _paragraph(section, "**Replacing")
    observing = _paragraph(section, "**Observing")
    if (
        REPLACEMENT_RULING_WORDS not in replacing
        or REPLACEMENT_RULING_STAMP not in replacing
    ):
        found.append(
            "the replacement paragraph does not cite the ruling verbatim with its stamp"
        )
    if "contracted deadline" not in replacing or "fixed fallback" not in replacing:
        found.append(
            "the replacement paragraph lacks the contracted deadline or fixed fallback"
        )
    if not re.search(
        r"only observes\W.*never waits on Kafka", observing, flags=re.DOTALL
    ):
        found.append(
            "the observing paragraph does not say an observing hook never waits on Kafka"
        )
    return found


def ac2_failures(text: str) -> list[str]:
    found: list[str] = []
    section = _section(text, TURN_HOLDING_HEADING)
    if not section:
        return [
            "the turn-holding section is absent, so its separation from the "
            "journal-failure rule cannot be shown"
        ]
    if "OMN-20110" in section:
        found.append("the turn-holding section cites OMN-20110")
    outside = text.replace(section, "") if section else text
    if "OMN-20110" not in outside:
        found.append(
            "the bounded journal-failure rule (OMN-20110) is not stated anywhere else"
        )
    return found


def ac3_failures(text: str) -> list[str]:
    return [
        f"line {n}: emit.sock"
        for n, line in enumerate(text.splitlines(), 1)
        if "emit.sock" in line
    ]


def ac4_failures(text: str) -> list[str]:
    found: list[str] = []
    additive = _paragraph(_section(text, TURN_HOLDING_HEADING), "**Additive")
    if not additive:
        return ["the additive paragraph is absent"]
    if ADDITIVE_RULING_STAMP not in additive:
        found.append(
            "the additive paragraph does not cite the 2026-10-02T14:58:44Z row"
        )
    for budget in ("5 s", "3 s", "500 ms"):
        if budget not in additive:
            found.append(
                f"the additive paragraph leaves a profile unbounded: no {budget}"
            )
    for needed in ("journalled miss record", "injects nothing"):
        if needed not in additive:
            found.append(f"the additive paragraph lacks '{needed}'")
    if re.search(r"\bD2\b", additive) or REPLACEMENT_RULING_STAMP in additive:
        found.append(
            "the additive paragraph cites the replacement decision as its authority"
        )
    return found


def ac5_failures(text: str) -> list[str]:
    found: list[str] = []
    if "Full prompts go **only** to" in text:
        found.append("the single-family claim is still in CLAUDE.md")
    section = _section(text, CONTENT_TOPICS_HEADING)
    if not section:
        return [*found, "the content-topics section is absent"]
    rows = {line for line in section.splitlines() if line.startswith("|")}
    for topic in CONTENT_COMMAND_TOPICS:
        row = next((r for r in rows if f"`{topic}`" in r), None)
        if row is None:
            found.append(f"{topic}: not listed")
        elif row.count("|") < 4 or not row.split("|")[-2].strip():
            found.append(f"{topic}: no access-control reading")
    return found


@pytest.mark.parametrize(
    "check",
    [ac1_failures, ac2_failures, ac3_failures, ac4_failures, ac5_failures],
    ids=["AC1", "AC2", "AC3", "AC4", "AC5"],
)
def test_claude_md_meets_criterion(check) -> None:
    assert check(_read()) == []


def test_claude_md_exists() -> None:
    assert CLAUDE_MD.is_file()


# Positive controls: each check must fire on a text that violates its criterion.
_BAD = (
    "| Hook scripts must **never block** on Kafka | x |\n"
    "Emit daemon: hook -> `~/.claude/emit.sock`.\n"
    "| Full prompts go **only** to `onex.cmd.omniintelligence.*` | x |\n"
    "Failure Modes mentions nothing.\n"
    "\n### Turn-holding\n\n"
    "**Replacing** a thing (OMN-20110).\n\n"
    "**Observing** hooks may wait.\n\n"
    "**Additive** hooks wait, citing D2.\n"
)


@pytest.mark.parametrize(
    "check",
    [ac1_failures, ac2_failures, ac3_failures, ac4_failures, ac5_failures],
    ids=["AC1", "AC2", "AC3", "AC4", "AC5"],
)
def test_check_fires_on_violating_text(check) -> None:
    assert check(_BAD) != []
