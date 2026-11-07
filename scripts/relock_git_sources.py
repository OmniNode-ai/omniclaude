#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
# Advance this repo's immutable git-rev sibling pins to the clone head (OMN-18752).
#
# ## The gap this closes
#
# ``.github/workflows/sibling-lock-refresh.yml`` (OMN-13902) is the surface that
# already owns "make the lock follow its upstream". Its own header records why it
# could not do so for one class of pin:
#
#     Repos whose siblings are pinned to an immutable git rev/tag in
#     ``[tool.uv.sources]`` ... are left untouched — ``uv lock
#     --upgrade-package`` cannot move a pinned rev
#
# ``pyproject.toml`` repeats the same sentence. That is mechanically true and it
# is why advancing ``omnimarket`` has been a hand-filed ticket every time
# (OMN-18622, OMN-18639, and a third the same week). omnimarket publishes
# release-on-merge, so the pin goes stale on essentially every omnimarket PR, and
# each staleness window is one in which the plugin CLI venv and the lock disagree
# about which commit is correct.
#
# ``uv lock --upgrade-package`` cannot move the rev because the rev is **input**,
# not output. So this module moves the input first: it rewrites the rev in
# ``pyproject.toml``, and ``uv lock`` then re-resolves against it. That is the
# whole trick, and it is why this lives beside the workflow rather than inside
# uv.
#
# ## Forward only, and refused rather than clamped
#
# The canonical clone is the authority (see ``git_source_pins``), but "follow the
# clone" must never mean "follow the clone backwards". A candidate that is not a
# **strict descendant** of the current rev raises ``ErrorNotADescendant`` and
# nothing is written — the file is byte-identical afterwards. A clamp would be
# worse than a refusal here: it would silently keep a stale pin while reporting
# success, which is the failure shape OMN-18663 already had to close once.
#
# Ancestry is resolved against a real clone, never against version strings. The
# clone is a parameter so the workflow can point at its own checkout and the
# tests can point at a fixture, with no network in either case.
#
# ## Why both occurrences move together
#
# In ``omniclaude/pyproject.toml`` the sha appears twice — once in the
# ``dependencies`` entry (``omnimarket @ git+...@<sha>``) and once in
# ``[tool.uv.sources]`` (``rev = "<sha>"``). uv will not resolve a tree where
# those disagree, so a rewrite that moved one and not the other would produce a
# lock failure rather than a stale pin. ``rewrite_rev`` returns the occurrence
# count and the caller asserts it.

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from omniclaude.handlers.handler_dev_merge_tag import dev_merge_tag_stamp

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
    """Return a strict-descendant advance, None if equal; refuse all other moves."""
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
    """Replace old_rev on live lines and return its count; refuse zero matches."""
    lines = pyproject.read_text(encoding="utf-8").splitlines(keepends=True)
    count = 0
    rewritten: list[str] = []
    for line in lines:
        if line.lstrip().startswith("#"):
            rewritten.append(line)
            continue
        count += line.count(old_rev)
        rewritten.append(line.replace(old_rev, new_rev))
    if count == 0:
        raise ErrorRevNotFound(
            f"{package}: rev {old_rev[:12]} appears on no live line of "
            f"{pyproject}; refusing to report a rewrite that did not happen"
        )
    pyproject.write_text("".join(rewritten), encoding="utf-8")
    return count


def advance_all(
    *,
    repo_root: Path,
    registry_root: str | None = None,
    packages: list[str] | None = None,
) -> list[ModelRevAdvance]:
    """Advance clone-governed rev pins, skipping missing clones unless requested."""
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
        # A tag-pinned source (OMN-21900) names no rev on any pyproject line, so
        # there is nothing here to rewrite; the dev-tag train below moves it.
        if declared is not gsp.EnumGitSourceAuthority.CLONE or source.tag:
            print(f"[relock] skip {name}: authority {declared.value} or tag pin")
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


