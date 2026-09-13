# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Lane identity: register a lane, resolve it from a worktree, stamp it into
commits (OMN-18260, phase 5 item 3 of the 2026-09-12 process-friction plan).

THE PROBLEM, MEASURED 2026-09-13. Zero commits carry a lane trailer across the
last 200 commits of each of three worked repositories. The same window carries
`Co-authored-by:`, `Ticket:` and `Evidence-Ticket:` trailers, so the mechanism
works and is simply unused. Every lane pushes under one account, so neither
authorship nor branch name says which lane produced a commit. That is why the
cross-lane push on 2026-09-12 at 14:17Z -- three commits to one repository's
branch and four to another's, both under a ticket held by a different lane --
was invisible until a person noticed it by hand.

WHY THAT MATTERS MORE THAN IT SOUNDS. A pre-push refusal compares the claim
holder against the pushing lane. Without this file, the second operand does not
exist, and no hook or check can reproduce the comparison. This is the missing
operand, and nothing downstream in phase 5 works without it.

DESIGN OF RECORD: `beta/plans/2026-09-13-lane-identity-and-claim-index-design.md`
in knowledge-base-internal (OMN-18259), sections 3 and 9. Four alternative
homes for the identity are rejected there on the record; the one adopted here is
a registry keyed by the worktree's resolved path, held outside every repository,
so no product repository needs an ignore entry and the resolution survives the
session that wrote it.

PRIOR ART: OMN-17005 measured what happens without this. Its claimant identity
was an environment variable that is unset, falling back to one shared constant,
so every concurrent lane claimed as the same string and two anonymous lanes
could never be told apart. That is the failure this module exists to not repeat,
which is why the environment-variable option is rejected rather than reused.

THE HONEST LIMIT. A lane stamps its own identity. Nothing here proves a lane is
who it says it is; a lane registering under another lane's slug produces a
correct-looking trailer. This enforces ATTRIBUTION AND BLAST RADIUS, not
authority -- the same limit the production-promotion, staging-namespace and
credential-rotation gates each record about themselves. What it removes is the
silent case: commits on a branch with nothing anywhere saying which lane made
them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "LANE_TRAILER",
    "SESSION_TRAILER",
    "LaneRecord",
    "BadRange",
    "UnregisteredLane",
    "apply_trailers",
    "commit_identity",
    "record_path",
    "register",
    "registry_root_from_env",
    "resolve",
    "trailer_lines",
    "unstamped_commits",
    "valid_lane",
]

LANE_TRAILER = "Onex-Lane"
SESSION_TRAILER = "Onex-Session"

# The slug the ledger already uses: lowercase, digits, single hyphens, no
# leading or trailing hyphen. Adopted rather than invented so a trailer and a
# claim row name the same thing in the same vocabulary -- a trailer in a
# different alphabet could not be compared against a claim row at all.
_LANE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_LANE_MAX = 64
_TICKET_RE = re.compile(r"^OMN-\d+$")

# A trailer is read as a trailer -- a `Key: value` line in the message's final
# trailer block -- never searched for in the body. CLAUDE.md rule 15: prose that
# merely spells a trigger must not satisfy a gate.
_TRAILER_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):[ \t]*(.*)$")


class BadRange(RuntimeError):
    """The revision range does not resolve. Raised rather than returning an
    empty finding list: no commits and no defects look identical to a caller,
    and this check's whole value is that its zero means something."""


class UnregisteredLane(RuntimeError):
    """The worktree has no lane identity. Raised rather than defaulted: a
    trailer that can be wrong is worse than one that is absent, because the
    check downstream cannot tell the two apart."""


@dataclass(frozen=True)
class LaneRecord:
    lane: str
    session_id: str
    ticket: str
    worktree: str
    registered_at: str

    def as_dict(self) -> dict[str, str]:
        return {
            "lane": self.lane,
            "session_id": self.session_id,
            "ticket": self.ticket,
            "worktree": self.worktree,
            "registered_at": self.registered_at,
        }


def valid_lane(lane: str) -> bool:
    return bool(lane) and len(lane) <= _LANE_MAX and _LANE_RE.match(lane) is not None


