# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Every published onex install command pins the interpreter (OMN-16632).

An unpinned ``uv tool install`` takes the newest interpreter uv can fetch. On a
clean machine that was Python 3.15, for which ``confluent-kafka`` (a dependency
of ``omnimarket``) publishes no wheel, so the build failed and the customer
never got an ``onex``. Pinning ``--python 3.12`` installs: 3.12 is the floor the
three packages declare (``Requires-Python: >=3.12``) and the version this
repository itself supports.

The scan covers every user-facing copy under ``plugins/`` and ``.claude-plugin/``
(manifests, compat files, skill docs, getting-started text, hook messages), not a
hand-kept list, so a sixth copy added later is caught without editing this file.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from packaging.specifiers import SpecifierSet

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[3]
PINNED_PYTHON = "3.12"

#: Text suffixes a customer or a hook message can read an install line from.
_SUFFIXES = {".md", ".json", ".yaml", ".yml", ".sh", ".py", ".txt"}
_SCAN_ROOTS = (REPO_ROOT / "plugins", REPO_ROOT / ".claude-plugin")
_INSTALL = re.compile(r"(?P<cmd>uv tool install|pipx install)\b(?P<rest>.*)")
_PIN = re.compile(rf"--python(?:=|\s+){re.escape(PINNED_PYTHON)}(?![\d.])")

#: Copies that must stay covered; the scan finding none of them means it went blind.
_REQUIRED_COVERED = (
    ".claude-plugin/marketplace.json",
    "plugins/.claude-plugin/marketplace.json",
    "plugins/onex-delegate/.claude-plugin/plugin.json",
    "plugins/onex-delegate/plugin-compat.yaml",
    "plugins/onex-delegate/skills/delegate/SKILL.md",
    "plugins/onex/plugin-compat.yaml",
    "plugins/onex/.claude-plugin/plugin.json",
)


def unpinned_install_lines(text: str) -> list[tuple[int, str]]:
    """Install lines in ``text`` with no ``--python <pin>`` after the command.

    Comment lines are skipped: they narrate history (the command that used to be
    published) and are not something a reader is told to run.
    """
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        for match in _INSTALL.finditer(line):
            if not _PIN.search(match.group("rest")):
                found.append((number, line.strip()))
                break
    return found


def _published_files() -> list[Path]:
    files: list[Path] = []
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*")):
            if (
                path.is_file()
                and path.suffix in _SUFFIXES
                and "tests" not in path.relative_to(root).parts
                and "node_modules" not in path.parts
            ):
                files.append(path)
    return files


def test_scanner_flags_unpinned_and_accepts_pinned() -> None:
    """Positive control: the scanner reports a bad line, so a clean result means something."""
    unpinned = "uv tool install --with omnimarket omnibase-core"
    assert unpinned_install_lines(unpinned) == [(1, unpinned)]
    assert unpinned_install_lines("pipx install 'omnibase-core>=0.46.8'")
    assert not unpinned_install_lines(
        "uv tool install --python 3.12 --with omnimarket omnibase-core"
    )
    assert not unpinned_install_lines("pipx install --python=3.12 omnibase-core")
    # A different interpreter is not the pin.
    assert unpinned_install_lines("uv tool install --python 3.15 omnibase-core")
    assert unpinned_install_lines("uv tool install --python 3.120 omnibase-core")
    assert not unpinned_install_lines("# pipx install omnibase-core (history)")


def test_published_install_commands_pin_python() -> None:
    scanned_with_install: set[str] = set()
    offenders: list[str] = []
    for path in _published_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(REPO_ROOT).as_posix()
        if _INSTALL.search(text):
            scanned_with_install.add(rel)
        offenders.extend(
            f"{rel}:{number}: {line[:160]}"
            for number, line in unpinned_install_lines(text)
        )
    assert not offenders, (
        f"published install commands without `--python {PINNED_PYTHON}` "
        "(an unpinned uv picks the newest interpreter, which has no wheel for "
        "confluent-kafka; OMN-16632):\n" + "\n".join(offenders)
    )
    missing = [p for p in _REQUIRED_COVERED if p not in scanned_with_install]
    assert not missing, f"the scan no longer sees an install command in: {missing}"


def test_pin_is_a_version_this_repo_supports() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    supported = SpecifierSet(pyproject["project"]["requires-python"])
    assert PINNED_PYTHON in supported, (
        f"pin {PINNED_PYTHON} is outside requires-python {supported}"
    )