# ---------------------------------------------------------------------------
# OMN-19998: the nightly sibling-pin train.
#
# RULING 2026-10-19T10:11:00Z: "turn this into a nightly release train where all
# the tags are rolled up to a single bump". Every dev merge of an internal
# sibling is tagged dev-<UTC YYYYMMDDHHMMSS>-<sha12> by the sibling's own
# dev-merge-tag.yml, on push, before its dev CI has run. So the newest tag is
# not the train's choice: the train walks the tags newer than the consumer's
# pin, newest first, and takes the first whose commit has green dev CI. A red
# tag and a tag whose CI it could not read (pending, no check runs, API
# failure) are both passed over, and the pin never moves backwards. Every pin
# that moves lands in ONE plan, so the workflow opens one PR per consumer.
#
# The set of train members is the consumer's own [tool.uv.sources]: every entry
# that pins an OmniNode-ai repository by a dev merge tag. A rev, a release tag,
# a branch or a PyPI range is not a member, and is left to the clone-governed
# relock above or to `uv lock --upgrade-package`.
#
# The rewrite itself is omnimarket's node_dev_tag_pin_mover_compute (#4129),
# called with --tests not_run: it writes the candidate pin in place, and the
# bump PR's own CI is the consumer test run that decides whether it lands.
#
# OMN-22636: a sibling's pre-commit hook blocks are a second home of its tags.
# Two tests hold every hook block of a pinned repository to a dev merge tag not
# older than the pin, and first-party-ref allows one home per tag literal, so a
# hook must sit strictly NEWER than the pin it follows. omnimarket's
# node_sibling_pin_hook_revs_compute plans that: the newest green tag for the
# floor-bound hook blocks of `.pre-commit-config.yaml`, the newest green tag
# strictly under them for the source pin. This script reads the tags, their CI
# and the hook blocks, and writes both files.
# ---------------------------------------------------------------------------

_OMNINODE_GIT = re.compile(
    r"^https://github\.com/OmniNode-ai/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?$"
)
# Tags examined per sibling, newest first. Bounds the CI reads a night costs; a
# sibling with this many consecutive red or unread tags stays where it is and
# the plan says why.
_MAX_CANDIDATES = 15
_GREEN_CONCLUSIONS = frozenset({"success", "skipped", "neutral"})
MOVER_MODULE = "omnimarket.nodes.node_dev_tag_pin_mover_compute"
_MOVER_EXIT_CANDIDATE_WRITTEN = 3
_HOOK_REPO = re.compile(r"\s*-\s*repo:\s*(?P<url>\S+)")
_HOOK_REV = re.compile(r"^(?P<head>\s*rev:\s*)(?P<rev>\S+?)(?P<tail>\s*(?:#.*)?)$")


@dataclass(frozen=True)
class ModelDevTagPin:
    distribution: str
    repo: str
    url: str
    tag: str


@dataclass(frozen=True)
class ModelTrainMove:
    distribution: str
    repo: str
    old_tag: str
    new_tag: str
    # OMN-21282: every dev tag newer than old_tag up to new_tag, newest first --
    # the tags this one bump rolls in.
    rolled: list[str] = field(default_factory=list)
    # OMN-22636: the tag the sibling's pre-commit hook blocks move to, and how many move.
    hook_tag: str | None = None
    hook_blocks: int = 0


@dataclass(frozen=True)
class ModelTrainPlan:
    moves: list[ModelTrainMove]
    unchanged: list[str]
    skipped: dict[str, dict[str, str]]

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)


GreenOracle = Callable[[str, str], "bool | None"]
Mover = Callable[[Path, ModelDevTagPin, str], None]


