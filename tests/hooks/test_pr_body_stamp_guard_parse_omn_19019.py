# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Regression set for the PR-body stamp guard's command parser (OMN-19542).

OMN-19542 is the stamp-guard slice of OMN-19019. Between the guard's first
refusal row (rolling work ledger row 666, 2026-09-23T18:07Z) and 2026-09-25T08:05Z it
logged 22 refusal rows. Lane occ-stamp-rebind classified them (TERMINAL row
ledger:3319):

* 15 "cannot be tokenised": the command carried a here-document whose body
  held an apostrophe, and ``shlex`` read the body as shell. Almost all of them
  wrote a body file and then CREATED a pull request, commented, or ran a Python
  script: no body-replacing edit at all.
* 3 "replacement body could not be read": one command fetched the live body
  into a file, changed it, and edited the pull request with it. The guard read
  the file before the command had written it.
* 4 real dropped-line refusals, which must keep refusing.

The fixtures below are the command SHAPES of those rows, harvested from the
refusing sessions' transcripts and rewritten with fixture paths and fixture
text: the quoting, the here-document spelling, the segment order and the
programs are the logged ones; the prose is not.

The rule under test is unchanged: a body-replacing edit whose new body drops a
change-control evidence line the live body carries is refused, and a body the
guard cannot determine is refused with the workaround named. Only the reading
of the command changes.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "plugins" / "onex" / "hooks" / "lib"
POLICY_PATH = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "config" / "pr_body_stamp_policy.json"
)
HOOK_SCRIPT = (
    REPO_ROOT
    / "plugins"
    / "onex"
    / "hooks"
    / "scripts"
    / "pre_tool_use_pr_body_stamp_guard.sh"
)

sys.path.insert(0, str(LIB_DIR))

from pr_body_stamp_guard import (  # noqa: E402
    Policy,
    check_bash_command,
    load_policy,
    render_block_reason,
)

pytestmark = pytest.mark.unit

#: Spelled in two halves so this file never carries a whole stamp line in its
#: own prose; the fixtures assemble it.
_PREFIX = "Evidence-" + "Source: "
STAMP = f"{_PREFIX}OCC#9999"
REPO = "OmniNode-ai/omnimarket"

LIVE_BODY = f"## Summary\n\nFixture body.\n\nEvidence-Ticket: OMN-1\n{STAMP}\n"
RETAINING = f"## Summary\n\nRewritten, and it's careful.\n\n{STAMP}\n"
LOSSY = "## Summary\n\nRewritten, and it's lost the line.\n"


@pytest.fixture
def policy() -> Policy:
    return load_policy(POLICY_PATH)


def reader(bodies: dict[str, str]):
    calls: list[str] = []

    def _read(edit) -> str | None:
        key = f"{edit.repo}#{edit.selector}"
        calls.append(key)
        return bodies.get(key)

    _read.calls = calls  # type: ignore[attr-defined]
    return _read


LIVE = {f"{REPO}#42": LIVE_BODY}


def _kinds(findings) -> list[str]:
    return [f.kind for f in findings]


# --------------------------------------------------------------------------
# AC1 -- the 15 "cannot be tokenised" rows: a here-document body is not shell
# --------------------------------------------------------------------------

