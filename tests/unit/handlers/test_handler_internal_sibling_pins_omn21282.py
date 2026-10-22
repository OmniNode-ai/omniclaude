# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21282 AC2: internal-sibling-pins refuses a release-version internal pin
where a newer dev tag exists.

RULING 2026-10-16T07:34:18Z: an internal sibling is read by branch or tag, with
no waiting for a release. Every dev merge of a sibling is tagged
``dev-<UTC YYYYMMDDHHMMSS>-<sha12>``, so a change that lands the consumer on a
release (a PyPI version, or a git release tag) while the sibling already carries
a newer dev merge tag is pinning the past. These tests run the pin check over
fixture lock files: the release published before the newest dev tag is refused,
the release newer than every dev tag passes, a dev-tag pin passes, a pin the
change does not move stands without being refused, and a moved release pin whose
sibling's tags were never read is refused rather than assumed fine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omniclaude.enums.enum_sibling_pin_kind import EnumSiblingPinKind
from omniclaude.enums.enum_sibling_pin_verdict import EnumSiblingPinVerdict
from omniclaude.handlers.handler_internal_sibling_pins import handle, main
from omniclaude.models.model_internal_sibling_pins import (
    ModelInternalSiblingPinsRequest,
)

pytestmark = pytest.mark.unit

_CORE_REPO = "omnibase_core"
_DEV_OLD = "dev-20261018000000-aaaaaaaaaaaa"
_DEV_NEW = "dev-20261020120000-bbbbbbbbbbbb"


def _registry(name: str, version: str, uploaded: str) -> str:
    return (
        "[[package]]\n"
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        f'sdist = {{ url = "https://files.example/{name}-{version}.tar.gz", '
        f'hash = "sha256:00", size = 1, upload-time = "{uploaded}" }}\n'
        "wheels = [\n"
        f'    {{ url = "https://files.example/{name}-{version}.whl", '
        f'hash = "sha256:00", size = 1, upload-time = "{uploaded}" }},\n'
        "]\n\n"
    )


def _git(name: str, version: str, repo: str, ref_kind: str, ref: str) -> str:
    sha = "c" * 40
    return (
        "[[package]]\n"
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        f'source = {{ git = "https://github.com/OmniNode-ai/{repo}.git?{ref_kind}={ref}#{sha}" }}\n\n'
    )


def _lock(*packages: str) -> str:
    return 'version = 1\nrequires-python = ">=3.12"\n\n' + "".join(packages)


def _request(
    head: str, base: str | None, tags: dict[str, list[str]] | None = None
) -> ModelInternalSiblingPinsRequest:
    return ModelInternalSiblingPinsRequest(
        head_lock_text=head,
        base_lock_text=base,
        dev_tags={} if tags is None else tags,
    )


def test_moved_release_pin_older_than_a_dev_tag_is_refused() -> None:
    base = _lock(_registry("omnibase-core", "0.47.50", "2026-10-17T09:00:00Z"))
    head = _lock(_registry("omnibase-core", "0.47.51", "2026-10-19T09:00:00Z"))
    result = handle(_request(head, base, {_CORE_REPO: [_DEV_OLD, _DEV_NEW]}))
    assert not result.passed
    [refused] = result.refused
    assert refused.distribution == "omnibase-core"
    assert refused.kind is EnumSiblingPinKind.RELEASE
    assert refused.verdict is EnumSiblingPinVerdict.REFUSED
    assert refused.newest_dev_tag == _DEV_NEW
    assert _DEV_NEW in refused.reason


def test_release_newer_than_every_dev_tag_passes() -> None:
    base = _lock(_registry("omnibase-core", "0.47.50", "2026-10-17T09:00:00Z"))
    head = _lock(_registry("omnibase-core", "0.47.51", "2026-10-21T09:00:00Z"))
    result = handle(_request(head, base, {_CORE_REPO: [_DEV_OLD, _DEV_NEW]}))
    assert result.passed
    assert result.refused == []


def test_dev_tag_pin_passes_without_reading_tags() -> None:
    base = _lock(_registry("omnibase-core", "0.47.50", "2026-10-17T09:00:00Z"))
    head = _lock(_git("omnibase-core", "0.47.52", _CORE_REPO, "tag", _DEV_NEW))
    result = handle(_request(head, base))
    assert result.passed
    [finding] = result.findings
    assert finding.kind is EnumSiblingPinKind.DEV_TAG
    assert finding.verdict is EnumSiblingPinVerdict.ALLOWED


def test_git_release_tag_is_refused_when_any_dev_tag_exists() -> None:
    head = _lock(_git("omnibase-core", "0.47.46", _CORE_REPO, "tag", "v0.47.46"))
    result = handle(_request(head, _lock(), {_CORE_REPO: [_DEV_OLD]}))
    [refused] = result.refused
    assert refused.kind is EnumSiblingPinKind.RELEASE_TAG


def test_unmoved_release_pin_stands_and_is_not_refused() -> None:
    lock = _lock(_registry("omnibase-core", "0.47.51", "2026-10-19T09:00:00Z"))
    result = handle(_request(lock, lock))
    assert result.passed
    [finding] = result.findings
    assert finding.verdict is EnumSiblingPinVerdict.STANDING
    assert result.repos_needing_tags == []


def test_moved_release_pin_with_unread_tags_is_refused() -> None:
    base = _lock(_registry("omnibase-core", "0.47.50", "2026-10-17T09:00:00Z"))
    head = _lock(_registry("omnibase-core", "0.47.51", "2026-10-19T09:00:00Z"))
    result = handle(_request(head, base))
    assert not result.passed
    assert result.repos_needing_tags == [_CORE_REPO]
    assert "not read" in result.refused[0].reason


def test_rev_pin_and_third_party_packages_are_not_judged() -> None:
    head = _lock(
        _git("omnimarket", "0.4.319", "omnimarket", "rev", "d" * 40),
        _registry("pydantic", "2.13.4", "2026-01-01T00:00:00Z"),
    )
    result = handle(_request(head, _lock()))
    assert result.passed
    assert [(f.distribution, f.kind) for f in result.findings] == [
        ("omnimarket", EnumSiblingPinKind.REV),
    ]


def test_cli_over_fixture_lock_files(tmp_path: Path, capsys) -> None:
    base = tmp_path / "base.lock"
    head = tmp_path / "head.lock"
    tags = tmp_path / "tags.json"
    base.write_text(
        _lock(_registry("omnibase-core", "0.47.50", "2026-10-17T09:00:00Z"))
    )
    head.write_text(
        _lock(_registry("omnibase-core", "0.47.51", "2026-10-19T09:00:00Z"))
    )
    args = ["--head-lock", str(head), "--base-lock", str(base)]
    assert main([*args, "--needs-tags"]) == 0
    assert capsys.readouterr().out.split() == [_CORE_REPO]

    tags.write_text(json.dumps({_CORE_REPO: [_DEV_NEW]}))
    assert main([*args, "--dev-tags", str(tags)]) == 1
    assert "REFUSED omnibase-core" in capsys.readouterr().out

    tags.write_text(json.dumps({_CORE_REPO: [_DEV_OLD]}))
    assert main([*args, "--dev-tags", str(tags)]) == 0
