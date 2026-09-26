# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Tests for ``scripts/worktree_removal_snapshot.py`` (OMN-19539).

Every test builds a throwaway bare origin, a clone and a linked worktree under
``tmp_path``, with ``OMNI_HOME`` pointed at a scratch registry, so nothing here
can read or write a real clone, worktree or ``.onex_state``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tarfile
from collections.abc import Mapping
from pathlib import Path

import pytest

from scripts import worktree_removal_snapshot as snap

pytestmark = pytest.mark.unit

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "worktree_removal_snapshot.py"
)


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    """Drop the git location variables that override ``-C`` (OMN-18434)."""
    scrubbed = dict(env)
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        scrubbed.pop(key, None)
    return scrubbed


_GIT_ENV = {
    **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    "GIT_AUTHOR_NAME": "omn19539",
    "GIT_COMMITTER_NAME": "omn19539",
    "GIT_AUTHOR_EMAIL": "omn19539@example.invalid",
    "GIT_COMMITTER_EMAIL": "omn19539@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        env=scrub_git_location_env(_GIT_ENV),
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc.stdout


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A scratch OMNI_HOME holding a bare origin and a clone pushed to it."""
    registry_root = tmp_path / "registry_root"
    origin = tmp_path / "origin.git"
    clone = registry_root / "omnibase_infra"
    registry_root.mkdir()
    _git(tmp_path, "init", "-q", "--bare", "-b", "dev", str(origin))
    _git(tmp_path, "clone", "-q", str(origin), str(clone))
    (clone / ".gitignore").write_text(
        ".env\n.venv/\ndist/\n*.local.json\nscratch/\n", encoding="utf-8"
    )
    (clone / "src").mkdir()
    (clone / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (clone / "logo.bin").write_bytes(bytes(range(256)))
    _git(clone, "add", "-A")
    _git(clone, "commit", "-q", "-m", "init")
    _git(clone, "push", "-q", "origin", "HEAD:dev")
    monkeypatch.setenv("OMNI_HOME", str(registry_root))
    return registry_root


def _worktree(registry: Path, ticket: str = "OMN-1", branch: str = "wt-1") -> Path:
    clone = registry / "omnibase_infra"
    worktree = registry / "omni_worktrees" / ticket / "omnibase_infra"
    worktree.parent.mkdir(parents=True, exist_ok=True)
    _git(clone, "worktree", "add", "-q", str(worktree), "-b", branch, "origin/dev")
    return worktree


def _members(snapshot: snap.Snapshot) -> set[str]:
    with tarfile.open(Path(snapshot.directory) / "untracked.tar.gz", "r:gz") as tar:
        return set(tar.getnames())


class TestClassification:
    def test_secret_shaped_names_are_never_regenerable(self) -> None:
        for name in (
            ".env",
            ".env.local",
            "prod.env",
            "id_rsa",
            "tls.pem",
            "settings.local.json",
        ):
            assert snap.is_secret_shaped(name), name
            assert not snap.is_regenerable_file(name), name
            assert not snap.is_regenerable_dir(name), name

    def test_caches_are_regenerable(self) -> None:
        for name in (
            ".venv",
            "node_modules",
            "dist",
            "build",
            "__pycache__",
            "pkg.egg-info",
        ):
            assert snap.is_regenerable_dir(name), name
        for name in ("a.pyc", ".DS_Store", ".coverage"):
            assert snap.is_regenerable_file(name), name

    def test_ordinary_names_are_neither(self) -> None:
        for name in ("notes.md", "scratch", "data.csv", "credentials.py"):
            assert not snap.is_secret_shaped(name), name
            assert not snap.is_regenerable_dir(name), name
            assert not snap.is_regenerable_file(name), name


class TestSnapshotContents:
    def test_dirty_worktree_saves_diff_untracked_and_ignored_non_regenerable(
        self, registry: Path
    ) -> None:
        worktree = _worktree(registry)
        (worktree / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
        (worktree / "logo.bin").write_bytes(bytes(reversed(range(256))))
        (worktree / "src" / "staged.py").write_text("STAGED = 1\n", encoding="utf-8")
        _git(worktree, "add", "src/staged.py")
        (worktree / "notes.md").write_text("untracked\n", encoding="utf-8")
        (worktree / ".env").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
        (worktree / ".claude").mkdir()
        (worktree / ".claude" / "settings.local.json").write_text(
            "{}\n", encoding="utf-8"
        )
        (worktree / "scratch").mkdir()
        (worktree / "scratch" / "draft.txt").write_text("draft\n", encoding="utf-8")
        (worktree / ".venv" / "lib").mkdir(parents=True)
        (worktree / ".venv" / "lib" / "big.py").write_text("x = 1\n", encoding="utf-8")
        (worktree / "dist").mkdir()
        (worktree / "dist" / "bundle.js").write_text("built\n", encoding="utf-8")
        (worktree / "dist" / ".env").write_text("DIST_TOKEN=x\n", encoding="utf-8")

        snapshot = snap.snapshot_before_removal(worktree, reason="test")

        members = _members(snapshot)
        assert {
            "notes.md",
            ".env",
            ".claude/settings.local.json",
            "scratch/draft.txt",
            "dist/.env",
        } <= members
        assert "dist/bundle.js" not in members
        assert ".venv/lib/big.py" not in members
        skipped = (Path(snapshot.directory) / "skipped-regenerable.txt").read_text()
        assert ".venv/" in skipped and "dist/" in skipped

        # The patch carries the tracked edits, binary included, and restores them
        # onto a clean checkout of the same HEAD.
        patch = Path(snapshot.directory) / "full-vs-HEAD.patch"
        assert b"GIT binary patch" in patch.read_bytes()
        fresh = _worktree(registry, ticket="OMN-2", branch="wt-2")
        _git(fresh, "apply", "--index", str(patch))
        assert (fresh / "src" / "app.py").read_text() == "VALUE = 2\n"
        assert (fresh / "src" / "staged.py").read_text() == "STAGED = 1\n"
        assert (fresh / "logo.bin").read_bytes() == (worktree / "logo.bin").read_bytes()

    def test_manifest_digests_match_the_files_and_the_index_names_the_snapshot(
        self, registry: Path
    ) -> None:
        worktree = _worktree(registry)
        (worktree / "notes.md").write_text("untracked\n", encoding="utf-8")

        snapshot = snap.snapshot_before_removal(worktree, reason="test-manifest")

        directory = Path(snapshot.directory)
        assert (
            directory.parent == registry / ".onex_state" / "worktree-removal-snapshots"
        )
        assert directory.name.startswith("OMN-1-omnibase_infra-")
        manifest = (directory / "MANIFEST.txt").read_text().splitlines()
        digests = {
            line.split("  ", 1)[1]: line.split()[1]
            for line in manifest
            if line.startswith("sha256 ")
        }
        for name in ("status.txt", "full-vs-HEAD.patch", "untracked.tar.gz"):
            assert digests[name] == snap._sha256(directory / name)
        assert f"worktree={worktree}" in manifest
        index = (directory.parent / "INDEX.tsv").read_text().splitlines()
        assert any(str(directory) in line and "test-manifest" in line for line in index)
        assert not list(directory.parent.glob("*.partial"))

    def test_unpushed_commits_are_bundled_and_verify(self, registry: Path) -> None:
        worktree = _worktree(registry)
        (worktree / "src" / "new.py").write_text("NEW = 1\n", encoding="utf-8")
        _git(worktree, "add", "-A")
        _git(worktree, "commit", "-q", "-m", "local only")

        snapshot = snap.snapshot_before_removal(worktree, reason="test")

        assert snapshot.unpushed_commits == 1
        bundle = Path(snapshot.bundle)
        assert bundle.is_file()
        heads = _git(registry / "omnibase_infra", "bundle", "list-heads", str(bundle))
        assert _git(worktree, "rev-parse", "HEAD").strip() in heads

    def test_clean_pushed_worktree_saves_an_empty_diff_and_no_bundle(
        self, registry: Path
    ) -> None:
        worktree = _worktree(registry)

        snapshot = snap.snapshot_before_removal(worktree, reason="test")

        assert Path(snapshot.directory, "full-vs-HEAD.patch").read_bytes() == b""
        assert snapshot.unpushed_commits == 0
        assert snapshot.bundle == ""
        assert snapshot.files_archived == 0

    def test_non_git_debris_archives_the_whole_directory(
        self, tmp_path: Path, registry: Path
    ) -> None:
        debris = registry / "omni_worktrees" / "OMN-3" / "omnimarket"
        (debris / "src").mkdir(parents=True)
        (debris / "src" / "left.py").write_text("LEFT = 1\n", encoding="utf-8")
        (debris / ".env").write_text("K=V\n", encoding="utf-8")
        (debris / "node_modules" / "pkg").mkdir(parents=True)
        (debris / "node_modules" / "pkg" / "index.js").write_text(
            "x\n", encoding="utf-8"
        )

        snapshot = snap.snapshot_before_removal(
            debris, reason="debris", allow_non_git=True
        )

        assert snapshot.git_worktree is False
        assert _members(snapshot) == {"src/left.py", ".env"}


class TestRefusals:
    def test_unset_registry_root_refuses(
        self, registry: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        worktree = _worktree(registry)
        monkeypatch.delenv("OMNI_HOME")
        with pytest.raises(snap.SnapshotError, match="OMNI_HOME"):
            snap.snapshot_before_removal(worktree, reason="test")

    def test_size_cap_refuses_and_leaves_no_partial_snapshot(
        self, registry: Path
    ) -> None:
        worktree = _worktree(registry)
        (worktree / "scratch").mkdir()
        (worktree / "scratch" / "big.dat").write_bytes(b"\0" * 4096)

        with pytest.raises(snap.SnapshotError, match="cap"):
            snap.snapshot_before_removal(worktree, reason="test", max_bytes=1024)

        root = registry / ".onex_state" / "worktree-removal-snapshots"
        assert not [p for p in root.iterdir() if p.name != "INDEX.tsv"]

    def test_a_directory_that_is_not_a_worktree_refuses_without_allow_non_git(
        self, registry: Path
    ) -> None:
        plain = registry / "omni_worktrees" / "OMN-4" / "omniclaude"
        plain.mkdir(parents=True)
        (plain / "file.txt").write_text("x\n", encoding="utf-8")
        with pytest.raises(snap.SnapshotError, match="not a readable git worktree"):
            snap.snapshot_before_removal(plain, reason="test")

    def test_a_state_root_inside_the_worktree_refuses(self, registry: Path) -> None:
        worktree = _worktree(registry)
        with pytest.raises(snap.SnapshotError, match="inside the worktree"):
            snap.snapshot_before_removal(
                worktree, reason="test", registry_root=worktree
            )

    def test_a_corrupt_index_refuses(self, registry: Path) -> None:
        worktree = _worktree(registry)
        gitdir = Path(_git(worktree, "rev-parse", "--absolute-git-dir").strip())
        (gitdir / "index").write_bytes(b"not an index")
        with pytest.raises(snap.SnapshotError):
            snap.snapshot_before_removal(worktree, reason="test")


class TestCli:
    def test_cli_exit_0_prints_the_snapshot(self, registry: Path) -> None:
        worktree = _worktree(registry)
        proc = subprocess.run(
            ["python3", str(SCRIPT), str(worktree), "--reason", "cli"],
            capture_output=True,
            text=True,
            env=scrub_git_location_env(dict(os.environ)),
            check=False,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["ok"] is True
        assert Path(payload["directory"]).is_dir()

    def test_cli_exit_3_on_refusal(self, registry: Path) -> None:
        worktree = _worktree(registry)
        env = scrub_git_location_env(dict(os.environ))
        env.pop("OMNI_HOME", None)
        proc = subprocess.run(
            ["python3", str(SCRIPT), str(worktree), "--reason", "cli"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
            timeout=120,
        )
        assert proc.returncode == 3
        assert json.loads(proc.stdout)["ok"] is False
        assert "REFUSED" in proc.stderr
