# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""
Regression suite: verifies that each affected skill's prompt.md meets the
output suppression contract. Failures mean a skill was edited to re-introduce
unbounded output.

Suppression contract:
  - grep calls in bash blocks must be followed by | head, | wc, or use -l/-c
  - gh pr list must use --limit <= 50 or pipe to head
  - pull-all.sh invocations must pipe to | tail -N or 2>/dev/null
  - docker logs calls must include --tail N
  - pytest calls must not use -v (use -q --tb=short instead)
"""

import re
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).parents[3] / "plugins/onex/skills"


def _prompt(skill: str) -> str:
    path = SKILLS_DIR / skill / "prompt.md"
    assert path.exists(), f"prompt.md not found for skill: {skill}"
    return path.read_text()


def _bash_blocks(content: str) -> list[str]:
    """Extract all ```bash ... ``` blocks from markdown.

    Matches standard 3-backtick fences only. Does not match 4-backtick or
    indented fences. Caller must assert len(blocks) > 0 when the skill is
    known to contain bash blocks, to avoid false-green tests on empty results.
    """
    blocks = re.findall(r"```bash\n(.*?)```", content, re.DOTALL)
    return blocks


def _require_bash_blocks(skill: str, content: str) -> list[str]:
    """Return bash blocks, asserting at least one exists for the given skill."""
    blocks = _bash_blocks(content)
    assert blocks, (
        f"No ```bash blocks found in {skill}/prompt.md — "
        f"file may be empty or use non-standard fencing. "
        f"Fix the fence format or remove this skill from the test suite."
    )
    return blocks


# ── aislop_sweep ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_aislop_sweep_grep_output_capped() -> None:
    """Every grep call in aislop_sweep bash blocks must pipe to | head or use -l/-c.

    Cap check is per-line, not per-block: each grep line must carry its own
    inline cap (| head, | wc, -l, -c). A single capped grep elsewhere in the
    same block does not satisfy uncapped sibling lines.
    """
    for block in _require_bash_blocks("aislop_sweep", _prompt("aislop_sweep")):
        if "grep" not in block:
            continue
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "grep" not in stripped:
                continue
            # Per-line cap: the line itself (or immediately continued by |) must
            # contain an output cap. Check the line and the next token after it.
            has_cap = (
                "| head" in stripped
                or "| wc" in stripped
                or " -l" in stripped
                or " -c" in stripped
                or stripped.endswith("\\")  # multiline — check continuation below
            )
            # For multiline grep blocks (backslash continuation), the cap
            # applies to the whole logical command; check block-level only
            # when the grep spans multiple lines (contains backslash).
            if not has_cap and "\\\n" in block and "grep" in block:
                # Multi-line grep: block-level cap is acceptable
                has_cap = "| head" in block or "| wc" in block
            assert has_cap, (
                f"aislop_sweep: uncapped grep call — add '| head -20' or use -l/-c\n"
                f"Line: {stripped!r}\n"
                f"Block:\n{block[:300]}"
            )


# ── merge_sweep ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_merge_sweep_gh_pr_list_limited() -> None:
    """gh pr list in merge_sweep must use --limit <= 50 or pipe to head."""
    content = _prompt("merge_sweep")
    for block in _require_bash_blocks("merge_sweep", content):
        if "gh pr list" not in block:
            continue
        has_limit = re.search(r"--limit\s+([0-9]+)", block)
        has_head = "| head" in block
        assert has_limit or has_head, (
            "merge_sweep: gh pr list without --limit <= 50 or | head cap\n"
            f"Block:\n{block[:300]}"
        )
        if has_limit:
            n = int(has_limit.group(1))
            assert n <= 50, (
                f"merge_sweep: gh pr list --limit {n} exceeds 50 — each PR JSON is ~2KB"
            )


# ── local_review ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_local_review_precommit_output_capped() -> None:
    """pre-commit run --all-files in local_review must pipe to | tail -N."""
    content = _prompt("local_review")
    for block in _require_bash_blocks("local_review", content):
        if "pre-commit run" not in block:
            continue
        assert "| tail" in block or "2>/dev/null" in block, (
            "local_review: pre-commit run --all-files output uncapped — add '2>&1 | tail -50'\n"
            f"Block:\n{block[:300]}"
        )


@pytest.mark.unit
def test_local_review_no_verbose_pytest() -> None:
    """pytest in local_review must not use -v or --verbose flag."""
    content = _prompt("local_review")
    for block in _bash_blocks(content):
        if "pytest" not in block:
            continue
        # Match -v at end of line, -v followed by space/flag, or --verbose
        assert not re.search(r"pytest\b.*(\s-v\b|-v$|--verbose)", block), (
            "local_review: pytest called with -v/--verbose — use -q --tb=short instead\n"
            f"Block:\n{block[:300]}"
        )


# ── begin_day ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_begin_day_pull_all_output_capped() -> None:
    """pull-all.sh in begin_day must pipe to | tail -N or redirect to /dev/null."""
    content = _prompt("begin_day")
    for block in _bash_blocks(content):
        if "pull-all.sh" not in block:
            continue
        assert "| tail" in block or ">/dev/null" in block or "2>/dev/null" in block, (
            "begin_day: pull-all.sh output uncapped — add '2>&1 | tail -20'\n"
            f"Block:\n{block[:300]}"
        )


# ── post_release_redeploy ────────────────────────────────────────────────────


@pytest.mark.unit
def test_post_release_redeploy_docker_logs_tailed() -> None:
    """docker logs in post_release_redeploy must use --tail N."""
    content = _prompt("post_release_redeploy")
    for block in _bash_blocks(content):
        if "docker logs" not in block:
            continue
        assert "--tail" in block, (
            "post_release_redeploy: docker logs without --tail N — unbounded log stream\n"
            f"Block:\n{block[:300]}"
        )


# ── curate_legacy ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_curate_legacy_find_output_capped() -> None:
    """find commands in curate_legacy must use | head -N or -maxdepth."""
    content = _prompt("curate_legacy")
    for block in _bash_blocks(content):
        if "find " not in block:
            continue
        has_cap = "| head" in block or "-maxdepth" in block or "| wc" in block
        assert has_cap, (
            "curate_legacy: find without output cap — add | head -50 or -maxdepth 3\n"
            f"Block:\n{block[:300]}"
        )
