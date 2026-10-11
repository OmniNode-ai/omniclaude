# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for the PR-body stamp-preservation admission gate (OMN-18335).

Written red first: the first run of this file was a collection error against an
absent decision core, recorded on OMN-18335.

The gate refuses a body-REPLACING pull-request edit whose replacement text drops
an evidence-source line the live body currently carries. Measured cause (plan of
record, section 2 correction 1): the description is a surface a lane overwrites
wholesale with no compare-and-swap, and it silently lost that line on four of the
last five misses, twice after the pull request had already merged. One lost line
makes every downstream reader conclude no evidence exists.

There is deliberately no case asserting that some spelling of "I meant to remove
it" is admitted. The remedy is the paste the refusal prints, not a bypass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.hooks._bash_guard_registration import is_live_on_bash_matcher

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
HOOK_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_pr_body_stamp_guard.sh"
)
POLICY_PATH = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "config" / "pr_body_stamp_policy.json"
)

sys.path.insert(0, str(LIB_DIR))

from pr_body_stamp_guard import (  # noqa: E402
    GATE_BIT_NAME,
    Policy,
    PolicyError,
    check_bash_command,
    load_policy,
    parse_pr_body_edits,
    render_block_reason,
    stamp_lines,
    strip_noncanonical_regions,
    watcher_record_reader,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

#: A live description carrying the stamp line the gate protects. The stamp
#: value is a FIXTURE and binds nothing.
STAMP = "Evidence-Source: OCC#9999"

LIVE_BODY = f"""## Summary

Fixture product pull request body.

{STAMP}
Evidence-Ticket: OMN-18335
"""

#: The same body rewritten by hand, with the evidence block dropped. This is the
#: exact loss the plan measured.
LOSSY_BODY = """## Summary

Fixture product pull request body, rewritten.
"""

RETAINING_BODY = f"""## Summary

Fixture product pull request body, rewritten but careful.

{STAMP}
Evidence-Ticket: OMN-18335
"""

NO_STAMP_BODY = "## Summary\n\nA pull request that never carried a stamp.\n"


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


def reader_for(bodies: dict[str, str]):
    """A live-body reader over a MUTABLE mapping keyed by ``owner/repo#number``.

    Mutable on purpose: AC4 requires the comparison to be against the body as
    the platform holds it at evaluation time, so the test changes the mapping
    after the reader is built and asserts the later value is the one judged.
    """

    def _read(edit) -> str | None:
        return bodies.get(f"{edit.repo}#{edit.selector}")

    return _read


def _shq(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


# --------------------------------------------------------------------------
# AC1 -- a lossy description-replacing edit is refused
# --------------------------------------------------------------------------


def test_lossy_body_edit_is_refused(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings, "a body edit dropping a live stamp line must be refused"
    assert findings[0].kind == "dropped_stamp"


def test_body_file_edit_is_refused(policy: Policy, tmp_path: Path) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(LOSSY_BODY, encoding="utf-8")
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body-file {body_file}"
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "dropped_stamp"


def test_gh_api_patch_is_refused(policy: Policy) -> None:
    """The REST path is the one a lane reaches for on a MERGED pull request.

    ``gh pr edit`` refuses to touch a merged pull request, so the REST PATCH is
    exactly the shape used where the plan measured two of its four losses.
    """
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = (
        "gh api -X PATCH repos/OmniNode-ai/omniclaude/pulls/42 "
        f"-f body={_shq(LOSSY_BODY)}"
    )
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "dropped_stamp"


def test_gh_api_patch_long_method_flag_is_refused(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = (
        "gh api --method PATCH repos/OmniNode-ai/omniclaude/pulls/42 "
        f"--raw-field body={_shq(LOSSY_BODY)}"
    )
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "dropped_stamp"


# --------------------------------------------------------------------------
# AC2 -- the refusal prints the dropped line verbatim
# --------------------------------------------------------------------------


def test_refusal_prints_the_dropped_line_verbatim(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    findings = check_bash_command(command, policy, reader_for(bodies))
    reason = render_block_reason(findings)
    assert STAMP in reason, (
        "the remedy must be one paste, so the exact dropped line has to appear "
        "in the refusal"
    )


# --------------------------------------------------------------------------
# AC3 -- positive controls: ordinary edits pass untouched
# --------------------------------------------------------------------------


def test_edit_retaining_the_line_passes(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = (
        f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(RETAINING_BODY)}"
    )
    assert check_bash_command(command, policy, reader_for(bodies)) == []


def test_edit_to_a_pr_that_never_carried_a_stamp_passes(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": NO_STAMP_BODY}
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    assert check_bash_command(command, policy, reader_for(bodies)) == []


def test_read_only_gh_commands_are_never_gated(policy: Policy) -> None:
    """Reads are outside every shape -- they are not allowlisted, they simply
    name no body-replacing flag."""
    for command in (
        "gh pr view 42 --repo OmniNode-ai/omniclaude --json body",
        "gh pr list --repo OmniNode-ai/omniclaude",
        "gh api repos/OmniNode-ai/omniclaude/pulls/42",
        "gh pr edit 42 --repo OmniNode-ai/omniclaude --add-label ready",
        "gh pr comment 42 --repo OmniNode-ai/omniclaude --body hello",
    ):
        assert check_bash_command(command, policy, reader_for({})) == [], command


def test_a_quoted_mention_of_the_shape_is_not_an_edit(policy: Policy) -> None:
    """the workspace CLAUDE.md rule 15: prose that merely NAMES a trigger must not
    fire the gate. Token matching by program is what keeps that true."""
    command = "echo 'gh pr edit 42 --body whatever'"
    assert check_bash_command(command, policy, reader_for({})) == []


def test_a_stamp_inside_a_fenced_block_is_not_protected(policy: Policy) -> None:
    """A stamp quoted as an example is DOCUMENTATION, never a declaration.

    Protecting it would refuse every meta pull request about this gate, and a
    guard whose false refusals outnumber its true ones gets routed around.
    """
    quoted = f"## Summary\n\n```\n{STAMP}\n```\n"
    bodies = {"OmniNode-ai/omniclaude#42": quoted}
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    assert check_bash_command(command, policy, reader_for(bodies)) == []


# --------------------------------------------------------------------------
# Unexpanded shell arguments -- a body the guard cannot SEE is not a body it
# may accuse the author of having emptied
# --------------------------------------------------------------------------


def test_a_cat_substitution_body_is_read_from_the_named_file(
    policy: Policy, tmp_path: Path
) -> None:
    """``--body "$(cat path)"`` is how a composed body is actually passed.

    The shell has not expanded it by the time the guard sees the command, so a
    guard that could not read it would refuse the single most common
    legitimate spelling -- and get switched off.
    """
    body_file = tmp_path / "body.md"
    body_file.write_text(RETAINING_BODY, encoding="utf-8")
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f'gh pr edit 42 --repo OmniNode-ai/omniclaude --body "$(cat {body_file})"'
    assert check_bash_command(command, policy, reader_for(bodies)) == []


def test_a_lossy_cat_substitution_is_still_refused(
    policy: Policy, tmp_path: Path
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(LOSSY_BODY, encoding="utf-8")
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f'gh pr edit 42 --repo OmniNode-ai/omniclaude --body "$(cat {body_file})"'
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "dropped_stamp"


def test_a_backtick_cat_substitution_is_read_too(
    policy: Policy, tmp_path: Path
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text(RETAINING_BODY, encoding="utf-8")
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = f'gh pr edit 42 --repo OmniNode-ai/omniclaude --body "`cat {body_file}`"'
    assert check_bash_command(command, policy, reader_for(bodies)) == []


def test_an_unresolvable_substitution_is_unreadable_not_a_dropped_line(
    policy: Policy,
) -> None:
    """The distinction is the whole point: the guard did not SEE the body.

    Reporting a dropped line here would send the author hunting for a line
    they never removed, and the remedy the message names has to be one they
    can actually take.
    """
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = 'gh pr edit 42 --repo OmniNode-ai/omniclaude --body "$BODY"'
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "unreadable_new_body"
    assert "--body-file" in render_block_reason(findings)


# --------------------------------------------------------------------------
# AC4 -- the live body is read at evaluation time, not cached or assumed
# --------------------------------------------------------------------------


def test_live_body_is_read_at_evaluation_time(policy: Policy) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": NO_STAMP_BODY}
    read = reader_for(bodies)
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    # Constructed against a body with no stamp; the platform then acquires one.
    bodies["OmniNode-ai/omniclaude#42"] = LIVE_BODY
    findings = check_bash_command(command, policy, read)
    assert findings and findings[0].kind == "dropped_stamp", (
        "the guard judged a stale body; the comparison must be against the "
        "description as the platform currently holds it"
    )


def test_a_line_gained_between_construction_and_evaluation_is_not_ignored(
    policy: Policy,
) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    read = reader_for(bodies)
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    # The reverse direction: the stamp is removed by somebody else first, so
    # this edit loses nothing and must pass.
    bodies["OmniNode-ai/omniclaude#42"] = NO_STAMP_BODY
    assert check_bash_command(command, policy, read) == []


# --------------------------------------------------------------------------
# Fail-closed boundary
# --------------------------------------------------------------------------


def test_unreadable_new_body_is_refused(policy: Policy, tmp_path: Path) -> None:
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    missing = tmp_path / "absent.md"
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body-file {missing}"
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "unreadable_new_body"


def test_body_from_stdin_is_refused(policy: Policy) -> None:
    """``--body-file -`` hands the gate a body it structurally cannot read."""
    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    command = "gh pr edit 42 --repo OmniNode-ai/omniclaude --body-file -"
    findings = check_bash_command(command, policy, reader_for(bodies))
    assert findings and findings[0].kind == "unreadable_new_body"


def test_unreadable_live_body_is_refused(policy: Policy) -> None:
    command = f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(LOSSY_BODY)}"
    findings = check_bash_command(command, policy, lambda edit: None)
    assert findings and findings[0].kind == "unreadable_live_body", (
        "a live read that FAILED is evidence of nothing; it must never be "
        "converted into evidence that there was no stamp (rule 16)"
    )


def test_untokenisable_command_is_refused(policy: Policy) -> None:
    command = "gh pr edit 42 --body 'unbalanced"
    findings = check_bash_command(command, policy, reader_for({}))
    assert findings and findings[0].kind == "untokenisable"


def test_non_string_command_is_refused(policy: Policy) -> None:
    findings = check_bash_command(None, policy, reader_for({}))
    assert findings and findings[0].kind == "non_string_command"


# --------------------------------------------------------------------------
# One vocabulary
# --------------------------------------------------------------------------


def test_stamp_pattern_is_the_repo_canonical_one() -> None:
    """The gate may not own a second spelling of the stamp line.

    Pinned byte-for-byte against ``check_occ_companion_merged.EVIDENCE_SOURCE_RE``,
    the omniclaude-side authority the OCC companion gate already reads with.
    Changing one without the other turns this red.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "ci"))
    from check_occ_companion_merged import EVIDENCE_SOURCE_RE  # noqa: PLC0415

    policy = load_policy(POLICY_PATH)
    assert policy.stamp_line.pattern == EVIDENCE_SOURCE_RE.pattern
    assert policy.stamp_line.flags == EVIDENCE_SOURCE_RE.flags


def test_every_canonical_rendered_stamp_matches_the_pattern() -> None:
    """Positive control across the shared contract, when it is importable.

    ``omnibase_compat`` renders the line every producer writes. Both of its
    source kinds must be recognised by this gate, or the gate protects only
    half the vocabulary.
    """
    compat = pytest.importorskip("omnibase_compat.contracts.pr_occ_stamp")
    policy = load_policy(POLICY_PATH)
    for rendered in ("Evidence-Source: OCC#1234", "Evidence-Source: 0a1b2c3d4e5f"):
        assert stamp_lines(rendered, policy) == [rendered], rendered
    assert hasattr(compat, "parse_pr_occ_metadata_stamp")


def test_strip_is_idempotent() -> None:
    body = f"a\n```\n{STAMP}\n```\n> quoted\n{STAMP}\n"
    once = strip_noncanonical_regions(body)
    assert strip_noncanonical_regions(once) == once


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def test_parse_reads_repo_and_selector(policy: Policy) -> None:
    edits = parse_pr_body_edits(
        "gh pr edit 42 -R OmniNode-ai/omniclaude --body x", policy
    )
    assert len(edits) == 1
    assert edits[0].repo == "OmniNode-ai/omniclaude"
    assert edits[0].selector == "42"


def test_parse_reads_a_pr_url_selector(policy: Policy) -> None:
    edits = parse_pr_body_edits(
        "gh pr edit https://github.com/OmniNode-ai/omniclaude/pull/42 --body x",
        policy,
    )
    assert len(edits) == 1
    assert edits[0].selector == "https://github.com/OmniNode-ai/omniclaude/pull/42"


def test_parse_finds_an_edit_in_a_later_segment(policy: Policy) -> None:
    edits = parse_pr_body_edits(
        "git status && gh pr edit 42 -R OmniNode-ai/omniclaude --body x", policy
    )
    assert len(edits) == 1


def test_body_file_variable_from_the_hook_environment_is_resolved(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unchanged inherited variable names the same file the shell uploads."""
    body_file = tmp_path / "body.md"
    body_file.write_text("the new body\n", encoding="utf-8")
    monkeypatch.setenv("OMN19229_B", str(body_file))
    (edit,) = parse_pr_body_edits(
        'gh pr edit 42 -R OmniNode-ai/omniclaude --body-file "$OMN19229_B"', policy
    )
    assert edit.new_body == body_file.read_text()
    assert edit.unreadable_reason is None


def test_body_file_under_home_is_expanded(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "body.md").write_text("home body\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    (edit,) = parse_pr_body_edits("gh pr edit 42 --body-file ~/body.md", policy)
    assert edit.new_body == "home body\n", edit.unreadable_reason


def test_body_file_variable_assigned_in_the_command_is_expanded(
    policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("assigned body\n", encoding="utf-8")
    monkeypatch.delenv("OMN19229_B", raising=False)
    (edit,) = parse_pr_body_edits(
        f'OMN19229_B={body_file}; gh pr edit 42 --body-file "$OMN19229_B"', policy
    )
    assert edit.new_body == "assigned body\n", edit.unreadable_reason
    (edit,) = parse_pr_body_edits(
        f'OMN19229_B={body_file}; gh pr edit 42 --body "$(cat "$OMN19229_B")"',
        policy,
    )
    assert edit.new_body == "assigned body\n", edit.unreadable_reason


def test_unset_body_file_variable_is_unreadable_not_guessed(
    policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OMN19229_B", raising=False)
    (edit,) = parse_pr_body_edits('gh pr edit 42 --body-file "$OMN19229_B"', policy)
    assert edit.new_body is None
    assert edit.unreadable_reason is not None
    assert "`$OMN19229_B` is unset" in edit.unreadable_reason


@pytest.mark.parametrize(
    "command",
    [
        'read OMN19229_B; gh pr edit 5 --body-file "$OMN19229_B"',
        'cd {tmp} && gh pr edit 5 --body-file "$PWD/new.md"',
    ],
)
def test_a_variable_the_command_changes_is_not_read_from_the_environment(
    command: str, policy: Policy, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment holds the value from BEFORE the command; reading it
    would judge a file gh never uploads. Unreadable, as before AC4."""
    stale = tmp_path / "stale.md"
    stale.write_text(LIVE_BODY, encoding="utf-8")
    new = tmp_path / "new.md"
    new.write_text("dropped the stamp\n", encoding="utf-8")
    monkeypatch.setenv("OMN19229_B", str(stale))
    monkeypatch.setenv("PWD", str(tmp_path / "elsewhere"))
    (edit,) = parse_pr_body_edits(command.format(new=new, tmp=tmp_path), policy)
    assert edit.new_body is None, command
    assert edit.unreadable_reason is not None


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


def test_policy_has_no_escape_entry() -> None:
    raw = POLICY_PATH.read_text(encoding="utf-8")
    lowered = raw.lower()
    for escape in ("allow_all", "exempt", "wildcard", "bypass"):
        assert f'"{escape}"' not in lowered, (
            f"the policy names an escape entry ({escape}); destroying the "
            "evidence line is the defect, so there is no sanctioned spelling"
        )


def test_malformed_policy_raises_rather_than_defaulting(tmp_path: Path) -> None:
    bad = tmp_path / "policy.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


def test_policy_missing_pattern_raises(tmp_path: Path) -> None:
    bad = tmp_path / "policy.json"
    bad.write_text(json.dumps({"gh_pr_edit": {}}), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_policy(bad)


# --------------------------------------------------------------------------
# Hook script
# --------------------------------------------------------------------------


def _run_hook(
    payload: dict[str, object], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    base.update(env)
    return subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=base,
        timeout=120,
        check=False,
    )


@pytest.fixture
def fake_gh(tmp_path: Path) -> Path:
    """A `gh` stand-in on PATH whose `pr view --json body` returns LIVE_BODY.

    The hook must never reach the network in a test, and a stub proves the
    guard shells out to a READ rather than assuming a body.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "pr" && "$2" == "view" ]]; then\n'
        f"  cat <<'BODY'\n{LIVE_BODY}BODY\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bindir


def test_hook_script_blocks_a_lossy_edit(tmp_path: Path, fake_gh: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "gh pr edit 42 --repo OmniNode-ai/omniclaude "
                    f"--body {_shq(LOSSY_BODY)}"
                )
            },
        },
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert STAMP in payload["reason"]


def test_hook_script_allows_a_retaining_edit(tmp_path: Path, fake_gh: Path) -> None:
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "gh pr edit 42 --repo OmniNode-ai/omniclaude "
                    f"--body {_shq(RETAINING_BODY)}"
                )
            },
        },
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_script_passes_unrelated_traffic(tmp_path: Path) -> None:
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        {
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_script_refuses_malformed_json_carrying_the_vocabulary(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        ["bash", str(HOOK_SCRIPT)],
        input='{"tool_name": "Bash", "tool_input": {"command": "gh pr edit 42 --body',
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
        timeout=120,
        check=False,
    )
    assert result.returncode == 2, result.stdout + result.stderr


def test_disabled_hook_allows_and_logs(tmp_path: Path, fake_gh: Path) -> None:
    """A deliberate disable is allowed, and it is LOGGED, never silent."""
    log = tmp_path / "hooks.log"
    result = _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "gh pr edit 42 --repo OmniNode-ai/omniclaude "
                    f"--body {_shq(LOSSY_BODY)}"
                )
            },
        },
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
            "ONEX_HOOKS_MASK": "0x0",
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert log.exists(), "a disabled run must leave a log line"
    text = log.read_text(encoding="utf-8")
    assert "DISABLED" in text
    assert GATE_BIT_NAME in text


def test_hook_script_logs_a_refusal(tmp_path: Path, fake_gh: Path) -> None:
    log = tmp_path / "hooks.log"
    _run_hook(
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": (
                    "gh pr edit 42 --repo OmniNode-ai/omniclaude "
                    f"--body {_shq(LOSSY_BODY)}"
                )
            },
        },
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
            "ONEX_HOOK_LOG": str(log),
        },
    )
    assert "BLOCKED" in log.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Registration