#: Each shape carries an apostrophe inside a quoted here-document, which is
#: what made ``shlex`` raise. None of them replaces a pull-request body.
UNTOKENISABLE_NO_EDIT = {
    # The dominant shape (ledger:666, 880, 974, 1204, ...): write a body file
    # with a quoted here-document, then open a pull request with it.
    "write-body-then-create": (
        "cd {sp}; cat > {sp}/t0-prbody.md <<'EOF'\n"
        "## What\n\nIt's the plan's T0 amendments.\nEOF\n"
        'gh pr create --repo {repo} --base dev --title "docs: t0" '
        "--body-file {sp}/t0-prbody.md"
    ),
    "assigned-dir-then-create-with-label": (
        "B={sp}/pr_body_runner.md; cat > $B <<'EOF'\n"
        "## Runner\n\nThe lane's verify job lands here.\nEOF\n"
        'gh pr create --repo {repo} --title "feat: runner" --body-file $B '
        "--label hold:auto-merge 2>&1 | tail -1"
    ),
    "spaced-delimiter": (
        "cat > {sp}/pr3798_body.md << 'BODYEOF'\n"
        "## No publisher is repointed\n\nIt doesn't repoint anything.\nBODYEOF\n"
        'gh pr create --repo {repo} --title "t" --body-file {sp}/pr3798_body.md\n'
    ),
    "newline-separated-assignment": (
        "S={sp}\n"
        "cat > $S/body_market.md <<'EOF'\n## What and why\n\nThe market's half.\nEOF\n"
        'gh pr create --repo {repo} --title "t" --body-file $S/body_market.md '
        '--label "hold:auto-merge" 2>&1 | tail -1'
    ),
    "python-heredoc-naming-the-flags": (
        "cd {sp} && python3 - <<'EOF'\n"
        "t = open('draft.md').read()\n"
        "t = t.replace('a body edit (`--body`)', \"the lane's --body-file\")\n"
        "EOF\nsed -n 1,40p draft.md"
    ),
    "python-heredoc-with-arg-then-view": (
        "cd {sp}; S={sp}; python3 - \"$S\" <<'EOF'\n"
        "import sys\nb = open(f'{{sys.argv[1]}}/t4-body.md').read()\n"
        "add = '''## Round 2: the node's gate'''\nEOF\n"
        "gh pr view 42 --repo {repo} --json body -q "
        "'[(.body|contains(\"Round 2\"))]'"
    ),
    "append-report-then-echo": (
        "cat >> {sp}/report.md <<'EOF'\n\n## Addendum\n\n"
        "- Not delegated: the PR body's --body-file text.\nEOF\necho ok"
    ),
    "write-comment-then-pr-comment": (
        "SC={sp}; cat > $SC/c2814.md <<'EOF'\nLane r's readback.\nEOF\n"
        "gh pr comment 2814 --repo {repo} --body-file $SC/c2814.md; echo rc=$?"
    ),
    "write-comment-then-issue-comment-api": (
        "SP={sp}; cat > $SP/rt-comment.md <<'EOF'\nThe lab's receipt.\nEOF\n"
        "gh api repos/{repo}/issues/2813/comments -F body=@$SP/rt-comment.md "
        "--jq '\"comment \\(.id)\"'"
    ),
    "create-with-heredoc-substitution": (
        "gh pr create --repo {repo} \\\n"
        '  --title "docs: eval" \\\n'
        "  --body \"$(cat <<'EOF'\n"
        "Ticket: OMN-1. The model's numbers.\nEOF\n)\""
    ),
    "live-body-to-file-then-append-no-edit": (
        "S={sp}; gh pr view 3951 --repo {repo} --json body -q .body > $S/b3951.md; "
        "cat >> $S/b3951.md <<'EOF'\n\n### Drain pass\n\nIt's built.\nEOF\n"
        "gh pr view 3951 --repo {repo} --json body -q .isDraft"
    ),
    "close-comment-via-api": (
        "cat > {sp}/close.md <<'EOF'\n**Superseded**, it's the same head.\nEOF\n"
        "gh api repos/{repo}/issues/2846/comments -F body=@{sp}/close.md "
        "--jq .html_url; gh api repos/{repo}/pulls/2846 --jq '{{state,merged}}'"
    ),
}


@pytest.mark.parametrize("name", sorted(UNTOKENISABLE_NO_EDIT))
def test_a_heredoc_command_with_no_body_edit_is_admitted(
    name: str, policy: Policy, tmp_path: Path
) -> None:
    command = UNTOKENISABLE_NO_EDIT[name].format(sp=tmp_path, repo=REPO)
    read = reader(LIVE)
    findings = check_bash_command(command, policy, read, cwd=str(tmp_path))
    assert findings == [], (name, render_block_reason(findings))


# --------------------------------------------------------------------------
# AC2 -- a body file written earlier in the same command is judged on the text
# that command writes, never on the disk file at hook time
# --------------------------------------------------------------------------


def _heredoc_then_edit(sp: Path, body: str) -> str:
    return (
        f"cat > {sp}/b.md <<'EOF'\n{body}EOF\n"
        f"gh pr edit 42 --repo {REPO} --body-file {sp}/b.md"
    )


def test_heredoc_written_body_file_retaining_the_line_is_admitted(
    policy: Policy, tmp_path: Path
) -> None:
    assert not (tmp_path / "b.md").exists()
    command = _heredoc_then_edit(tmp_path, RETAINING)
    assert check_bash_command(command, policy, reader(LIVE)) == []


def test_heredoc_written_body_file_dropping_the_line_is_refused(
    policy: Policy, tmp_path: Path
) -> None:
    command = _heredoc_then_edit(tmp_path, LOSSY)
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"]
    assert STAMP in render_block_reason(findings)


