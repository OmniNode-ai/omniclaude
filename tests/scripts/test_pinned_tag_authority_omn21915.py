# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21915: both omnimarket gates compare against the pinned dev-merge tag.

``check_omnimarket_dispatch_drift.py`` and ``check_daemon_venv_skew.py`` used to
compare against the canonical clone's CHECKED-OUT head. That head moved 11 times in
2 hours, so a commit whose hooks run for minutes was refused for a pin that was
right when it started. Both now resolve the commit of the dev-merge tag the lock
pins, through ``handler_omnimarket_pinned_tag``, reading the clone for its tags only.

Each test builds a throwaway clone with real commits and real tags and runs the real
gate against it. The positive control is the same state judged by the old rule: the
clone head differs from the tag commit in every fixture, so a gate that still read
the head would fail the passing cases.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "scripts"
_GIT_LOCATION_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CEILING_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _load(name: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


drift = _load("check_omnimarket_dispatch_drift")
skew = _load("check_daemon_venv_skew")
pins = skew.git_source_pins


def scrub_git_location_env(env: Mapping[str, str]) -> dict[str, str]:
    return {k: v for k, v in env.items() if k not in _GIT_LOCATION_VARS}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=scrub_git_location_env(os.environ),
    ).stdout.strip()


class Clone:
    """A throwaway omnimarket clone: four commits, tagged at the second."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        _git(path, "init", "-q", "-b", "dev")
        _git(path, "config", "user.email", "t@example.invalid")
        _git(path, "config", "user.name", "t")
        self.commits: list[str] = []
        for n in range(4):
            (path / "f.txt").write_text(f"{n}\n", encoding="utf-8")
            _git(path, "add", "f.txt")
            _git(path, "commit", "-q", "-m", f"c{n}")
            self.commits.append(_git(path, "rev-parse", "HEAD"))
        self.tagged = self.commits[1]
        self.tag = self.tag_of(self.tagged)
        _git(path, "tag", self.tag, self.tagged)

    @staticmethod
    def tag_of(sha: str) -> str:
        return f"dev-20261101120000-{sha[:12]}"

    @property
    def head(self) -> str:
        return _git(self.path, "rev-parse", "HEAD")


@pytest.fixture
def clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Clone:
    c = Clone(tmp_path / "registry" / "omnimarket")
    for var in (
        "OMNIMARKET_EXPECTED_SHA",
        "OMNIMARKET_CANONICAL_SHA",
        "PLUGIN_PYTHON_BIN",
        "ONEX_REGISTRY_ROOT",
        "OMNICLAUDE_PROJECT_ROOT",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "registry"))
    monkeypatch.setenv("OMNIMARKET_ROOT", str(c.path))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "no-venv"))
    assert c.head != c.tagged, "the fixture must advance the clone past the tag"
    return c


def _lock(tmp_path: Path, *, rev: str, tag: str | None) -> Path:
    query = f"tag={tag}" if tag else f"rev={rev}"
    lock = tmp_path / "uv.lock"
    lock.write_text(
        'version = 1\n\n[[package]]\nname = "omnimarket"\nversion = "1"\n'
        f'source = {{ git = "https://github.com/OmniNode-ai/omnimarket.git?{query}#{rev}" }}\n',
        encoding="utf-8",
    )
    return lock


def _fake_venv(tmp_path: Path, commit: str) -> Path:
    """A plugin venv whose omnimarket was installed from ``commit`` (PEP 610)."""
    venv = tmp_path / "data" / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").write_text("#!/bin/sh\n", encoding="utf-8")
    dist = venv / "lib" / "python3.12" / "site-packages" / "omnimarket-1.dist-info"
    dist.mkdir(parents=True)
    (dist / "direct_url.json").write_text(
        json.dumps({"vcs_info": {"vcs": "git", "commit_id": commit}}), encoding="utf-8"
    )
    return venv


# ---------------------------------------------------------------------------
# AC1: the gate result follows the tag, not the clone head
# ---------------------------------------------------------------------------


def test_dispatch_gate_passes_a_pin_at_the_tag_commit_while_the_clone_is_past_it(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)

    rc = drift.main([f"--lock={lock}"])

    out = capsys.readouterr().out
    assert rc == 0, out
    assert clone.tag in out and "clone head not consulted" in out


def test_the_result_does_not_change_when_the_clone_head_moves(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The race itself: HEAD moves between two runs of one commit's hooks."""
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    first = drift._resolve_expected_sha(lock_path=lock)

    (clone.path / "f.txt").write_text("later\n", encoding="utf-8")
    _git(clone.path, "commit", "-q", "-am", "an omnimarket dev merge lands")

    assert drift._resolve_expected_sha(lock_path=lock) == first
    assert drift.main([f"--lock={lock}"]) == 0, capsys.readouterr().out


