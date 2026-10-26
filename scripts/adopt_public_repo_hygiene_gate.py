#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Generate a repository's public-repo hygiene gate adoption files (OMN-18016).

Adopting the gate is two files, and both are mechanical:

* ``.public-repo-hygiene.yaml`` — layer (a), the repo's declaration of its
  permitted TOP-LEVEL entries. Seeded from the repo's live root tree so the
  first run is not 40 false ``top-level-not-allowed`` findings, MINUS the
  entries that are themselves findings. That subtraction is the point of this
  script: an allowlist generated blindly from the current tree would bless
  every junk directory in it, and the gate would then certify the exact
  material it was built to refuse.
* ``.github/workflows/public-repo-hygiene.yml`` — the thin caller, pinned to
  an immutable omniclaude SHA.

Seeding an allowlist is a decision, not a formality. Anything this script
excludes is left OUT so the gate reports it, and the exclusion list is printed
so the operator sees what was withheld rather than discovering it later.

The plan requires every new public repository to get the gate at creation.
That is only true if adoption is one command; two repositories in the org
today ship with no gate, no LICENSE and no SECURITY.md, which is what
"someone will remember to add it" looks like after a year.

## Usage

    python3 scripts/adopt_public_repo_hygiene_gate.py --repo omnibase_spi \\
        --pin <omniclaude-sha> --out-dir <path-to-that-repo>

    python3 scripts/adopt_public_repo_hygiene_gate.py --repo omnibase_spi \\
        --pin <sha> --print   # dry run, writes nothing

## Exit codes

0  files generated (or printed)
1  the repository's root tree could not be read — never a partial write
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

OWNER = "OmniNode-ai"
CONFIG_BASENAME = ".public-repo-hygiene.yaml"
WORKFLOW_PATH = ".github/workflows/public-repo-hygiene.yml"

# Root entries that are THEMSELVES findings. Never seeded into an allowlist:
# blessing them at adoption time would make the gate certify the material it
# exists to refuse, and would do it silently, in the one commit nobody reads
# closely.
NEVER_SEED: frozenset[str] = frozenset(
    {
        ".onex",
        ".onex_state",
        ".claude_scratch",
        ".evidence",
        ".repowise-workspace",
        ".repowise-workspace.yaml",
        "drift",
        "merge-sweep",
        ".DS_Store",
    }
)

# Entries the gate creates, so they must be permitted even though they are not
# in the tree yet. ``.github`` is here for the same reason the other two are:
# this script WRITES .github/workflows/public-repo-hygiene.yml, and three
# public repos (omnibot, omnigemini, omnibase) carry no ``.github`` directory
# at all -- so a tree-seeded allowlist omitted it and the gate's first run
# reported the caller workflow the adoption had just written as
# ``top-level-not-allowed``. In enforce mode that gate would refuse the commit
# that installs it.
ALWAYS_SEED: tuple[str, ...] = (
    ".github",
    ".public-repo-hygiene.yaml",
    ".public-repo-hygiene-suppressions.yaml",
)


class AdoptionError(Exception):
    """The adoption could not be generated. Never a partial write."""