# --------------------------------------------------------------------------


def test_hook_is_registered_on_the_bash_matcher() -> None:
    # OMN-20118: registered through the one Bash guards entrypoint, which
    # sources this guard in its former order.
    assert is_live_on_bash_matcher("pre_tool_use_pr_body_stamp_guard.sh"), (
        "the guard must be live on the Bash matcher"
    )


def test_borrowed_bit_namesake_stays_unregistered() -> None:
    """The borrow is only safe while the namesake is not itself registered.

    Asserted over the PARSED registration, never over the raw file text: this
    file's own carve-out record names the namesake in prose, and a
    substring check would read documentation about the rule as a breach of it
    (the workspace CLAUDE.md rule 15, the OCC#7213 shape).
    """
    hooks = json.loads(
        (REPO_ROOT / "plugins" / "onex" / "hooks" / "hooks.json").read_text(
            encoding="utf-8"
        )
    )["hooks"]
    registered = {
        Path(entry.get("command", "")).name
        for groups in hooks.values()
        for group in groups
        for entry in group.get("hooks", [])
    }
    assert "pre_tool_use_branch_protection_guard.sh" not in registered, (
        "the namesake script is registered again, so "
        f"`onex hooks disable {GATE_BIT_NAME}` would disable two controls. "
        "Give the stamp guard its own bit before re-registering it."
    )


