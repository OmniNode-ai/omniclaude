# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Keep hooks portable to macOS /bin/bash 3.2 (OMN-20389, OMN-20961)."""

from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DIRECTORIES = (
    ".pre-commit-hooks",
    "plugins/onex/hooks/scripts",
    "plugins/onex/hooks/lib",
)
PAYLOAD_SIZES = (61440, 65536)
_QUOTE_CHARS = ("'", '"', "`")


def _comment_quote_hazards(script_text: str) -> list[tuple[int, str]]:
    """Return (line, text) for each comment inside ``$( )`` with an odd quote count.

    bash 3.2 does not treat ``#`` as a comment while it scans a command
    substitution for the closing parenthesis, so an unbalanced quote in a
    comment opens a string that runs to EOF. bash 4+ and the Linux CI runners
    skip the comment and never notice. The scan is a small lexer (quotes,
    escapes, nesting, comments), not a bash parser: it can miss a hazard in
    exotic syntax such as ``case`` patterns inside a substitution, never invent one.
    """
    hazards: list[tuple[int, str]] = []
    saved_dq: list[bool] = []  # per open `$(`: the quote state to restore at its `)`
    open_parens: list[int] = []  # per open `$(`: nested plain `(` not yet closed
    in_sq = in_dq = False
    for lineno, line in enumerate(script_text.splitlines(), start=1):
        i = 0
        while i < len(line):
            char = line[i]
            opens_subst = char == "$" and line[i + 1 : i + 2] == "("
            if in_sq:
                in_sq = char != "'"
            elif char == "\\":
                i += 1
            elif in_dq:
                if char == '"':
                    in_dq = False
                elif opens_subst:
                    saved_dq.append(in_dq)
                    open_parens.append(0)
                    in_dq = False
                    i += 1
            elif char == "'":
                in_sq = True
            elif char == '"':
                in_dq = True
            elif opens_subst:
                saved_dq.append(in_dq)
                open_parens.append(0)
                i += 1
            elif saved_dq and char == "(":
                open_parens[-1] += 1
            elif saved_dq and char == ")":
                if open_parens[-1]:
                    open_parens[-1] -= 1
                else:
                    open_parens.pop()
                    in_dq = saved_dq.pop()
            elif char == "#" and (i == 0 or line[i - 1] in " \t;"):
                comment = line[i:]
                if saved_dq and any(comment.count(q) % 2 for q in _QUOTE_CHARS):
                    hazards.append((lineno, line.strip()))
                break
            i += 1
    return hazards


@pytest.fixture
def bash_binary() -> str:
    """Prefer the Homebrew Bash affected by the macOS pipe deadlock."""
    homebrew_bash = Path("/opt/homebrew/bin/bash")
    if homebrew_bash.exists():
        return str(homebrew_bash)
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash unavailable for OMN-20389 hook regression tests")
    return bash


def _write_payload(target: Path, size: int) -> None:
    """Write exactly size bytes of ordinary ASCII prose over many lines."""
    line = "This ordinary prose describes routine project work and progress.\n"
    payload = (line * (size // len(line) + 1))[:size]
    target.write_text(payload, encoding="utf-8")


def _run_hook(
    bash_binary: str, hook_name: str, target: Path
) -> subprocess.CompletedProcess[str]:
    """Run the real hook outside the repository with a hard timeout."""
    hook = REPO_ROOT / ".pre-commit-hooks" / hook_name
    try:
        return subprocess.run(
            [bash_binary, str(hook), str(target)],
            cwd=target.parent,
            capture_output=True,
            check=False,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"OMN-20389: {hook_name} hung on {target.stat().st_size} bytes")


@pytest.mark.unit
def test_hooks_are_here_string_free() -> None:
    """Ratchet all shell hooks against here-strings, ignoring comment lines."""
    violations: list[str] = []
    for directory in HOOK_DIRECTORIES:
        for script in sorted((REPO_ROOT / directory).rglob("*.sh")):
            for lineno, line in enumerate(
                script.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if line.lstrip().startswith("#"):
                    continue
                if "<<<" in line:
                    violations.append(f"{script.relative_to(REPO_ROOT)}:{lineno}")
    assert not violations, (
        "OMN-20389: use < <(printf '%s\\n' \"$var\") instead of here-strings:\n"
        + "\n".join(violations)
    )


@pytest.mark.unit
def test_hooks_have_no_unbalanced_quote_in_substitution_comment() -> None:
    """OMN-20961: no `#` comment inside `$( )` may carry an unbalanced quote.

    OMN-20916 shipped ``# The session's mode ...`` inside a ``$( )`` block; macOS
    /bin/bash 3.2 failed to parse the entrypoint and refused every Bash call.
    """
    violations: list[str] = []
    for directory in HOOK_DIRECTORIES:
        for script in sorted((REPO_ROOT / directory).rglob("*.sh")):
            violations.extend(
                f"{script.relative_to(REPO_ROOT)}:{lineno}: {text}"
                for lineno, text in _comment_quote_hazards(
                    script.read_text(encoding="utf-8")
                )
            )
    assert not violations, (
        "OMN-20961: bash 3.2 reads a quote inside a comment in $( ) as a string "
        "opener; reword the comment without it:\n" + "\n".join(violations)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("snippet", "expected_lines"),
    [
        pytest.param(
            """
            x="$(
                # The session's mode goes to the node
                true
            )"
            """,
            [3],
            id="apostrophe-in-comment-in-substitution",
        ),
        pytest.param(
            """
            x="$(
                true  # say "hi
            )"
            """,
            [3],
            id="trailing-double-quote-in-comment",
        ),
        pytest.param(
            """
            # The session's mode, at top level, is fine
            x="$(
                # The session mode goes to the node
                echo 'it'
            )"
            """,
            [],
            id="clean-substitution-and-top-level-apostrophe",
        ),
        pytest.param(
            """
            x="$(
                # both 'quoted' words are balanced
                true
            )"
            """,
            [],
            id="balanced-quotes-in-comment",
        ),
    ],
)
def test_comment_quote_hazard_scanner_controls(
    snippet: str, expected_lines: list[int]
) -> None:
    """Positive and negative controls for the scanner behind the ratchet."""
    found = [lineno for lineno, _ in _comment_quote_hazards(textwrap.dedent(snippet))]
    assert found == expected_lines


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_skip_token_clean(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """Large clean markdown must pass without hanging."""
    target = tmp_path / "clean.md"
    _write_payload(target, size)
    result = _run_hook(bash_binary, "reject-deploy-gate-skip-token.sh", target)
    assert result.returncode == 0, result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_skip_token_rejected(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """A skip token appended to large markdown must still be rejected."""
    target = tmp_path / "skip.md"
    _write_payload(target, size)
    with target.open("a", encoding="utf-8") as stream:
        stream.write("\n[" + "skip-deploy-gate: x]\n")
    result = _run_hook(bash_binary, "reject-deploy-gate-skip-token.sh", target)
    assert result.returncode != 0, "Expected the large payload's skip token to fail"
    assert "contains a [skip-*] bypass token" in result.stderr


@pytest.mark.unit
@pytest.mark.parametrize("size", PAYLOAD_SIZES)
def test_large_payload_occ_non_artifact(
    tmp_path: Path, bash_binary: str, size: int
) -> None:
    """Large markdown without Evidence lines must pass without a validator."""
    target = tmp_path / "readme.md"
    _write_payload(target, size)
    result = _run_hook(bash_binary, "validate-occ-pr-stamp.sh", target)
    assert result.returncode == 0, result.stderr
