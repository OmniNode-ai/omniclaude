# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-19998: internal-sibling-pins accepts a published PyPI release behind a newer dev tag.

RULING 2026-11-02T15:20:36Z (lane=orchestrator-1036, ticket=OMN-19998, kind=process):
let internal-sibling-pins accept a published PyPI version while the sibling's dev
carries a newer merge tag. It loosens only pin freshness and keeps git sources
out of the chain. omnibase-core resolves from PyPI (OMN-13873), so a release
bump can never be satisfied by pinning the dev tag, and the old refusal made the
omnibase-core bump family (omniclaude#3038, #3042, #3063, #3102) unlandable.

The first three tests reproduce that refusal. The rest are negative controls: a
git release tag, a release off PyPI, and a release the lock records no upload
for are still refused behind a newer dev tag.
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

_PYPI = "https://pypi.org/simple"
_CORE_REPO = "omnibase_core"
_INFRA_REPO = "omnibase_infra"
# The refusal the omniclaude job printed: release 0.47.61 published
# 20261101145451 where core carried dev-20261101233629-173cd14208fe.
_RELEASE_UPLOADED = "2026-11-01T14:54:51Z"
_DEV_NEWER = "dev-20261101233629-173cd14208fe"


def _registry(
    name: str, version: str, *, index: str = _PYPI, uploaded: str | None
) -> str:
    stamp = "" if uploaded is None else f', upload-time = "{uploaded}"'
    return (
        "[[package]]\n"
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        f'source = {{ registry = "{index}" }}\n'
        f'sdist = {{ url = "https://files.example/{name}-{version}.tar.gz", '
        f'hash = "sha256:00", size = 1{stamp} }}\n\n'
    )


def _git_release_tag(name: str, version: str, repo: str) -> str:
    return (
        "[[package]]\n"
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        f'source = {{ git = "https://github.com/OmniNode-ai/{repo}.git'
        f'?tag=v{version}#{"c" * 40}" }}\n\n'
    )


def _lock(*packages: str) -> str:
    return 'version = 1\nrequires-python = ">=3.12"\n\n' + "".join(packages)


_BASE = _lock(_registry("omnibase-core", "0.47.57", uploaded="2026-10-30T09:00:00Z"))
_HEAD = _lock(_registry("omnibase-core", "0.47.61", uploaded=_RELEASE_UPLOADED))


def _request(
    head: str, base: str | None, tags: dict[str, list[str]] | None = None
) -> ModelInternalSiblingPinsRequest:
    return ModelInternalSiblingPinsRequest(
        head_lock_text=head, base_lock_text=base, dev_tags=tags or {}
    )


def test_published_pypi_release_behind_a_newer_dev_tag_passes() -> None:
    result = handle(_request(_HEAD, _BASE, {_CORE_REPO: [_DEV_NEWER]}))
    assert result.passed
    assert result.refused == []
    [finding] = result.findings
    assert finding.kind is EnumSiblingPinKind.RELEASE
    assert finding.verdict is EnumSiblingPinVerdict.ALLOWED
    assert finding.moved


def test_published_pypi_release_needs_no_dev_tags_read() -> None:
    result = handle(_request(_HEAD, _BASE))
    assert result.passed
    assert result.repos_needing_tags == []


def test_cli_exits_zero_for_the_release_the_job_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, head, tags = (tmp_path / n for n in ("base.lock", "head.lock", "tags.json"))
    base.write_text(_BASE)
    head.write_text(_HEAD)
    tags.write_text(json.dumps({_CORE_REPO: [_DEV_NEWER]}))
    args = ["--head-lock", str(head), "--base-lock", str(base)]
    assert main([*args, "--needs-tags"]) == 0
    assert capsys.readouterr().out == ""
    assert main([*args, "--dev-tags", str(tags)]) == 0
    out = capsys.readouterr().out
    assert "ALLOWED omnibase-core" in out
    assert "REFUSED" not in out


def test_git_release_tag_behind_a_newer_dev_tag_is_still_refused() -> None:
    head = _lock(_git_release_tag("omnibase-core", "0.47.61", _CORE_REPO))
    result = handle(_request(head, _lock(), {_CORE_REPO: [_DEV_NEWER]}))
    [refused] = result.refused
    assert refused.kind is EnumSiblingPinKind.RELEASE_TAG
    assert not result.passed


def test_release_off_pypi_behind_a_newer_dev_tag_is_still_refused() -> None:
    head = _lock(
        _registry(
            "omnibase-core",
            "0.47.61",
            index="https://registry.example.invalid/simple",
            uploaded=_RELEASE_UPLOADED,
        )
    )
    result = handle(_request(head, _BASE, {_CORE_REPO: [_DEV_NEWER]}))
    [refused] = result.refused
    assert refused.kind is EnumSiblingPinKind.RELEASE
    assert _DEV_NEWER in refused.reason


def test_lookalike_pypi_host_behind_a_newer_dev_tag_is_still_refused() -> None:
    head = _lock(
        _registry(
            "omnibase-core",
            "0.47.61",
            index="https://pypi.org.example.invalid/simple",
            uploaded=_RELEASE_UPLOADED,
        )
    )
    result = handle(_request(head, _BASE, {_CORE_REPO: [_DEV_NEWER]}))
    assert [f.distribution for f in result.refused] == ["omnibase-core"]


def test_pypi_release_with_no_recorded_upload_is_still_refused() -> None:
    head = _lock(_registry("omnibase-core", "0.47.61", uploaded=None))
    result = handle(_request(head, _BASE, {_CORE_REPO: [_DEV_NEWER]}))
    [refused] = result.refused
    assert refused.verdict is EnumSiblingPinVerdict.REFUSED


def test_one_refused_sibling_still_fails_beside_an_accepted_release() -> None:
    head = _lock(
        _registry("omnibase-core", "0.47.61", uploaded=_RELEASE_UPLOADED),
        _git_release_tag("omnibase-infra", "0.38.80", _INFRA_REPO),
    )
    result = handle(
        _request(head, _lock(), {_CORE_REPO: [_DEV_NEWER], _INFRA_REPO: [_DEV_NEWER]})
    )
    assert [f.distribution for f in result.refused] == ["omnibase-infra"]
    assert not result.passed