def test_the_heredoc_text_wins_over_a_stale_file_on_disk(
    policy: Policy, tmp_path: Path
) -> None:
    """The stale-file hazard OMN-19019 records: a file left at the same path
    still carries the line, and the command overwrites it without it."""
    (tmp_path / "b.md").write_text(LIVE_BODY, encoding="utf-8")
    command = _heredoc_then_edit(tmp_path, LOSSY)
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"]


def test_the_ledger_3209_shape_live_body_plus_appended_lines_is_admitted(
    policy: Policy, tmp_path: Path
) -> None:
    """ledger:3209 / ledger:2690-class: fetch the live body to a file, append
    lines with printf, edit with the file. Fully determined by the command."""
    command = (
        f"S={tmp_path}; gh pr view 42 --repo {REPO} --json body --jq .body "
        "> $S/42-body.md; grep -c -E '^Evidence-' $S/42-body.md; "
        "printf '\\nTicket: OMN-2.\\n\\nEvidence-Ticket: OMN-2\\n' >> $S/42-body.md; "
        f"gh pr edit 42 --repo {REPO} --body-file $S/42-body.md"
    )
    assert check_bash_command(command, policy, reader(LIVE)) == []


def test_live_body_overwritten_by_printf_is_refused(
    policy: Policy, tmp_path: Path
) -> None:
    command = (
        f"S={tmp_path}; gh pr view 42 --repo {REPO} --json body --jq .body "
        "> $S/42-body.md; printf 'Only a new line.\\n' > $S/42-body.md; "
        f"gh pr edit 42 --repo {REPO} --body-file $S/42-body.md"
    )
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"]


def test_printf_of_a_cat_substitution_is_read(policy: Policy, tmp_path: Path) -> None:
    """The omnibase_core#1763 shape: printf the old body plus a line into a new
    file, then PATCH with it."""
    (tmp_path / "old.md").write_text("## Old body\n", encoding="utf-8")
    command = (
        f"cd {tmp_path} && printf '%s\\n{STAMP}\\n' \"$(cat old.md)\" > new.md "
        f"&& tail -3 new.md && gh api -X PATCH repos/{REPO}/pulls/42 "
        "-F body=@new.md --jq '.body' | tail -2"
    )
    assert check_bash_command(command, policy, reader(LIVE)) == []
    lossy = command.replace(f"\\n{STAMP}\\n", "\\n")
    assert _kinds(check_bash_command(lossy, policy, reader(LIVE))) == ["dropped_stamp"]


def test_body_file_from_a_heredoc_on_stdin(policy: Policy) -> None:
    ok = f"gh pr edit 42 --repo {REPO} --body-file - <<'EOF'\n{RETAINING}EOF\n"
    assert check_bash_command(ok, policy, reader(LIVE)) == []
    bad = f"gh pr edit 42 --repo {REPO} --body-file - <<'EOF'\n{LOSSY}EOF\n"
    assert _kinds(check_bash_command(bad, policy, reader(LIVE))) == ["dropped_stamp"]


def test_body_from_a_heredoc_substitution(policy: Policy) -> None:
    ok = f"gh pr edit 42 --repo {REPO} --body \"$(cat <<'EOF'\n{RETAINING}EOF\n)\""
    assert check_bash_command(ok, policy, reader(LIVE)) == []
    bad = f"gh pr edit 42 --repo {REPO} --body \"$(cat <<'EOF'\n{LOSSY}EOF\n)\""
    assert _kinds(check_bash_command(bad, policy, reader(LIVE))) == ["dropped_stamp"]


def test_a_relative_body_file_resolves_against_the_session_directory(
    policy: Policy, tmp_path: Path
) -> None:
    """The hook process runs from HOME; a relative path is the session's."""
    (tmp_path / "rel.md").write_text(LOSSY, encoding="utf-8")
    command = f"gh pr edit 42 --repo {REPO} --body-file rel.md"
    findings = check_bash_command(command, policy, reader(LIVE), cwd=str(tmp_path))
    assert _kinds(findings) == ["dropped_stamp"]


def test_a_relative_body_file_follows_a_cd_in_the_command(
    policy: Policy, tmp_path: Path
) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    command = (
        f"cd {sub} && cat > rel.md <<'EOF'\n{RETAINING}EOF\n"
        f"gh pr edit 42 --repo {REPO} --body-file rel.md"
    )
    assert check_bash_command(command, policy, reader(LIVE), cwd="/") == []


