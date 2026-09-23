#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Print a file as committed at a ref, never as it sits in the working tree [OMN-19255].

A skill that injects a file into something else — a rules block into every lane
a dispatch starts, a brief into the lane itself — must inject what was
committed, not whatever is on disk. In a clone several sessions share, the
working-tree copy can carry another session's uncommitted edits, and a read of
it hands those edits to every lane dispatched from it. Measured on the dispatch
skill's first dry run: 13,383 bytes in the working tree against 10,256 at HEAD.

Two ways to name the file:

- ``--path P``: a repository-relative path, read with ``git show <ref>:P``.
- ``--dir D --stem S``: the one committed entry directly under ``D`` whose name,
  without its extension, is ``S``. A brief is named by stem; resolving it from
  the committed tree means an untracked file of the same name is never found.

Prints the content on stdout, byte for byte, and one line on stderr naming the
path, the ref, the commit it resolved to and the byte count. When the working
tree differs from the committed copy, stderr says so, because that is exactly
the case this exists for. Exits ``2``, printing nothing on stdout, when the
repository, the ref or the path does not resolve, when a stem matches zero or
several entries, or when the committed file is empty: an empty injection is a
dispatch with the content omitted, and it is refused rather than reported.

Standard library only; a skill step runs this under whatever ``python3`` the
session has.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

EXIT_OK = 0
EXIT_REFUSED = 2


class NotCommitted(Exception):
    """The file does not resolve at the ref, or resolves to nothing."""


# Git exports these into hook environments, and they override ``git -C``: left
# in place, a read aimed at one repository silently reads another.
_GIT_LOCATION_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_LOCATION_ENV}
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False, env=env
    )


def resolve_commit(repo: Path, ref: str) -> str:
    """The full commit id ``ref`` names in ``repo``."""
    proc = _git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise NotCommitted(f"ref {ref!r} does not resolve in {repo}. {detail}".strip())
    return proc.stdout.decode().strip()


def resolve_stem(repo: Path, commit: str, directory: str, stem: str) -> str:
    """The single committed entry under ``directory`` whose stem is ``stem``."""
    proc = _git(repo, "ls-tree", "--name-only", commit, f"{directory.rstrip('/')}/")
    if proc.returncode != 0:
        raise NotCommitted(proc.stderr.decode(errors="replace").strip())
    names = [n for n in proc.stdout.decode().splitlines() if n]
    matches = [n for n in names if PurePosixPath(n).stem == stem]
    if len(matches) != 1:
        found = ", ".join(matches) if matches else "none"
        raise NotCommitted(
            f"{len(matches)} committed entries under {directory} have stem "
            f"{stem!r} (found: {found}); exactly one is required"
        )
    return matches[0]


def read_committed(repo: Path, path: str, commit: str) -> bytes:
    """The bytes of ``path`` at ``commit``; refuses a missing or empty file."""
    proc = _git(repo, "show", f"{commit}:{path}")
    if proc.returncode != 0:
        detail = proc.stderr.decode(errors="replace").strip()
        raise NotCommitted(
            f"{path} is not committed at {commit[:12]}. {detail}".strip()
        )
    if not proc.stdout:
        raise NotCommitted(f"{path} is committed empty at {commit[:12]}")
    return proc.stdout


def working_tree_differs(repo: Path, path: str, content: bytes) -> bool:
    on_disk = repo / path
    return not on_disk.is_file() or on_disk.read_bytes() != content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="read_committed_file.py",
        description="Print a file as committed at a ref, never the working-tree copy.",
    )
    parser.add_argument("--repo", required=True, help="The repository to read from.")
    parser.add_argument(
        "--ref", default="HEAD", help="The ref to read at (default HEAD)."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--path", help="A repository-relative file path.")
    target.add_argument(
        "--dir", help="A repository-relative directory; use with --stem."
    )
    parser.add_argument(
        "--stem", help="With --dir: the file name without its extension."
    )
    args = parser.parse_args(argv)
    if bool(args.dir) != bool(args.stem):
        parser.error("--dir and --stem go together")

    repo = Path(args.repo)
    try:
        commit = resolve_commit(repo, args.ref)
        path = args.path or resolve_stem(repo, commit, args.dir, args.stem)
        content = read_committed(repo, path, commit)
    except NotCommitted as exc:
        print(f"REFUSED — {exc}", file=sys.stderr)
        return EXIT_REFUSED

    sys.stdout.buffer.write(content)
    sys.stdout.flush()
    note = (
        "; the working-tree copy differs and was NOT read"
        if working_tree_differs(repo, path, content)
        else ""
    )
    print(
        f"read {path} at {args.ref} ({commit[:12]}): {len(content)} bytes{note}",
        file=sys.stderr,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
