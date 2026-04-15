# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

# CI lint gate — OMN-8795 (SD-08)
# Fails if any skill file contains monorepo-local references that would break
# standalone plugin installs. Gate goes green after SD-04/SD-05/SD-07 merge.

import re
from pathlib import Path

import pytest

# Each entry: (regex_pattern, replacement_guidance)
FORBIDDEN_PATTERNS = [
    (
        r"\$OMNI_HOME",
        "Use $ONEX_STATE_DIR or $ONEX_WORKTREES_ROOT instead",
    ),
    (
        r"uv run python -m omni",
        "Use 'onex run <node_name>' instead — see OMN-8770 standalone install",
    ),
    (
        r"/Users/jonah/",  # local-path-ok: this file IS the pattern registry
        "Hardcoded user path — use environment variable instead",
    ),
    (
        r"/Volumes/PRO-G40/",  # local-path-ok: this file IS the pattern registry
        "Hardcoded volume path — use environment variable instead",
    ),
]

_ESCAPE_HATCH = "# local-path-ok"


def _all_skill_files() -> list[Path]:
    skills_root = Path(__file__).parent.parent.parent / "plugins" / "onex" / "skills"
    md_files = list(skills_root.rglob("*.md"))
    return md_files


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "skill_file" in metafunc.fixturenames:
        files = _all_skill_files()
        metafunc.parametrize(
            "skill_file",
            files,
            ids=[
                str(f.relative_to(Path(__file__).parent.parent.parent)) for f in files
            ],
        )


def test_no_monorepo_refs(skill_file: Path) -> None:
    lines = skill_file.read_text().splitlines()
    violations: list[str] = []
    escape_hatch_with_reason = re.compile(r"#\s*local-path-ok\b\s+.+")
    for lineno, line in enumerate(lines, start=1):
        if _ESCAPE_HATCH in line:
            if not escape_hatch_with_reason.search(line):
                violations.append(
                    f"  line {lineno}: escape hatch requires a reason after '# local-path-ok'"
                )
            continue
        for pattern, message in FORBIDDEN_PATTERNS:
            if re.search(pattern, line):
                violations.append(f"  line {lineno}: {pattern!r} matched — {message}")
    if violations:
        violation_text = "\n".join(violations)
        pytest.fail(
            f"{skill_file}: monorepo reference(s) found (add '# local-path-ok' to suppress):\n{violation_text}"
        )
