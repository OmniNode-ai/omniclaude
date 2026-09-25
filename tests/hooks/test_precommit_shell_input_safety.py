# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Static ratchets for shell scripts registered as pre-commit hooks."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PRECOMMIT_CONFIG = REPO_ROOT / ".pre-commit-config.yaml"
IMPERATIVE_SKILL_GUARD = (
    REPO_ROOT / ".pre-commit-hooks" / "reject-imperative-skill-patterns.sh"
)
HOOK_EVENT_GUARD = REPO_ROOT / "scripts" / "check_hook_event_names.sh"


def _registered_shell_scripts() -> list[Path]:
    """Return in-repo shell scripts referenced by pre-commit configuration."""
    config = PRECOMMIT_CONFIG.read_text(encoding="utf-8")
    relative_paths = set(re.findall(r"(?:\./)?[\w./-]+\.sh\b", config))
    scripts = [REPO_ROOT / path.removeprefix("./") for path in relative_paths]
    return sorted(path for path in scripts if path.is_file())


def test_registered_hooks_do_not_feed_read_loops_from_heredocs() -> None:
    """OMN-19623: reject the bash 5.1+ pipe-deadlock construct."""
    offenders: list[str] = []
    for script in _registered_shell_scripts():
        for line_number, line in enumerate(
            script.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if line.lstrip().startswith("#"):
                continue
            if re.search(r"\bdone\s*<<", line):
                offenders.append(
                    f"{script.relative_to(REPO_ROOT)}:{line_number}: {line.strip()}"
                )

    assert not offenders, (
        "OMN-19623: a registered pre-commit hook feeds a while-read loop from "
        "a here-string/heredoc, which can deadlock under bash 5.1+ pipe "
        f"pressure; feed it from a temp file instead: {offenders}"
    )


def test_affected_hooks_read_their_loops_from_real_files() -> None:
    """Require the positive temp-file shape, not only removal of old syntax."""
    expected_snippets = {
        IMPERATIVE_SKILL_GUARD: (
            'tmp_violations="$(mktemp ',
            "trap 'rm -f \"$tmp_violations\"' EXIT",
            'done < "$tmp_violations"',
        ),
        HOOK_EVENT_GUARD: (
            'tmp_offenders="$(mktemp ',
            'trap \'rm -f "$tmp_candidates" "$tmp_offenders"\' EXIT',
            'done < "$tmp_offenders"',
        ),
    }
    for script, snippets in expected_snippets.items():
        content = script.read_text(encoding="utf-8")
        for snippet in snippets:
            assert snippet in content