# --------------------------------------------------------------------------
# AC4 -- a body that genuinely cannot be determined is still refused, and the
# refusal names the workaround
# --------------------------------------------------------------------------

WORKAROUND = "as its own Bash call"


def test_the_ledger_3164_shape_sed_in_place_is_refused_with_the_workaround(
    policy: Policy, tmp_path: Path
) -> None:
    """ledger:3164: fetch, rewrite the line with ``sed -i``, PATCH. The guard
    does not run sed, so the body is unknown until the command has run."""
    command = (
        f"SP={tmp_path}; gh api repos/{REPO}/pulls/42 --jq .body > $SP/b42.md; "
        f"sed -i '' 's/^{STAMP}$/{_PREFIX}OCC#1/' $SP/b42.md; "
        f'grep -n "^Evidence-Source" $SP/b42.md; '
        f"gh api -X PATCH repos/{REPO}/pulls/42 -F body=@$SP/b42.md --jq .body"
    )
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["unreadable_new_body"]
    reason = render_block_reason(findings)
    assert "`sed`" in reason and WORKAROUND in reason, reason


def test_the_ledger_2416_shape_loop_and_python_writer_is_refused(
    policy: Policy, tmp_path: Path
) -> None:
    """ledger:2416: a loop fetches bodies to computed paths, a Python
    here-document rewrites them, then the edits run."""
    command = (
        f"SP={tmp_path}; for pr in omnibase_infra:4081 omnimarket:42; do "
        "r=${pr%%:*}; n=${pr##*:}; "
        "gh pr view $n --repo OmniNode-ai/$r --json body --jq .body > $SP/body_$n.md; "
        "done; python3 - $SP <<'EOF'\n"
        "import sys\np = sys.argv[1] + '/body_42.md'\n"
        "open(p, 'w').write(open(p).read() + \"it's revised\")\nEOF\n"
        f"gh pr edit 42 --repo {REPO} --body-file $SP/body_42.md >/dev/null "
        "&& echo edited"
    )
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["unreadable_new_body"]
    assert WORKAROUND in render_block_reason(findings)


def test_a_script_run_earlier_may_rewrite_a_file_on_disk(
    policy: Policy, tmp_path: Path
) -> None:
    """A file on disk that RETAINS the line is not evidence when a script runs
    first in the same command: the edit would send what the script wrote."""
    (tmp_path / "pr_body.md").write_text(RETAINING, encoding="utf-8")
    command = (
        f"S={tmp_path}; python3 $S/edit_body.py && "
        f"gh pr edit 42 --repo {REPO} --body-file $S/pr_body.md"
    )
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["unreadable_new_body"]
    assert "`python3`" in render_block_reason(findings)


def test_an_expanding_heredoc_with_a_substitution_is_refused(
    policy: Policy, tmp_path: Path
) -> None:
    command = (
        f"cat > {tmp_path}/b.md <<EOF\n{STAMP}\nRun at $(date -u)\nEOF\n"
        f"gh pr edit 42 --repo {REPO} --body-file {tmp_path}/b.md"
    )
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["unreadable_new_body"]
    assert WORKAROUND in render_block_reason(findings)


def test_an_expanding_heredoc_with_plain_variables_is_read(
    policy: Policy, tmp_path: Path
) -> None:
    command = (
        f"N=9999; cat > {tmp_path}/b.md <<EOF\n{_PREFIX}OCC#$N\nEOF\n"
        f"gh pr edit 42 --repo {REPO} --body-file {tmp_path}/b.md"
    )
    assert check_bash_command(command, policy, reader(LIVE)) == []


def test_a_genuinely_unbalanced_edit_is_refused_with_the_workaround(
    policy: Policy,
) -> None:
    command = f"gh pr edit 42 --repo {REPO} --body 'it is unbalanced"
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["untokenisable"]
    reason = render_block_reason(findings)
    assert "--body-file" in reason and WORKAROUND in reason, reason


def test_an_unbalanced_command_naming_no_edit_is_admitted(policy: Policy) -> None:
    """No pull-request edit can hide in text that never names ``gh``."""
    command = "echo 'the --body-file flag is documented here"
    assert check_bash_command(command, policy, reader({})) == []


def test_stdin_with_nothing_on_it_is_still_refused(policy: Policy) -> None:
    command = f"gh pr edit 42 --repo {REPO} --body-file -"
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["unreadable_new_body"]


