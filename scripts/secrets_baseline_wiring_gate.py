#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""A repository that carries `.secrets.baseline` must wire a gate that READS it (OMN-18669).

The failure this exists to remove
---------------------------------
`.secrets.baseline` is the allowlist a detect-secrets scan is judged against.
On its own it is inert: it blocks nothing, it proves nothing, and it looks
exactly like a repository that is protected. Measured 2026-09-18 (integration
probe R9, OMN-18521 fan-out census): `omnimemory` carried a committed baseline
that NO pre-commit hook and NO CI workflow read. Its findings were four files
old; a full scan against it surfaced 47 findings in 18 files that nothing had
ever been asked to approve. Nobody had loosened a gate -- there was no gate.

CLAUDE.md rule 5: detection that is not a pre-merge gate is advisory and gets
ignored. So the invariant this enforces is the WIRING, not the scan:

    a repository carrying `.secrets.baseline` MUST carry BOTH
      (a) a pre-commit config entry that reads it, and
      (b) a CI workflow that reads it.

A repository with no baseline passes -- this gate never demands one, because
"should this repository scan for secrets" is a different question with a
different owner. What it refuses is the SILENT state: the file present, and
nothing reading it.

Why both halves, never one
--------------------------
The CI half alone lets a developer commit a live credential and discover it
after it is pushed to a remote -- which is real exposure under rule 22, and the
expensive kind. The pre-commit half alone is a gate any lane can skip with a
flag, and it never sees a commit made on another machine. The two are not
substitutes and this gate accepts neither on its own.

How a "reader" is recognised, and the honest limit
--------------------------------------------------
Matching is literal, over NON-COMMENT lines only, against a small vocabulary
(`BASELINE_TOKENS`). Comment stripping is deliberate and is the OMN-18162 rule
15 lesson applied to a new gate: prose that MENTIONS a trigger must not satisfy
a gate that scans for it, or the gate reports green over documentation about
itself.

The limit, stated rather than implied: this proves a file references the
baseline. It does not prove that reference is reached at runtime, and it cannot
read branch protection, so it cannot prove the CI job is a REQUIRED check. What
it removes is the silent case -- a baseline with no reader anywhere. Whether
the CI reader is required is asserted per repository in the pull request that
wires it; this gate names the file it found so a reviewer can check that claim
instead of assuming it.

Every run executes a POSITIVE CONTROL (rule 16): the evaluator is run against a
synthetic repository that must fail. If the control passes, the matcher is
broken and this exits 2 rather than reporting a clean bill of health, because a
zero from a broken sweep is indistinguishable from a zero from a clean one.

Exit codes
----------
0  no baseline, or baseline with both halves wired
1  baseline present with a half missing (the violation)
2  the gate could not decide -- unreadable config, bad YAML, failed positive
   control. Never a pass.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

BASELINE_FILENAME = ".secrets.baseline"
PRECOMMIT_CONFIG = ".pre-commit-config.yaml"
WORKFLOWS_DIR = Path(".github") / "workflows"

# A line carrying any of these, outside a comment, is a reader of the baseline.
# Kept deliberately small: every entry names a concrete detect-secrets surface
# in use somewhere on the fleet, not a word that could appear by accident.
BASELINE_TOKENS: tuple[str, ...] = (
    ".secrets.baseline",
    "detect-secrets-hook",
    "detect-secrets scan",
    "detect_secrets_guard",
    "detect_secrets_ci_diff",
    "Yelp/detect-secrets",
)


@dataclass(frozen=True)
class ModelWiringInputs:
    """Everything the verdict is computed from, so it can be built synthetically."""

    baseline_present: bool
    precommit_text: str | None
    workflow_texts: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelWiringVerdict:
    ok: bool
    exit_code: int
    lines: list[str]


def strip_comments(text: str) -> list[str]:
    """Return the non-comment content of each line.

    A whole-line comment becomes empty; a trailing comment is cut. This is
    intentionally cruder than a YAML parse: a `#` inside a quoted string loses
    its tail, which can only ever make the gate STRICTER (a reader hidden
    inside a quoted string after a `#` is not counted), never more permissive.
    """
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            out.append("")
            continue
        out.append(raw.split("#", 1)[0])
    return out


def find_reader(text: str) -> str | None:
    """Return the first baseline token found outside a comment, or None."""
    for line in strip_comments(text):
        for needle in BASELINE_TOKENS:
            if needle in line:
                return needle
    return None