def test_hook_is_declared_in_the_typed_inventory() -> None:
    inventory = (
        REPO_ROOT / "plugins" / "onex" / "hooks" / "contracts" / "hook_inventory.yaml"
    ).read_text(encoding="utf-8")
    assert "pre_tool_use_pr_body_stamp_guard.sh" in inventory
    assert "OMN-18335" in inventory


def test_hook_is_classified_in_the_distribution_manifest() -> None:
    manifest = (REPO_ROOT / "plugins" / "distribution_manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert "hooks/scripts/pre_tool_use_pr_body_stamp_guard.sh" in manifest


def test_guard_never_spells_a_gate_trigger_in_its_own_prose() -> None:
    """the workspace CLAUDE.md rule 15, applied to the guard's own source.

    A file about the stamp line has to name the line in code. It must not
    additionally spell a MERGE-HOLD phrase or a skip-token prefix, either of
    which a body-parsing gate would read as a declaration.
    """
    for path in (
        LIB_DIR / "pr_body_stamp_guard.py",
        HOOK_SCRIPT,
        POLICY_PATH,
    ):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\[skip-[a-z]", text, re.IGNORECASE), path
        assert not re.search(r"do[ -]not[ -]merge", text, re.IGNORECASE), path


# --------------------------------------------------------------------------
# OMN-20911 -- the PR watcher's record is the second source of the live body
# --------------------------------------------------------------------------
#
# A lane's gh shim refuses every GitHub read, so the guard's own `gh pr view
# --json body` always fails there and, read alone, refuses every body edit. The
# watcher's state file holds each open PR's live body; the guard reads it only
# when the gh read fails, and only while the record can be trusted.

WATCHER_NOW = datetime(2026, 10, 11, 3, 0, 0, tzinfo=UTC)
WATCHER_PR = "omniclaude#42"
WATCHER_HEAD_REF = "lane/omn-20911-fixture"


def _stamp_time(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_watcher_state(
    path: Path,
    *,
    body: str | None = LIVE_BODY,
    tick_age_s: int = 60,
    head_sha: str = "a" * 40,
    state: str = "OPEN",
    key: str = WATCHER_PR,
    schema: int = 1,
) -> Path:
    facts: dict[str, object] = {
        "repo": "omniclaude",
        "number": 42,
        "state": state,
        "head_ref": WATCHER_HEAD_REF,
        "head_sha": head_sha,
        "updated_at": _stamp_time(WATCHER_NOW - timedelta(seconds=tick_age_s)),
    }
    if body is not None:
        facts["body"] = body
    path.write_text(
        json.dumps(
            {
                "schema": schema,
                "last_tick": _stamp_time(WATCHER_NOW - timedelta(seconds=tick_age_s)),
                "prs": {key: {"facts": facts}},
            }
        ),
        encoding="utf-8",
    )
    return path


def _watcher(policy: Policy, state: Path, cwd: str | None = None):
    return watcher_record_reader(
        policy,
        cwd=cwd,
        environ={"ONEX_PR_WATCHER_STATE": str(state)},
        now=lambda: WATCHER_NOW,
    )


def _edit_command(body: str) -> str:
    return f"gh pr edit 42 --repo OmniNode-ai/omniclaude --body {_shq(body)}"


def _refused_gh_read(edit) -> None:
    return None


def test_refused_gh_read_and_fresh_record_drops_stamp_is_refused(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json")
    findings = check_bash_command(
        _edit_command(LOSSY_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert [f.kind for f in findings] == ["dropped_stamp"]
    assert findings[0].dropped_lines == (STAMP,)
    reason = render_block_reason(findings)
    assert STAMP in reason
    assert "PR watcher record omniclaude#42" in reason, (
        "the refusal must name the source it compared against"
    )


def test_refused_gh_read_and_fresh_record_keeping_stamp_is_admitted(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json")
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert findings == []


def test_refused_gh_read_and_record_without_a_stamp_admits_any_body(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json", body=NO_STAMP_BODY)
    findings = check_bash_command(
        _edit_command(LOSSY_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert findings == []


def test_stale_record_is_refused_as_before(policy: Policy, tmp_path: Path) -> None:
    # One second past the watcher's freshness window.
    state = _write_watcher_state(tmp_path / "state.json", tick_age_s=481)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]
    assert "481" in findings[0].detail and "480" in findings[0].detail


def test_record_at_the_edge_of_the_window_is_still_fresh(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json", tick_age_s=480)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert findings == []


def test_missing_state_file_is_refused_as_before(
    policy: Policy, tmp_path: Path
) -> None:
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, tmp_path / "absent.json"),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]
    assert "absent.json" in findings[0].detail


def test_pr_absent_from_the_state_is_refused_as_before(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json", key="omniclaude#7")
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]
    assert "omniclaude#42" in findings[0].detail


@pytest.mark.parametrize(
    "overrides",
    [
        {"body": None},
        {"state": "MERGED"},
        {"state": "CLOSED"},
        {"schema": 2},
    ],
    ids=["no-body", "merged", "closed", "schema"],
)
def test_untrustworthy_record_is_refused_as_before(
    policy: Policy, tmp_path: Path, overrides: dict[str, Any]
) -> None:
    state = _write_watcher_state(tmp_path / "state.json", **overrides)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]


def test_unparseable_state_is_refused_as_before(policy: Policy, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{not json", encoding="utf-8")
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        watcher_body=_watcher(policy, state),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]


def test_working_gh_read_never_consults_the_record(
    policy: Policy, tmp_path: Path
) -> None:
    """A working live read decides alone: behaviour is unchanged (AC4)."""

    def _must_not_be_called(edit):
        raise AssertionError("the watcher record was read although gh answered")

    bodies = {"OmniNode-ai/omniclaude#42": LIVE_BODY}
    lossy = check_bash_command(
        _edit_command(LOSSY_BODY),
        policy,
        reader_for(bodies),
        watcher_body=_must_not_be_called,
    )
    assert [f.kind for f in lossy] == ["dropped_stamp"]
    assert "live gh read" in render_block_reason(lossy)
    kept = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        reader_for(bodies),
        watcher_body=_must_not_be_called,
    )
    assert kept == []


def test_no_watcher_reader_wired_is_refused_as_before(policy: Policy) -> None:
    findings = check_bash_command(
        _edit_command(RETAINING_BODY), policy, _refused_gh_read
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]


def test_record_is_found_from_a_pull_request_url(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json")
    command = (
        "gh pr edit https://github.com/OmniNode-ai/omniclaude/pull/42 "
        f"--body {_shq(LOSSY_BODY)}"
    )
    findings = check_bash_command(
        command, policy, _refused_gh_read, watcher_body=_watcher(policy, state)
    )
    assert [f.kind for f in findings] == ["dropped_stamp"]


def test_record_is_not_used_for_another_organisation(
    policy: Policy, tmp_path: Path
) -> None:
    state = _write_watcher_state(tmp_path / "state.json")
    command = f"gh pr edit 42 --repo someone-else/omniclaude --body {_shq(LOSSY_BODY)}"
    findings = check_bash_command(
        command, policy, _refused_gh_read, watcher_body=_watcher(policy, state)
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]


# -- the newest push the guard can see ---------------------------------------


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


def _git(repo: Path, *args: str) -> str:
    identity = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env({**os.environ, **identity}),
    ).stdout.strip()


@pytest.fixture
def pushed_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A checkout of omniclaude with two commits; returns (path, first, second)."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "remote", "add", "origin", "git@github.com:OmniNode-ai/omniclaude.git")
    (repo / "f").write_text("1", encoding="utf-8")
    _git(repo, "add", "f")
    _git(repo, "commit", "-q", "-m", "one")
    first = _git(repo, "rev-parse", "HEAD")
    (repo / "f").write_text("2", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "two")
    second = _git(repo, "rev-parse", "HEAD")
    return repo, first, second


def test_record_behind_a_visible_push_is_refused(
    policy: Policy, tmp_path: Path, pushed_repo: tuple[Path, str, str]
) -> None:
    repo, first, second = pushed_repo
    _git(repo, "update-ref", f"refs/remotes/origin/{WATCHER_HEAD_REF}", second)
    state = _write_watcher_state(tmp_path / "state.json", head_sha=first)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        cwd=str(repo),
        watcher_body=_watcher(policy, state, cwd=str(repo)),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]
    assert first[:12] in findings[0].detail and second[:12] in findings[0].detail


def test_record_at_the_visible_push_is_admitted(
    policy: Policy, tmp_path: Path, pushed_repo: tuple[Path, str, str]
) -> None:
    repo, _first, second = pushed_repo
    _git(repo, "update-ref", f"refs/remotes/origin/{WATCHER_HEAD_REF}", second)
    state = _write_watcher_state(tmp_path / "state.json", head_sha=second)
    findings = check_bash_command(
        _edit_command(LOSSY_BODY),
        policy,
        _refused_gh_read,
        cwd=str(repo),
        watcher_body=_watcher(policy, state, cwd=str(repo)),
    )
    assert [f.kind for f in findings] == ["dropped_stamp"]


def test_record_ahead_of_the_visible_push_is_admitted(
    policy: Policy, tmp_path: Path, pushed_repo: tuple[Path, str, str]
) -> None:
    repo, first, second = pushed_repo
    _git(repo, "update-ref", f"refs/remotes/origin/{WATCHER_HEAD_REF}", first)
    state = _write_watcher_state(tmp_path / "state.json", head_sha=second)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        cwd=str(repo),
        watcher_body=_watcher(policy, state, cwd=str(repo)),
    )
    assert findings == []


def test_record_head_unknown_to_the_checkout_is_refused(
    policy: Policy, tmp_path: Path, pushed_repo: tuple[Path, str, str]
) -> None:
    repo, _first, second = pushed_repo
    _git(repo, "update-ref", f"refs/remotes/origin/{WATCHER_HEAD_REF}", second)
    state = _write_watcher_state(tmp_path / "state.json", head_sha="b" * 40)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        cwd=str(repo),
        watcher_body=_watcher(policy, state, cwd=str(repo)),
    )
    assert [f.kind for f in findings] == ["unreadable_live_body"]


def test_checkout_that_has_seen_no_push_does_not_block_the_record(
    policy: Policy, tmp_path: Path, pushed_repo: tuple[Path, str, str]
) -> None:
    repo, first, _second = pushed_repo
    state = _write_watcher_state(tmp_path / "state.json", head_sha=first)
    findings = check_bash_command(
        _edit_command(RETAINING_BODY),
        policy,
        _refused_gh_read,
        cwd=str(repo),
        watcher_body=_watcher(policy, state, cwd=str(repo)),
    )
    assert findings == []


# -- the hook as wired -------------------------------------------------------


@pytest.fixture
def refusing_gh(tmp_path: Path) -> Path:
    """A `gh` that refuses every read, as a lane's shim does (OMN-20911)."""
    bindir = tmp_path / "refusing-bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/bash\necho 'gh: reads are refused from a lane' >&2\nexit 1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bindir


def test_hook_script_verifies_an_edit_from_the_watcher_record(
    tmp_path: Path, refusing_gh: Path
) -> None:
    now = datetime.now(UTC)
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "schema": 1,
                "last_tick": _stamp_time(now - timedelta(seconds=30)),
                "prs": {
                    WATCHER_PR: {
                        "facts": {
                            "repo": "omniclaude",
                            "state": "OPEN",
                            "head_ref": WATCHER_HEAD_REF,
                            "head_sha": "a" * 40,
                            "body": LIVE_BODY,
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    env = {
        "PATH": f"{refusing_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
        "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        "ONEX_PR_WATCHER_STATE": str(state),
    }

    def payload(body: str) -> dict[str, object]:
        return {"tool_name": "Bash", "tool_input": {"command": _edit_command(body)}}

    blocked = _run_hook(payload(LOSSY_BODY), env)
    assert blocked.returncode == 2, blocked.stdout + blocked.stderr
    reason = json.loads(blocked.stdout)["reason"]
    assert STAMP in reason and "PR watcher record omniclaude#42" in reason

    allowed = _run_hook(payload(RETAINING_BODY), env)
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