def test_a_pin_at_the_clone_head_is_refused_when_the_tag_names_an_older_commit(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The old rule would have passed this pin; the tag is the authority now."""
    lock = _lock(tmp_path, rev=clone.head, tag=clone.tag)

    rc = drift.main([f"--lock={lock}"])

    err = capsys.readouterr().err
    assert rc == 1
    assert clone.head[:12] in err and clone.tagged[:12] in err


def test_rev_pin_is_judged_against_the_dev_merge_tag_that_names_it(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=None)

    assert drift.main([f"--lock={lock}"]) == 0, capsys.readouterr().out


def test_skew_gate_expects_the_tag_commit_not_the_clone_head(
    clone: Clone, tmp_path: Path
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    sources = pins.parse_git_sources(lock)
    assert sources["omnimarket"].tag == clone.tag
    authority = {"omnimarket": pins.EnumGitSourceAuthority.CLONE}
    venv = _fake_venv(tmp_path, clone.tagged)

    findings, _ = skew._check_git_source_skew(
        sources, [("plugin CLI venv", venv / "bin" / "python3")], authority
    )

    assert findings == []


# ---------------------------------------------------------------------------
# AC2: exactly as strict -- a wrong pin, an off-tag venv, an unreadable tag source
# ---------------------------------------------------------------------------


def test_a_pin_that_is_not_the_tag_commit_is_refused(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = _lock(tmp_path, rev=clone.commits[0], tag=clone.tag)

    rc = drift.main([f"--lock={lock}"])

    err = capsys.readouterr().err
    assert rc == 1
    assert "does not match expected dispatch SHA" in err
    assert clone.commits[0][:12] in err and clone.tagged[:12] in err


def test_a_rev_that_no_dev_merge_tag_names_is_refused(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lock = _lock(tmp_path, rev=clone.commits[2], tag=None)

    rc = drift.main([f"--lock={lock}"])

    err = capsys.readouterr().err
    assert rc == 1
    assert "names no dev-merge tag" in err or "no dev-merge tag" in err


def test_a_tag_the_clone_does_not_hold_fails_closed_and_never_falls_back_to_the_lock(
    clone: Clone, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ghost = Clone.tag_of("f" * 40)
    lock = _lock(tmp_path, rev="f" * 40, tag=ghost)

    rc = drift.main([f"--lock={lock}"])

    err = capsys.readouterr().err
    assert rc == 1, "the lock must not be compared with itself"
    assert "fails closed" in err


def test_a_tag_whose_name_disagrees_with_its_commit_is_refused(
    clone: Clone,
) -> None:
    liar = Clone.tag_of(clone.commits[2])
    _git(clone.path, "tag", liar, clone.commits[0])

    with pytest.raises(pins.ErrorPinnedTag, match="not at the commit its name"):
        pins.pinned_tag_commit(clone.path, rev=clone.commits[2], declared_tag=liar)


def test_a_declared_tag_that_is_not_a_dev_merge_tag_is_refused(clone: Clone) -> None:
    with pytest.raises(pins.ErrorPinnedTag, match="not a dev-merge tag"):
        pins.pinned_tag_commit(clone.path, rev=clone.tagged, declared_tag="v0.4.0")


def test_a_stale_installed_venv_is_still_refused_by_the_dispatch_gate(
    clone: Clone,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    _fake_venv(tmp_path, clone.commits[0])
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))

    rc = drift.main([f"--lock={lock}"])

    err = capsys.readouterr().err
    assert rc == 1
    assert "STALE" in err and clone.commits[0][:12] in err


def test_an_installed_venv_at_the_tag_commit_passes_though_the_clone_is_past_it(
    clone: Clone,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    _fake_venv(tmp_path, clone.tagged)
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))

    assert drift.main([f"--lock={lock}"]) == 0, capsys.readouterr().out


@pytest.mark.parametrize(
    ("installed_index", "state"),
    [
        (0, "BEHIND"),  # an ancestor of the tag commit
        (2, "AHEAD"),  # a descendant: what a venv converged to the clone head is
    ],
)
def test_an_off_tag_installed_commit_is_refused_by_the_skew_gate(
    clone: Clone, tmp_path: Path, installed_index: int, state: str
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    authority = {"omnimarket": pins.EnumGitSourceAuthority.CLONE}
    venv = _fake_venv(tmp_path, clone.commits[installed_index])

    findings, _ = skew._check_git_source_skew(
        pins.parse_git_sources(lock),
        [("plugin CLI venv", venv / "bin" / "python3")],
        authority,
    )

    assert len(findings) == 1 and state in findings[0]
    assert clone.tag in findings[0]


def test_the_skew_gate_fails_closed_on_a_tag_the_clone_does_not_hold(
    clone: Clone, tmp_path: Path
) -> None:
    lock = _lock(tmp_path, rev="f" * 40, tag=Clone.tag_of("f" * 40))
    authority = {"omnimarket": pins.EnumGitSourceAuthority.CLONE}

    findings, _ = skew._check_git_source_skew(
        pins.parse_git_sources(lock), [], authority
    )

    assert len(findings) == 1 and "fails closed" in findings[0]


def test_override_flags_and_env_names_keep_their_behaviour(
    clone: Clone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    other = "a" * 40

    assert (
        drift._resolve_expected_sha(expected_sha_override=other, lock_path=lock)[0]
        == other
    )
    assert (
        drift._resolve_expected_sha(canonical_sha_override=other, lock_path=lock)[0]
        == other
    )
    monkeypatch.setenv("OMNIMARKET_CANONICAL_SHA", other)
    assert drift._resolve_expected_sha(lock_path=lock)[0] == other
    monkeypatch.setenv("OMNIMARKET_EXPECTED_SHA", "b" * 40)
    assert (
        drift._resolve_expected_sha(canonical_sha_override=other, lock_path=lock)[0]
        == "b" * 40
    )


def test_without_a_clone_the_lock_pin_is_still_the_fallback(
    clone: Clone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = _lock(tmp_path, rev=clone.tagged, tag=clone.tag)
    monkeypatch.delenv("OMNIMARKET_ROOT")
    monkeypatch.setenv("OMNI_HOME", str(tmp_path / "no-registry"))

    sha, source = drift._resolve_expected_sha(lock_path=lock)

    assert sha == clone.tagged and "uv.lock pin" in source


def test_an_inherited_git_dir_does_not_retarget_the_tag_probe(
    clone: Clone, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pre-commit exports GIT_DIR to every hook; it must not redirect the tag read."""
    other = tmp_path / "unrelated"
    other.mkdir()
    _git(other, "init", "-q", "-b", "dev")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))

    assert pins.pinned_tag_commit(
        clone.path, rev=clone.tagged, declared_tag=clone.tag
    ) == (clone.tag, clone.tagged)