def parse_dev_tag_pins(pyproject_text: str) -> list[ModelDevTagPin]:
    """Every [tool.uv.sources] entry pinning an OmniNode-ai repo by dev merge tag."""
    sources = (
        tomllib.loads(pyproject_text).get("tool", {}).get("uv", {}).get("sources", {})
    )
    pins: list[ModelDevTagPin] = []
    for distribution, attrs in sources.items():
        if not isinstance(attrs, dict) or set(attrs) & {"rev", "branch"}:
            continue
        url, tag = attrs.get("git"), attrs.get("tag")
        if (
            not isinstance(url, str)
            or not isinstance(tag, str)
            or dev_merge_tag_stamp(tag) is None
        ):
            continue
        match = _OMNINODE_GIT.match(url)
        if match is None:
            continue
        pins.append(
            ModelDevTagPin(
                distribution=distribution, repo=match.group("repo"), url=url, tag=tag
            )
        )
    return pins


def dev_tags_newest_first(clone: Path) -> list[tuple[str, str]]:
    """(tag, commit) for every dev merge tag in ``clone``, newest stamp first."""
    result = _git(
        clone,
        "for-each-ref",
        "--format=%(refname:strip=2) %(*objectname) %(objectname)",
        "refs/tags/dev-*",
    )
    if result.returncode != 0:
        raise ErrorRelock(f"cannot list dev tags in {clone}: {result.stderr.strip()}")
    tags: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if not parts or dev_merge_tag_stamp(parts[0]) is None:
            continue
        # Annotated tags carry the commit in %(*objectname); lightweight ones in
        # %(objectname), and then the peeled column is empty.
        tags.append((parts[0], parts[1] if len(parts) == 3 else parts[-1]))
    return sorted(
        tags, key=lambda t: (dev_merge_tag_stamp(t[0]) or "", t[0]), reverse=True
    )


def check_runs_verdict(runs: list[tuple[str, str]]) -> bool | None:
    """Green, red, or None (unread) from (status, conclusion) pairs of one commit."""
    if not runs:
        return None
    if any(
        conclusion and conclusion not in _GREEN_CONCLUSIONS for _, conclusion in runs
    ):
        return False
    if any(status != "completed" for status, _ in runs):
        return None
    return True


