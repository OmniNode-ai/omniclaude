# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Immutable GitHub PR manifest transport for the deploy-gate classifier."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass

_PAGE_SIZE = 100
_ALLOWED_STATUSES = frozenset(
    {"added", "modified", "removed", "renamed", "copied", "changed", "unchanged"}
)
_ALLOWED_OBJECT_TYPES = frozenset({"blob", "tree", "commit"})


class PrManifestResolutionError(ValueError):
    """A PR identity or manifest response cannot safely drive package-only policy."""


@dataclass(frozen=True)
class ModelPullFileRecord:
    """Untrusted GitHub API file record before Git-object enrichment."""

    filename: str
    status: str
    previous_filename: str | None
    blob_sha: str | None


@dataclass(frozen=True)
class ModelPullManifestSnapshot:
    """Stable PR identity plus the immutable merge base for its file diff."""

    base_sha: str
    head_sha: str
    diff_base_sha: str
    files: tuple[ModelPullFileRecord, ...]


@dataclass(frozen=True)
class ModelPullManifestEntry:
    """One complete manifest entry derived from immutable Git objects."""

    filename: str
    status: str
    previous_filename: str | None
    old_blob_sha: str | None
    new_blob_sha: str | None
    blob_sha: str
    old_mode: str | None
    new_mode: str | None
    old_object_type: str | None
    new_object_type: str | None
    is_binary: bool
    is_submodule: bool

    def as_core_payload(self) -> dict[str, object]:
        """Return the exact fields consumed by the shared typed Core model."""

        return {
            "filename": self.filename,
            "status": self.status,
            "previous_filename": self.previous_filename,
            "blob_sha": self.blob_sha,
            "old_mode": self.old_mode,
            "new_mode": self.new_mode,
            "old_object_type": self.old_object_type,
            "new_object_type": self.new_object_type,
            "is_binary": self.is_binary,
            "is_submodule": self.is_submodule,
        }


@dataclass(frozen=True)
class _GitTreeEntry:
    mode: str
    object_type: str
    sha: str


