# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Redirect tokens from the shared shell tokenizer (OMN-19542).

Drafted by local delegation (onex delegate run 18a8b05c-dd56-4f0c-8330-f91dadf03aa9,
--task-type test) and reviewed here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB_DIR = Path(__file__).resolve().parents[2] / "plugins" / "onex" / "hooks" / "lib"
sys.path.insert(0, str(LIB_DIR))

from shell_words import (  # noqa: E402
    HereDoc,
    Redirect,
    ShellSyntaxError,
    Word,
    tokenize,
)

pytestmark = [pytest.mark.unit]


def get_words(tokens):
    return [t for t in tokens if isinstance(t, Word)]


def get_redirects(tokens):
    return [t for t in tokens if isinstance(t, Redirect)]


def get_heredocs(tokens):
    return [t for t in tokens if isinstance(t, HereDoc)]


def test_heredoc_with_redirects():
    cmd = "cat > out.md <<'EOF'\nit's fine\nEOF"
    tokens = tokenize(cmd, keep_redirects=True)
    words = get_words(tokens)
    redirects = get_redirects(tokens)
    heredocs = get_heredocs(tokens)

    assert "cat" in [w.text for w in words]
    assert len(redirects) == 1
    assert redirects[0].op == ">"
    assert redirects[0].fd is None
    assert isinstance(redirects[0].target, Word)
    assert redirects[0].target.text == "out.md"

    assert len(heredocs) == 1
    assert heredocs[0].delimiter == "EOF"
    assert heredocs[0].expands is False
    assert heredocs[0].body == "it's fine\n"


def test_redirect_with_variable():
    cmd = "printf '%s' x >> \"$S/b.md\""
    tokens = tokenize(cmd, keep_redirects=True)
    redirects = get_redirects(tokens)
    assert len(redirects) == 1
    assert redirects[0].op == ">>"
    assert redirects[0].fd is None
    assert isinstance(redirects[0].target, Word)
    assert redirects[0].target.text == "$S/b.md"


def test_multiple_redirects():
    cmd = "cmd 2>err.log 2>&1 >/dev/null"
    tokens = tokenize(cmd, keep_redirects=True)
    words = get_words(tokens)
    redirects = get_redirects(tokens)

    assert [w.text for w in words] == ["cmd"]
    assert len(redirects) == 3

    assert redirects[0].fd == "2"
    assert redirects[0].op == ">"
    assert redirects[0].target.text == "err.log"

    assert redirects[1].fd == "2"
    assert redirects[1].op == ">&"
    assert redirects[1].target.text == "1"

    assert redirects[2].fd is None
    assert redirects[2].op == ">"
    assert redirects[2].target.text == "/dev/null"


def test_input_redirect():
    cmd = "gh pr edit 5 --body-file - < body.md"
    tokens = tokenize(cmd, keep_redirects=True)
    words = get_words(tokens)
    redirects = get_redirects(tokens)

    assert [w.text for w in words] == ["gh", "pr", "edit", "5", "--body-file", "-"]
    assert len(redirects) == 1
    assert redirects[0].op == "<"
    assert redirects[0].fd is None
    assert redirects[0].target.text == "body.md"


def test_heredoc_string_redirect():
    cmd = 'cat <<< "hello world"'
    tokens = tokenize(cmd, keep_redirects=True)
    redirects = get_redirects(tokens)
    assert len(redirects) == 1
    assert redirects[0].op == "<<<"
    assert redirects[0].fd is None
    assert redirects[0].target.text == "hello world"


def test_exec_redirect_to_none():
    cmd = "exec 3>&-"
    tokens = tokenize(cmd, keep_redirects=True)
    redirects = get_redirects(tokens)
    assert len(redirects) == 1
    assert redirects[0].fd == "3"
    assert redirects[0].op == ">&"
    assert redirects[0].target is None


def test_default_mode_no_redirects():
    cmd = "cat > out.md <<'EOF'\nx\nEOF\n"
    tokens = tokenize(cmd)
    redirects = get_redirects(tokens)
    words = get_words(tokens)

    assert len(redirects) == 0
    assert "out.md" not in [w.text for w in words]


def test_heredoc_in_substitution():
    cmd = "echo --body \"$(cat <<'EOF'\nbody with 'apostrophe'\nEOF\n)\""
    tokens = tokenize(cmd, keep_redirects=True)
    words = get_words(tokens)
    # echo, --body, and the whole substitution as ONE word: the apostrophe in
    # the quoted here-document body is data, not an open quote.
    assert len(words) == 3
    assert words[0].text == "echo"
    assert words[1].text == "--body"
    assert words[2].text.startswith("$(cat <<'EOF'")
    assert words[2].text.endswith("EOF\n)")


def test_unbalanced_quote_raises():
    cmd = "echo 'abc"
    with pytest.raises(ShellSyntaxError):
        tokenize(cmd, keep_redirects=True)
