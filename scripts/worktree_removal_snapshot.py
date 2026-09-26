#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Save a worktree's unrecoverable state before anything removes it (OMN-19539).

Why this exists
---------------
On 2026-09-16 a seven-day abandon pass removed 171 worktrees, 127 of them with
uncommitted edits: 1,957 files of work destroyed with no copy (ledger archive
2026-09-18-split, rows 2368 and 2378). Five approved Codex compositions for
eleven tickets survived only as loose objects about to be garbage-collected
(sealed-review audit, 2026-09-25). The operator ruled on 2026-09-25 that EVERY
worktree-removal path saves the worktree's binary diff and untracked files under
``$OMNI_HOME/.onex_state`` before removing it, as ``converge-canonical-clone.sh``
already does for canonical clones.

This module is the one helper every removal path calls. It needs no commit and
no push, so no repository hook can refuse it: the 2026-09-14 rescue failed
precisely because commits into omnibase_core were refused by its hooks, and a
push runs the branch's own pre-push suite (OMN-19539).

What it saves, under ``$OMNI_HOME/.onex_state/worktree-removal-snapshots/
<ticket>-<repo>-<utc>/`` (the converge script's ``<name>-<utc>`` scheme):

* ``status.txt``          ``git status --porcelain --ignored``
* ``full-vs-HEAD.patch``  ``git diff --binary HEAD`` (staged and unstaged)
* ``untracked.tar.gz``    every untracked file and every ignored file that is
                          not a regenerable cache, symlinks kept as symlinks
* ``commits.bundle``      only when HEAD holds commits on no remote-tracking
                          ref; verified with ``git bundle verify``
* ``reflog.txt``          the worktree's HEAD reflog, which dies with it
* ``skipped-regenerable.txt``  what was left out as regenerable, for audit
* ``MANIFEST.txt``        key=value facts plus ``sha256 <hex>  <file>`` lines,
                          the converge script's manifest format

and appends one line to ``worktree-removal-snapshots/INDEX.tsv`` so "where did
my worktree go" has an answer. Retention is the converge script's: none. The
evidence is kept until an operator deletes it.

Regenerable, and never regenerable
----------------------------------
A cache that a build or an install recreates (``.venv``, ``node_modules``,
``dist``, ``__pycache__``, ...) is left out, because it can be tens of
gigabytes and holds nothing a person wrote. A SECRETS-SHAPED file (``.env``,
``*.pem``, ``id_rsa``, ``settings.local.json``, ...) is never regenerable,
wherever it sits: a ``.env`` inside an ignored ``dist/`` is saved, because
``git status`` collapses that directory to ``dist/`` and a name-only check
would otherwise let it be destroyed (the edge case the omnibase_infra#4065
verifier found, ledger 2026-09-25T15:26:03Z).

Failure is a refusal
--------------------
Any failure (git cannot read the tree, the archive would exceed the size cap,
the state root is unset or inside the tree being removed, a bundle does not
verify) raises :class:`SnapshotError`, and the caller must NOT remove the
worktree. The partial snapshot directory is discarded so a failed save is never
mistaken for a good one.

CLI::

    worktree_removal_snapshot.py <worktree> --reason <text> [--allow-non-git]
                                 [--registry-root <path>] [--max-bytes N]

prints one JSON object. Exit 0: saved, removal may proceed. Exit 3: refused,
the worktree must be kept. Exit 2: usage error. Standard library only, so any
repository's removal path can run it with ``python3``.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

SNAPSHOT_SUBDIR = Path(".onex_state") / "worktree-removal-snapshots"
INDEX_NAME = "INDEX.tsv"
DEFAULT_MAX_BYTES = 512 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 300

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_REFUSED = 3

# Directory names a build, an install or a test run recreates. Matched on the
# basename, at any depth, the same set omnibase_infra#4065 keeps as regenerable.
REGENERABLE_DIR_NAMES = frozenset(
    {
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "htmlcov",
        ".tox",
        ".nox",
        "dist",
        "build",
        ".eggs",
        ".hypothesis",
        ".turbo",
        ".next",
        ".uv-cache",
    }
)
REGENERABLE_DIR_GLOBS = ("*.egg-info",)
REGENERABLE_FILE_GLOBS = (
    "*.pyc",
    "*.pyo",
    ".DS_Store",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
)

# Names that hold credentials or local configuration. Never regenerable, at any
# depth, inside any cache directory. Matched case-insensitively on the basename.
SECRET_SHAPED_GLOBS = (
    ".env",
    ".env.*",
    "*.env",
    ".envrc",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    "*.keystore",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".pgpass",
    ".git-credentials",
    "credentials",
    "credentials.json",
    "service-account*.json",
    "secret",
    "secrets",
    "secret.*",
    "secrets.*",
    "*.secret",
    "*.secrets",
    "kubeconfig",
    "*.kubeconfig",
    "*.tfvars",
    "*.tfstate",
    "settings.local.json",
)


class SnapshotError(Exception):
    """The worktree could not be saved. The caller must keep the worktree."""


class Snapshot(NamedTuple):
    """Where a worktree's state was saved, and the digests that prove it."""

    worktree: str
    directory: str
    ticket: str
    repo: str
    branch: str
    head: str
    reason: str
    utc: str
    patch_sha256: str
    tar_sha256: str
    files_archived: int
    bytes_archived: int
    skipped_regenerable: int
    unpushed_commits: int
    bundle: str
    git_worktree: bool

    def summary(self) -> str:
        """One line for a report cell or a ledger row."""
        return (
            f"snapshot {self.directory} (patch sha256 {self.patch_sha256[:12]}, "
            f"tar sha256 {self.tar_sha256[:12]}, {self.files_archived} file(s), "
            f"{self.unpushed_commits} unpushed commit(s) bundled)"
        )


def is_secret_shaped(name: str) -> bool:
    lowered = name.lower()
    return any(fnmatch.fnmatchcase(lowered, glob) for glob in SECRET_SHAPED_GLOBS)


def is_regenerable_dir(name: str) -> bool:
    if is_secret_shaped(name):
        return False
    return name in REGENERABLE_DIR_NAMES or any(
        fnmatch.fnmatchcase(name, glob) for glob in REGENERABLE_DIR_GLOBS
    )


def is_regenerable_file(name: str) -> bool:
    if is_secret_shaped(name):
        return False
    return any(fnmatch.fnmatchcase(name, glob) for glob in REGENERABLE_FILE_GLOBS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_env() -> dict[str, str]:
    """Drop the variables that would point git at another repository than -C."""
    env = dict(os.environ)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        env.pop(key, None)
    return env


def _git(worktree: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            env=_git_env(),
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SnapshotError(f"git {' '.join(args)} could not run: {exc}") from exc


def _git_ok(worktree: Path, *args: str) -> bytes:
    result = _git(worktree, *args)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip()[:400]
        raise SnapshotError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {stderr}"
        )
    return result.stdout


def _is_git_worktree(worktree: Path) -> bool:
    result = _git(worktree, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != b"true":
        return False
    top = _git(worktree, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return False
    return Path(top.stdout.decode().strip()).resolve() == worktree.resolve()


def _split_z(raw: bytes) -> list[str]:
    return [
        item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item
    ]


def _names_for(worktree: Path) -> tuple[str, str]:
    """``(<ticket>, <repo>)`` from the ``omni_worktrees/<ticket>/<repo>`` layout."""
    repo = worktree.name or "worktree"
    ticket = worktree.parent.name or "unknown"
    safe = str.maketrans(dict.fromkeys("/\\ \t\n:", "_"))
    return ticket.translate(safe), repo.translate(safe)


class _Collector:
    """Chooses the files to archive and enforces the size cap while it walks."""

    def __init__(self, worktree: Path, max_bytes: int) -> None:
        self.worktree = worktree
        self.max_bytes = max_bytes
        self.members: dict[str, Path] = {}
        self.skipped: list[str] = []
        self.total_bytes = 0

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.worktree).as_posix()

    def _take(self, path: Path) -> None:
        rel = self._rel(path)
        if rel in self.members:
            return
        if not path.is_symlink():
            try:
                self.total_bytes += path.stat().st_size
            except OSError as exc:
                raise SnapshotError(f"cannot stat {rel}: {exc}") from exc
            if self.total_bytes > self.max_bytes:
                raise SnapshotError(
                    f"untracked and ignored content exceeds the {self.max_bytes}-byte "
                    f"snapshot cap at {rel}; the worktree is kept for a person to review"
                )
        self.members[rel] = path

    def add_entry(self, rel: str, *, skip_top_level_git: bool = False) -> None:
        """Add one ``git ls-files --others --directory`` entry (or the whole tree)."""
        path = (
            self.worktree / rel.rstrip("/") if rel not in ("", "./") else self.worktree
        )
        if path.is_symlink() or path.is_file():
            if is_regenerable_file(path.name):
                self.skipped.append(self._rel(path))
            else:
                self._take(path)
            return
        if not path.is_dir():
            return  # vanished since git listed it: nothing left to lose
        top_regen = path != self.worktree and is_regenerable_dir(path.name)
        regen_by_dir: dict[str, bool] = {str(path): top_regen}
        if top_regen:
            self.skipped.append(self._rel(path) + "/")
        for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
            regen = regen_by_dir[dirpath]
            if skip_top_level_git and dirpath == str(self.worktree):
                dirnames[:] = [d for d in dirnames if d != ".git"]
                filenames = [f for f in filenames if f != ".git"]
            kept_dirs: list[str] = []
            for name in dirnames:
                child = Path(dirpath) / name
                if child.is_symlink():
                    if not regen and not is_regenerable_dir(name):
                        self._take(child)
                    continue
                child_regen = regen or is_regenerable_dir(name)
                if child_regen and not regen:
                    self.skipped.append(self._rel(child) + "/")
                regen_by_dir[str(child)] = child_regen
                kept_dirs.append(name)
            dirnames[:] = kept_dirs
            for name in filenames:
                child = Path(dirpath) / name
                if is_secret_shaped(name):
                    self._take(child)
                elif regen or is_regenerable_file(name):
                    continue
                else:
                    self._take(child)


def _state_root(registry_root: Path | None, worktree: Path) -> Path:
    if registry_root is None:
        raw = os.environ.get("OMNI_HOME")
        if not raw:
            raise SnapshotError(
                "OMNI_HOME is not set, so there is nowhere durable to save the "
                "worktree; the worktree is kept"
            )
        registry_root = Path(raw)
    root = (registry_root / SNAPSHOT_SUBDIR).resolve()
    resolved = worktree.resolve()
    if root == resolved or resolved in root.parents:
        raise SnapshotError(
            f"the snapshot root {root} is inside the worktree being removed; "
            "the worktree is kept"
        )
    return root


def _unique_dir(root: Path, base: str) -> Path:
    for suffix in range(1000):
        candidate = root / (base if suffix == 0 else f"{base}-{suffix}")
        partial = candidate.with_name(candidate.name + ".partial")
        if not candidate.exists() and not partial.exists():
            return candidate
    raise SnapshotError(f"no free snapshot directory name for {base} under {root}")


def _write_tar(path: Path, collector: _Collector) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for rel in sorted(collector.members):
            archive.add(str(collector.members[rel]), arcname=rel, recursive=False)
    with tarfile.open(path, "r:gz") as check:
        names = check.getnames()
    if len(names) != len(collector.members):
        raise SnapshotError(
            f"archive holds {len(names)} member(s), expected {len(collector.members)}"
        )


def snapshot_before_removal(
    worktree: Path,
    *,
    reason: str,
    registry_root: Path | None = None,
    allow_non_git: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Snapshot:
    """Save ``worktree``'s unrecoverable state and return where it went.

    Raises :class:`SnapshotError` on any failure; the caller must then keep the
    worktree. ``allow_non_git`` is for debris whose ``.git`` link is gone: the
    whole directory (less regenerable caches) is archived instead of a diff.
    """
    if not reason.strip():
        raise SnapshotError("a snapshot needs a reason")
    worktree = Path(worktree)
    if not worktree.is_dir() or worktree.is_symlink():
        raise SnapshotError(f"not a directory: {worktree}")
    root = _state_root(registry_root, worktree)
    git_worktree = _is_git_worktree(worktree)
    if not git_worktree and not allow_non_git:
        raise SnapshotError(
            f"{worktree} is not a readable git worktree, so its changes cannot be "
            "diffed; the worktree is kept"
        )

    ticket, repo = _names_for(worktree)
    utc = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SnapshotError(f"cannot create {root}: {exc}") from exc
    final = _unique_dir(root, f"{ticket}-{repo}-{utc}")
    partial = final.with_name(final.name + ".partial")
    try:
        partial.mkdir(parents=True)
        snapshot = _fill(
            partial,
            final,
            worktree,
            git_worktree=git_worktree,
            ticket=ticket,
            repo=repo,
            utc=utc,
            reason=reason,
            max_bytes=max_bytes,
        )
        partial.rename(final)
    except SnapshotError:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    except OSError as exc:
        shutil.rmtree(partial, ignore_errors=True)
        raise SnapshotError(f"snapshot write failed: {exc}") from exc
    _append_index(root, snapshot)
    return snapshot


def _fill(
    out: Path,
    final: Path,
    worktree: Path,
    *,
    git_worktree: bool,
    ticket: str,
    repo: str,
    utc: str,
    reason: str,
    max_bytes: int,
) -> Snapshot:
    collector = _Collector(worktree, max_bytes)
    branch = head = ""
    unpushed = 0
    bundle_name = ""
    patch = out / "full-vs-HEAD.patch"
    status_file = out / "status.txt"
    if git_worktree:
        status_file.write_bytes(_git_ok(worktree, "status", "--porcelain", "--ignored"))
        head_result = _git(worktree, "rev-parse", "--verify", "-q", "HEAD")
        head = (
            head_result.stdout.decode().strip() if head_result.returncode == 0 else ""
        )
        branch_result = _git(worktree, "symbolic-ref", "-q", "--short", "HEAD")
        branch = (
            branch_result.stdout.decode().strip()
            if branch_result.returncode == 0
            else ""
        )
        patch.write_bytes(
            _git_ok(worktree, "diff", "--binary", "HEAD") if head else b""
        )
        entries = _split_z(
            _git_ok(
                worktree,
                "ls-files",
                "-z",
                "--others",
                "--exclude-standard",
                "--directory",
            )
        ) + _split_z(
            _git_ok(
                worktree,
                "ls-files",
                "-z",
                "--others",
                "--ignored",
                "--exclude-standard",
                "--directory",
            )
        )
        for rel in entries:
            collector.add_entry(rel)
        if head:
            count = _git_ok(
                worktree, "rev-list", "--count", "HEAD", "--not", "--remotes"
            )
            unpushed = int(count.decode().strip() or "0")
        if unpushed:
            bundle = out / "commits.bundle"
            _git_ok(
                worktree, "bundle", "create", str(bundle), "HEAD", "--not", "--remotes"
            )
            _git_ok(worktree, "bundle", "verify", str(bundle))
            bundle_name = bundle.name
        reflog = _git(worktree, "reflog", "-n", "50", "HEAD")
        (out / "reflog.txt").write_bytes(
            reflog.stdout if reflog.returncode == 0 else b""
        )
    else:
        status_file.write_text(
            "not a git worktree: whole directory archived\n", encoding="utf-8"
        )
        patch.write_bytes(b"")
        collector.add_entry("", skip_top_level_git=True)

    tar_path = out / "untracked.tar.gz"
    _write_tar(tar_path, collector)
    (out / "skipped-regenerable.txt").write_text(
        "".join(f"{rel}\n" for rel in sorted(set(collector.skipped))), encoding="utf-8"
    )

    snapshot = Snapshot(
        worktree=str(worktree),
        directory=str(final),
        ticket=ticket,
        repo=repo,
        branch=branch,
        head=head,
        reason=reason,
        utc=utc,
        patch_sha256=_sha256(patch),
        tar_sha256=_sha256(tar_path),
        files_archived=len(collector.members),
        bytes_archived=collector.total_bytes,
        skipped_regenerable=len(set(collector.skipped)),
        unpushed_commits=unpushed,
        bundle=str(final / bundle_name) if bundle_name else "",
        git_worktree=git_worktree,
    )
    lines = [f"{key}={value}" for key, value in snapshot._asdict().items()]
    for name in sorted(p.name for p in out.iterdir()):
        lines.append(f"sha256 {_sha256(out / name)}  {name}")
    (out / "MANIFEST.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return snapshot


def _append_index(root: Path, snapshot: Snapshot) -> None:
    """One line per snapshot. A failed index write never undoes a good save."""
    fields = (
        snapshot.utc,
        snapshot.worktree,
        snapshot.branch or "-",
        snapshot.head or "-",
        snapshot.directory,
        snapshot.patch_sha256,
        snapshot.tar_sha256,
        snapshot.reason.replace("\t", " ").replace("\n", " "),
    )
    try:
        with (root / INDEX_NAME).open("a", encoding="utf-8") as handle:
            handle.write("\t".join(fields) + "\n")
    except OSError as exc:
        print(f"WARNING: snapshot index not updated: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Save a worktree's diff and untracked files before removal (OMN-19539)."
    )
    parser.add_argument("worktree", help="The worktree about to be removed.")
    parser.add_argument("--reason", required=True, help="Which removal path is asking.")
    parser.add_argument(
        "--registry-root", help="Registry root (default: $OMNI_HOME, required)."
    )
    parser.add_argument(
        "--allow-non-git",
        action="store_true",
        help="Archive the whole directory when it is no longer a git worktree (debris).",
    )
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return EXIT_USAGE if exc.code else EXIT_OK
    try:
        snapshot = snapshot_before_removal(
            Path(args.worktree),
            reason=args.reason,
            registry_root=Path(args.registry_root) if args.registry_root else None,
            allow_non_git=args.allow_non_git,
            max_bytes=args.max_bytes,
        )
    except SnapshotError as exc:
        print(json.dumps({"ok": False, "worktree": args.worktree, "error": str(exc)}))
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(json.dumps({"ok": True, **snapshot._asdict()}))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