def root_entries(repo: str, ref: str) -> list[str]:
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{OWNER}/{repo}/git/trees/{ref}",
            "--jq",
            ".tree[].path",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AdoptionError(
            f"could not read the root tree of {OWNER}/{repo}@{ref}: "
            f"{proc.stderr.strip()}. Refusing to generate an allowlist from an "
            "unread tree — an empty result would produce a config that fails "
            "every file, or worse, one that looks plausible."
        )
    entries = sorted(
        {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    )
    if not entries:
        raise AdoptionError(
            f"the root tree of {OWNER}/{repo}@{ref} came back EMPTY. An empty "
            "result is not evidence of an empty repository."
        )
    return entries


def render_config(repo: str, ref: str, entries: list[str]) -> tuple[str, list[str]]:
    withheld = sorted(e for e in entries if e in NEVER_SEED)
    allowed = sorted({e for e in entries if e not in NEVER_SEED} | set(ALWAYS_SEED))

    withheld_note = (
        "\n".join(
            f"#   {e} — a finding, not a root entry. Fix or delete it; do not"
            for e in withheld
        )
        + "\n#     add it here."
        if withheld
        else "#   (none — every root entry in this repo is legitimate)"
    )

    body = f"""# Public-repository hygiene gate — this repo's declaration (OMN-18014).
#
# Layer (a) of the gate: the TOP-LEVEL PATH ALLOWLIST. Anything tracked at the
# repository root that is not named below fails. This is the half that refuses
# the next junk directory nobody has invented yet — a denylist must anticipate
# that directory, an allowlist does not.
#
# Seeded from {OWNER}/{repo}@{ref} at adoption time, MINUS the entries that
# are themselves findings. Adding an entry here is a decision to publish that
# directory, not a formality.
#
# WITHHELD AT ADOPTION, and they must stay withheld:
{withheld_note}
#
# mode: report — the gate records every finding with a per-class count and
# exits 0. It flips to enforce when the residue is FIXED, never by moving the
# residue into this file: that is the recurrence mechanism the OMN-17992
# programme exists to remove.

mode: report
suppression_registry: ".public-repo-hygiene-suppressions.yaml"

allowed_top_level:
"""
    body += "".join(f'  - "{e}"\n' for e in allowed)
    return body, withheld


def render_workflow(repo: str, ref: str, pin: str) -> str:
    return f"""# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# Public Repo Hygiene -- thin caller. OMN-18016, epic OMN-17992.
#
# This repository is PUBLIC. The gate refuses internal operating detail landing
# in it: an undeclared top-level directory, an agent-state or evidence tree, a
# misplaced dated document, a brand asset, an env file, cloud identity, a
# private address, an operator machine path, a private repository name, and
# internal-KB prose in a public README.
#
# mode: report. The gate records every finding and exits 0, so it lands without
# blocking unrelated PRs on a repository that carries pre-existing residue. It
# flips to enforce when that residue is FIXED -- never by moving it into
# .public-repo-hygiene.yaml.
#
# Layer (a) reads .public-repo-hygiene.yaml at this repo's root; the gate
# refuses to run without it rather than treating an absent config as an empty
# allowlist.
#
# `secrets: inherit` IS REQUIRED: the denylist vocabulary lives in a private
# repository and the reusable workflow mints an installation token to read it.
# Without the secrets the gate fails CLOSED, which is the correct behaviour and
# a loud one.
#
# The pin is a SINGLE source of truth: the reusable workflow checks its own
# validator out at validated job.workflow_sha, i.e. this very SHA, so the
# workflow and the script can never drift apart. Pin to an omniclaude commit on `dev`;
# `main` is release-synced and does not carry the gate.

name: Public Repo Hygiene

on:
  pull_request:
    branches: [{ref}]

jobs:
  public-repo-hygiene:
    uses: {OWNER}/omniclaude/.github/workflows/public-repo-hygiene-reusable.yml@{pin}
    with:
      mode: report
    secrets: inherit
"""


def render_ratchet_rollout(root: Path, pin: str, baseline: str) -> dict[str, str]:
    """Prepare adoption changes without changing any gate exception/declaration.

    The measured candidate baseline is still checked against the trusted base
    by CI. Supplying one here grants no permission to increase it.
    """
    if not re.fullmatch(r"[a-f0-9]{40}", pin):
        raise AdoptionError("ratchet rollout requires an immutable 40-hex gate pin")
    try:
        from scripts.public_repo_hygiene_gate import (
            ConfigError,
            load_deployment_baseline,
            render_deployment_declaration,
        )
    except ModuleNotFoundError:
        from public_repo_hygiene_gate import (
            ConfigError,
            load_deployment_baseline,
            render_deployment_declaration,
        )
    try:
        load_deployment_baseline(baseline)
    except ConfigError as exc:
        raise AdoptionError(str(exc)) from exc
    workflow = (root / WORKFLOW_PATH).read_text()
    workflow, count = re.subn(
        r"(OmniNode-ai/omniclaude/\.github/workflows/public-repo-hygiene-reusable\.yml@)[a-f0-9]{40}",
        lambda match: match[1] + pin,
        workflow,
    )
    if count != 1:
        raise AdoptionError("expected exactly one pinned reusable hygiene caller")
    if re.search(r"^\s+deployment_config_ratchet:", workflow, re.M):
        workflow = re.sub(
            r"(?m)^(\s+)deployment_config_ratchet:.*$",
            r"\1deployment_config_ratchet: true",
            workflow,
        )
    else:
        workflow, count = re.subn(
            r"(?m)^(\s+)mode: (?:report|enforce)\s*$",
            r"\g<0>\n\1deployment_config_ratchet: true",
            workflow,
        )
        if count != 1:
            raise AdoptionError("expected one mode declaration in the reusable caller")
    precommit = (root / ".pre-commit-config.yaml").read_text()
    lines = precommit.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = re.match(r"^(\s*)- id: deployment-config\s*$", line)
        if match:
            repo_starts = [
                i for i in range(index) if re.match(r"^\s*- repo:", lines[i])
            ]
            if (
                not repo_starts
                or "https://github.com/OmniNode-ai/omniclaude"
                not in lines[repo_starts[-1]]
            ):
                raise AdoptionError(
                    "deployment-config must come from the canonical gate repository"
                )
            revision_lines = [
                i
                for i in range(repo_starts[-1] + 1, index)
                if re.match(r"^\s+rev:", lines[i])
            ]
            if len(revision_lines) != 1:
                raise AdoptionError(
                    "expected one immutable deployment-config hook revision"
                )
            revision = revision_lines[0]
            lines[revision], count = re.subn(
                r"(rev: )[a-f0-9]{40}", lambda match: match[1] + pin, lines[revision]
            )
            if count != 1:
                raise AdoptionError("deployment-config hook revision must be immutable")
            indent = len(match[1])
            end = index + 1
            while end < len(lines):
                next_line = lines[end]
                if next_line.strip() and not next_line.lstrip().startswith("#"):
                    if len(next_line) - len(next_line.lstrip()) <= indent:
                        break
                end += 1
            body = lines[index + 1 : end]
            # Keep unrelated hook settings and comments, while replacing scope.
            keys = {"args", "pass_filenames", "always_run"}
            body = [
                entry
                for entry in body
                if not any(re.match(rf"^\s+{key}:", entry) for key in keys)
            ]
            scope = " " * (indent + 2)
            body.extend(
                [
                    f"{scope}args: [--ratchet]\n",
                    f"{scope}pass_filenames: false\n",
                    f"{scope}always_run: true\n",
                ]
            )
            lines[index + 1 : end] = body
            break
    else:
        raise AdoptionError("deployment-config hook is absent; adopt the class first")
    files = {
        WORKFLOW_PATH: workflow,
        ".pre-commit-config.yaml": "".join(lines),
        ".public-repo-hygiene.yaml": render_deployment_declaration(
            (root / CONFIG_BASENAME).read_text(), load_deployment_baseline(baseline)
        ),
    }
    summary_path = "scripts/ci/ci_summary_gate.py"
    summary = root / summary_path
    if summary.is_file():
        text = summary.read_text()
        for statement in ast.parse(text).body:
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else (
                    [statement.target] if isinstance(statement, ast.AnnAssign) else []
                )
            )
            if any(
                isinstance(target, ast.Name)
                and target.id == "EXPECTED_EXTERNAL_CONTEXTS"
                for target in targets
            ):
                contexts = ast.literal_eval(statement.value)
                required = (
                    "public-repo-hygiene / public-repo-hygiene",
                    "public-repo-hygiene / deployment-config",
                )
                missing = [context for context in required if context not in contexts]
                if missing:
                    # Insert at the tuple's closing delimiter, preserving its comments.
                    value = statement.value
                    assert (
                        value is not None
                        and value.end_lineno is not None
                        and value.end_col_offset is not None
                    )
                    source_lines = text.splitlines(keepends=True)
                    row = value.end_lineno - 1
                    column = value.end_col_offset - 1
                    source_lines[row] = (
                        source_lines[row][:column]
                        + "".join(f'    "{context}",\n' for context in missing)
                        + source_lines[row][column:]
                    )
                    text = "".join(source_lines)
                files[summary_path] = text
                break
        else:
            raise AdoptionError("CI Summary has no external-context registration")
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--repo", required=True)
    parser.add_argument(
        "--ref", default=None, help="default branch; resolved live if omitted"
    )
    parser.add_argument("--pin", required=True, help="immutable omniclaude SHA")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--print", dest="print_only", action="store_true")
    parser.add_argument(
        "--ratchet-rollout-root",
        type=Path,
        help="prepare whole-tree rollout files from an existing checkout without changing its exception declaration",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="measured candidate baseline for --ratchet-rollout-root",
    )
    args = parser.parse_args(argv)

    if args.ratchet_rollout_root is not None:
        try:
            if args.baseline is None:
                raise AdoptionError("ratchet rollout requires --baseline")
            files = render_ratchet_rollout(
                args.ratchet_rollout_root, args.pin, args.baseline.read_text()
            )
            for relative, content in files.items():
                if args.print_only or args.out_dir is None:
                    print(f"=== {relative} ===\n{content}")
                else:
                    target = args.out_dir / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                    print(f"wrote {target}")
        except (AdoptionError, OSError, ValueError) as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        return 0

    try:
        ref = args.ref
        if ref is None:
            proc = subprocess.run(
                ["gh", "api", f"repos/{OWNER}/{args.repo}", "--jq", ".default_branch"],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                raise AdoptionError(
                    f"could not resolve the default branch of {args.repo}: "
                    f"{proc.stderr.strip()}"
                )
            ref = proc.stdout.strip()
        entries = root_entries(args.repo, ref)
        config, withheld = render_config(args.repo, ref, entries)
        workflow = render_workflow(args.repo, ref, args.pin)
    except AdoptionError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if withheld:
        print(f"{args.repo}: WITHHELD from the allowlist ({len(withheld)}):")
        for entry in withheld:
            print(f"  {entry}")
    else:
        print(f"{args.repo}: nothing withheld — every root entry is legitimate")

    if args.print_only or args.out_dir is None:
        print(f"\n=== {CONFIG_BASENAME} ===\n{config}")
        print(f"=== {WORKFLOW_PATH} ===\n{workflow}")
        return 0

    (args.out_dir / CONFIG_BASENAME).write_text(config, encoding="utf-8")
    workflow_file = args.out_dir / WORKFLOW_PATH
    workflow_file.parent.mkdir(parents=True, exist_ok=True)
    workflow_file.write_text(workflow, encoding="utf-8")
    print(f"\nwrote {args.out_dir / CONFIG_BASENAME}")
    print(f"wrote {workflow_file}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
