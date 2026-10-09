#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Plugin version gate and post-merge bump [OMN-20710, port of OMN-20497].

PRs no longer bump the onex version: the post-merge plugin-version-bump workflow
raises plugin.json and its marketplace entries together in one bot PR. This gate
refuses only a changed version that is broken or lowered from its merge-base
value, and marketplace versions that disagree with the plugin manifest.

OMN-16913 originally required every shipped plugin change to raise the version
because the Claude Code plugin cache is version-keyed. That per-PR rule made
concurrent PRs race for the same next version; the post-merge bump preserves cache
updates without those races. Tests and bytecode remain exempt from the bump.

The comparison uses the working tree, including staged and unstaged edits.
``--bump-to-base`` raises stale versions for shipped changes since the merge base
with the last version-setting commit, changing only the version value bytes.

Exit codes: 0 clean, 1 finding, 2 the gate could not run (never a pass).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PLUGIN_DIR = "plugins/onex/"
PLUGIN_JSON = "plugins/onex/.claude-plugin/plugin.json"
#: The in-repo directory marketplace(s) that pin the onex plugin version.
MARKETPLACE_GLOB = "plugins/*-marketplace/.claude-plugin/marketplace.json"
PLUGIN_NAME = "onex"
_EXEMPT_PREFIXES = ("plugins/onex/tests/",)
_EXEMPT_PARTS = ("__pycache__", ".venv")
_EXEMPT_SUFFIXES = (".pyc",)
VERSION_VALUE_RE = re.compile(r'"version"\s*:\s*"([^"\\]*)"')
_VERSION_FIX = (
    "PRs no longer bump the version; the post-merge plugin-version-bump workflow "
    "does (OMN-20710). Put dev's value back in both files (plugin.json and the "
    "onex marketplace entry)."
)


class GateError(RuntimeError):
    """The gate could not decide; the caller must treat this as a refusal."""


@dataclass(frozen=True)
class Finding:
    kind: str
    detail: str


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GateError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _is_shipped(path: str) -> bool:
    if not path.startswith(PLUGIN_DIR):
        return False
    if path.startswith(_EXEMPT_PREFIXES) or path.endswith(_EXEMPT_SUFFIXES):
        return False
    return not any(part in _EXEMPT_PARTS for part in path.split("/"))


def _version_key(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.split("."))
    except ValueError as exc:
        raise GateError(f"non-numeric plugin version {version!r}") from exc


def _plugin_version(text: str, source: str) -> str:
    try:
        version = json.loads(text)["version"]
    except (ValueError, KeyError, TypeError) as exc:
        raise GateError(f"{source} has no readable version") from exc
    if not isinstance(version, str):
        raise GateError(f"{source} version is not a string")
    return version


