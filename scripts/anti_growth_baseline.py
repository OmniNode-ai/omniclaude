#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Reject baseline growth relative to the Git merge base.

OMN-19677 centralizes the one-way rule for grandfathered debt baselines.  The
working-tree/checked-out baseline is compared with the same path at
``git merge-base HEAD <base-ref>``.  A baseline may be unchanged or shrink; it
may not gain entries, increase a numeric ceiling, or increase a per-key count.

Parser identifiers:

* ``yaml-list:<key.path>`` / ``json-list:<key.path>``
* ``yaml-count-map:<key.path>`` / ``json-count-map:<key.path>``
* ``yaml-list-tree`` (all list members, namespaced by their mapping path)
* ``line-set`` (blank and comment-only lines are ignored)
* ``number``

Every CLI invocation first runs a parser-specific positive control that adds a
member or increments a value.  If the comparator ever accepts that synthetic
growth, the gate fails before examining the repository baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple

import yaml


class BaselineParseError(ValueError):
    """The parser identifier or baseline content is invalid."""


class ParserSpec(NamedTuple):
    kind: str
    key_path: tuple[str, ...]


class ParsedBaseline(NamedTuple):
    kind: str
    value: int | frozenset[str] | dict[str, int]
    entry_count: int


_KEYED_KINDS = frozenset({"yaml-list", "json-list", "yaml-count-map", "json-count-map"})
_SIMPLE_KINDS = frozenset({"line-set", "number", "yaml-list-tree"})
_GIT_LOCATION_VARS = frozenset(
    {
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES",
        "GIT_COMMON_DIR",
        "GIT_CEILING_DIRECTORIES",
        "GIT_NAMESPACE",
    }
)


def parse_parser_spec(parser: str) -> ParserSpec:
    """Parse and validate a public parser identifier."""
    if parser in _SIMPLE_KINDS:
        return ParserSpec(parser, ())
    kind, separator, raw_path = parser.partition(":")
    if kind not in _KEYED_KINDS or not separator or not raw_path:
        allowed = ", ".join(
            sorted(_SIMPLE_KINDS | {f"{item}:<key.path>" for item in _KEYED_KINDS})
        )
        msg = f"invalid parser {parser!r}; expected one of: {allowed}"
        raise BaselineParseError(msg)
    key_path = tuple(raw_path.split("."))
    if any(not part for part in key_path):
        msg = f"invalid empty key component in parser {parser!r}"
        raise BaselineParseError(msg)
    return ParserSpec(kind, key_path)


