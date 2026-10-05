# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Verdict harness for the OMN-20566 validator conversion (plan Phase 5, template step 5).

A verdict is the pair ``(exit code, set of (path, line))``. The harness runs a core
check node's runtime module, the hook's own entry point, in a throwaway repository that
holds only the fixture files, and parses the findings out of the printed output.

Nothing here is a validator. It never decides what a finding is: it compares the node's
printed verdict with a golden file captured from the old script before the script was
deleted (in the commits before this one, the same harness ran the script beside the node).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import NamedTuple

import yaml

from tests.scripts.validator_parity_omn20566.corpus import FIXTURE_TOKENS

CORE_REPO = "https://github.com/OmniNode-ai/omnibase_core"
REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# ``path:line`` at the start of a (stripped) output line, or ``path: SyntaxError``.
_FINDING_LINE = re.compile(
    r"^(?:\[[A-Z]+\]\s+)?(?P<path>[\w./@+-]+\.(?:py|sh|bash|ya?ml|json|md)):(?:(?P<line>\d+)\b|\s)"
)


class Verdict(NamedTuple):
    """What a validator run decided: the exit code and where it flagged."""

    exit_code: int
    findings: tuple[tuple[str, int | None], ...]

    def to_json(self) -> dict[str, object]:
        return {
            "exit": self.exit_code,
            "findings": [[path, line] for path, line in self.findings],
        }


def verdict_from_json(raw: Mapping[str, object]) -> Verdict:
    exit_code = raw["exit"]
    findings = raw["findings"]
    assert isinstance(exit_code, int)
    assert isinstance(findings, list)
    return Verdict(
        exit_code=exit_code,
        findings=tuple(
            sorted(
                ((str(p), None if ln is None else int(ln)) for p, ln in findings),
                key=_sort_key,
            )
        ),
    )


def _sort_key(item: tuple[str, int | None]) -> tuple[str, int]:
    return (item[0], -1 if item[1] is None else item[1])


def parse_findings(output: str, root: Path) -> tuple[tuple[str, int | None], ...]:
    """Pull ``(repo-relative path, line)`` pairs out of a validator's printed output."""
    found: set[tuple[str, int | None]] = set()
    prefixes = {str(root) + "/", str(root.resolve()) + "/"}
    for raw_line in output.splitlines():
        text = raw_line.strip()
        for prefix in sorted(prefixes, key=len, reverse=True):
            text = text.replace(prefix, "")
        match = _FINDING_LINE.match(text)
        if match is None:
            continue
        line = match.group("line")
        found.add((match.group("path"), None if line is None else int(line)))
    return tuple(sorted(found, key=_sort_key))


def materialise(root: Path, files: Mapping[str, str]) -> None:
    """Write the fixture files into ``root`` (paths are repo-relative)."""
    for rel, source in files.items():
        for token, literal in FIXTURE_TOKENS.items():
            source = source.replace(token, literal)
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")


def hook_scope(hook_id: str, rels: Iterable[str]) -> list[str]:
    """The paths pre-commit would hand the hook: its ``files:`` and ``exclude:`` regexes.

    Read from the repository's own ``.pre-commit-config.yaml``, so the scope the
    node is tested under is the scope the hook is wired with.
    """
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        hook
        for repo in config["repos"]
        if repo.get("repo") == CORE_REPO
        for hook in repo["hooks"]
        if hook["id"] == hook_id
    ]
    assert len(hooks) == 1, f"{hook_id} must be wired exactly once from {CORE_REPO}"
    hook = hooks[0]
    include = re.compile(hook.get("files", ""))
    exclude = re.compile(hook["exclude"]) if "exclude" in hook else None
    return sorted(
        rel
        for rel in rels
        if include.search(rel) and not (exclude and exclude.search(rel))
    )


def run_script(
    root: Path,
    script: str,
    helpers: Iterable[str],
    args: list[str],
) -> Verdict:
    """Run an OLD validation script copied to the same relative location in ``root``.

    The scripts find the repository root by walking up from ``__file__``, so the
    copy must sit at the same depth as the original, and the tree needs the
    ``pyproject.toml`` marker the walk stops at.
    """
    (root / "pyproject.toml").touch()
    for rel in (script, *helpers):
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, destination)
    proc = subprocess.run(
        [sys.executable, script, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return Verdict(proc.returncode, parse_findings(proc.stdout + proc.stderr, root))


def hook_args(hook_id: str) -> list[str]:
    """The ``args:`` the repository's config gives a core hook that takes no filenames."""
    config = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        hook
        for repo in config["repos"]
        if repo.get("repo") == CORE_REPO
        for hook in repo["hooks"]
        if hook["id"] == hook_id
    ]
    assert len(hooks) == 1, f"{hook_id} must be wired exactly once from {CORE_REPO}"
    return [str(arg) for arg in hooks[0].get("args", [])]


def run_node(root: Path, module: str, args: list[str]) -> Verdict:
    """Run the core check node's runtime module, the hook's own entry point."""
    proc = subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return Verdict(proc.returncode, parse_findings(proc.stdout + proc.stderr, root))


def load_golden(rule: str) -> dict[str, Verdict]:
    raw = json.loads((GOLDEN_DIR / f"{rule}.json").read_text(encoding="utf-8"))
    return {name: verdict_from_json(entry) for name, entry in raw.items()}


def dump_golden(rule: str, verdicts: Mapping[str, Verdict]) -> None:
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    payload = {name: verdict.to_json() for name, verdict in sorted(verdicts.items())}
    (GOLDEN_DIR / f"{rule}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