def _read_text(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise GateError(f"{path} is unreadable") from exc


def _json_at(repo: Path, commit: str, path: str) -> str | None:
    if not _git(repo, "ls-tree", "--name-only", commit, "--", path).strip():
        return None
    return _git(repo, "show", f"{commit}:{path}")


def marketplace_skew(repo: Path) -> list[Finding]:
    plugin = _plugin_version(_read_text(repo / PLUGIN_JSON), PLUGIN_JSON)
    manifests = sorted(repo.glob(MARKETPLACE_GLOB))
    if not manifests:
        raise GateError(f"no marketplace manifest matches {MARKETPLACE_GLOB}")
    findings = []
    for manifest in manifests:
        name = manifest.relative_to(repo).as_posix()
        try:
            entries = json.loads(_read_text(manifest))["plugins"]
        except (ValueError, KeyError, TypeError) as exc:
            raise GateError(f"{name} has no readable plugins list") from exc
        for entry in entries:
            if entry.get("name") == PLUGIN_NAME and entry.get("version") != plugin:
                findings.append(
                    Finding(
                        "MARKETPLACE_SKEW",
                        f"{name} pins {PLUGIN_NAME} {entry.get('version')} "
                        f"but {PLUGIN_JSON} is {plugin}. {_VERSION_FIX}",
                    )
                )
    return findings


def check(repo: Path, base: str) -> list[Finding]:
    _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    current = _plugin_version(_read_text(repo / PLUGIN_JSON), PLUGIN_JSON)
    previous_text = _json_at(repo, merge_base, PLUGIN_JSON)
    previous = (
        _plugin_version(previous_text, f"{merge_base}:{PLUGIN_JSON}")
        if previous_text is not None
        else None
    )
    findings = []
    if current != previous:
        try:
            current_key = _version_key(current)
        except GateError:
            findings.append(
                Finding(
                    "BROKEN_VERSION",
                    f"{PLUGIN_JSON} version {current!r} is not dotted integers. {_VERSION_FIX}",
                )
            )
        else:
            try:
                previous_key = _version_key(previous) if previous is not None else None
            except GateError:
                previous_key = None
            if previous_key is not None and current_key <= previous_key:
                findings.append(
                    Finding(
                        "LOWERED_VERSION",
                        f"{PLUGIN_JSON} version {current} is not above {previous} at the "
                        f"merge base with {base}. {_VERSION_FIX}",
                    )
                )
    return findings + marketplace_skew(repo)


def _set_version(text: str, data: dict, entry_name: str | None, new: str) -> str | None:
    """Replace one ``"version"`` value in ``text``, leaving every other byte as is. The occurrence
    is the one whose replacement parses to ``data`` with only that version changed (the manifest's
    own, or the named marketplace entry's), so a nested or top-level ``version`` is never taken.
    None when no occurrence qualifies."""
    expected = json.loads(json.dumps(data))
    if entry_name is None:
        expected["version"] = new
    else:
        for entry in expected["plugins"]:
            if isinstance(entry, dict) and entry.get("name") == entry_name:
                entry["version"] = new
                break
    for match in VERSION_VALUE_RE.finditer(text):
        candidate = text[: match.start(1)] + new + text[match.end(1) :]
        try:
            if json.loads(candidate) == expected:
                return candidate
        except json.JSONDecodeError:
            continue
    return None


def bump_to_base(repo: Path, base: str) -> list[str]:
    """Bump stale files above their own base versions, preserving all other bytes."""
    _git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    merge_base = _git(repo, "merge-base", base, "HEAD").strip()
    changed = _git(repo, "diff", "--name-only", merge_base).splitlines()
    changed += _git(repo, "ls-files", "--others", "--exclude-standard").splitlines()
    if not any(_is_shipped(path) for path in changed):
        return []
    base_plugin = _json_at(repo, merge_base, PLUGIN_JSON)
    if base_plugin is None:
        return []

    # Each file is compared to its own floor, even if the base files disagree.
    files: list[tuple[Path, str | None, str, object]] = []
    try:
        base_v = _plugin_version(base_plugin, f"{merge_base}:{PLUGIN_JSON}")
        _version_key(base_v)
        head_v = _plugin_version(_read_text(repo / PLUGIN_JSON), PLUGIN_JSON)
        files.append((repo / PLUGIN_JSON, None, base_v, head_v))
        for name in _git(repo, "ls-tree", "-r", "--name-only", merge_base).splitlines():
            if not Path(name).match(MARKETPLACE_GLOB):
                continue
            base_text = _json_at(repo, merge_base, name)
            if base_text is None:
                continue
            base_entry = next(
                entry
                for entry in json.loads(base_text)["plugins"]
                if entry.get("name") == PLUGIN_NAME
            )
            base_v = base_entry["version"]
            if not isinstance(base_v, str):
                raise GateError(f"{name} has a non-string base version")
            _version_key(base_v)
            head_entry = next(
                entry
                for entry in json.loads(_read_text(repo / name))["plugins"]
                if entry.get("name") == PLUGIN_NAME
            )
            files.append((repo / name, PLUGIN_NAME, base_v, head_entry.get("version")))
    except (GateError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise GateError(
            f"cannot read dotted integer base/head versions: {exc}; "
            "set the version by hand"
        ) from exc

    top = max(_version_key(base_v) for _, _, base_v, _ in files)
    target = ".".join(str(n) for n in (*top[:-1], top[-1] + 1))
    stale = []
    for _, _, base_v, current in files:
        try:
            head_key = _version_key(current) if isinstance(current, str) else None
        except GateError:
            head_key = None
        is_stale = head_key is None or head_key <= _version_key(base_v)
        stale.append(is_stale)
        if not is_stale and head_key is not None and head_key > top:
            target = str(current)
    if not any(stale):
        return []

    edits: dict[Path, str] = {}
    lines = []
    for (path, entry, _, old), is_stale in zip(files, stale, strict=True):
        if not is_stale:
            continue
        text = _read_text(path)
        try:
            edited = _set_version(text, json.loads(text), entry, target)
        except (ValueError, KeyError, TypeError) as exc:
            raise GateError(f"{path}: cannot edit version") from exc
        if edited is None:
            raise GateError(
                f"{path}: cannot find the one version value to set to {target!r}"
            )
        edits[path] = edited
        lines.append(
            f"bumped {path.relative_to(repo).as_posix()}: onex {old} -> {target}"
        )
    for path, text in edits.items():
        try:
            path.write_bytes(text.encode("utf-8"))
        except OSError as exc:
            raise GateError(f"{path}: cannot write version") from exc
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--base", default="origin/dev")
    parser.add_argument(
        "--bump-to-base",
        action="store_true",
        help=(
            "First raise plugin.json and the onex marketplace entries to the next "
            "patch above --base's when shipped files changed since it, print one "
            "line per file changed, then check as usual. The post-merge "
            "plugin-version-bump workflow's engine (OMN-20710)."
        ),
    )
    parser.add_argument(
        "--defer-to-workflow-in-ci",
        action="store_true",
        help=(
            "Exit 0 when running under GitHub Actions. The whole-tree pre-commit "
            "job checks out one commit with no base ref to compare against; the "
            "dedicated Plugin Version Bump Gate workflow is the blocking verdict "
            "there. Local runs are unaffected."
        ),
    )
    args = parser.parse_args(argv)
    if args.defer_to_workflow_in_ci and os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            "plugin-version-bump: deferred to the Plugin Version Bump Gate workflow",
            file=sys.stderr,
        )
        return 0
    try:
        if args.bump_to_base:
            for line in bump_to_base(args.repo_root, args.base):
                print(line)
        findings = check(args.repo_root, args.base)
    except GateError as exc:
        print(f"plugin-version-bump gate could not run: {exc}", file=sys.stderr)
        return 2
    for finding in findings:
        print(f"{finding.kind}: {finding.detail}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