def evaluate(inputs: ModelWiringInputs) -> ModelWiringVerdict:
    """Pure verdict function. The positive control depends on this being pure."""
    if not inputs.baseline_present:
        return ModelWiringVerdict(
            ok=True,
            exit_code=0,
            lines=[
                f"PASS: no {BASELINE_FILENAME} in this repository -- nothing to govern.",
                "      This gate never demands a baseline; it refuses a baseline nothing reads.",
            ],
        )

    lines: list[str] = [f"{BASELINE_FILENAME} is present. Both halves are required."]
    failures: list[str] = []

    if inputs.precommit_text is None:
        failures.append(
            f"local half: no {PRECOMMIT_CONFIG} at the repository root, so no "
            f"pre-commit hook can be reading {BASELINE_FILENAME}."
        )
    else:
        matched = find_reader(inputs.precommit_text)
        if matched is None:
            failures.append(
                f"local half: {PRECOMMIT_CONFIG} carries no hook that reads "
                f"{BASELINE_FILENAME}. Wire the detect-secrets pre-commit hook "
                f"with `--baseline {BASELINE_FILENAME}`."
            )
        else:
            lines.append(
                f"  local half  OK -- {PRECOMMIT_CONFIG} matched on {matched!r}"
            )

    ci_hits = sorted(
        name for name, text in inputs.workflow_texts.items() if find_reader(text)
    )
    if not ci_hits:
        failures.append(
            f"CI half: no workflow under {WORKFLOWS_DIR.as_posix()}/ reads "
            f"{BASELINE_FILENAME}. A local-only gate is skippable and never sees "
            f"a commit made on another machine."
        )
    else:
        lines.append(f"  CI half     OK -- read by: {', '.join(ci_hits)}")
        lines.append(
            "              (presence, not requiredness -- confirm this job feeds a "
            "required check)"
        )

    if failures:
        lines.append("")
        lines.extend(f"VIOLATION: {f}" for f in failures)
        lines.append("")
        lines.append(
            "Remedy (OMN-18669): wire the missing half in the same change, or "
            f"delete {BASELINE_FILENAME} and say so. A baseline nobody reads is "
            "the one outcome rule 5 rules out."
        )
        return ModelWiringVerdict(ok=False, exit_code=1, lines=lines)

    lines.append("PASS: both halves wired.")
    return ModelWiringVerdict(ok=True, exit_code=0, lines=lines)


def run_positive_control() -> str | None:
    """Prove the evaluator can still fail. Returns an error string, or None."""
    control = ModelWiringInputs(
        baseline_present=True,
        precommit_text="repos:\n  - repo: local\n    hooks:\n      - id: ruff\n",
        workflow_texts={"ci.yml": "jobs:\n  lint:\n    runs-on: ubuntu-latest\n"},
    )
    verdict = evaluate(control)
    if verdict.ok or verdict.exit_code != 1:
        return (
            "positive control PASSED when it must fail -- a synthetic repository "
            "with a baseline and no reader was accepted. The matcher is broken, so "
            "a clean result from it means nothing."
        )

    comment_control = ModelWiringInputs(
        baseline_present=True,
        precommit_text="# this repo should read .secrets.baseline one day\nrepos: []\n",
        workflow_texts={
            "ci.yml": "# detect-secrets-hook is not wired here\njobs: {}\n"
        },
    )
    if evaluate(comment_control).ok:
        return (
            "comment control PASSED when it must fail -- prose merely MENTIONING "
            "the baseline was accepted as a reader (CLAUDE.md rule 15)."
        )
    return None


def collect(repo_root: Path) -> ModelWiringInputs:
    precommit_path = repo_root / PRECOMMIT_CONFIG
    precommit_text: str | None = None
    if precommit_path.is_file():
        precommit_text = precommit_path.read_text(encoding="utf-8", errors="replace")

    workflow_texts: dict[str, str] = {}
    workflows_dir = repo_root / WORKFLOWS_DIR
    if workflows_dir.is_dir():
        for path in sorted(workflows_dir.iterdir()):
            if path.suffix not in {".yml", ".yaml"} or not path.is_file():
                continue
            workflow_texts[path.name] = path.read_text(
                encoding="utf-8", errors="replace"
            )

    return ModelWiringInputs(
        baseline_present=(repo_root / BASELINE_FILENAME).is_file(),
        precommit_text=precommit_text,
        workflow_texts=workflow_texts,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Refuse a repository that carries .secrets.baseline without a "
            "pre-commit hook AND a CI workflow that read it (OMN-18669)."
        )
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root to inspect (default: the current directory).",
    )
    # Deliberately no --force, no --skip, no allowlist file. A repository that
    # genuinely should not scan deletes its baseline; there is no third answer.
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    control_error = run_positive_control()
    if control_error is not None:
        print(f"ERROR: {control_error}", file=sys.stderr)
        print("THE GATE DID NOT RUN.", file=sys.stderr)
        return 2

    repo_root = Path(args.repo_root)
    if not repo_root.is_dir():
        print(f"ERROR: --repo-root {repo_root} is not a directory.", file=sys.stderr)
        return 2

    try:
        inputs = collect(repo_root)
    except OSError as exc:
        print(f"ERROR: could not read the repository: {exc}", file=sys.stderr)
        print("THE GATE DID NOT RUN.", file=sys.stderr)
        return 2

    verdict = evaluate(inputs)
    stream = sys.stdout if verdict.ok else sys.stderr
    for line in verdict.lines:
        print(line, file=stream)
    return verdict.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