def github_check_runs_green(repo: str, sha: str) -> bool | None:
    """Read dev-commit check runs with gh under the train workflow's App token."""
    result = subprocess.run(
        [
            "gh",
            "api",
            "--paginate",
            f"repos/OmniNode-ai/{repo}/commits/{sha}/check-runs?per_page=100",
            "--jq",
            r'.check_runs[] | "\(.status) \(.conclusion // "")"',
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        print(
            f"[train] {repo}@{sha[:12]}: check runs unreadable "
            f"({result.stderr.strip()[:200]})",
            file=sys.stderr,
        )
        return None
    runs = []
    for line in result.stdout.splitlines():
        status, _, conclusion = line.partition(" ")
        runs.append((status, conclusion.strip()))
    return check_runs_verdict(runs)


def hook_blocks(config_text: str, url: str) -> list[tuple[int, str]]:
    """(line index, rev) of every pre-commit block of the repository at ``url``, in file order."""
    blocks, in_block = [], False
    for at, line in enumerate(config_text.splitlines()):
        if repo := _HOOK_REPO.match(line):
            in_block = repo["url"].removesuffix(".git") == url.removesuffix(".git")
        elif in_block and (rev := _HOOK_REV.match(line)):
            blocks.append((at, rev["rev"]))
            in_block = False
    return blocks


def mover_argv(pyproject: Path, pin: ModelDevTagPin, new_tag: str) -> list[str]:
    return [
        sys.executable,
        "-m",
        MOVER_MODULE,
        "--pyproject",
        str(pyproject),
        "--distribution",
        pin.distribution,
        "--repository-url",
        pin.url,
        "--tag",
        new_tag,
        "--tests",
        "not_run",
    ]


def move_dependency_home(pyproject: Path, pin: ModelDevTagPin, new_tag: str) -> int:
    """Move live direct-URL dependency pins alongside uv sources; return the count."""
    url = pin.url.removesuffix(".git")
    home = re.compile(
        rf"(?P<head>git\+{re.escape(url)}(?:\.git)?@){re.escape(pin.tag)}(?![0-9A-Za-z])"
    )
    count = 0
    lines: list[str] = []
    for line in pyproject.read_text(encoding="utf-8").splitlines(keepends=True):
        if not line.lstrip().startswith("#"):
            line, hits = home.subn(lambda m: f"{m.group('head')}{new_tag}", line)
            count += hits
        lines.append(line)
    if count:
        pyproject.write_text("".join(lines), encoding="utf-8")
    return count


def node_mover(pyproject: Path, pin: ModelDevTagPin, new_tag: str) -> None:
    """Move uv sources through the pin mover, then update direct-URL dependencies."""
    result = subprocess.run(
        mover_argv(pyproject, pin, new_tag),
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != _MOVER_EXIT_CANDIDATE_WRITTEN:
        raise ErrorRelock(
            f"{pin.distribution}: the pin mover refused {pin.tag} -> {new_tag} "
            f"(exit {result.returncode}): {result.stdout.strip()} {result.stderr.strip()}"
        )
    move_dependency_home(pyproject, pin, new_tag)


def run_dev_tag_train(
    *,
    pyproject: Path,
    registry_root: str | None,
    is_green: GreenOracle,
    mover: Mover = node_mover,
    apply: bool,
) -> ModelTrainPlan:
    """One plan moving every dev-tag pin of ``pyproject``, and the hook blocks that follow it."""
    # The planning node is imported here, not at module level: the workflow's earlier steps
    # import this script under a bare python3 with PYTHONPATH=src, where omnimarket is absent.
    from omnimarket.nodes.node_sibling_pin_hook_revs_compute.handlers.handler_sibling_pin_hook_revs import (
        HandlerSiblingPinHookRevs,
    )
    from omnimarket.nodes.node_sibling_pin_hook_revs_compute.models import (
        ModelHookRevsCandidate,
        ModelSiblingPinHookRevsRequest,
    )

    moves: list[ModelTrainMove] = []
    unchanged: list[str] = []
    skipped: dict[str, dict[str, str]] = {}
    config = pyproject.parent / ".pre-commit-config.yaml"
    for pin in parse_dev_tag_pins(pyproject.read_text(encoding="utf-8")):
        clone = gsp.canonical_clone(pin.repo, registry_root)
        if clone is None:
            # Named, not skipped: a train that silently examined no clone is
            # indistinguishable from one with nothing to move.
            raise ErrorRelock(
                f"{pin.distribution}: no canonical clone for {pin.repo!r} under "
                f"{registry_root or '$OMNI_HOME'}"
            )
        stamp = dev_merge_tag_stamp(pin.tag) or ""
        tags = dev_tags_newest_first(clone)
        newer = [t for t in tags if (dev_merge_tag_stamp(t[0]) or "") > stamp]
        text = config.read_text(encoding="utf-8") if config.is_file() else ""
        blocks = hook_blocks(text, pin.url)
        verdicts = [
            (tag, is_green(pin.repo, sha)) for tag, sha in newer[:_MAX_CANDIDATES]
        ]
        plan = HandlerSiblingPinHookRevs().handle(
            ModelSiblingPinHookRevsRequest(
                pin_tag=pin.tag,
                hook_revs=tuple(rev for _, rev in blocks),
                candidates=tuple(
                    ModelHookRevsCandidate(tag=t, green=g) for t, g in verdicts
                ),
            )
        )
        written = dev_merge_tag_stamp(plan.pin_tag or "") or ""
        passed = {
            t: "red" if g is False else "unread"
            for t, g in verdicts
            if g is not True and (dev_merge_tag_stamp(t) or "") > written
        } | {t: "beyond-candidate-cap" for t, _ in newer[_MAX_CANDIDATES:][:1]}
        if passed:
            skipped[pin.distribution] = passed
        # The hook blocks follow the pin: with the pin left where it was, they stay too.
        if plan.pin_tag is None:
            unchanged.append(pin.distribution)
            continue
        if apply:
            mover(pyproject, pin, plan.pin_tag)
            lines = text.splitlines(keepends=True)
            for index in plan.hook_indexes:
                lines[blocks[index][0]] = _HOOK_REV.sub(
                    rf"\g<head>{plan.hook_tag}\g<tail>", lines[blocks[index][0]]
                )
            if plan.hook_indexes:
                config.write_text("".join(lines), encoding="utf-8")
        moves.append(
            ModelTrainMove(
                distribution=pin.distribution,
                repo=pin.repo,
                old_tag=pin.tag,
                new_tag=plan.pin_tag,
                rolled=[
                    t
                    for t, _ in tags
                    if stamp < (dev_merge_tag_stamp(t) or "") <= written
                ],
                hook_tag=plan.hook_tag,
                hook_blocks=len(plan.hook_indexes),
            )
        )
    return ModelTrainPlan(moves=moves, unchanged=unchanged, skipped=skipped)


def render_pr_body(plan: ModelTrainPlan) -> str:
    """Render one bump PR body listing every dev tag rolled into each sibling pin."""
    lines = ["## Dev-tag pin train", ""]
    if not plan.moves:
        lines.append("The train found no sibling moved: no newer green dev tag.")
    for move in plan.moves:
        lines.append(
            f"- `{move.distribution}` ({move.repo}): `{move.old_tag}` -> "
            f"`{move.new_tag}`, rolling {len(move.rolled)} dev tag(s): "
            + ", ".join(f"`{tag}`" for tag in move.rolled)
            + (
                f"; {move.hook_blocks} hook block(s) to `{move.hook_tag}`"
                if move.hook_tag
                else ""
            )
        )
    if plan.unchanged or plan.skipped:
        lines += ["", "### Left where they were", ""]
    for distribution in plan.unchanged:
        passed = plan.skipped.get(distribution, {})
        detail = (
            "; passed over " + ", ".join(f"`{t}` ({why})" for t, why in passed.items())
            if passed
            else ""
        )
        lines.append(f"- `{distribution}`{detail}")
    return "\n".join(lines) + "\n"


def _assume_unread(repo: str, sha: str) -> None:
    return None


def main_train(args: argparse.Namespace) -> int:
    oracle: GreenOracle = (
        github_check_runs_green if args.green_from == "github" else _assume_unread
    )
    try:
        plan = run_dev_tag_train(
            pyproject=args.repo_root / "pyproject.toml",
            registry_root=args.registry_root,
            is_green=oracle,
            apply=args.apply,
        )
    except ErrorRelock as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    rendered = plan.to_json()
    print(rendered)
    if args.plan_out:
        Path(args.plan_out).write_text(rendered + "\n", encoding="utf-8")
    if args.body_out:
        Path(args.body_out).write_text(render_pr_body(plan), encoding="utf-8")
    for move in plan.moves:
        verb = "moved" if args.apply else "would move"
        print(f"[train] {verb} {move.distribution}: {move.old_tag} -> {move.new_tag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Advance this repo's git-rev sibling pins and run the dev-tag train (OMN-18752, OMN-19998)."
    )
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
    parser.add_argument(
        "--dev-tag-train",
        action="store_true",
        help="OMN-19998: move every dev-tag pin to its newest green dev tag",
    )
    parser.add_argument(
        "--green-from",
        choices=["github", "none"],
        default="github",
        help="train only: read dev CI with gh (github) or read none (dry runs)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="train only: rewrite pyproject.toml (default: print the plan only)",
    )
    parser.add_argument(
        "--plan-out", default=None, help="train only: write the plan JSON here"
    )
    parser.add_argument(
        "--body-out",
        default=None,
        help="train only: write the one bump PR body here (OMN-21282)",
    )
    args = parser.parse_args(argv)

    if args.dev_tag_train:
        return main_train(args)

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
