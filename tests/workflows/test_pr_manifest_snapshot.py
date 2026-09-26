# SPDX-FileCopyrightText: 2026 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Focused tests for immutable deploy-gate PR manifest transport."""

from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_MODULE = (
    Path(__file__).resolve().parents[2]
    / ".github"
    / "actions"
    / "deploy-gate"
    / "pr_manifest_snapshot.py"
)


def _load_module() -> ModuleType:
    sys.path.insert(0, str(_MODULE.parent))
    spec = importlib.util.spec_from_file_location("pr_manifest_snapshot", _MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


snapshot = _load_module()
_REPO = "OmniNode-ai/omnibase_core"
_BASE = "a" * 40
_HEAD = "b" * 40
_DIFF_BASE = "d" * 40


def _pr(count: int, head: str = _HEAD) -> dict[str, object]:
    return {
        "base": {"sha": _BASE, "repo": {"full_name": _REPO}},
        "head": {"sha": head},
        "changed_files": count,
    }


def _comparison() -> dict[str, object]:
    return {"merge_base_commit": {"sha": _DIFF_BASE}}


def _file(index: int) -> dict[str, str]:
    return {
        "filename": f"src/omnibase_core/models/model_{index}.py",
        "status": "modified",
        "sha": f"{index:040x}",
    }


def test_reads_every_page_and_rechecks_head_identity() -> None:
    pages = [_file(index) for index in range(101)]

    def api_get(endpoint: str) -> object:
        if endpoint == f"repos/{_REPO}/pulls/123":
            return _pr(101)
        if endpoint == f"repos/{_REPO}/compare/{_BASE}...{_HEAD}":
            return _comparison()
        if endpoint.endswith("page=1"):
            return pages[:100]
        if endpoint.endswith("page=2"):
            return pages[100:]
        raise AssertionError(endpoint)

    result = snapshot.resolve_pull_manifest(
        repository=_REPO, pr_number=123, event_head_sha=_HEAD, api_get=api_get
    )

    assert result.base_sha == _BASE
    assert result.head_sha == _HEAD
    assert result.diff_base_sha == _DIFF_BASE
    assert len(result.files) == 101


def test_rejects_head_changed_during_pagination() -> None:
    calls = 0

    def api_get(endpoint: str) -> object:
        nonlocal calls
        if endpoint == f"repos/{_REPO}/pulls/123":
            calls += 1
            return _pr(1, _HEAD if calls == 1 else "c" * 40)
        if endpoint == f"repos/{_REPO}/compare/{_BASE}...{_HEAD}":
            return _comparison()
        if endpoint.endswith("page=1"):
            return [_file(1)]
        raise AssertionError(endpoint)

    with pytest.raises(snapshot.PrManifestResolutionError, match="changed"):
        snapshot.resolve_pull_manifest(
            repository=_REPO, pr_number=123, event_head_sha=_HEAD, api_get=api_get
        )


@pytest.mark.parametrize(
    ("event_head", "files_payload", "match"),
    [
        ("", [_file(1)], "event"),
        (_HEAD, [_file(1)] * 2, "pagination"),
        (_HEAD, {"filename": "not-an-array"}, "not an array"),
    ],
)
def test_rejects_missing_head_truncation_and_malformed_pages(
    event_head: str, files_payload: object, match: str
) -> None:
    def api_get(endpoint: str) -> object:
        if endpoint == f"repos/{_REPO}/pulls/123":
            return _pr(1)
        if endpoint == f"repos/{_REPO}/compare/{_BASE}...{_HEAD}":
            return _comparison()
        if endpoint.endswith("page=1"):
            return files_payload
        raise AssertionError(endpoint)

    with pytest.raises(snapshot.PrManifestResolutionError, match=match):
        snapshot.resolve_pull_manifest(
            repository=_REPO, pr_number=123, event_head_sha=event_head, api_get=api_get
        )


def _tree_entry(
    path: str, sha: str, *, mode: str = "100644", kind: str = "blob"
) -> dict[str, str]:
    return {"path": path, "mode": mode, "type": kind, "sha": sha}


def _blob(content: bytes) -> dict[str, str]:
    return {
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
    }


def test_enriches_modes_types_binary_and_rename_from_git_objects() -> None:
    old_rename = "1" * 40
    removed = "2" * 40
    old_modified = "3" * 40
    new_rename = "4" * 40
    added = "5" * 40
    new_modified = "6" * 40
    snapshot_value = snapshot.ModelPullManifestSnapshot(
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        files=(
            snapshot.ModelPullFileRecord(
                "pkg/new.py", "renamed", "pkg/old.py", new_rename
            ),
            snapshot.ModelPullFileRecord("pkg/added.py", "added", None, added),
            snapshot.ModelPullFileRecord("pkg/removed.py", "removed", None, removed),
            snapshot.ModelPullFileRecord(
                "pkg/changed.py", "modified", None, new_modified
            ),
        ),
    )
    trees = {
        _DIFF_BASE: [
            _tree_entry("pkg/old.py", old_rename),
            _tree_entry("pkg/removed.py", removed),
            _tree_entry("pkg/changed.py", old_modified),
        ],
        _HEAD: [
            _tree_entry("pkg/new.py", new_rename),
            _tree_entry("pkg/added.py", added),
            _tree_entry("pkg/changed.py", new_modified),
        ],
    }
    blobs = {
        old_rename: _blob(b"old\n"),
        removed: _blob(b"removed\n"),
        old_modified: _blob(b"old\n"),
        new_rename: _blob(b"new\n"),
        added: _blob(b"binary\x00payload"),
        new_modified: _blob(b"new\n"),
    }

    def api_get(endpoint: str) -> object:
        prefix = f"repos/{_REPO}/git/trees/"
        if endpoint.startswith(prefix):
            revision = endpoint.removeprefix(prefix).removesuffix("?recursive=1")
            return {"truncated": False, "tree": trees[revision]}
        blob_prefix = f"repos/{_REPO}/git/blobs/"
        if endpoint.startswith(blob_prefix):
            return blobs[endpoint.removeprefix(blob_prefix)]
        raise AssertionError(endpoint)

    entries = snapshot.enrich_pull_manifest(
        repository=_REPO, snapshot=snapshot_value, api_get=api_get
    )

    assert [entry.blob_sha for entry in entries] == [
        new_rename,
        added,
        removed,
        new_modified,
    ]
    assert entries[0].previous_filename == "pkg/old.py"
    assert (entries[0].old_mode, entries[0].new_mode) == ("100644", "100644")
    assert (entries[1].old_mode, entries[1].new_mode) == (None, "100644")
    assert (entries[2].old_mode, entries[2].new_mode) == ("100644", None)
    assert entries[1].is_binary is True
    assert all(entry.is_submodule is False for entry in entries)


def test_enrichment_uses_pr_merge_base_not_current_base_tip() -> None:
    """A current base tip can already contain the head's blob after the PR forked."""

    old_blob = "1" * 40
    head_blob = "2" * 40
    snapshot_value = snapshot.ModelPullManifestSnapshot(
        base_sha=_BASE,
        head_sha=_HEAD,
        diff_base_sha=_DIFF_BASE,
        files=(
            snapshot.ModelPullFileRecord("pyproject.toml", "modified", None, head_blob),
        ),
    )

    def api_get(endpoint: str) -> object:
        if endpoint == f"repos/{_REPO}/git/trees/{_DIFF_BASE}?recursive=1":
            return {
                "truncated": False,
                "tree": [_tree_entry("pyproject.toml", old_blob)],
            }
        if endpoint == f"repos/{_REPO}/git/trees/{_HEAD}?recursive=1":
            return {
                "truncated": False,
                "tree": [_tree_entry("pyproject.toml", head_blob)],
            }
        if endpoint.startswith(f"repos/{_REPO}/git/blobs/"):
            return _blob(b"text\n")
        raise AssertionError(endpoint)

    (entry,) = snapshot.enrich_pull_manifest(
        repository=_REPO, snapshot=snapshot_value, api_get=api_get
    )

    assert entry.old_mode == "100644"
    assert entry.blob_sha == head_blob


@pytest.mark.parametrize(
    ("tree_payload", "match"),
    [
        ({"truncated": True, "tree": []}, "truncated"),
        ({"truncated": False, "tree": []}, "lacks changed path"),
    ],
)
def test_enrichment_fails_closed_for_incomplete_git_tree(
    tree_payload: dict[str, object], match: str
) -> None:
    record = snapshot.ModelPullFileRecord("pkg/changed.py", "modified", None, "1" * 40)
    snapshot_value = snapshot.ModelPullManifestSnapshot(
        _BASE, _HEAD, _DIFF_BASE, (record,)
    )

    def api_get(endpoint: str) -> object:
        if endpoint.startswith(f"repos/{_REPO}/git/trees/"):
            return tree_payload
        raise AssertionError(endpoint)

    with pytest.raises(snapshot.PrManifestResolutionError, match=match):
        snapshot.enrich_pull_manifest(
            repository=_REPO, snapshot=snapshot_value, api_get=api_get
        )
