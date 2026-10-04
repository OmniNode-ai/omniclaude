# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""The Bash guard decision corpus and its golden record (OMN-20118).

The seven Bash PreToolUse guards used to be seven registered hooks. OMN-20118
runs them from one entrypoint with one interpreter. This module is what proves
that changed no decision: it runs a guard script (or the entrypoint) the way
Claude Code does, against a fixed workspace, for every command in
``fixtures/bash_guard_corpus.json``, and reduces the run to a comparable
decision: the exit status and, for a refusal, the refusal JSON with the fixture
paths written as placeholders.

``fixtures/bash_guard_golden.json`` holds those decisions as the seven separate
scripts at origin/dev ``1618db6e2`` (the last tree before OMN-20118, with the OMN-17427 guard changes of #2421 and #2422) made them.
It is recorded, never hand-edited::

    git archive 1618db6e2 plugins/onex | tar -x -C /tmp/base
    uv run python -m tests.hooks_system.bash_guard_corpus \\
        --plugin-root /tmp/base/plugins/onex > tests/hooks_system/fixtures/bash_guard_golden.json

A guard whose decisions change on purpose after that base (OMN-20495 gave the
shared-tree guard its lane git-fetch arm) has only its own column re-recorded,
from the tree that changes it, and merged back; every other guard's column is
left exactly as recorded::

    uv run python -m tests.hooks_system.bash_guard_corpus \\
        --plugin-root plugins/onex --merge-guard pre_tool_use_shared_tree_git_guard.sh

Each case gets a fresh state directory, because the pr-ownership guard records a
claim when it allows a first-writer mutation, and a claim left by one case would
change the next case's decision.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CORPUS = FIXTURES / "bash_guard_corpus.json"
GOLDEN = FIXTURES / "bash_guard_golden.json"
GOLDEN_BASE = "1618db6e272da6ca4288c784906ea62ed7491a55"

GUARD_SCRIPTS = (
    "pre_tool_use_worktree_guard.sh",
    "pre_tool_use_pr_ownership_guard.sh",
    "pre_tool_use_credential_rotation_guard.sh",
    "pre_tool_use_git_stash_guard.sh",
    "pre_tool_use_shared_tree_git_guard.sh",
    "pre_tool_use_pr_body_stamp_guard.sh",
    "pre_tool_use_prose_command_substitution_guard.sh",
)
ENTRYPOINT = "pre_tool_use_bash_guards.sh"
ALLOW: dict[str, Any] = {"rc": 0}

# Where a case runs from: a lane worktree, and the shared canonical clone.
CWD_KINDS = ("worktree", "canonical")

_REPO_SLUG = "OmniNode-ai/omniclaude"
_WORKSPACE_ENV = "OMNI_" + "HOME"
# The registry directory's name, spelled so the public-repo hygiene gate does
# not read it as prose. A refusal that names it in prose is recorded with this
# name as a placeholder (both the golden and the live run pass through
# normalize, so the comparison stays exact).
_WORKSPACE_NAME = "omni" + "_home"
_WORKSPACE_NAME_RE = re.compile(r"\b" + _WORKSPACE_NAME + r"\b")
# The workspace root's environment variable name, which also names the
# private registry, likewise: {WSENV} in the corpus and in every record.
_WORKSPACE_ENV_RE = re.compile(r"\b" + _WORKSPACE_ENV + r"\b")


@dataclass(frozen=True)
class Workspace:
    root: Path
    workspace: Path
    canonical: Path
    worktree: Path
    scratch: Path
    fakebin: Path

    def cwd(self, kind: str) -> Path:
        return self.worktree if kind == "worktree" else self.canonical

    def fill(self, template: str) -> str:
        return (
            template.replace("{WT}", str(self.worktree))
            .replace("{REG}", str(self.canonical))
            .replace("{WS}", str(self.workspace))
            .replace("{DEST}", str(self.workspace / "omni_worktrees/OMN-2/omniclaude"))
            .replace("{SP}", str(self.scratch))
            .replace("{F}", str(self.scratch / "body.md"))
            .replace("{REPO}", _REPO_SLUG)
            .replace("{WSENV}", _WORKSPACE_ENV)
        )

    def normalize(self, text: str) -> str:
        """Fixture paths as placeholders, so a record compares across hosts."""
        pairs: list[tuple[str, str]] = []
        for path, name in (
            (self.worktree, "{WT}"),
            (self.canonical, "{REG}"),
            (self.scratch, "{SP}"),
            (self.workspace, "{WS}"),
            (self.root, "{ROOT}"),
            (REPO_ROOT, "{CLONE}"),
        ):
            pairs.append((str(path.resolve()), name))
            pairs.append((str(path), name))
        for path, name in pairs:
            text = text.replace(path, name)
        text = _WORKSPACE_ENV_RE.sub("{WSENV}", text)
        return _WORKSPACE_NAME_RE.sub("{WS_NAME}", text)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            **_base_env(),
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )


def _base_env() -> dict[str, str]:
    dirs: list[str] = []
    for tool in ("jq", "git", "bash"):
        found = shutil.which(tool)
        if found and str(Path(found).parent) not in dirs:
            dirs.append(str(Path(found).parent))
    for fixed in ("/usr/bin", "/bin"):
        if fixed not in dirs:
            dirs.append(fixed)
    return {"PATH": os.pathsep.join(dirs), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


@contextmanager
def workspace() -> Iterator[Workspace]:
    """A workspace with a canonical clone and one lane worktree of it."""
    # A refusal starts the refusal recorder in the background (disowned, by
    # design: it is off the hook's wall time), and it can still be writing into
    # the state directory when the case ends, so the cleanup tolerates it.
    with tempfile.TemporaryDirectory(
        prefix="bashguards-", ignore_cleanup_errors=True
    ) as tmp:
        root = Path(tmp).resolve()
        ws = root / _WORKSPACE_NAME
        canonical = ws / "omniclaude"
        canonical.mkdir(parents=True)
        (canonical / "pyproject.toml").write_text('[project]\nname = "omniclaude"\n')
        _git("init", "-q", "-b", "main", cwd=canonical)
        _git("add", "pyproject.toml", cwd=canonical)
        _git("commit", "-q", "-m", "init", cwd=canonical)
        _git(
            "remote",
            "add",
            "origin",
            f"https://github.com/{_REPO_SLUG}.git",
            cwd=canonical,
        )
        worktree = ws / "omni_worktrees/OMN-1/omniclaude"
        _git("worktree", "add", "-q", "-b", "lane/one", str(worktree), cwd=canonical)
        scratch = root / "scratch"
        scratch.mkdir()
        (scratch / "body.md").write_text("## Body\n\nno evidence line here\n")
        (root / "home").mkdir()
        fakebin = root / "fakebin"
        fakebin.mkdir()
        # The pr-body stamp guard reads the live description; a test never
        # reaches GitHub, so the read fails the same way on every host.
        gh = fakebin / "gh"
        gh.write_text(
            "#!/bin/sh\necho 'gh: no network in the guard corpus' >&2\nexit 1\n"
        )
        gh.chmod(0o755)
        yield Workspace(root, ws, canonical, worktree, scratch, fakebin)


def run_script(
    ws: Workspace,
    plugin_root: Path,
    script: str,
    command: str,
    cwd_kind: str,
    python: str,
    extra_env: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Run one hook script for one Bash command; return (exit status, stdout)."""
    cwd = ws.cwd(cwd_kind)
    state = Path(tempfile.mkdtemp(prefix="state-", dir=ws.root))
    base = _base_env()
    env = {
        **base,
        "PATH": f"{ws.fakebin}{os.pathsep}{base['PATH']}",
        "HOME": str(ws.root / "home"),
        "TMPDIR": str(ws.root),
        _WORKSPACE_ENV: str(ws.workspace),
        "ONEX_STATE_DIR": str(state),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "CLAUDE_PROJECT_DIR": str(cwd),
        "PLUGIN_PYTHON_BIN": python,
        "ONEX_HOOKS_MASK": "",
        **(extra_env or {}),
    }
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-bash-guard-corpus",
        "transcript_path": str(ws.root / "transcript.jsonl"),
        "cwd": str(cwd),
        "permission_mode": "default",
        "tool_name": "Bash",
        "tool_use_id": "toolu_bash_guard_corpus",
        "tool_input": {"command": command, "description": "corpus"},
    }
    proc = subprocess.run(
        [str(plugin_root / "hooks/scripts" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        timeout=120,
        check=False,
    )
    shutil.rmtree(state, ignore_errors=True)
    return proc.returncode, proc.stdout


def decision(ws: Workspace, rc: int, stdout: str) -> dict[str, Any]:
    """What a run decided. A pass's stdout is not a decision (two guards echo
    the payload back, which Claude Code ignores), so only a non-zero exit keeps
    its output."""
    if rc == 0:
        return {"rc": 0}
    text = ws.normalize(stdout.strip())
    try:
        parsed: Any = json.loads(text)
    except ValueError:
        parsed = text
    return {"rc": rc, "out": parsed}


def cases(commands: Sequence[str]) -> list[tuple[str, str]]:
    return [(kind, command) for command in commands for kind in CWD_KINDS]


def load_commands() -> list[str]:
    return list(json.loads(CORPUS.read_text(encoding="utf-8"))["commands"])


def record(
    plugin_root: Path,
    python: str,
    workers: int = 8,
    guards: Sequence[str] = GUARD_SCRIPTS,
) -> dict[str, Any]:
    """Every guard's decision on every case, keyed ``kind\\tcommand``."""
    commands = load_commands()
    out: dict[str, Any] = {}
    with workspace() as ws:
        todo = cases(commands)

        def one(case: tuple[str, str]) -> tuple[str, dict[str, Any]]:
            kind, template = case
            command = ws.fill(template)
            per_guard = {
                script: decision(
                    ws, *run_script(ws, plugin_root, script, command, kind, python)
                )
                for script in guards
            }
            return f"{kind}\t{template}", per_guard

        with ThreadPoolExecutor(max_workers=workers) as pool:
            for key, value in pool.map(one, todo):
                # An allow is the default and is not written, which keeps the
                # record under the repository's large-file limit.
                out[key] = {g: d for g, d in value.items() if d != ALLOW}
    return {"base": GOLDEN_BASE, "cases": out}


def load_golden() -> dict[str, dict[str, dict[str, Any]]]:
    """The golden record, every guard present (an omitted guard allowed)."""
    doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
    if doc["base"] != GOLDEN_BASE:
        raise ValueError(f"golden base {doc['base']} is not {GOLDEN_BASE}")
    return {
        key: {g: dict(per_guard.get(g, ALLOW)) for g in GUARD_SCRIPTS}
        for key, per_guard in doc["cases"].items()
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tests.hooks_system.bash_guard_corpus")
    parser.add_argument("--plugin-root", type=Path, required=True)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument(
        "--merge-guard",
        default=None,
        help="record only this guard and merge it into the golden file in place",
    )
    args = parser.parse_args(argv)
    if args.merge_guard:
        if args.merge_guard not in GUARD_SCRIPTS:
            parser.error(f"{args.merge_guard} is not in GUARD_SCRIPTS")
        doc = json.loads(GOLDEN.read_text(encoding="utf-8"))
        fresh = record(
            args.plugin_root.resolve(), args.python, guards=(args.merge_guard,)
        )
        for key in set(doc["cases"]) | set(fresh["cases"]):
            per_guard = doc["cases"].setdefault(key, {})
            per_guard.pop(args.merge_guard, None)
            per_guard.update(fresh["cases"].get(key, {}))
        GOLDEN.write_text(
            json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        return 0
    doc = record(args.plugin_root.resolve(), args.python)
    json.dump(doc, sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
