# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""internal-sibling-pins: refuse a release pin where a newer dev tag exists (OMN-21282).

RULING 2026-10-16T07:34:18Z: a consumer reads an internal sibling by branch or
tag and never waits for a release. Every dev merge of a sibling is tagged
``dev-<UTC YYYYMMDDHHMMSS>-<sha12>`` by the sibling's own dev-merge-tag.yml, and
the nightly train (RULING 2026-10-19T10:11:00Z, OMN-19998) rolls those tags into
one bump per consumer. A change that lands the consumer on a release, a PyPI
version or a git release tag, while the sibling already carries a newer dev
merge tag pins the past, so this check refuses it.

Only pins the change moves are judged. A release pin the change leaves where it
was is reported as STANDING and not refused: refusing it would refuse every
change to this repository for a pin it did not touch. A moved release pin whose
sibling's tags were not read is refused, never assumed fine.

Release time is the earliest ``upload-time`` uv.lock records for the version's
files. A git release tag carries no time in the lock, so it is refused whenever
its sibling carries any dev merge tag. A ``rev`` pin is not a release-version
pin and is left to the clone-governed relock (OMN-18752); a dev merge tag pin
passes.

The handler reads no network and runs no git. The CI job lists the repositories
it needs (``--needs-tags``), reads their tags with ``git ls-remote`` and passes
them back as JSON (``--dev-tags``).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from omniclaude.enums.enum_sibling_pin_kind import EnumSiblingPinKind
from omniclaude.enums.enum_sibling_pin_verdict import EnumSiblingPinVerdict
from omniclaude.models.model_internal_sibling_pins import (
    ModelInternalSiblingPinFinding,
    ModelInternalSiblingPinsRequest,
    ModelInternalSiblingPinsResult,
)

#: Internal siblings that resolve from a package index, by distribution name.
REGISTRY_SIBLING_REPOS: Final[dict[str, str]] = {
    "omnibase-compat": "omnibase_compat",
    "omnibase-core": "omnibase_core",
    "omnibase-infra": "omnibase_infra",
    "omnibase-spi": "omnibase_spi",
    "omnimarket": "omnimarket",
    "omninode-intelligence": "omniintelligence",
    "omninode-memory": "omnimemory",
}

_OMNINODE_GIT: Final = re.compile(
    r"^https://github\.com/OmniNode-ai/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?"
    r"(?:\?(?P<query>[^#]*))?(?:#.*)?$"
)
_DEV_MERGE_TAG: Final = re.compile(r"^dev-(?P<stamp>[0-9]{14})-[0-9a-f]{12}$")
_STAMP_FORMAT: Final = "%Y%m%d%H%M%S"


def _stamp_of(tag: str) -> str | None:
    match = _DEV_MERGE_TAG.match(tag)
    return match.group("stamp") if match else None


def _release_stamp(package: dict[str, object]) -> str | None:
    """The earliest upload time of the version's files, as a dev tag stamp."""
    files: list[object] = []
    sdist = package.get("sdist")
    if sdist is not None:
        files.append(sdist)
    wheels = package.get("wheels")
    if isinstance(wheels, list):
        files.extend(wheels)
    stamps: list[str] = []
    for entry in files:
        uploaded = entry.get("upload-time") if isinstance(entry, dict) else None
        if not isinstance(uploaded, str):
            continue
        moment = datetime.fromisoformat(uploaded.replace("Z", "+00:00"))
        stamps.append(moment.astimezone(UTC).strftime(_STAMP_FORMAT))
    return min(stamps) if stamps else None


def _classify(
    package: dict[str, object],
) -> tuple[str, EnumSiblingPinKind, str | None, str | None] | None:
    """(repo, kind, ref, release stamp) of an internal sibling, else None."""
    name = str(package.get("name", ""))
    source = package.get("source")
    if not isinstance(source, dict):
        return None
    git = source.get("git")
    if isinstance(git, str):
        match = _OMNINODE_GIT.match(git)
        if match is None:
            return None
        query = dict(
            part.split("=", 1)
            for part in (match.group("query") or "").split("&")
            if "=" in part
        )
        tag = query.get("tag")
        if tag is None:
            return match.group("repo"), EnumSiblingPinKind.REV, query.get("rev"), None
        if _stamp_of(tag) is not None:
            return match.group("repo"), EnumSiblingPinKind.DEV_TAG, tag, None
        return match.group("repo"), EnumSiblingPinKind.RELEASE_TAG, tag, None
    if "registry" in source and name in REGISTRY_SIBLING_REPOS:
        return (
            REGISTRY_SIBLING_REPOS[name],
            EnumSiblingPinKind.RELEASE,
            None,
            _release_stamp(package),
        )
    return None


def _packages(lock_text: str) -> dict[str, dict[str, object]]:
    packages = tomllib.loads(lock_text).get("package", [])
    return {str(p.get("name")): p for p in packages if isinstance(p, dict)}