def _canonical_entry(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        msg = f"baseline entry is not canonically serializable: {value!r}"
        raise BaselineParseError(msg) from exc


def _resolve_key_path(data: Any, key_path: tuple[str, ...]) -> Any:
    current = data
    traversed: list[str] = []
    for key in key_path:
        traversed.append(key)
        if not isinstance(current, dict) or key not in current:
            msg = f"baseline has no mapping value at {'.'.join(traversed)!r}"
            raise BaselineParseError(msg)
        current = current[key]
    return current


def _load_structured(text: str, kind: str) -> Any:
    try:
        if kind.startswith("yaml-"):
            return yaml.safe_load(text)
        return json.loads(text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        msg = f"could not parse {kind.split('-', 1)[0].upper()} baseline: {exc}"
        raise BaselineParseError(msg) from exc


def _flatten_list_tree(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    entries: list[str] = []
    if isinstance(value, list):
        namespace = ".".join(path) or "<root>"
        entries.extend(f"{namespace}={_canonical_entry(item)}" for item in value)
    elif isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise BaselineParseError("yaml-list-tree requires string mapping keys")
            entries.extend(_flatten_list_tree(child, (*path, key)))
    return entries


def parse_baseline_text(text: str, parser: str) -> ParsedBaseline:
    """Parse baseline text into the comparison model selected by ``parser``."""
    spec = parse_parser_spec(parser)
    if spec.kind == "number":
        try:
            value = int(text.strip())
        except ValueError as exc:
            msg = "number baseline must contain exactly one integer"
            raise BaselineParseError(msg) from exc
        if value < 0:
            raise BaselineParseError("number baseline cannot be negative")
        return ParsedBaseline(spec.kind, value, value)

    if spec.kind == "line-set":
        line_entries = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return ParsedBaseline(spec.kind, frozenset(line_entries), len(line_entries))

    if spec.kind == "yaml-list-tree":
        tree_entries = _flatten_list_tree(_load_structured(text, spec.kind))
        return ParsedBaseline(spec.kind, frozenset(tree_entries), len(tree_entries))

    selected = _resolve_key_path(_load_structured(text, spec.kind), spec.key_path)
    if spec.kind.endswith("-list"):
        if not isinstance(selected, list):
            msg = f"{'.'.join(spec.key_path)!r} must resolve to a list"
            raise BaselineParseError(msg)
        canonical_entries = frozenset(_canonical_entry(item) for item in selected)
        return ParsedBaseline(spec.kind, canonical_entries, len(selected))

    if not isinstance(selected, dict):
        msg = f"{'.'.join(spec.key_path)!r} must resolve to a count mapping"
        raise BaselineParseError(msg)
    counts: dict[str, int] = {}
    for key, value in selected.items():
        if (
            not isinstance(key, str)
            or not isinstance(value, int)
            or isinstance(value, bool)
        ):
            msg = "count-map baselines require string keys and integer values"
            raise BaselineParseError(msg)
        if value < 0:
            raise BaselineParseError("count-map values cannot be negative")
        counts[key] = value
    return ParsedBaseline(spec.kind, counts, len(counts))


def compare_parsed(base: ParsedBaseline, head: ParsedBaseline) -> list[str]:
    """Return human-readable growth violations; an empty list is a pass."""
    if base.kind != head.kind:
        return [f"parser kind changed from {base.kind!r} to {head.kind!r}"]

    failures: list[str] = []
    if isinstance(base.value, int) and isinstance(head.value, int):
        if head.value > base.value:
            failures.append(f"numeric value grew from {base.value} to {head.value}")
        return failures

    if isinstance(base.value, frozenset) and isinstance(head.value, frozenset):
        added = sorted(head.value - base.value)
        if head.entry_count > base.entry_count:
            failures.append(
                f"entry count grew from {base.entry_count} to {head.entry_count}"
            )
        if added:
            preview = ", ".join(added[:5])
            suffix = " ..." if len(added) > 5 else ""
            failures.append(
                f"entry set gained {len(added)} member(s): {preview}{suffix}"
            )
        return failures

    if isinstance(base.value, dict) and isinstance(head.value, dict):
        added_keys = sorted(set(head.value) - set(base.value))
        if added_keys:
            preview = ", ".join(added_keys[:5])
            suffix = " ..." if len(added_keys) > 5 else ""
            failures.append(
                f"count-map gained {len(added_keys)} key(s): {preview}{suffix}"
            )
        for key in sorted(set(base.value) & set(head.value)):
            if head.value[key] > base.value[key]:
                failures.append(
                    f"count for {key!r} grew from {base.value[key]} to {head.value[key]}"
                )
        return failures

    return ["internal parser result type mismatch"]


def compare_texts(base_text: str, head_text: str, parser: str) -> list[str]:
    """Parse and compare two serialized baselines."""
    return compare_parsed(
        parse_baseline_text(base_text, parser),
        parse_baseline_text(head_text, parser),
    )


def run_positive_control(parser: str) -> list[str]:
    """Return failures only when synthetic growth is not rejected."""
    spec = parse_parser_spec(parser)
    if spec.kind == "number":
        base = ParsedBaseline(spec.kind, 1, 1)
        grown = ParsedBaseline(spec.kind, 2, 2)
    elif spec.kind.endswith("-list") or spec.kind in {"line-set", "yaml-list-tree"}:
        base = ParsedBaseline(spec.kind, frozenset({"old"}), 1)
        grown = ParsedBaseline(spec.kind, frozenset({"old", "new"}), 2)
    else:
        base = ParsedBaseline(spec.kind, {"old": 1}, 1)
        grown = ParsedBaseline(spec.kind, {"old": 2, "new": 1}, 2)
    if compare_parsed(base, grown):
        return []
    return [f"positive control FAILED: {parser!r} accepted synthetic growth"]


def _git(repo_root: Path, *args: str) -> str:
    git_env = {
        key: value for key, value in os.environ.items() if key not in _GIT_LOCATION_VARS
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        env=git_env,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        msg = f"git {' '.join(args)} failed ({result.returncode}): {detail}"
        raise RuntimeError(msg)
    return result.stdout.strip()


def check_repository_baseline(
    repo_root: Path,
    baseline_path: Path,
    parser: str,
    base_ref: str,
) -> list[str]:
    """Compare a working-tree baseline with its value at the merge base."""
    if baseline_path.is_absolute() or ".." in baseline_path.parts:
        raise BaselineParseError("baseline path must be repository-relative")
    head_path = repo_root / baseline_path
    if not head_path.is_file():
        raise BaselineParseError(f"head baseline does not exist: {baseline_path}")

    merge_base = _git(repo_root, "merge-base", "HEAD", base_ref)
    if not merge_base:
        raise RuntimeError(f"git merge-base HEAD {base_ref} returned no commit")
    base_text = _git(repo_root, "show", f"{merge_base}:{baseline_path.as_posix()}")
    head_text = head_path.read_text(encoding="utf-8")
    return compare_texts(base_text, head_text, parser)


def _default_base_ref() -> str:
    github_base_ref = os.environ.get("GITHUB_BASE_REF", "").strip()
    if github_base_ref:
        return f"origin/{github_base_ref}"
    return "origin/dev"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--parser", required=True)
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        control_failures = run_positive_control(args.parser)
        if control_failures:
            for failure in control_failures:
                print(f"ANTI-GROWTH BASELINE ERROR: {failure}", file=sys.stderr)
            return 2
        print(f"positive control passed: {args.parser} rejects synthetic growth")

        repo_root = args.repo_root.resolve()
        base_ref = args.base_ref or _default_base_ref()
        failures = check_repository_baseline(
            repo_root, args.baseline, args.parser, base_ref
        )
    except (BaselineParseError, OSError, RuntimeError) as exc:
        print(f"ANTI-GROWTH BASELINE ERROR: {exc}", file=sys.stderr)
        return 2

    if failures:
        for failure in failures:
            print(
                f"ANTI-GROWTH BASELINE FAILED ({args.baseline}): {failure}",
                file=sys.stderr,
            )
        return 1
    print(
        f"ANTI-GROWTH BASELINE PASSED: {args.baseline} did not grow relative to "
        f"merge-base(HEAD, {base_ref})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