def _is_full_sha(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _read_identity(payload: object, repository: str) -> tuple[str, str, int]:
    if not isinstance(payload, dict):
        raise PrManifestResolutionError("PR resolution returned a non-object payload")
    base = payload.get("base")
    head = payload.get("head")
    if not isinstance(base, dict) or not isinstance(head, dict):
        raise PrManifestResolutionError("PR resolution lacks base/head identity")
    base_repo = base.get("repo")
    if not isinstance(base_repo, dict) or base_repo.get("full_name") != repository:
        raise PrManifestResolutionError(
            "PR base repository does not match caller repository"
        )
    base_sha = base.get("sha")
    head_sha = head.get("sha")
    changed_files = payload.get("changed_files")
    if (
        not _is_full_sha(base_sha)
        or not _is_full_sha(head_sha)
        or not isinstance(changed_files, int)
        or changed_files < 1
    ):
        raise PrManifestResolutionError(
            "PR resolution has malformed base/head/file count"
        )
    return base_sha, head_sha, changed_files


def _read_file_record(raw: object, page: int) -> ModelPullFileRecord:
    if not isinstance(raw, dict):
        raise PrManifestResolutionError(
            f"PR files page {page} contains a non-object entry"
        )
    filename = raw.get("filename")
    status = raw.get("status")
    previous_filename = raw.get("previous_filename")
    blob_sha = raw.get("sha")
    if (
        not isinstance(filename, str)
        or not isinstance(status, str)
        or status not in _ALLOWED_STATUSES
        or (previous_filename is not None and not isinstance(previous_filename, str))
        or (blob_sha is not None and not _is_full_sha(blob_sha))
    ):
        raise PrManifestResolutionError(
            f"PR files page {page} contains malformed file metadata"
        )
    return ModelPullFileRecord(filename, status, previous_filename, blob_sha)


def resolve_pull_manifest(
    *,
    repository: str,
    pr_number: int,
    event_head_sha: str,
    api_get: Callable[[str], object],
) -> ModelPullManifestSnapshot:
    """Read a full paginated PR manifest and reject time-of-check changes."""

    if not _is_full_sha(event_head_sha):
        raise PrManifestResolutionError(
            "pull_request event lacks an immutable head SHA"
        )
    endpoint = f"repos/{repository}/pulls/{pr_number}"
    initial = api_get(endpoint)
    base_sha, head_sha, expected_count = _read_identity(initial, repository)
    if head_sha != event_head_sha:
        raise PrManifestResolutionError("event head SHA differs from resolved PR head")

    files: list[ModelPullFileRecord] = []
    page = 1
    while True:
        payload = api_get(f"{endpoint}/files?per_page={_PAGE_SIZE}&page={page}")
        if not isinstance(payload, list):
            raise PrManifestResolutionError(f"PR files page {page} is not an array")
        if not payload:
            break
        files.extend(_read_file_record(raw, page) for raw in payload)
        if len(payload) < _PAGE_SIZE:
            break
        page += 1

    if len(files) != expected_count:
        raise PrManifestResolutionError(
            f"PR files pagination returned {len(files)} entries; expected {expected_count}"
        )

    final = api_get(endpoint)
    final_base, final_head, final_count = _read_identity(final, repository)
    if (final_base, final_head, final_count) != (base_sha, head_sha, expected_count):
        raise PrManifestResolutionError(
            "PR base/head/file count changed while manifest pages were read"
        )
    comparison = api_get(f"repos/{repository}/compare/{base_sha}...{head_sha}")
    if not isinstance(comparison, dict):
        raise PrManifestResolutionError("PR comparison returned a non-object payload")
    merge_base = comparison.get("merge_base_commit")
    diff_base_sha = merge_base.get("sha") if isinstance(merge_base, dict) else None
    if not _is_full_sha(diff_base_sha):
        raise PrManifestResolutionError("PR comparison lacks an immutable merge base")
    return ModelPullManifestSnapshot(base_sha, head_sha, diff_base_sha, tuple(files))


def _read_tree(
    *,
    repository: str,
    revision: str,
    api_get: Callable[[str], object],
) -> dict[str, _GitTreeEntry]:
    payload = api_get(f"repos/{repository}/git/trees/{revision}?recursive=1")
    if not isinstance(payload, dict) or payload.get("truncated") is not False:
        raise PrManifestResolutionError(
            f"Git tree for {revision} is missing or truncated"
        )
    raw_entries = payload.get("tree")
    if not isinstance(raw_entries, list):
        raise PrManifestResolutionError(f"Git tree for {revision} lacks an entry array")

    entries: dict[str, _GitTreeEntry] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise PrManifestResolutionError(
                f"Git tree for {revision} contains a non-object entry"
            )
        path = raw.get("path")
        mode = raw.get("mode")
        object_type = raw.get("type")
        sha = raw.get("sha")
        if (
            not isinstance(path, str)
            or not isinstance(mode, str)
            or not isinstance(object_type, str)
            or object_type not in _ALLOWED_OBJECT_TYPES
            or not _is_full_sha(sha)
            or path in entries
        ):
            raise PrManifestResolutionError(
                f"Git tree for {revision} contains malformed object metadata"
            )
        entries[path] = _GitTreeEntry(mode, object_type, sha)
    return entries


def _binary_blob(
    *,
    repository: str,
    blob_sha: str,
    api_get: Callable[[str], object],
) -> bool:
    payload = api_get(f"repos/{repository}/git/blobs/{blob_sha}")
    if not isinstance(payload, dict):
        raise PrManifestResolutionError(f"Git blob {blob_sha} is not an object")
    if payload.get("encoding") != "base64" or not isinstance(
        payload.get("content"), str
    ):
        raise PrManifestResolutionError(
            f"Git blob {blob_sha} lacks base64-encoded content"
        )
    try:
        encoded = "".join(payload["content"].split())
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise PrManifestResolutionError(
            f"Git blob {blob_sha} has invalid base64 content"
        ) from exc
    return b"\x00" in content


def read_git_blob_text(
    *, repository: str, blob_sha: str, api_get: Callable[[str], object]
) -> str:
    """Read one immutable text blob, failing closed on invalid encoding."""

    payload = api_get(f"repos/{repository}/git/blobs/{blob_sha}")
    if not isinstance(payload, dict):
        raise PrManifestResolutionError(f"Git blob {blob_sha} is not an object")
    if payload.get("encoding") != "base64" or not isinstance(
        payload.get("content"), str
    ):
        raise PrManifestResolutionError(
            f"Git blob {blob_sha} lacks base64-encoded content"
        )
    try:
        encoded = "".join(payload["content"].split())
        return base64.b64decode(encoded, validate=True).decode("utf-8")
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise PrManifestResolutionError(
            f"Git blob {blob_sha} is not valid UTF-8 text"
        ) from exc


def _tree_object(
    tree: dict[str, _GitTreeEntry],
    path: str,
    *,
    revision: str,
    required: bool,
) -> _GitTreeEntry | None:
    entry = tree.get(path)
    if entry is None and required:
        raise PrManifestResolutionError(
            f"Git tree for {revision} lacks changed path {path!r}"
        )
    return entry


def _side_metadata(
    entry: _GitTreeEntry | None,
) -> tuple[str | None, str | None]:
    if entry is None:
        return None, None
    return entry.mode, entry.object_type


def enrich_pull_manifest(
    *,
    repository: str,
    snapshot: ModelPullManifestSnapshot,
    api_get: Callable[[str], object],
) -> tuple[ModelPullManifestEntry, ...]:
    """Derive complete manifest metadata from base/head Git objects.

    PR file-list records supply the closed diff status and rename predecessor.
    Modes, object types, blob identities, binary status, and submodule status come
    only from immutable base/head Git trees and blobs.
    """

    diff_base_tree = _read_tree(
        repository=repository, revision=snapshot.diff_base_sha, api_get=api_get
    )
    head_tree = _read_tree(
        repository=repository, revision=snapshot.head_sha, api_get=api_get
    )
    binary_by_blob: dict[str, bool] = {}
    entries: list[ModelPullManifestEntry] = []

    def is_binary(tree_entry: _GitTreeEntry | None) -> bool:
        if tree_entry is None or tree_entry.object_type != "blob":
            return False
        if tree_entry.sha not in binary_by_blob:
            binary_by_blob[tree_entry.sha] = _binary_blob(
                repository=repository, blob_sha=tree_entry.sha, api_get=api_get
            )
        return binary_by_blob[tree_entry.sha]

    for record in snapshot.files:
        old_path = (
            record.previous_filename
            if record.status in {"renamed", "copied"}
            else record.filename
        )
        old_required = record.status != "added"
        new_required = record.status != "removed"
        old = _tree_object(
            diff_base_tree,
            old_path,
            revision=snapshot.diff_base_sha,
            required=old_required,
        )
        new = _tree_object(
            head_tree,
            record.filename,
            revision=snapshot.head_sha,
            required=new_required,
        )

        reported_blob = (
            new.sha if new is not None else old.sha if old is not None else None
        )
        if record.blob_sha != reported_blob:
            raise PrManifestResolutionError(
                f"PR file blob SHA does not match Git object for {record.filename!r}"
            )
        if reported_blob is None:
            raise PrManifestResolutionError(
                f"changed path {record.filename!r} has no Git blob identity"
            )

        old_mode, old_type = _side_metadata(old)
        new_mode, new_type = _side_metadata(new)
        is_submodule = (old is not None and old.object_type == "commit") or (
            new is not None and new.object_type == "commit"
        )
        entries.append(
            ModelPullManifestEntry(
                filename=record.filename,
                status=record.status,
                previous_filename=record.previous_filename,
                old_blob_sha=old.sha
                if old is not None and old.object_type == "blob"
                else None,
                new_blob_sha=new.sha
                if new is not None and new.object_type == "blob"
                else None,
                blob_sha=reported_blob,
                old_mode=old_mode,
                new_mode=new_mode,
                old_object_type=old_type,
                new_object_type=new_type,
                is_binary=is_binary(old) or is_binary(new),
                is_submodule=is_submodule,
            )
        )
    return tuple(entries)