def _pin_identity(package: dict[str, object] | None) -> tuple[str, str] | None:
    if package is None:
        return None
    return str(package.get("version")), json.dumps(
        package.get("source"), sort_keys=True
    )


def _newest_dev_tag(tags: list[str]) -> str | None:
    dev = [t for t in tags if _stamp_of(t) is not None]
    return max(dev, key=lambda t: _stamp_of(t) or "") if dev else None


def handle(request: ModelInternalSiblingPinsRequest) -> ModelInternalSiblingPinsResult:
    """Judge every internal sibling pin of the head lock against the dev tags."""
    head = _packages(request.head_lock_text)
    base = None if request.base_lock_text is None else _packages(request.base_lock_text)
    findings: list[ModelInternalSiblingPinFinding] = []
    needing: set[str] = set()
    for name in sorted(head):
        package = head[name]
        classified = _classify(package)
        if classified is None:
            continue
        repo, kind, ref, released = classified
        moved = base is None or _pin_identity(package) != _pin_identity(base.get(name))

        def finding(
            verdict: EnumSiblingPinVerdict,
            reason: str,
            newest: str | None = None,
            *,
            name: str = name,
            repo: str = repo,
            kind: EnumSiblingPinKind = kind,
            moved: bool = moved,
            released: str | None = released,
            version: str = str(package.get("version")),
        ) -> ModelInternalSiblingPinFinding:
            return ModelInternalSiblingPinFinding(
                distribution=name,
                repo=repo,
                version=version,
                kind=kind,
                moved=moved,
                released_at=released,
                newest_dev_tag=newest,
                verdict=verdict,
                reason=reason,
            )

        if kind in (EnumSiblingPinKind.DEV_TAG, EnumSiblingPinKind.REV):
            reason = (
                f"pinned by dev merge tag {ref}"
                if kind is EnumSiblingPinKind.DEV_TAG
                else f"pinned by rev {ref}; not a release-version pin"
            )
            findings.append(finding(EnumSiblingPinVerdict.ALLOWED, reason))
            continue
        pinned = f"release {ref}" if ref else f"release {package.get('version')}"
        if not moved:
            findings.append(
                finding(
                    EnumSiblingPinVerdict.STANDING,
                    f"{pinned} is not moved by this change",
                )
            )
            continue
        if repo not in request.dev_tags:
            needing.add(repo)
            findings.append(
                finding(
                    EnumSiblingPinVerdict.REFUSED,
                    f"{pinned}: the dev tags of {repo} were not read",
                )
            )
            continue
        newest = _newest_dev_tag(request.dev_tags[repo])
        newer = newest is not None and (
            released is None or (_stamp_of(newest) or "") > released
        )
        if newer:
            when = f"published {released}" if released else "with no recorded time"
            reason = (
                f"{pinned} ({when}) where {repo} carries the newer dev merge tag "
                f"{newest}; pin the dev tag instead (OMN-19998)"
            )
            verdict = EnumSiblingPinVerdict.REFUSED
        else:
            reason = f"{pinned} is newer than every dev merge tag of {repo}"
            verdict = EnumSiblingPinVerdict.ALLOWED
        findings.append(finding(verdict, reason, newest))
    return ModelInternalSiblingPinsResult(
        findings=findings, repos_needing_tags=sorted(needing)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--head-lock", type=Path, required=True)
    parser.add_argument(
        "--base-lock", type=Path, default=None, help="omit to judge every pin"
    )
    parser.add_argument(
        "--dev-tags", type=Path, default=None, help="JSON: repo -> tag names"
    )
    parser.add_argument(
        "--needs-tags",
        action="store_true",
        help="print the repositories whose dev tags the verdict needs, then exit 0",
    )
    args = parser.parse_args(argv)

    tags: dict[str, list[str]] = {}
    if args.dev_tags is not None:
        tags = json.loads(args.dev_tags.read_text(encoding="utf-8"))
    result = handle(
        ModelInternalSiblingPinsRequest(
            head_lock_text=args.head_lock.read_text(encoding="utf-8"),
            base_lock_text=(
                None
                if args.base_lock is None
                else args.base_lock.read_text(encoding="utf-8")
            ),
            dev_tags=tags,
        )
    )
    if args.needs_tags:
        sys.stdout.writelines(f"{repo}\n" for repo in result.repos_needing_tags)
        return 0
    sys.stdout.writelines(
        f"{f.verdict.value.upper()} {f.distribution}: {f.reason}\n"
        for f in result.findings
    )
    if not result.passed:
        sys.stderr.write(
            f"internal-sibling-pins: {len(result.refused)} release pin(s) refused "
            "(RULING 2026-10-16T07:34:18Z, OMN-21282)\n"
        )
        return 1
    return 0


__all__ = ["REGISTRY_SIBLING_REPOS", "handle", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
