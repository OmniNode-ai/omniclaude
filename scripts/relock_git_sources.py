#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Advance this repo's immutable git-rev sibling pins to the clone head (OMN-18752).

## The gap this closes

``.github/workflows/sibling-lock-refresh.yml`` (OMN-13902) is the surface that
already owns "make the lock follow its upstream". Its own header records why it
could not do so for one class of pin:

    Repos whose siblings are pinned to an immutable git rev/tag in
    ``[tool.uv.sources]`` ... are left untouched — ``uv lock
    --upgrade-package`` cannot move a pinned rev

``pyproject.toml`` repeats the same sentence. That is mechanically true and it
is why advancing ``omnimarket`` has been a hand-filed ticket every time
(OMN-18622, OMN-18639, and a third the same week). omnimarket publishes
release-on-merge, so the pin goes stale on essentially every omnimarket PR, and
each staleness window is one in which the plugin CLI venv and the lock disagree
about which commit is correct.

``uv lock --upgrade-package`` cannot move the rev because the rev is **input**,
not output. So this module moves the input first: it rewrites the rev in
``pyproject.toml``, and ``uv lock`` then re-resolves against it. That is the
whole trick, and it is why this lives beside the workflow rather than inside
uv.

## Forward only, and refused rather than clamped

The canonical clone is the authority (see ``git_source_pins``), but "follow the
clone" must never mean "follow the clone backwards". A candidate that is not a
**strict descendant** of the current rev raises ``ErrorNotADescendant`` and
nothing is written — the file is byte-identical afterwards. A clamp would be
worse than a refusal here: it would silently keep a stale pin while reporting
success, which is the failure shape OMN-18663 already had to close once.

Ancestry is resolved against a real clone, never against version strings. The
clone is a parameter so the workflow can point at its own checkout and the
tests can point at a fixture, with no network in either case.

## Why both occurrences move together

In ``omniclaude/pyproject.toml`` the sha appears twice — once in the
``dependencies`` entry (``omnimarket @ git+...@<sha>``) and once in
``[tool.uv.sources]`` (``rev = "<sha>"``). uv will not resolve a tree where
those disagree, so a rewrite that moved one and not the other would produce a
lock failure rather than a stale pin. ``rewrite_rev`` returns the occurrence
count and the caller asserts it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import git_source_pins as gsp  # noqa: E402

_GIT_TIMEOUT_SECONDS = 30


class ErrorRelock(Exception):
    """Base for every refusal in this module."""


class ErrorNotADescendant(ErrorRelock):
    """The candidate rev would move the pin backwards or sideways."""


class ErrorRevNotFound(ErrorRelock):
    """The current rev does not appear in the file being rewritten."""


@dataclass(frozen=True)
class ModelRevAdvance:
    package: str
    old_rev: str
    new_rev: str


