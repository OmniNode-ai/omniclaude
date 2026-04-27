# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent

OTHER_LAUNCHERS = [
    "plugins/onex/hooks/scripts/session-start.sh",
    "plugins/onex/hooks/scripts/session-end.sh",
    "plugins/onex/hooks/scripts/user-prompt-submit.sh",
]
COMMON = "plugins/onex/hooks/scripts/common.sh"

# Lines that are non-invocation uses of "python" in these scripts.
# Each entry is a substring that, if present, means the line is NOT a bare invocation.
_NON_INVOCATION_MARKERS = [
    "os.path.realpath",  # bootstrap realpath fallback (pre-common.sh)
    "command -v python",  # availability probe
    ".venv/bin/python3",  # path string / existence check
    "/bin/python3",  # path reference (not a bare invocation)
    "BREW_PY=",  # assignment
    "$BREW_PY",  # already using BREW_PY
    "${BREW_PY}",  # already using BREW_PY
    "$PYTHON_CMD",  # using PYTHON_CMD (the resolved interpreter)
    "${PYTHON_CMD",  # PYTHON_CMD expansion
    "PYTHON_CMD}",  # end of PYTHON_CMD expansion
    "PYTHON_CMD=",  # PYTHON_CMD assignment
    "python-version",  # CLI flag, not an invocation
    "--python",  # CLI flag
    'echo "python3"',  # echoing the string "python3" (lite mode return)
    "echo python3",  # echoing the string python3
    "pgrep",  # process grep
    "| python",  # pipeline into python (excluded separately below)
    "uv run python",  # uv-managed python (not a bare invocation)
    "uv --project",  # uv project invocations
]


def _is_bare_python_invocation(line: str) -> bool:
    """Return True if the line contains a bare python/python3 invocation not via BREW_PY."""
    stripped = line.strip()
    # Comments are not invocations
    if stripped.startswith("#"):
        return False
    for marker in _NON_INVOCATION_MARKERS:
        if marker in stripped:
            return False
    # Skip bash test expressions [[ ... ]] and case patterns
    if re.search(r"\[\[.*python.*\]\]", stripped):
        return False
    # Skip parameter expansion ${VAR%...python...}
    if re.search(r"\$\{[^}]*python[^}]*\}", stripped, re.IGNORECASE):
        return False
    # Skip printf/log lines that mention Python symbolically
    if re.search(r"(printf|log)\s+.*python", stripped, re.IGNORECASE):
        return False
    # Skip lines where python3 appears only inside a quoted string argument (not executed)
    if re.search(r'"[^"]*python3[^"]*"', stripped) and not re.search(
        r'^[^"]*python3', stripped
    ):
        return False
    # Match bare python3 or python as the invoked command
    return bool(re.search(r"(?<![/$'\"])(?<!\w)(python3|python)(?!\w|[-])", stripped))


def test_common_defines_brew_py_once_with_correct_value():
    text = (REPO_ROOT / COMMON).read_text()
    matches = re.findall(
        r'^\s*BREW_PY\s*=\s*"?(/opt/homebrew/bin/python3\.13)"?',
        text,
        re.MULTILINE,
    )
    assert len(matches) == 1, (
        f"common.sh must define BREW_PY exactly once with /opt/homebrew/bin/python3.13 "
        f"(found {len(matches)} definitions)"
    )


def test_other_launchers_source_common_and_use_brew_py_var():
    for path in OTHER_LAUNCHERS:
        text = (REPO_ROOT / path).read_text()
        if "python" not in text.lower():
            continue
        assert "common.sh" in text, f"{path} must source common.sh"
        assert "$BREW_PY" in text or "${BREW_PY}" in text, (
            f"{path} must reference $BREW_PY (not the literal /opt/homebrew path)"
        )
        assert "/opt/homebrew/bin/python3.13" not in text, (
            f"{path} must not hardcode the literal interpreter path; use $BREW_PY from common.sh"
        )


def test_brew_py_invocations_strip_pythonpath():
    """Every $BREW_PY invocation (in any of the four scripts) must use env -u PYTHONPATH."""
    for path in [COMMON, *OTHER_LAUNCHERS]:
        text = (REPO_ROOT / path).read_text()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "$BREW_PY" in stripped or "${BREW_PY}" in stripped:
                # Assignment lines are fine
                if "BREW_PY=" in stripped:
                    continue
                assert "env -u PYTHONPATH" in stripped, (
                    f"{path}: BREW_PY invocation must be wrapped in `env -u PYTHONPATH`: {stripped!r}"
                )


def test_no_bare_python3_outside_bootstrap():
    """No bare python3 invocations outside of bootstrap/path-check lines."""
    for path in OTHER_LAUNCHERS:
        text = (REPO_ROOT / path).read_text()
        for line in text.splitlines():
            if _is_bare_python_invocation(line):
                raise AssertionError(
                    f"{path}: bare python3 invocation found (use $BREW_PY via common.sh): {line.strip()!r}"
                )