def test_the_resolver_never_reads_the_clone_head() -> None:
    """A gate that asked for HEAD again would restore the race; pin it in the source."""
    resolver = (_SCRIPTS / "git_source_pins.py").read_text(encoding="utf-8")
    body = resolver.split("def pinned_tag_commit", 1)[1].split("\ndef ", 1)[0]
    assert "HEAD" not in body.split('"""')[-1]
    gate = (_SCRIPTS / "check_omnimarket_dispatch_drift.py").read_text(encoding="utf-8")
    code = gate.split("def _resolve_expected_sha", 1)[1].split("\ndef ", 1)[0]
    assert "rev-parse" not in code.split('"""')[-1]
    assert not hasattr(pins, "clone_head")


def test_shallow_tagless_clone_names_the_lock_pin_but_a_full_one_fails(
    clone: Clone, tmp_path: Path
) -> None:
    """The CI sibling clone is one shallow rev with no tags: no tag source at all."""
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{clone.path}", str(shallow))

    assert pins.pinned_tag_commit(shallow, rev=clone.tagged, declared_tag=None) == (
        "uv.lock",
        clone.tagged,
    )
    with pytest.raises(pins.ErrorPinnedTag):
        pins.pinned_tag_commit(clone.path, rev="0" * 40, declared_tag=None)