def _git(clone: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Same GIT_DIR scrub as ``git_source_pins._git`` — see its comment."""
    return subprocess.run(
        ["git", "-C", str(clone), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=_GIT_TIMEOUT_SECONDS,
        env=gsp._clean_git_env(),
    )


def plan_rev_advance(
    *, clone: Path, package: str, current: str, candidate: str
) -> ModelRevAdvance | None:
    """Decide whether ``current`` may advance to ``candidate``.

    Returns None when already at the candidate (an ordinary no-op, not an
    error). Raises ``ErrorNotADescendant`` for every other non-advance, so a
    refusal is loud and a caller cannot mistake it for "nothing to do".
    """
    if current == candidate:
        return None

    for commit, label in ((current, "current"), (candidate, "candidate")):
        if _git(clone, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
            raise ErrorNotADescendant(
                f"{package}: the {label} rev {commit[:12]} is not present in the "
                f"clone {clone}; ancestry cannot be proven, so the advance is "
                f"refused rather than assumed"
            )

    if _git(clone, "merge-base", "--is-ancestor", current, candidate).returncode != 0:
        raise ErrorNotADescendant(
            f"{package}: candidate {candidate[:12]} is not a strict descendant of "
            f"the current rev {current[:12]} — advancing would move the pin "
            f"backwards or onto a diverged line. Refused; nothing written"
        )

    return ModelRevAdvance(package=package, old_rev=current, new_rev=candidate)


def rewrite_rev(*, pyproject: Path, package: str, old_rev: str, new_rev: str) -> int:
    """Replace every occurrence of ``old_rev`` in ``pyproject``; return the count.

    The sha is a 40-hex string, so a literal replace is unambiguous — there is
    no plausible second meaning for it in this file. Raises when the rev is
    absent, because silently rewriting nothing and reporting success is the
    exact failure this whole ticket exists to remove.
    """
    text = pyproject.read_text(encoding="utf-8")
    count = text.count(old_rev)
    if count == 0:
        raise ErrorRevNotFound(
            f"{package}: rev {old_rev[:12]} does not appear in {pyproject}; "
            f"refusing to report a rewrite that did not happen"
        )
    pyproject.write_text(text.replace(old_rev, new_rev), encoding="utf-8")
    return count


def advance_all(
    *,
    repo_root: Path,
    registry_root: str | None = None,
    packages: list[str] | None = None,
) -> list[ModelRevAdvance]:
    """Advance every git-sourced pin in ``uv.lock`` to its canonical clone head.

    Each package is resolved independently so one unresolvable clone does not
    block the others; its refusal is raised to the caller only if that package
    was explicitly requested.
    """
    lock = repo_root / "uv.lock"
    pyproject = repo_root / "pyproject.toml"
    sources = gsp.parse_git_sources(lock)
    authority = gsp.read_authority(pyproject)
    wanted = {gsp.normalize(p) for p in packages} if packages else None

    advanced: list[ModelRevAdvance] = []
    for name, source in sorted(sources.items()):
        if wanted is not None and name not in wanted:
            continue
        # Only a DECLARED clone-governed source follows the clone. Advancing an
        # undeclared one would open a bump PR on a repo whose rev is a reviewed
        # pin with nothing enforcing the clone — see the authority table in
        # pyproject.toml and ``EnumGitSourceAuthority``.
        declared = authority.get(name, gsp.EnumGitSourceAuthority.LOCK)
        if declared is not gsp.EnumGitSourceAuthority.CLONE:
            print(f"[relock] skip {name}: authority is {declared.value}, not clone")
            continue
        clone = gsp.canonical_clone(source.repo, registry_root)
        if clone is None:
            message = (
                f"{name}: no canonical clone for {source.repo!r} under OMNI_HOME; "
                f"cannot resolve the authority head"
            )
            if wanted is not None:
                raise ErrorRelock(message)
            print(f"[relock] skip — {message}", file=sys.stderr)
            continue
        head = gsp.clone_head(clone)
        if head is None:
            raise ErrorRelock(f"{name}: cannot read HEAD of {clone}")
        plan = plan_rev_advance(
            clone=clone, package=name, current=source.rev, candidate=head
        )
        if plan is None:
            print(f"[relock] {name}: already at clone head {head[:12]}")
            continue
        moved = rewrite_rev(
            pyproject=pyproject,
            package=name,
            old_rev=plan.old_rev,
            new_rev=plan.new_rev,
        )
        print(
            f"[relock] {name}: {plan.old_rev[:12]} -> {plan.new_rev[:12]} "
            f"({moved} occurrence(s) rewritten in pyproject.toml)"
        )
        advanced.append(plan)
    return advanced


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root holding pyproject.toml and uv.lock",
    )
    parser.add_argument(
        "--registry-root",
        default=None,
        help="registry root holding the canonical clones (default: $OMNI_HOME)",
    )
    parser.add_argument(
        "--package",
        action="append",
        dest="packages",
        help="restrict to this package (repeatable); default: every git source",
    )
    args = parser.parse_args(argv)

    try:
        advanced = advance_all(
            repo_root=args.repo_root,
            registry_root=args.registry_root,
            packages=args.packages,
        )
    except ErrorRelock as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    if not advanced:
        print("[relock] no git source moved — every pin is at its clone head")
        return 0
    print(f"[relock] advanced {len(advanced)} git source(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