def registry_root_from_env() -> Path:
    """Where the registry lives, resolved fail-fast.

    `ONEX_LANE_REGISTRY_ROOT` wins when set, so tests and alternate workspaces
    do not have to fake a workspace root. Otherwise the workspace root, read as
    a required key so a missing one raises rather than silently picking a wrong
    default (CLAUDE.md rule 8). A silent default here would scatter lane records
    into an unrelated directory and make every resolution miss -- which reads
    exactly like "no lane is registered" and refuses every commit on the box.
    """
    explicit = os.environ.get("ONEX_LANE_REGISTRY_ROOT")
    if explicit:
        return Path(explicit)
    return Path(os.environ["OMNI_HOME"]) / ".onex_state"


def _registry_dir(base: Path) -> Path:
    return base / "lane_identity"


def _key(worktree: Path) -> str:
    return hashlib.sha256(str(worktree.resolve()).encode("utf-8")).hexdigest()[:32]


def record_path(base: Path, worktree: Path) -> Path:
    return _registry_dir(base) / f"{_key(worktree)}.json"


def register(
    base: Path,
    worktree: Path,
    *,
    lane: str,
    ticket: str,
    session_id: str | None = None,
) -> LaneRecord:
    """Register `worktree` as belonging to `lane`. Re-registering replaces the
    record: a worktree has exactly one lane at a time, and a second lane taking
    over a directory is a fact to record, not an error."""
    if not valid_lane(lane):
        raise ValueError(
            f"lane {lane!r} is not a valid slug: lowercase letters, digits and single "
            f"hyphens, at most {_LANE_MAX} characters"
        )
    if not _TICKET_RE.match(ticket):
        raise ValueError(f"ticket {ticket!r} is not of the form OMN-<digits>")
    resolved = worktree.resolve()
    record = LaneRecord(
        lane=lane,
        session_id=session_id or uuid.uuid4().hex,
        ticket=ticket,
        worktree=str(resolved),
        registered_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    path = record_path(base, resolved)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(record.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    return record


def resolve(base: Path, path: Path) -> LaneRecord | None:
    """The lane owning `path`, or None.

    Walks upward, so a lane working in a subdirectory of its worktree still
    resolves. Returns None -- not a partial record -- for anything unreadable or
    incomplete: an unresolvable identity must read as unregistered so the commit
    is refused and the lane re-registers, never as a successful resolution of a
    record that is missing half its fields.
    """
    try:
        current = path.resolve()
    except OSError:
        return None
    for candidate in [current, *current.parents]:
        record_file = record_path(base, candidate)
        if not record_file.is_file():
            continue
        try:
            data = json.loads(record_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        lane = data.get("lane")
        session_id = data.get("session_id")
        if not isinstance(lane, str) or not isinstance(session_id, str):
            return None
        if not valid_lane(lane) or not session_id:
            return None
        return LaneRecord(
            lane=lane,
            session_id=session_id,
            ticket=str(data.get("ticket", "")),
            worktree=str(data.get("worktree", candidate)),
            registered_at=str(data.get("registered_at", "")),
        )
    return None


def trailer_lines(base: Path, worktree: Path) -> list[str]:
    record = resolve(base, worktree)
    if record is None:
        raise UnregisteredLane(str(worktree))
    return [f"{LANE_TRAILER}: {record.lane}", f"{SESSION_TRAILER}: {record.session_id}"]


def _split_comments(message: str) -> tuple[str, str]:
    """Separate the authored message from git's own comment block, which is
    everything from the first line starting with `#` that begins the trailing
    run of comment lines. A trailer appended after the comments is not a trailer
    -- git strips that region before the commit is written."""
    lines = message.splitlines(keepends=True)
    first_comment = len(lines)
    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if stripped.startswith("#") or not stripped:
            first_comment = index
        else:
            break
    return "".join(lines[:first_comment]), "".join(lines[first_comment:])


def apply_trailers(message: str, lines: list[str]) -> str:
    """Append the trailers to `message`, idempotently.

    Idempotent because a commit gets amended and reworded, and a message
    accumulating a second copy of its own lane trailer would make the reader
    downstream see two lanes for one commit.
    """
    body, comments = _split_comments(message)
    present = {
        line.split(":", 1)[0]
        for line in body.splitlines()
        if _TRAILER_LINE_RE.match(line)
    }
    missing = [line for line in lines if line.split(":", 1)[0] not in present]
    if not missing:
        return message
    if not body.endswith("\n"):
        body += "\n"
    last = [line for line in body.splitlines() if line.strip()]
    needs_blank = bool(last) and _TRAILER_LINE_RE.match(last[-1]) is None
    if needs_blank:
        body += "\n"
    body += "\n".join(missing) + "\n"
    return body + comments


def commit_identity(message: str) -> tuple[str, str] | None:
    """The (lane, session) a commit message declares, or None.

    Read from the message's final trailer block only. A mention in the body is
    not a declaration, and a trailer whose lane value is not a valid slug is not
    one either: an identifier that cannot be compared against a claim row fails
    the check exactly as an absent one does.
    """
    body, _ = _split_comments(message)
    lines = [line for line in body.splitlines() if line.strip()]
    trailers: dict[str, str] = {}
    for line in reversed(lines):
        match = _TRAILER_LINE_RE.match(line)
        if match is None:
            break
        trailers.setdefault(match.group(1), match.group(2).strip())
    lane = trailers.get(LANE_TRAILER)
    session = trailers.get(SESSION_TRAILER)
    if not lane or not session or not valid_lane(lane):
        return None
    return lane, session


def _git_env() -> dict[str, str]:
    """The ambient environment with every GIT_* variable removed.

    This matters in production, not only in tests. Git exports GIT_DIR and
    GIT_INDEX_FILE to the hooks it runs, and GIT_DIR is frequently the relative
    string ".git". A `git log` launched from inside a hook therefore reads the
    HOOK OWNER repository no matter which directory it is pointed at -- so a
    window check invoked from a hook silently answered about the wrong
    repository, reporting its commits as the findings. Caught by running the
    check inside a real `git commit` rather than beside one.
    """
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def unstamped_commits(repo: Path, rev_range: str) -> list[tuple[str, str]]:
    """Commits in `rev_range` carrying no resolvable lane identity, as
    (sha, subject).

    Merge commits are exempt: git writes them, not a lane, and refusing them
    would make the check fire on the correct behaviour.

    This is the phase 5 AC3 window check. Note what it does NOT do: it cannot
    confirm the identifier resolves to exactly one claim row, because the claim
    index that answers that lands in OMN-18261. Presence and shape are what this
    half proves, and saying so is better than implying the whole criterion is
    closed here.
    """
    separator = "\x1e"
    completed = subprocess.run(
        ["git", "log", "--no-merges", f"--format=%H%x1f%s%x1f%B{separator}", rev_range],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if completed.returncode != 0:
        # A range git cannot resolve must be an ERROR, never an empty result.
        # An unresolvable range returns no commits, which reads exactly like
        # "every commit is stamped" -- a zero that is not evidence of absence
        # (CLAUDE.md rule 16). Found by running the check with a bad range
        # against a one-commit repository, where it raised an unhandled
        # traceback instead of saying so.
        raise BadRange(
            f"git could not resolve {rev_range!r}: {completed.stderr.strip()}"
        )
    out = completed.stdout
    findings: list[tuple[str, str]] = []
    for chunk in out.split(separator):
        if not chunk.strip():
            continue
        sha, _, rest = chunk.lstrip("\n").partition("\x1f")
        subject, _, message = rest.partition("\x1f")
        if commit_identity(message) is None:
            findings.append((sha, subject))
    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _base(args: argparse.Namespace) -> Path:
    if getattr(args, "registry_root", None):
        return Path(args.registry_root)
    try:
        return registry_root_from_env()
    except KeyError:
        print(
            "lane_identity: neither ONEX_LANE_REGISTRY_ROOT nor OMNI_HOME is set, so the "
            "lane registry has no home. Set one; there is deliberately no default "
            "(CLAUDE.md rule 8).",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry-root", help="override the registry location")
    sub = parser.add_subparsers(dest="command", required=True)

    p_reg = sub.add_parser("register", help="register this worktree as a lane")
    p_reg.add_argument("--lane", required=True)
    p_reg.add_argument("--ticket", required=True)
    p_reg.add_argument("--worktree", default=".")
    p_reg.add_argument("--session")

    p_res = sub.add_parser(
        "resolve", help="print this worktree's lane identity as JSON"
    )
    p_res.add_argument("--worktree", default=".")

    p_tr = sub.add_parser(
        "trailers", help="print the commit trailers for this worktree"
    )
    p_tr.add_argument("--worktree", default=".")

    p_ver = sub.add_parser(
        "verify", help="fail if any commit in a range carries no lane identity"
    )
    p_ver.add_argument("--repo", default=".")
    p_ver.add_argument("--range", dest="rev_range", required=True)

    p_inst = sub.add_parser(
        "install-hook", help="install the prepare-commit-msg hook in a clone"
    )
    p_inst.add_argument("--repo", default=".")

    args = parser.parse_args(argv)

    if args.command == "register":
        try:
            record = register(
                _base(args),
                Path(args.worktree),
                lane=args.lane,
                ticket=args.ticket,
                session_id=args.session,
            )
        except ValueError as exc:
            print(f"lane_identity: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(record.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "resolve":
        resolved = resolve(_base(args), Path(args.worktree))
        if resolved is None:
            print(
                f"lane_identity: {Path(args.worktree).resolve()} has no lane",
                file=sys.stderr,
            )
            return 3
        print(json.dumps(resolved.as_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "trailers":
        try:
            for line in trailer_lines(_base(args), Path(args.worktree)):
                print(line)
        except UnregisteredLane as exc:
            print(f"lane_identity: {exc} has no lane", file=sys.stderr)
            return 3
        return 0

    if args.command == "verify":
        try:
            findings = unstamped_commits(Path(args.repo), args.rev_range)
        except BadRange as exc:
            print(f"lane_identity: {exc}", file=sys.stderr)
            return 2
        if not findings:
            print(
                f"lane_identity: every commit in {args.rev_range} carries a lane identity"
            )
            return 0
        print(
            f"lane_identity: {len(findings)} commit(s) in {args.rev_range} carry no resolvable "
            f"lane identity:",
            file=sys.stderr,
        )
        for sha, subject in findings:
            print(f"  {sha[:12]} {subject}", file=sys.stderr)
        print(
            "Each lane registers once per worktree:\n"
            "  python3 scripts/lane_identity.py register --lane <slug> --ticket OMN-XXXX",
            file=sys.stderr,
        )
        return 1

    if args.command == "install-hook":
        repo = Path(args.repo)
        hooks = Path(
            subprocess.run(
                ["git", "rev-parse", "--git-path", "hooks"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
                env=_git_env(),
            ).stdout.strip()
        )
        if not hooks.is_absolute():
            hooks = repo / hooks
        # REFUSE a hooks directory that is not inside this repository own git
        # directory. A clone can set core.hooksPath to a SHARED directory --
        # this workspace points every canonical clone at one -- and installing
        # there silently arms a commit-refusing hook for every repository that
        # shares it. That is not hypothetical: it happened during this ticket
        # development, when an inherited GIT_DIR pointed the installer at the
        # shared directory and every canonical clone started refusing commits
        # until the file was removed by hand.
        common = Path(
            subprocess.run(
                ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
                env=_git_env(),
            ).stdout.strip()
        )
        if not hooks.resolve().is_relative_to(common.resolve()):
            print(
                f"lane_identity: refusing to install into {hooks} -- that directory is "
                f"outside this repository git directory ({common}), so it is shared with "
                "other repositories and a refusing hook there would arm all of them. "
                "Install per clone, into its own hooks directory.",
                file=sys.stderr,
            )
            return 2
        hooks.mkdir(parents=True, exist_ok=True)
        source = Path(__file__).resolve().parent / "hooks" / "prepare-commit-msg-lane"
        target = hooks / "prepare-commit-msg"
        # Bake the module's absolute path into the copy. The hook then needs no
        # environment variable at commit time, which removes the failure mode
        # where a correctly installed hook cannot find its own module on a box
        # that does not export the workspace variable.
        body = source.read_text(encoding="utf-8").replace(
            "@LANE_IDENTITY_PATH@", str(Path(__file__).resolve())
        )
        target.write_text(body, encoding="utf-8")
        target.chmod(0o755)
        print(f"lane_identity: installed {target}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