def test_raw_field_at_sign_is_literal_not_a_file(
    policy: Policy, tmp_path: Path
) -> None:
    """``-f`` sends its value verbatim; only ``-F`` reads ``@file``. Reading the
    file for ``-f`` would judge a body gh never sends."""
    (tmp_path / "b.md").write_text(RETAINING, encoding="utf-8")
    command = f"gh api -X PATCH repos/{REPO}/pulls/42 -f body=@{tmp_path}/b.md"
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"]


def test_an_edit_inside_a_loop_body_is_still_seen(policy: Policy) -> None:
    """``do`` is a keyword, not the program of the segment."""
    command = f"for n in 42; do gh pr edit $n --repo {REPO} --body 'no line'; done"
    findings = check_bash_command(command, policy, reader(LIVE))
    assert findings, "an edit after `do` must be judged"


def test_an_edit_on_a_later_line_is_judged(policy: Policy) -> None:
    """Fail-open found while calibrating: ``shlex`` treats a newline as plain
    whitespace, so the old parser read ``cd /tmp`` NEWLINE ``gh pr edit ...``
    as one segment whose program was ``cd`` and never saw the edit. All 46
    transcript commands whose verdict moved from admit to refuse under this
    change were edits of that shape."""
    command = f"cd /tmp\ngh pr edit 42 --repo {REPO} --body 'no line'"
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"]


# --------------------------------------------------------------------------
# AC3 -- the four real refusals keep refusing
# --------------------------------------------------------------------------

REAL = {
    # ledger:1028 omnimarket#2819: a prepared file that lacks the line.
    "edit-with-prepared-file": "gh pr edit 42 --repo {repo} --body-file {f}",
    # ledger:1070 omnibase_infra#4036: the same, then a multi-line readback.
    "edit-then-readback": (
        "gh pr edit 42 --repo {repo} --body-file {f} 2>&1\nsleep 2\n"
        'echo "---readback---"\ngh pr view 42 --repo {repo} --json body --jq .body'
    ),
    # ledger:2793 omnibase_core#1762: REST PATCH with a typed field file.
    "api-patch-field-file": (
        "gh api -X PATCH repos/{repo}/pulls/42 -F body=@{f} --jq '.body' "
        "| grep 'Evidence-'"
    ),
    # ledger:3101 omnibase_core#1762: the same after a read of the live body.
    "api-patch-after-read": (
        "gh api repos/{repo}/pulls/42 --jq .body | grep '^Evidence-Source'; "
        "gh api -X PATCH repos/{repo}/pulls/42 -F body=@{f} --jq '.head.sha'"
    ),
}


@pytest.mark.parametrize("name", sorted(REAL))
def test_a_real_dropped_line_is_still_refused(
    name: str, policy: Policy, tmp_path: Path
) -> None:
    body_file = tmp_path / "prepared.md"
    body_file.write_text(LOSSY, encoding="utf-8")
    command = REAL[name].format(repo=REPO, f=body_file)
    findings = check_bash_command(command, policy, reader(LIVE))
    assert _kinds(findings) == ["dropped_stamp"], name
    assert STAMP in render_block_reason(findings)


# --------------------------------------------------------------------------
# The hook wrapper
# --------------------------------------------------------------------------


def _run_hook(payload: dict[str, object], env: dict[str, str]):
    base = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", "/tmp"),
        "CLAUDE_PROJECT_DIR": str(REPO_ROOT),
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
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(
        "#!/bin/bash\n"
        'if [[ "$1" == "pr" && "$2" == "view" ]]; then\n'
        f"  cat <<'BODY'\n{LIVE_BODY}BODY\n"
        "  exit 0\nfi\nexit 1\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return bindir


def test_hook_admits_a_create_then_edit_command(tmp_path: Path, fake_gh: Path) -> None:
    command = _heredoc_then_edit(tmp_path, RETAINING)
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)},
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_refuses_a_lossy_input_payload(tmp_path: Path, fake_gh: Path) -> None:
    """``--input`` replaces a body too, so the wrapper's cheap pre-filter must
    let it through to the decision core."""
    payload_file = tmp_path / "p.json"
    payload_file.write_text(json.dumps({"body": LOSSY}), encoding="utf-8")
    command = f"gh api -X PATCH repos/{REPO}/pulls/42 --input {payload_file}"
    result = _run_hook(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(tmp_path)},
        {
            "PATH": f"{fake_gh}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "ONEX_HOOK_LOG": str(tmp_path / "hooks.log"),
        },
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert STAMP in result.stdout
