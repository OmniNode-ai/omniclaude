#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The one matcher behind the skill monorepo-ref gate (OMN-8795 SD-08, OMN-16850).

Why this module exists
----------------------
The gate used to be implemented TWICE -- once in
``tests/skills/test_no_monorepo_refs_in_plugin_skills.py`` (Python ``re``) and once
in ``scripts/check-skill-monorepo-refs.sh`` (``grep -E``) -- with the pattern list
hand-copied between them. Two engines and two copies of one rule is a drift risk
that OMN-16850 was opened to remove, so both surfaces now call *this* module and
read *one* registry (``skill_monorepo_ref_patterns.json``). The shell entrypoint is
a wrapper over ``main()``; the pytest gate imports ``scan_file``.

What OMN-16850 widened
----------------------
The old registry held a single pattern for the workspace variable, ``\\$OMNI_HOME``.
That regex requires ``$`` immediately followed by ``O``, so it could not see:

  * ``${OMNI_HOME}`` / ``${OMNI_HOME:-.}`` -- the braced forms
  * ``os.environ["OMNI_HOME"]`` / ``os.environ.get("OMNI_HOME")``
  * YAML ``OMNI_HOME:`` and click ``envvar="OMNI_HOME"``

That blind spot was not theoretical. OMN-16835 reproduced the gate against
``plugins/onex-delegate/skills/delegate/SKILL.md``: it fired on lines 58/59/66/88 --
bare ``$OMNI_HOME`` in explanatory prose -- and stayed silent on lines 73 and 75,
the two actual customer install commands, because those carry ``${OMNI_HOME:-.}``.
Red on prose, blind on the executable surface. ``${OMNI_HOME:-.}`` resolves to the
caller's *current working directory* when unset, so the install command's
``git -C ./omnimarket rev-parse HEAD`` fails, falls through to ``|| echo dev``, and
the customer installs an unpinned ``dev`` ref believing they pinned a commit.

``OMNIBASE_PATH`` (OMN-16849) is deliberately absent from the forbidden list in its
fail-fast form and present in its fail-soft forms: the rename is only worth making
if the silent default does not survive it.

Usage
-----
    python3 scripts/skill_monorepo_refs.py            # scan the configured roots
    python3 scripts/skill_monorepo_refs.py PATH...    # scan explicit paths/dirs
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = Path(__file__).resolve().parent / "skill_monorepo_ref_patterns.json"


@dataclass(frozen=True)
class Pattern:
    """One forbidden form plus the guidance shown when it matches."""

    id: str
    regex: re.Pattern[str]
    message: str


@dataclass(frozen=True)
class Violation:
    """A single offending line, addressed the way CI annotations want it."""

    path: Path
    lineno: int
    pattern_id: str
    message: str

    def render(self, root: Path = REPO_ROOT) -> str:
        try:
            rel = self.path.relative_to(root).as_posix()
        except ValueError:
            rel = str(self.path)
        return f"{rel}:{self.lineno}: {self.pattern_id} -- {self.message}"


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


_REGISTRY = _registry()

ESCAPE_HATCH: str = _REGISTRY["escape_hatch"]

PATTERNS: tuple[Pattern, ...] = tuple(
    Pattern(id=entry["id"], regex=re.compile(entry["regex"]), message=entry["message"])
    for entry in _REGISTRY["patterns"]
)

#: A bare escape-hatch marker is not enough -- it must carry a reason. Silencing a
#: finding without saying why is how a gate stops meaning anything.
_ESCAPE_HATCH_WITH_REASON = re.compile(r"#\s*local-path-ok\b(\s*:\s*|\s+)\S")


def scan_line(line: str, lineno: int, path: Path) -> list[Violation]:
    """Every forbidden form on one line, or the escape-hatch complaint about it."""
    if ESCAPE_HATCH in line:
        if not _ESCAPE_HATCH_WITH_REASON.search(line):
            return [
                Violation(
                    path=path,
                    lineno=lineno,
                    pattern_id="escape_hatch_without_reason",
                    message=(
                        f"escape hatch '{ESCAPE_HATCH}' requires a reason "
                        f"(e.g. '{ESCAPE_HATCH}: <why>')"
                    ),
                )
            ]
        return []
    return [
        Violation(
            path=path, lineno=lineno, pattern_id=pattern.id, message=pattern.message
        )
        for pattern in PATTERNS
        if pattern.regex.search(line)
    ]


def scan_text(text: str, path: Path) -> list[Violation]:
    violations: list[Violation] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        violations.extend(scan_line(line, lineno, path))
    return violations


def scan_file(path: Path) -> list[Violation]:
    return scan_text(path.read_text(), path)


def gated_files(root: Path = REPO_ROOT) -> list[Path]:
    """Every file the configured roots put under the gate, sorted for stable output."""
    found: list[Path] = []
    for entry in _REGISTRY["roots"]:
        base = root / entry["path"]
        if not base.exists():
            continue
        for glob in entry["include"]:
            found.extend(p for p in base.rglob(glob) if p.is_file())
    return sorted(set(found))


def _expand(targets: list[str]) -> list[Path]:
    files: list[Path] = []
    for target in targets:
        path = Path(target)
        if path.is_dir():
            files.extend(p for p in path.rglob("*") if p.is_file())
        elif path.is_file():
            files.append(path)
    return sorted(set(files))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    files = _expand(argv) if argv else gated_files()

    if not files:
        print("No gated files found -- skipping")
        return 0

    violations: list[Violation] = []
    for path in files:
        found = scan_file(path)
        violations.extend(found)
        for violation in found:
            try:
                rel = violation.path.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = str(violation.path)
            print(
                f"::error file={rel},line={violation.lineno}::"
                f"{violation.pattern_id} -- {violation.message}"
            )

    if violations:
        print()
        print("Skill monorepo-ref gate FAILED.")
        print(f"Fix violations or add '{ESCAPE_HATCH}: <reason>' to suppress.")
        return 1

    print(f"Skill monorepo-ref gate PASSED ({len(files)} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
