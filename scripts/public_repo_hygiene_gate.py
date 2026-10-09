#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Public-repository hygiene gate — the canonical implementation (OMN-18014).

One gate, fail-closed, for every public OmniNode repository. Built from the
OMN-17992 inventory's root causes; the design is section 5 of the prevention
plan. This module is the single source of truth for the rules — the reusable
workflow ``.github/workflows/public-repo-hygiene-reusable.yml`` and the
exported ``public-repo-hygiene`` pre-commit hook both run THIS script, so a
local verdict and a CI verdict can never diverge.

Stdlib only, deliberately. The structural precedent is RSD's
``scripts/ci/validate_public_release.py``: a gate that needs a dependency
install to run is a gate that does not run in the window where it matters.
That constraint is why the config parser below is a restricted YAML subset
rather than PyYAML, and why it fails loud on syntax it does not understand
instead of silently ignoring half a file.

## Why this exists rather than a ninth detector

The org has at least eight purpose-built detectors for these exact classes.
Every one of them is subtree-scoped (root cause 4.4), extension-scoped
(4.2 — ``kb_doc_gate.py`` is ``path.lower().endswith(".md")``, which is why
every misplaced artifact in the inventory is a YAML, JSON, CSV, TSV, TXT, PNG
or SVG), or self-waivable (4.3 — roughly 234 suppression annotations in one
repo, every reason string written by the author of the violation). A ninth
advisory sweep would be ignored on the standing rule that detection without a
merge gate is advisory.

## Two layers

**Layer (a) — top-level path allowlist.** Each repo checks in
``.public-repo-hygiene.yaml`` declaring its permitted root entries. Anything
else at the root fails. This is the half that refuses ``.onex/``,
``.onex_state/``, ``.evidence/``, ``drift/``, ``merge-sweep/`` and the next
junk directory nobody has invented yet. A denylist must anticipate that
directory; an allowlist does not.

**Layer (b) — path and content denylist, extension-agnostic.** Applied to
every tracked file regardless of suffix. The path half covers agent-state
trees, evidence and receipt trees, misplaced dated documents, brand assets
under ``docs/``, env files, OS junk, caches and logs. The content half is the
class table below, whose vocabulary is fetched from a PRIVATE repository
(see ``--vocabulary``): it names private repositories and collaborators, so
publishing the denylist in a public repo would itself be the disclosure it
protects against.

## Detection classes

| class                     | layer   | exemptable |
|---------------------------|---------|------------|
| ``top-level-not-allowed`` | path    | registry   |
| ``agent-state``           | path    | registry   |
| ``evidence-tree``         | path    | registry   |
| ``misplaced-doc``         | path    | registry   |
| ``brand-asset``           | path    | registry   |
| ``env-file``              | path    | registry   |
| ``os-junk``               | path    | registry   |
| ``cache-or-log``          | path    | registry   |
| ``cloud-identity``        | content | **never**  |
| ``private-network``       | content | **never**  |
| ``machine-path``          | content | **never**  |
| ``private-repo-name``     | content | **never**  |
| ``internal-kb-prose``     | content | **never**  |
| ``public-doc-private-repo`` | content | **never** |
| ``lab-config``            | content | **never**  |
| ``person-name``           | content | registry   |
| ``tracker-url``           | content | registry   |
| ``secret-shaped``         | content | registry   |
| ``self-granted-annotation`` | content | informational |

``public-doc-private-repo`` (OMN-18017) is the rule that did not exist
anywhere in the org: a public README, CONTRIBUTING or SECURITY document may
not name a private repository, describe its contents, or state who has
access. It is the class that would have caught the paragraph the operator
found, in all eleven repositories, on the day the migration lane wrote it.

``lab-config`` (OMN-19766) refuses our lab's lane ids and lab compose project
names. Operator ruling 2026-09-26, firm: no lab configuration of any kind lives
in a public repository. Its ids come from a second private file, the LAB
vocabulary (``--lab-vocabulary``, key ``lab_lane_ids``), each matched as a whole
token, case-insensitively. It is a separate file rather than a new key in the
main vocabulary because every public caller pins an older gate, and an older
gate refuses an unknown vocabulary key: a new key would have stopped every one
of them from running the day it merged. A lab address and a lab host nickname
stay in ``private-network``; together the two are "the lab classes".

An older reusable resolves this script from omniclaude ``dev`` (its pinned
``job_workflow_sha`` resolves empty for a cross-repo caller) but fetches no lab
vocabulary. So with no ``--lab-vocabulary`` and none beside the main
vocabulary, the class is reported as NOT evaluated (a ``::warning::`` and a
report line) and every other class runs; a run that requests ``lab-config``
with ``--only-classes``, or a repo that enforces it, still refuses (exit 2).
Measured 2026-09-26 on onex_change_control#11491 and #11528, whose required
CI Summary went red on exit 2 after omniclaude#2373.

Bare ``OMN-<digits>`` ticket ids are **not** a class. Operator ruling P3,
2026-09-06: internal ticket ids in public source are an accepted convention.
Workspace-scoped tracker URLs are still a violation.

``self-granted-annotation`` counts the legacy ``# onex-allow-*``,
``# local-path-ok`` and ``# fallback-ok`` annotations and never blocks. Their
migration onto the two-party registry is OMN-18018, deliberately a separate
ticket: a lane that both builds the registry and migrates 234 entries into it
in one change has self-granted every one of them a second time.

## Suppression: two-party, scoped, expiring

An annotation stops being both the request and the approval. The inline form
is::

    # public-repo-hygiene-ok: <reason-code> <TICKET-ID>

and it suppresses NOTHING on its own. It must resolve against an entry in the
repo's CODEOWNERS-reviewed suppression registry whose ``path_glob`` matches
the file, whose ``class`` matches the finding, whose ``reason_code`` and
``ticket`` match the annotation, and whose ``expires_at`` is in the future.
A self-written annotation with no registry entry is a FAILURE, reported as
``unresolved-suppression`` — the finding it tried to hide is reported too.

The never-exemptable classes accept no annotation at any severity. There is
no legitimate fixture need for a real AWS account id or a real EC2 instance
id that a stable synthetic value cannot serve.

## Fail-closed, everywhere

A missing repo config, an unreadable or unparseable vocabulary, a vocabulary
whose live-visibility cache is stale beyond its declared max age, a
malformed registry, and an unrecognised mode are all non-zero exits. A gate
that cannot read its own rules has not passed; it has not run. This matters
more than it sounds: the four false "zero failures" readings of the
trusted-CI canary all came from a sweep that errored and returned no rows.

## Modes

``report``   scan and print everything, exit 0 unless ``enforce_classes`` fails.
``enforce``  exit 1 on any blocking finding.

A repo's own ``.public-repo-hygiene.yaml`` ``mode:`` wins over ``--mode``, so
the two surfaces cannot silently disagree about which one is authoritative.

**Per-class enforcement (OMN-19766).** ``enforce_classes:`` in the repo config
lists classes whose findings fail the run in ``report`` mode too. A repository
that reaches zero for the lab classes turns exactly those on, in the same pull
request, while its other classes are still being cleaned up; one ``mode:``
switch for every class could not express that. An unknown class name is a
config error, never an ignored line.

**``--only-classes a,b``** restricts the run to the named classes (path and
content alike), and its ``--mode`` then wins over the config's ``mode:``: a
targeted check reports what the caller asked for, so a repository still in
``report`` mode cannot read green to it. The lab-class gate every repository
task runs is::

    --mode enforce --only-classes private-network,lab-config

**Added-lines scope (OMN-19835).** ``enforce_scope: added-lines`` in the repo
config makes the run fail only on an enforced finding that sits on a line the
change ADDS. The scan and the report stay whole-tree, so the residue is still
counted on every run; what changes is which findings fail it. It exists for a
repository whose tree already carries a large residue in a class it must stop
growing: enforcing that class whole-tree would fail every unrelated pull
request, and leaving it in report mode is how internal content reached a
public ``dev`` unnoticed. The diff source is given on the command line:

- ``--diff-base <ref>``: the lines added between ``git merge-base <ref> HEAD``
  and the working tree. CI passes the pull request's merge-ref first parent.
- ``--diff-staged``: the lines the index adds over ``HEAD`` (pre-commit). On a
  merge commit a line counts only when it is added relative to EVERY parent,
  so the incoming branch's own lines are not charged to the merge author.

What counts as added is deliberately conservative. A moved line is added (the
diff runs with no move detection). A renamed file is added in full at its new
path (``--no-renames``): moving a file is re-publishing every line of it. A
changed file git treats as binary has no line numbers, so every finding in it
counts. A path-layer finding (line 0) counts when its file is new.

It is opt-in per repository and never weakens one that does not declare it:
with the default ``enforce_scope: whole-tree`` a diff source is ignored and
the verdict is exactly the whole-tree one. A repository that declares
``added-lines`` and runs with no diff source is refused (exit 2) rather than
silently enforcing nothing or everything. A targeted ``--only-classes`` run
with no diff source keeps its whole-file verdict over the paths it names.

## Usage

    python3 scripts/public_repo_hygiene_gate.py --repo-root . --mode report
    python3 scripts/public_repo_hygiene_gate.py --vocabulary <path> --mode enforce
    python3 scripts/public_repo_hygiene_gate.py --vocabulary <path> \\
        --lab-vocabulary <path> --mode enforce --only-classes private-network,lab-config
    python3 scripts/public_repo_hygiene_gate.py --staged <files...>
    python3 scripts/public_repo_hygiene_gate.py --diff-base origin/dev   # a branch
    python3 scripts/public_repo_hygiene_gate.py --diff-staged            # pre-commit
    python3 scripts/public_repo_hygiene_gate.py --refresh-visibility --vocabulary <path>

## Exit codes

0  no blocking finding (or ``--mode report``)
1  a blocking finding in ``enforce`` mode
2  a configuration error — the gate could not run
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

MODES = ("report", "enforce")

CONFIG_BASENAME = ".public-repo-hygiene.yaml"
DEFAULT_REGISTRY_BASENAME = ".public-repo-hygiene-suppressions.yaml"

INLINE_MARKER = "public-repo-hygiene-ok"
INLINE_RE = re.compile(
    rf"{re.escape(INLINE_MARKER)}:\s*(?P<reason>[a-z0-9][a-z0-9-]*)\s+(?P<ticket>[A-Z]+-\d+)"
)

# Legacy self-granted annotations. Counted, never blocking. Migration is
# OMN-18018.
LEGACY_ANNOTATION_RE = re.compile(
    r"#\s*(?:onex-allow-[a-z-]+|local-path-ok|fallback-ok|onex-allow-file)\b"
)

NEVER_EXEMPTABLE: frozenset[str] = frozenset(
    {
        "cloud-identity",
        "private-network",
        "machine-path",
        "private-repo-name",
        "internal-kb-prose",
        "public-doc-private-repo",
        "lab-config",
    }
)

PATH_CLASSES: frozenset[str] = frozenset(
    {
        "top-level-not-allowed",
        "agent-state",
        "evidence-tree",
        "misplaced-doc",
        "brand-asset",
        "env-file",
        "os-junk",
        "cache-or-log",
    }
)
CONTENT_CLASSES: frozenset[str] = frozenset(
    {
        "cloud-identity",
        "private-network",
        "machine-path",
        "private-repo-name",
        "internal-kb-prose",
        "public-doc-private-repo",
        "lab-config",
        "person-name",
        "tracker-url",
        "secret-shaped",
        "self-granted-annotation",
    }
)
#: Every class a repo config may enforce or a run may be restricted to.
SELECTABLE_CLASSES: frozenset[str] = PATH_CLASSES | CONTENT_CLASSES

#: The private lab vocabulary's file name. With no ``--lab-vocabulary`` the gate
#: reads the file of this name beside the main vocabulary when it exists, and
#: otherwise reports the lab-config class as not evaluated (see ``run``).
LAB_VOCABULARY_BASENAME = "public_repo_hygiene_lab_vocabulary.yaml"

INFORMATIONAL: frozenset[str] = frozenset({"self-granted-annotation"})

#: ``enforce_scope`` values (OMN-19835). ``whole-tree`` is the default and the
#: behaviour every repository had before the key existed.
WHOLE_TREE_SCOPE = "whole-tree"
ADDED_LINES_SCOPE = "added-lines"
ENFORCE_SCOPES = (WHOLE_TREE_SCOPE, ADDED_LINES_SCOPE)

#: git's empty tree, the diff base of a repository with no commit. Derived
#: rather than spelled: it is the object id of a zero-length tree.
EMPTY_TREE_SHA = hashlib.sha1(b"tree 0\x00", usedforsecurity=False).hexdigest()

# Public-facing prose surface for the OMN-18017 class. Matched on basename so
# it catches .github/README.md and docs/CONTRIBUTING.md alike.
PUBLIC_DOC_BASENAMES: frozenset[str] = frozenset(
    {
        "readme.md",
        "readme.rst",
        "readme",
        "contributing.md",
        "contributing.rst",
        "security.md",
        "security.rst",
        "code_of_conduct.md",
        "support.md",
    }
)

# Never worth scanning as text.
BINARY_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".bmp",
        ".tiff",
        ".pdf",
        ".zip",
        ".gz",
        ".bz2",
        ".xz",
        ".tar",
        ".tgz",
        ".7z",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".otf",
        ".mp4",
        ".mov",
        ".webm",
        ".mp3",
        ".wav",
        ".pyc",
        ".pyo",
        ".so",
        ".dylib",
        ".dll",
        ".class",
        ".jar",
    }
)

# Brand/media suffixes that do not belong under docs/ in a source repo.
MEDIA_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".tiff",
        ".ico",
        ".svg",
        ".mp4",
        ".mov",
        ".webm",
        ".key",
        ".pptx",
        ".ai",
        ".psd",
    }
)

DATED_DOC_RE = re.compile(r"(?:^|/)\d{4}-\d{2}-\d{2}[-_]")

MISPLACED_DOC_DIRS: tuple[str, ...] = (
    "docs/tracking/",
    "docs/handoffs/",
    "docs/deep-dives/",
    "docs/deep_dives/",
    "docs/reports/",
    "docs/audits/",
    "docs/status/",
    "docs/work-tracking/",
)

AGENT_STATE_PREFIXES: tuple[str, ...] = (
    ".onex/",
    ".onex_state/",
    ".claude_scratch/",
    ".repowise-workspace/",
    "merge-sweep/",
)
AGENT_STATE_EXACT: tuple[str, ...] = (".repowise-workspace.yaml",)

EVIDENCE_PREFIXES: tuple[str, ...] = (
    "docs/evidence/",
    ".evidence/",
    "drift/dod_receipts/",
)
EVIDENCE_SEGMENTS: tuple[str, ...] = ("/dod_receipts/", "/receipts/")

CACHE_SEGMENTS: tuple[str, ...] = (
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "node_modules/",
    ".venv/",
)

OS_JUNK_BASENAMES: frozenset[str] = frozenset({".ds_store", "thumbs.db", "desktop.ini"})


# ---------------------------------------------------------------------------
# Restricted YAML subset
# ---------------------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _strip_comment(value: str) -> str:
    """Drop a trailing ``#`` comment from an UNQUOTED scalar.

    A quoted scalar keeps everything inside its quotes — the vocabulary
    legitimately contains ``#`` inside patterns.
    """
    if value[:1] in ("'", '"'):
        return value
    idx = value.find(" #")
    return value[:idx].rstrip() if idx != -1 else value


class ConfigError(Exception):
    """A config the gate cannot understand. Always exit 2, never a pass."""


def parse_restricted_yaml(text: str, origin: str) -> dict[str, object]:
    """Parse the restricted YAML subset these config files are written in.

    Supported, and nothing else::

        key: scalar
        key:
          - scalar
          - scalar
        key:
          - subkey: scalar
            subkey: scalar

    Full-line ``#`` comments and blank lines are ignored. Any other syntax
    raises :class:`ConfigError` — fail closed on a file the parser cannot
    fully understand rather than silently honouring the half it could.
    """
    result: dict[str, object] = {}
    section: str | None = None
    scalar_list: list[str] | None = None
    map_list: list[dict[str, str]] | None = None
    current_map: dict[str, str] | None = None
    item_indent: int | None = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        # `---` (document start) and `...` (document end) are YAML DOCUMENT
        # MARKERS, not content. Several repos run a `yamlfmt` pre-commit hook
        # that PREPENDS `---` to every YAML file it touches, so the adoption
        # script writes a config without one and the hook adds it on the very
        # first commit. Before this, the gate then died with "unrecognized
        # top-level line" and exit 2 -- a red check that reads like a verdict
        # and is actually "the gate did not run". Skipping them changes
        # nothing else: an unparseable line is still a hard, fail-closed
        # error (OMN-18016).
        if raw.strip() in ("---", "..."):
            continue
        indent = len(raw) - len(raw.lstrip())
        line = raw.strip()
        where = f"{origin}:{lineno}"

        if indent == 0:
            if not line.endswith(":") and ":" not in line:
                raise ConfigError(f"{where}: unrecognized top-level line: {raw!r}")
            key, _, value = line.partition(":")
            key = key.strip()
            value = _strip_comment(value.strip())
            if key in result:
                raise ConfigError(f"{where}: duplicate top-level key {key!r}")
            if value:
                result[key] = _strip_quotes(value)
                section = None
                scalar_list = map_list = current_map = None
            else:
                section = key
                scalar_list = None
                map_list = None
                current_map = None
                item_indent = None
            continue

        if section is None:
            raise ConfigError(f"{where}: indented line outside any key: {raw!r}")

        if line.startswith("- "):
            item = line[2:].strip()
            item_indent = indent
            if ":" in item and not item.startswith(("'", '"')):
                subkey, _, subvalue = item.partition(":")
                if map_list is None:
                    if scalar_list is not None:
                        raise ConfigError(
                            f"{where}: {section!r} mixes scalar and mapping list items"
                        )
                    map_list = []
                    result[section] = map_list
                current_map = {
                    subkey.strip(): _strip_quotes(_strip_comment(subvalue.strip()))
                }
                map_list.append(current_map)
            else:
                if scalar_list is None:
                    if map_list is not None:
                        raise ConfigError(
                            f"{where}: {section!r} mixes scalar and mapping list items"
                        )
                    scalar_list = []
                    result[section] = scalar_list
                scalar_list.append(_strip_quotes(item))
                current_map = None
            continue

        if current_map is not None and item_indent is not None and indent > item_indent:
            if ":" not in line:
                raise ConfigError(f"{where}: unrecognized mapping line: {raw!r}")
            subkey, _, subvalue = line.partition(":")
            subkey = subkey.strip()
            if subkey in current_map:
                raise ConfigError(f"{where}: duplicate key {subkey!r} in list item")
            current_map[subkey] = _strip_quotes(_strip_comment(subvalue.strip()))
            continue

        raise ConfigError(f"{where}: unrecognized line: {raw!r}")

    return result


def _as_str_list(data: dict[str, object], key: str, origin: str) -> list[str]:
    value = data.get(key, [])
    if value == "":
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{origin}: {key!r} must be a list of strings")
    return list(value)


# ---------------------------------------------------------------------------
# Glob
# ---------------------------------------------------------------------------


def _escape_glob_segment(segment: str) -> str:
    buf: list[str] = []
    for ch in segment:
        if ch == "*":
            buf.append("[^/]*")
        elif ch == "?":
            buf.append("[^/]")
        else:
            buf.append(re.escape(ch))
    return "".join(buf)


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Restricted glob: ``*`` and ``?`` within one segment, ``/**/`` across
    segments, and a trailing ``/**`` meaning "this directory and everything
    under it". No other glob syntax is supported, by design.
    """
    trailing_any = pattern.endswith("/**")
    core = pattern[:-3] if trailing_any else pattern
    chunks = core.split("/**/")
    joined = "/(?:.*/)?".join(_escape_glob_segment(c) for c in chunks)
    suffix = "(?:/.*)?" if trailing_any else ""
    return re.compile("^" + joined + suffix + "$")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    class_name: str
    snippet: str

    @property
    def blocking(self) -> bool:
        return self.class_name not in INFORMATIONAL


@dataclass(frozen=True)
class Suppression:
    path_glob: str
    class_name: str
    reason_code: str
    ticket: str
    expires_at: date
    approved_by: str
    path_regex: re.Pattern[str]


@dataclass
class Vocabulary:
    person_names: list[str] = field(default_factory=list)
    private_repo_names: list[str] = field(default_factory=list)
    private_repo_names_resolved_at: str = ""
    private_repo_cache_max_age_days: int = 30
    internal_kb_prose: list[str] = field(default_factory=list)
    host_nicknames: list[str] = field(default_factory=list)
    tracker_url_patterns: list[str] = field(default_factory=list)
    sensitive_literal_patterns: list[str] = field(default_factory=list)
    sensitive_literal_exempt_globs: list[str] = field(default_factory=list)
    machine_path_patterns: list[str] = field(default_factory=list)
    lab_lane_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RepoConfig:
    mode: str | None
    allowed_top_level: frozenset[str]
    registry_path: str
    scan_excludes: tuple[re.Pattern[str], ...]
    enforce_classes: frozenset[str] = frozenset()
    enforce_scope: str = WHOLE_TREE_SCOPE


@dataclass(frozen=True)
class AddedLines:
    """What a change adds, as the added-lines scope reads it (OMN-19835).

    ``lines`` maps a path to the line numbers the change adds in its current
    content. ``whole_files`` are changed files git treats as binary: they have
    no line numbers, so every finding in them counts. ``added_files`` are new
    paths, which is where a path-layer finding (line 0) counts.
    """

    source: str
    lines: dict[str, frozenset[int]]
    whole_files: frozenset[str]
    added_files: frozenset[str]

    def covers(self, finding: Finding) -> bool:
        if finding.path in self.whole_files:
            return True
        if finding.line_no == 0:
            return finding.path in self.added_files
        return finding.line_no in self.lines.get(finding.path, frozenset())


# ---------------------------------------------------------------------------
# Loaders — every one of them fails closed
# ---------------------------------------------------------------------------


def load_repo_config(path: Path) -> RepoConfig:
    if not path.is_file():
        raise ConfigError(
            f"{path} not found. Every public repository declares its permitted "
            "root entries once; an absent config is not an empty allowlist and "
            "is not a pass. THE GATE DID NOT RUN."
        )
    data = parse_restricted_yaml(path.read_text(encoding="utf-8"), str(path))
    mode = data.get("mode")
    if mode is not None and (not isinstance(mode, str) or mode not in MODES):
        raise ConfigError(f"{path}: mode must be one of {MODES}, got {mode!r}")
    allowed = _as_str_list(data, "allowed_top_level", str(path))
    if not allowed:
        raise ConfigError(
            f"{path}: 'allowed_top_level' is empty or missing. The path "
            "allowlist is layer (a) of this gate; an empty one fails every "
            "file rather than passing, but a repo that means to allow nothing "
            "is a configuration mistake. Declare the roots."
        )
    registry = data.get("suppression_registry") or DEFAULT_REGISTRY_BASENAME
    if not isinstance(registry, str):
        raise ConfigError(f"{path}: 'suppression_registry' must be a string")
    excludes = tuple(
        glob_to_regex(g) for g in _as_str_list(data, "scan_excludes", str(path))
    )
    enforce = frozenset(_as_str_list(data, "enforce_classes", str(path)))
    unknown = sorted(enforce - SELECTABLE_CLASSES)
    if unknown:
        raise ConfigError(
            f"{path}: 'enforce_classes' names unknown class(es) {unknown}. A "
            "misspelled class would enforce nothing while reading as enforced. "
            f"Known classes: {sorted(SELECTABLE_CLASSES)}. THE GATE DID NOT RUN."
        )
    scope = data.get("enforce_scope", WHOLE_TREE_SCOPE)
    if not isinstance(scope, str) or scope not in ENFORCE_SCOPES:
        raise ConfigError(
            f"{path}: 'enforce_scope' must be one of {ENFORCE_SCOPES}, got "
            f"{scope!r}. A misspelled scope would enforce a different surface "
            "than the one it reads as. THE GATE DID NOT RUN."
        )
    return RepoConfig(
        mode=mode if isinstance(mode, str) else None,
        allowed_top_level=frozenset(allowed),
        registry_path=registry,
        scan_excludes=excludes,
        enforce_classes=enforce,
        enforce_scope=scope,
    )


# Every key the vocabulary may carry. A vocabulary with a MISSPELLED key used
# to be accepted silently: the loader read the key it expected, found nothing,
# and built an empty pattern for that class -- a fail-OPEN hole in a
# fail-closed gate, and one this lane hit for real. Renaming
# ``secret_patterns`` in the vocabulary without renaming it in the loader
# turned the secret-shaped class off entirely, and every test stayed green
# because the test fixtures carry their own vocabulary. So: unknown key is a
# hard error, and so is a required class going missing.
VOCABULARY_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "private_repo_names",
        "internal_kb_prose",
        "host_nicknames",
        "machine_path_patterns",
        "person_names",
    }
)
VOCABULARY_OPTIONAL_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "private_repo_names_resolved_at",
        "private_repo_cache_max_age_days",
        "tracker_url_patterns",
        "sensitive_literal_patterns",
        "sensitive_literal_exempt_globs",
    }
)


def _assert_vocabulary_keys(data: dict[str, object], origin: str) -> None:
    known = VOCABULARY_REQUIRED_KEYS | VOCABULARY_OPTIONAL_KEYS
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(
            f"{origin}: unknown vocabulary key(s) {unknown}. A misspelled key "
            "would otherwise be read as an EMPTY class -- the loader looks up "
            "the name it expects, finds nothing, and builds a pattern that "
            "matches nothing. That is a fail-open hole in a fail-closed gate. "
            "THE GATE DID NOT RUN."
        )
    missing = sorted(VOCABULARY_REQUIRED_KEYS - set(data))
    if missing:
        raise ConfigError(
            f"{origin}: missing required vocabulary class(es) {missing}. Each "
            "one is a never-exemptable detection class; an absent list would "
            "silently disable it. THE GATE DID NOT RUN."
        )


def load_vocabulary(path: Path) -> Vocabulary:
    """Load the private denylist vocabulary. FAILS CLOSED (OMN-18015).

    The vocabulary names private repositories and collaborators, so it lives
    in a private repository and is fetched at run time. An unreachable or
    unparseable vocabulary is exit 2, never a pass — otherwise a network
    blip reads as a clean bill of health, which is precisely the false-zero
    failure mode this programme exists to remove.
    """
    if not path.is_file():
        raise ConfigError(
            f"vocabulary not found at {path}. The gate fetches its denylist "
            "from a PRIVATE repository and cannot scan without it. This is a "
            "fail-closed refusal, not a pass. THE GATE DID NOT RUN."
        )
    origin = str(path)
    data = parse_restricted_yaml(path.read_text(encoding="utf-8"), origin)
    _assert_vocabulary_keys(data, origin)
    max_age_raw = data.get("private_repo_cache_max_age_days", "30")
    try:
        max_age = int(str(max_age_raw))
    except ValueError as exc:
        raise ConfigError(
            f"{origin}: 'private_repo_cache_max_age_days' must be an integer"
        ) from exc
    resolved_at = data.get("private_repo_names_resolved_at", "")
    if not isinstance(resolved_at, str):
        raise ConfigError(
            f"{origin}: 'private_repo_names_resolved_at' must be a string"
        )
    vocab = Vocabulary(
        person_names=_as_str_list(data, "person_names", origin),
        private_repo_names=_as_str_list(data, "private_repo_names", origin),
        private_repo_names_resolved_at=resolved_at,
        private_repo_cache_max_age_days=max_age,
        internal_kb_prose=_as_str_list(data, "internal_kb_prose", origin),
        host_nicknames=_as_str_list(data, "host_nicknames", origin),
        tracker_url_patterns=_as_str_list(data, "tracker_url_patterns", origin),
        sensitive_literal_patterns=_as_str_list(
            data, "sensitive_literal_patterns", origin
        ),
        sensitive_literal_exempt_globs=_as_str_list(
            data, "sensitive_literal_exempt_globs", origin
        ),
        machine_path_patterns=_as_str_list(data, "machine_path_patterns", origin),
    )
    _assert_visibility_cache_fresh(vocab, origin)
    return vocab


LAB_VOCABULARY_REQUIRED_KEYS: frozenset[str] = frozenset({"lab_lane_ids"})
LAB_VOCABULARY_OPTIONAL_KEYS: frozenset[str] = frozenset({"schema_version"})


def load_lab_vocabulary(path: Path) -> list[str]:
    """Load the private LAB vocabulary's ``lab_lane_ids``. FAILS CLOSED.

    Missing file, unknown key, and a missing or empty ``lab_lane_ids`` list are
    all exit 2: an absent list would build a pattern that matches nothing, and
    the never-exemptable ``lab-config`` class would report green over every
    lab lane id in the repository.
    """
    if not path.is_file():
        raise ConfigError(
            f"lab vocabulary not found at {path}. The lab-config class reads "
            "its lane ids from a PRIVATE file and cannot scan without it. This "
            "is a fail-closed refusal, not a pass. THE GATE DID NOT RUN."
        )
    origin = str(path)
    data = parse_restricted_yaml(path.read_text(encoding="utf-8"), origin)
    known = LAB_VOCABULARY_REQUIRED_KEYS | LAB_VOCABULARY_OPTIONAL_KEYS
    unknown = sorted(set(data) - known)
    if unknown:
        raise ConfigError(
            f"{origin}: unknown lab vocabulary key(s) {unknown}. A misspelled "
            "key would be read as an EMPTY class. THE GATE DID NOT RUN."
        )
    if "lab_lane_ids" not in data:
        raise ConfigError(
            f"{origin}: missing required key 'lab_lane_ids' "
            "(missing_lab_lane_ids). The lab-config class is never-exemptable; "
            "an absent list would silently disable it. THE GATE DID NOT RUN."
        )
    ids = [v for v in _as_str_list(data, "lab_lane_ids", origin) if v.strip()]
    if not ids:
        raise ConfigError(
            f"{origin}: 'lab_lane_ids' is empty. An empty list matches nothing "
            "and would report every lab lane id as clean. THE GATE DID NOT RUN."
        )
    return ids


def _assert_visibility_cache_fresh(vocab: Vocabulary, origin: str) -> None:
    """A stale private-repo cache is a refusal, not a warning.

    ``private-repo-name`` is a never-exemptable class resolved from repository
    visibility. A cache older than its declared max age is a list that has
    gone stale — exactly the hardcoded-list failure the plan names — so the
    gate refuses rather than scanning against it.
    """
    if not vocab.private_repo_names:
        return
    if not vocab.private_repo_names_resolved_at:
        raise ConfigError(
            f"{origin}: 'private_repo_names' is set but "
            "'private_repo_names_resolved_at' is missing. The private-repo "
            "class must be resolved from live repository visibility, not from "
            "an undated list. Run --refresh-visibility."
        )
    try:
        resolved = datetime.fromisoformat(
            vocab.private_repo_names_resolved_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ConfigError(
            f"{origin}: 'private_repo_names_resolved_at' is not an ISO-8601 "
            f"timestamp: {vocab.private_repo_names_resolved_at!r}"
        ) from exc
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=UTC)
    age_days = (datetime.now(UTC) - resolved).days
    if age_days > vocab.private_repo_cache_max_age_days:
        raise ConfigError(
            f"{origin}: the private-repo visibility cache was resolved "
            f"{age_days} days ago, past its declared max age of "
            f"{vocab.private_repo_cache_max_age_days} days. A stale list is "
            "the hardcoded-list failure this class exists to avoid. Run "
            "--refresh-visibility. THE GATE DID NOT RUN."
        )


def load_registry(path: Path) -> list[Suppression]:
    """Load the CODEOWNERS-reviewed suppression registry (Mechanism 3).

    An absent registry is legitimate — it means the repo grants no
    suppressions, and every annotation in it is therefore unresolved. A
    malformed one is exit 2.
    """
    if not path.is_file():
        return []
    origin = str(path)
    data = parse_restricted_yaml(path.read_text(encoding="utf-8"), origin)
    raw_entries = data.get("entries", [])
    if raw_entries == "":
        return []
    if not isinstance(raw_entries, list):
        raise ConfigError(f"{origin}: 'entries' must be a list")
    required = (
        "path_glob",
        "class",
        "reason_code",
        "ticket",
        "expires_at",
        "approved_by",
    )
    out: list[Suppression] = []
    for idx, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            raise ConfigError(f"{origin}: entries[{idx}] must be a mapping")
        missing = [k for k in required if not raw.get(k)]
        if missing:
            raise ConfigError(
                f"{origin}: entries[{idx}] missing required {missing}. Every "
                "field is load-bearing: without a ticket and an expiry this is "
                "a self-grant with extra steps."
            )
        cls = raw["class"]
        if cls in NEVER_EXEMPTABLE:
            raise ConfigError(
                f"{origin}: entries[{idx}] grants class {cls!r}, which is "
                "NEVER-EXEMPTABLE. There is no legitimate fixture need for a "
                "real cloud identifier, a real private address, an operator "
                "machine path or a private repository name that a stable "
                "synthetic value cannot serve. Fix the value, do not register it."
            )
        if raw["approved_by"] == raw["ticket"]:
            raise ConfigError(
                f"{origin}: entries[{idx}] approved_by looks like a ticket id"
            )
        try:
            expires = date.fromisoformat(raw["expires_at"])
        except ValueError as exc:
            raise ConfigError(
                f"{origin}: entries[{idx}] expires_at must be an ISO date "
                f"(YYYY-MM-DD), got {raw['expires_at']!r}"
            ) from exc
        out.append(
            Suppression(
                path_glob=raw["path_glob"],
                class_name=cls,
                reason_code=raw["reason_code"],
                ticket=raw["ticket"],
                expires_at=expires,
                approved_by=raw["approved_by"],
                path_regex=glob_to_regex(raw["path_glob"]),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Pattern construction
# ---------------------------------------------------------------------------


def _alternation(values: list[str]) -> str:
    """Escaped alternation over LITERAL vocabulary values.

    Sorted longest-first so an alternation containing both a name and a
    longer name that starts with it (``omniweb`` and ``omniweb-v2``) reports
    the longer one, which is the accurate finding.
    """
    if not values:
        return r"(?!)"
    return "|".join(re.escape(v) for v in sorted(values, key=len, reverse=True))


_ENV_VAR_SHAPED_NAME_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)+")


def _env_var_exemption(names: list[str]) -> str:
    """Negative lookahead: the UPPER-CASE environment variable is not a slug.

    A repository slug and an environment variable can be the same word. The
    variable (``$X``, ``${X}``, ``X=...``, ``os.environ["X"]``) is used across
    public repositories and names no private repository, so the whole-token,
    case-sensitive, upper-case spelling of an underscore-separated vocabulary
    name is not a private-repo reference. The class is otherwise
    case-insensitive and stays that way: the lower-case slug, a mixed-case
    spelling, ``<org>/<NAME>`` and any path-segment or ``@`` use of the upper
    case form are all still findings. The exemption is a property of the
    matcher, never of a file, so it cannot be granted by an annotation.
    """
    upper = [n.upper() for n in names if _ENV_VAR_SHAPED_NAME_RE.fullmatch(n)]
    if not upper:
        return ""
    return (
        r"(?!(?<![/\\@])(?-i:" + "|".join(re.escape(u) for u in upper) + r")"
        r"(?![A-Za-z0-9_-]))"
    )


def _raw_alternation(fragments: list[str]) -> str:
    """Alternation over vocabulary values that are already REGEX fragments.

    Some vocabulary classes cannot be expressed as literals: a lab host
    nickname needs a lookbehind so a version string like ``1.201`` does not
    read as a host, and an internal-prose phrasing needs flexible spacing.
    Those lists carry regex, not text, and are documented as such in the
    vocabulary file's own header.
    """
    if not fragments:
        return r"(?!)"
    return "|".join(f"(?:{f})" for f in fragments)


def build_content_patterns(vocab: Vocabulary) -> dict[str, re.Pattern[str]]:
    """Every content class as one compiled pattern, vocabulary-driven.

    The regexes for the structural classes (cloud identity, private network,
    machine paths) are here rather than in the vocabulary because their SHAPE
    is not secret — only the specific values are, and those are matched by
    shape. The vocabulary carries what cannot be expressed as a shape: the
    names of private repositories, of collaborators, the internal prose, and
    the lab host nicknames.
    """
    return {
        "cloud-identity": re.compile(
            r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:\d{12}:"
            r"|\b\d{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com"
            r"|\bi-[0-9a-f]{17}\b"
            r"|\bi-[0-9a-f]{8}\b"
            r"|\baws_account_id\s*[:=]\s*[\"']?\d{12}",
            re.IGNORECASE,
        ),
        "private-network": re.compile(
            r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
            r"|\b192\.168\.\d{1,3}\.\d{1,3}\b"
            r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
            r"|\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b"
            r"|\b[a-z0-9-]+\.[a-z0-9-]+\.ts\.net\b"
            r"|\b(?:ssh|scp)\s+(?:-[^\s]+\s+)*[a-z0-9_.-]+@[a-z0-9_.-]+"
            rf"|{_raw_alternation(vocab.host_nicknames)}",
            re.IGNORECASE,
        ),
        # The three filesystem prefixes are matched CASE-SENSITIVELY via a
        # scoped ``(?-i:...)`` group, while the vocabulary fragments keep the
        # class-wide IGNORECASE. The two macOS home/mounted-volume prefixes
        # carry fixed capitalisation and the Linux home prefix is lowercase;
        # matching them case-insensitively turned every REST URL path segment
        # bearing those words into a NEVER-EXEMPTABLE finding that no
        # annotation could waive and only a rewrite of correct product code
        # could clear.
        "machine-path": re.compile(
            r"(?-i:/Users/)[a-z0-9_.-]+"
            r"|(?-i:/Volumes/)"  # public-skill-ok: this IS the machine-path detector
            r"|(?-i:/home/)[a-z0-9_.-]+/"
            rf"|{_raw_alternation(vocab.machine_path_patterns)}",
            re.IGNORECASE,
        ),
        "private-repo-name": re.compile(
            rf"(?<![a-z0-9_-]){_env_var_exemption(vocab.private_repo_names)}"
            rf"(?:{_alternation(vocab.private_repo_names)})(?![a-z0-9_-])",
            re.IGNORECASE,
        ),
        "internal-kb-prose": re.compile(
            rf"{_raw_alternation(vocab.internal_kb_prose)}", re.IGNORECASE
        ),
        # Whole token: no letter, digit or underscore on either side. A hyphen
        # IS a boundary, so a compose container name that carries a lane id
        # (``<id>-runtime``) is refused too, while an id's prefix alone is not.
        "lab-config": re.compile(
            rf"(?<![A-Za-z0-9_])(?:{_alternation(vocab.lab_lane_ids)})(?![A-Za-z0-9_])",
            re.IGNORECASE,
        ),
        "person-name": re.compile(
            rf"(?<![a-z0-9_-])(?:{_alternation(vocab.person_names)})(?![a-z0-9_-])",
            re.IGNORECASE,
        ),
        "tracker-url": re.compile(
            _raw_alternation(vocab.tracker_url_patterns),
            re.IGNORECASE,
        ),
        "secret-shaped": re.compile(_raw_alternation(vocab.sensitive_literal_patterns)),
        "self-granted-annotation": LEGACY_ANNOTATION_RE,
    }


# ---------------------------------------------------------------------------
# Path layer
# ---------------------------------------------------------------------------


def classify_path(rel_path: str, allowed_top_level: frozenset[str]) -> str | None:
    """Return the path-layer class ``rel_path`` violates, or ``None``.

    Layer (a) first: the top-level allowlist. Then the extension-agnostic
    path denylist — applied to EVERY suffix, which is the whole point. The
    doc gate reads ``.md`` only, and that one line is why every misplaced
    artifact in the inventory is a YAML, JSON, CSV, TSV, TXT, PNG or SVG.
    """
    lowered = rel_path.lower()
    basename = rel_path.rsplit("/", 1)[-1]

    if basename.lower() in OS_JUNK_BASENAMES:
        return "os-junk"

    for prefix in AGENT_STATE_PREFIXES:
        if rel_path.startswith(prefix):
            return "agent-state"
    if rel_path in AGENT_STATE_EXACT or rel_path.startswith(".repowise-workspace"):
        return "agent-state"

    for prefix in EVIDENCE_PREFIXES:
        if rel_path.startswith(prefix):
            return "evidence-tree"
    for segment in EVIDENCE_SEGMENTS:
        if segment in rel_path:
            return "evidence-tree"

    if basename.startswith(".env") and basename != ".env.example":
        return "env-file"

    for segment in CACHE_SEGMENTS:
        if rel_path.startswith(segment) or f"/{segment}" in rel_path:
            return "cache-or-log"
    if lowered.endswith(".log"):
        return "cache-or-log"

    if rel_path.startswith("docs/") and any(
        lowered.endswith(s) for s in MEDIA_SUFFIXES
    ):
        return "brand-asset"

    for prefix in MISPLACED_DOC_DIRS:
        if rel_path.startswith(prefix):
            return "misplaced-doc"
    if rel_path.startswith("docs/") and DATED_DOC_RE.search(rel_path):
        return "misplaced-doc"

    top = rel_path.split("/", 1)[0]
    if top not in allowed_top_level:
        return "top-level-not-allowed"

    return None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------


def tracked_files(repo_root: Path) -> list[str]:
    """The TRACKED set, not the ignore rules and not a subtree.

    Root cause 4.9: an ignore file neither untracks an existing path nor
    stops a forced add. ``omnicursor/.DS_Store`` is committed AND ignored;
    ``omnibase_infra/.claude/settings.local.json`` is committed despite two
    matching ignore rules.
    """
    out = subprocess.run(
        ["git", "-C", str(repo_root), "ls-files", "-z"],
        check=True,
        capture_output=True,
        text=True,
    )
    return [p for p in out.stdout.split("\0") if p]


# ---------------------------------------------------------------------------
# Added lines (OMN-19835)
# ---------------------------------------------------------------------------

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")

_C_ESCAPES: dict[str, int] = {
    "a": 7,
    "b": 8,
    "t": 9,
    "n": 10,
    "v": 11,
    "f": 12,
    "r": 13,
    '"': 34,
    "\\": 92,
}

# Every option that could make `git diff` print something other than a plain
# unified diff with a/ b/ prefixes, pinned off whatever the user's or the
# runner's git config says. A diff that silently detected renames or moved
# lines would drop added lines from the verdict without saying so.
_DIFF_FLAGS: tuple[str, ...] = (
    "--no-renames",
    "--no-ext-diff",
    "--no-textconv",
    "--no-color",
    "--src-prefix=a/",
    "--dst-prefix=b/",
)


def _git(repo_root: Path, *args: str) -> str:
    """Run git in ``repo_root``; a failure is a ConfigError, never a zero."""
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "-c", "core.quotePath=true", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        check=False,
    )
    if proc.returncode != 0:
        raise ConfigError(
            f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr.strip()}. "
            "The added lines cannot be computed, and an unread diff is not an "
            "empty one. THE GATE DID NOT RUN."
        )
    return proc.stdout


def _unquote_git_path(raw: str) -> str:
    """Undo git's C-style quoting of a path in a patch header."""
    if not (len(raw) >= 2 and raw.startswith('"') and raw.endswith('"')):
        return raw
    body = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch != "\\":
            out.extend(ch.encode("utf-8", "surrogateescape"))
            i += 1
            continue
        nxt = body[i + 1 : i + 2]
        if nxt in _C_ESCAPES:
            out.append(_C_ESCAPES[nxt])
            i += 2
        elif body[i + 1 : i + 4].isdigit() and len(body[i + 1 : i + 4]) == 3:
            out.append(int(body[i + 1 : i + 4], 8))
            i += 4
        else:
            raise ConfigError(f"unparseable quoted path in a git diff: {raw!r}")
    return out.decode("utf-8", "surrogateescape")


def _added_over(repo_root: Path, base: str, *, cached: bool) -> AddedLines:
    """The lines added from ``base`` to the index (``cached``) or work tree."""
    target = ("--cached",) if cached else ()
    patch = _git(repo_root, "diff", *_DIFF_FLAGS, "-U0", *target, base, "--")
    lines: dict[str, set[int]] = {}
    current: str | None = None
    for row in patch.splitlines():
        if row.startswith("diff --git "):
            current = None
            continue
        if row.startswith("+++ "):
            # git appends a TAB to a header path that contains a space.
            dest = row[4:].removesuffix("\t")
            if dest == "/dev/null":
                current = None
                continue
            dest = _unquote_git_path(dest)
            if not dest.startswith("b/"):
                raise ConfigError(f"unexpected destination in a git diff: {row!r}")
            current = dest[2:]
            lines.setdefault(current, set())
            continue
        match = _HUNK_RE.match(row)
        if match and current is not None:
            start = int(match.group("start"))
            count = int(match.group("count") or "1")
            lines[current].update(range(start, start + count))

    # Binary files carry no hunk, so they are read from --numstat, which
    # prints "-<TAB>-" for them. -z keeps every path byte-exact.
    numstat = _git(repo_root, "diff", *_DIFF_FLAGS, "--numstat", "-z", *target, base)
    whole: set[str] = set()
    for record in numstat.split("\0"):
        if not record:
            continue
        added, _, rest = record.partition("\t")
        deleted, _, path = rest.partition("\t")
        if added == "-" and deleted == "-" and path:
            whole.add(path)

    status = _git(
        repo_root,
        "diff",
        *_DIFF_FLAGS,
        "--name-only",
        "--diff-filter=A",
        "-z",
        *target,
        base,
    )
    new_files = {p for p in status.split("\0") if p}
    return AddedLines(
        source=base,
        lines={k: frozenset(v) for k, v in lines.items()},
        whole_files=frozenset(whole),
        added_files=frozenset(new_files),
    )


def added_lines_from_base(repo_root: Path, ref: str) -> AddedLines:
    """Lines added between ``merge-base(ref, HEAD)`` and the working tree.

    The working tree, not ``HEAD``, because it is the working tree the scan
    reads: the line numbers must describe the content the findings came
    from. In CI the two are the same commit.
    """
    base = _git(repo_root, "merge-base", ref, "HEAD").strip()
    added = _added_over(repo_root, base, cached=False)
    return AddedLines(
        source=f"merge-base({ref}, HEAD) = {base[:12]}",
        lines=added.lines,
        whole_files=added.whole_files,
        added_files=added.added_files,
    )


def added_lines_staged(repo_root: Path) -> AddedLines:
    """Lines the index adds over every parent of the commit being made.

    With no ``HEAD`` (the first commit) the base is the empty tree. During a
    merge, every ``MERGE_HEAD`` is a parent too, and a line counts only when
    it is added relative to all of them: the incoming branch's own lines are
    not the merge author's.
    """
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    parents = [head.stdout.strip()] if head.returncode == 0 else [EMPTY_TREE_SHA]
    merge_head = Path(_git(repo_root, "rev-parse", "--git-path", "MERGE_HEAD").strip())
    if not merge_head.is_absolute():
        merge_head = repo_root / merge_head
    if merge_head.is_file():
        parents.extend(
            line.strip()
            for line in merge_head.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    per_parent = [_added_over(repo_root, p, cached=True) for p in parents]
    first, rest = per_parent[0], per_parent[1:]
    lines = dict(first.lines)
    whole = set(first.whole_files)
    new_files = set(first.added_files)
    for other in rest:
        lines = {
            path: nums & other.lines.get(path, frozenset())
            for path, nums in lines.items()
        }
        whole &= other.whole_files
        new_files &= other.added_files
    return AddedLines(
        source="index over " + ", ".join(p[:12] for p in parents),
        lines=lines,
        whole_files=frozenset(whole),
        added_files=frozenset(new_files),
    )


def _read_lines(path: Path) -> list[str] | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        return path.read_text(encoding="utf-8", errors="strict").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def scan_file(
    rel_path: str,
    lines: list[str],
    patterns: dict[str, re.Pattern[str]],
    sensitive_literal_exempt_regexes: tuple[re.Pattern[str], ...],
) -> list[Finding]:
    findings: list[Finding] = []
    is_public_doc = rel_path.rsplit("/", 1)[-1].lower() in PUBLIC_DOC_BASENAMES
    skip_sensitive_literal = any(
        r.match(rel_path) for r in sensitive_literal_exempt_regexes
    )

    for line_no, line in enumerate(lines, start=1):
        for class_name, pattern in patterns.items():
            if class_name == "secret-shaped" and skip_sensitive_literal:
                continue
            match = pattern.search(line)
            if match is None:
                continue
            findings.append(Finding(rel_path, line_no, class_name, line.strip()[:200]))
            # OMN-18017: the same hit inside a public-facing prose document
            # is a distinct, never-exemptable class. A README naming a
            # private repository is not the same finding as a script
            # importing from one.
            if is_public_doc and class_name in (
                "private-repo-name",
                "internal-kb-prose",
            ):
                findings.append(
                    Finding(
                        rel_path, line_no, "public-doc-private-repo", line.strip()[:200]
                    )
                )
    return findings


def resolve_suppression(
    finding: Finding,
    lines: list[str],
    registry: list[Suppression],
    today: date,
) -> tuple[bool, str | None]:
    """Decide whether ``finding`` is suppressed.

    Returns ``(suppressed, problem)``. ``problem`` is a human-readable reason
    the annotation did NOT resolve, which is itself reported as an
    ``unresolved-suppression`` finding — a self-written annotation must be
    louder than silence, not quieter.
    """
    if finding.class_name in NEVER_EXEMPTABLE:
        return False, None
    if finding.class_name in INFORMATIONAL:
        return False, None

    # A PATH-layer finding names a file, not a line, so there is nowhere to
    # write an inline annotation. Its only suppression route is a registry
    # entry — which is the two-party half anyway; the annotation was never
    # more than a pointer to it.
    if finding.line_no == 0:
        for entry in registry:
            if entry.class_name != finding.class_name:
                continue
            if not entry.path_regex.match(finding.path):
                continue
            if entry.expires_at < today:
                return False, (
                    f"registry entry {entry.reason_code}/{entry.ticket} for class "
                    f"{finding.class_name} expired on {entry.expires_at}"
                )
            return True, None
        return False, None

    if not 1 <= finding.line_no <= len(lines):
        return False, None
    line = lines[finding.line_no - 1]
    match = INLINE_RE.search(line)
    if match is None:
        return False, None

    reason = match.group("reason")
    ticket = match.group("ticket")
    for entry in registry:
        if entry.class_name != finding.class_name:
            continue
        if not entry.path_regex.match(finding.path):
            continue
        if entry.reason_code != reason or entry.ticket != ticket:
            continue
        if entry.expires_at < today:
            return False, (
                f"registry entry for {reason}/{ticket} expired on {entry.expires_at}"
            )
        return True, None

    return False, (
        f"annotation '{reason} {ticket}' resolves to no registry entry for class "
        f"{finding.class_name} at this path — a self-written annotation is not an approval"
    )


# ---------------------------------------------------------------------------
# Live visibility resolution
# ---------------------------------------------------------------------------


def resolve_private_repos(owner: str) -> list[str]:
    """Enumerate the owner's PRIVATE repositories from live visibility.

    The plan is explicit that the private-repo class must be resolved live
    rather than from a hardcoded list that goes stale. This is the resolver;
    ``--refresh-visibility`` prints its result for the vocabulary's cache, and
    ``_assert_visibility_cache_fresh`` refuses to SCAN against a cache past
    its declared max age.

    Shells out to ``gh`` rather than opening a socket. ``gh`` is present on
    every runner and on every developer machine here, it already holds the
    credential, and it keeps this module free of a hand-rolled HTTP client
    whose auth and pagination would be one more thing to get wrong. The scan
    path never touches the network at all — only this refresh command does.
    """
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"orgs/{owner}/repos",
            "--paginate",
            "-X",
            "GET",
            "-f",
            "type=private",
            "-f",
            "per_page=100",
            "--jq",
            ".[] | select(.private) | .name",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ConfigError(
            f"could not resolve private repositories for {owner}: "
            f"gh exited {proc.returncode}: {proc.stderr.strip()}. The "
            "private-repo class is never-exemptable and cannot be resolved "
            "against an unreadable visibility listing. FAILING CLOSED — an "
            "empty result here is not evidence that the org has no private "
            "repositories."
        )
    names = sorted({line.strip() for line in proc.stdout.splitlines() if line.strip()})
    if not names:
        raise ConfigError(
            f"the private-repository listing for {owner} came back EMPTY. An "
            "empty result is not evidence of absence — it is what a sweep "
            "returns when it errored and its stderr was discarded. Re-run "
            "with a positive control before treating this as a real zero."
        )
    return names


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run(
    repo_root: Path,
    vocab_path: Path,
    mode: str,
    only_paths: list[str] | None,
    *,
    lab_vocab_path: Path | None,
    only_classes: frozenset[str] | None = None,
    added_lines: AddedLines | None = None,
) -> tuple[int, list[Finding], list[Finding]]:
    """Scan ``repo_root``; return ``(exit_code, blocking, informational)``.

    ``added_lines`` is the change's diff (``--diff-base``/``--diff-staged``).
    It narrows the failing set only in a repository whose config declares
    ``enforce_scope: added-lines``; see :func:`failing_findings`. Such a
    repository with no diff is refused, unless the run is a targeted
    ``--only-classes`` check, which keeps its whole-file verdict.

    ``only_classes`` restricts the run to those classes. A blocking finding
    fails the run when the effective mode is ``enforce``, or when its class is
    in the repo config's ``enforce_classes`` whatever the mode.

    ``lab_vocab_path`` is ``None`` only when the caller passed no
    ``--lab-vocabulary`` and none exists beside the main vocabulary: a caller
    pinned to a reusable from before OMN-19766, which never fetched one. The
    ``lab-config`` class is then NOT evaluated, and the run says so on stderr
    and in the report. A run that names ``lab-config`` in ``--only-classes``,
    or a repo that lists it in ``enforce_classes``, still refuses (exit 2): a
    class somebody asked for is never skipped.
    """
    config = load_repo_config(repo_root / CONFIG_BASENAME)
    vocab = load_vocabulary(vocab_path)
    if lab_vocab_path is None:
        requested = only_classes is not None and "lab-config" in only_classes
        if requested or "lab-config" in config.enforce_classes:
            raise ConfigError(
                "the lab-config class is "
                + ("requested by --only-classes" if requested else "enforced")
                + " but no lab vocabulary was given (--lab-vocabulary) or found "
                f"beside the vocabulary ({LAB_VOCABULARY_BASENAME}). This is a "
                "fail-closed refusal, not a pass. THE GATE DID NOT RUN."
            )
        vocab.lab_lane_ids = []
        print(
            "::warning::lab-config class NOT evaluated: no --lab-vocabulary was "
            f"passed and no {LAB_VOCABULARY_BASENAME} exists beside the "
            "vocabulary (a caller pinned to a reusable from before OMN-19766). "
            "Every other class ran.",
            file=sys.stderr,
        )
    else:
        vocab.lab_lane_ids = load_lab_vocabulary(lab_vocab_path)
    if (
        config.enforce_scope == ADDED_LINES_SCOPE
        and added_lines is None
        and only_classes is None
    ):
        raise _no_diff_source_refusal()
    registry = load_registry(repo_root / config.registry_path)
    # A run restricted with --only-classes is an explicit, targeted check (the
    # lab-class gate): its --mode is the one the caller asked for. Otherwise
    # the repo's own config mode wins, as it always has.
    effective_mode = mode if only_classes is not None else (config.mode or mode)
    patterns = build_content_patterns(vocab)
    sensitive_literal_exempt = tuple(
        glob_to_regex(g) for g in vocab.sensitive_literal_exempt_globs
    )
    today = datetime.now(UTC).date()

    paths = only_paths if only_paths is not None else tracked_files(repo_root)
    blocking: list[Finding] = []
    informational: list[Finding] = []

    for rel_path in sorted(paths):
        if any(r.match(rel_path) for r in config.scan_excludes):
            continue
        full = repo_root / rel_path
        lines = _read_lines(full) or []

        path_class = classify_path(rel_path, config.allowed_top_level)
        candidates: list[Finding] = []
        if path_class is not None:
            candidates.append(Finding(rel_path, 0, path_class, rel_path))
        candidates.extend(
            scan_file(rel_path, lines, patterns, sensitive_literal_exempt)
        )

        for finding in candidates:
            if only_classes is not None and finding.class_name not in only_classes:
                continue
            if finding.class_name in INFORMATIONAL:
                informational.append(finding)
                continue
            suppressed, problem = resolve_suppression(finding, lines, registry, today)
            if problem is not None:
                blocking.append(
                    Finding(
                        finding.path, finding.line_no, "unresolved-suppression", problem
                    )
                )
            if not suppressed:
                blocking.append(finding)

    failing = failing_findings(
        blocking, config, effective_mode, added_lines, only_classes=only_classes
    )
    exit_code = 1 if failing else 0
    return exit_code, blocking, informational


def failing_findings(
    blocking: list[Finding],
    config: RepoConfig,
    effective_mode: str,
    added_lines: AddedLines | None,
    *,
    only_classes: frozenset[str] | None = None,
) -> list[Finding]:
    """The blocking findings that fail the run.

    A finding fails when the effective mode is ``enforce`` or its class is in
    ``enforce_classes``. Under ``enforce_scope: added-lines`` it must also sit
    on a line the change adds. A whole-tree repository ignores ``added_lines``
    entirely, so passing a diff can never weaken it.
    """
    enforced = [
        f
        for f in blocking
        if effective_mode == "enforce" or f.class_name in config.enforce_classes
    ]
    if config.enforce_scope != ADDED_LINES_SCOPE:
        return enforced
    if added_lines is None:
        if only_classes is not None:
            return enforced
        raise _no_diff_source_refusal()
    return [f for f in enforced if added_lines.covers(f)]


def _no_diff_source_refusal() -> ConfigError:
    return ConfigError(
        f"{CONFIG_BASENAME} declares 'enforce_scope: {ADDED_LINES_SCOPE}' but "
        "the run was given no diff source (--diff-base <ref> or --diff-staged), "
        "so it cannot tell a line the change adds from one already on the base. "
        "Refusing rather than enforcing nothing or the whole residue. "
        "THE GATE DID NOT RUN."
    )


def _print_report(
    blocking: list[Finding], informational: list[Finding], mode: str
) -> None:
    by_class: dict[str, list[Finding]] = {}
    for f in blocking:
        by_class.setdefault(f.class_name, []).append(f)
    info_by_class: dict[str, list[Finding]] = {}
    for f in informational:
        info_by_class.setdefault(f.class_name, []).append(f)

    print(f"public-repo hygiene gate — mode={mode}")
    if not blocking and not informational:
        print("  clean: no findings")
        return

    for class_name in sorted(by_class):
        hits = by_class[class_name]
        never = " (NEVER-EXEMPTABLE)" if class_name in NEVER_EXEMPTABLE else ""
        print(f"\n  {class_name}{never}: {len(hits)}")
        for f in hits[:20]:
            loc = f"{f.path}:{f.line_no}" if f.line_no else f.path
            print(f"    {loc}: {f.snippet}")
        if len(hits) > 20:
            print(f"    ... and {len(hits) - 20} more")

    for class_name in sorted(info_by_class):
        hits = info_by_class[class_name]
        print(f"\n  {class_name} (informational, never blocks): {len(hits)}")
        if class_name == "self-granted-annotation":
            print(
                "    Migration onto the two-party expiring registry is OMN-18018. "
                "This gate reports the count and does not migrate them: a lane "
                "that builds the registry and fills it in the same change has "
                "self-granted every entry a second time."
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Public-repository hygiene gate (OMN-18014). Fail-closed. "
            "Path allowlist + extension-agnostic path/content denylist, "
            "with a privately-hosted vocabulary and a two-party expiring "
            "suppression registry."
        )
    )
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument(
        "--vocabulary",
        type=Path,
        default=None,
        help=(
            "path to the PRIVATE denylist vocabulary. When omitted, the path "
            "is read from $OMNI_HYGIENE_VOCAB_PATH; with neither, the gate "
            "refuses to run. CI fetches the vocabulary and passes the path."
        ),
    )
    parser.add_argument(
        "--lab-vocabulary",
        type=Path,
        default=None,
        help=(
            "path to the PRIVATE lab vocabulary (lab_lane_ids) for the "
            f"lab-config class. Defaults to {LAB_VOCABULARY_BASENAME} beside "
            "the vocabulary; CI fetches it and passes the path. A given path "
            "that is absent is exit 2. With none given and none beside the "
            "vocabulary, the class is reported as not evaluated, unless it is "
            "requested (--only-classes) or enforced, which is exit 2."
        ),
    )
    parser.add_argument(
        "--only-classes",
        default=None,
        help=(
            "comma-separated classes to restrict the run to, e.g. "
            "private-network,lab-config. An unknown class is exit 2."
        ),
    )
    parser.add_argument("--mode", choices=MODES, default="report")
    parser.add_argument(
        "--staged",
        action="store_true",
        help="pre-commit mode: scan only the file paths given as arguments",
    )
    parser.add_argument(
        "--refresh-visibility",
        action="store_true",
        help="re-resolve the owner's private repositories and rewrite the cache",
    )
    diff_source = parser.add_mutually_exclusive_group()
    diff_source.add_argument(
        "--diff-base",
        default=None,
        help=(
            "added-lines scope (OMN-19835): the lines added between "
            "merge-base(REF, HEAD) and the working tree. Narrows the verdict "
            "only in a repository whose config declares 'enforce_scope: "
            "added-lines'; the report stays whole-tree."
        ),
    )
    diff_source.add_argument(
        "--diff-staged",
        action="store_true",
        help=(
            "added-lines scope for pre-commit: the lines the index adds over "
            "HEAD (and over every MERGE_HEAD during a merge)."
        ),
    )
    parser.add_argument("--owner", default="OmniNode-ai")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()

    vocab_path = args.vocabulary
    if vocab_path is None:
        import os

        vocabulary_env = os.environ.get("OMNI_HYGIENE_VOCAB_PATH")
        if not vocabulary_env:
            print(
                "::error::--vocabulary was not given and OMNI_HYGIENE_VOCAB_PATH "
                "is not set, so "
                "the private denylist vocabulary cannot be located. The gate "
                "fails closed rather than scanning with no vocabulary. "
                "THE GATE DID NOT RUN.",
                file=sys.stderr,
            )
            return 2
        vocab_path = Path(vocabulary_env)
        if not vocab_path.is_file():
            print(
                "::error::OMNI_HYGIENE_VOCAB_PATH does not name a readable "
                "file, so the private denylist vocabulary cannot be loaded. "
                "The gate fails closed rather than scanning with no "
                "vocabulary. THE GATE DID NOT RUN.",
                file=sys.stderr,
            )
            return 2

    if args.refresh_visibility:
        try:
            names = resolve_private_repos(args.owner)
        except ConfigError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 2
        print("\n".join(names))
        return 0

    # An explicit --lab-vocabulary must exist (load_lab_vocabulary refuses a
    # missing one). With none given, the file beside the vocabulary is read
    # when it exists; when it does not, the caller predates OMN-19766 and the
    # lab-config class is reported as not evaluated (see run()).
    lab_vocab_path: Path | None = args.lab_vocabulary
    if lab_vocab_path is None:
        beside = vocab_path.parent / LAB_VOCABULARY_BASENAME
        lab_vocab_path = beside if beside.is_file() else None

    only_classes: frozenset[str] | None = None
    if args.only_classes is not None:
        only_classes = frozenset(
            c.strip() for c in args.only_classes.split(",") if c.strip()
        )
        unknown = sorted(only_classes - SELECTABLE_CLASSES)
        if not only_classes or unknown:
            print(
                f"::error::--only-classes names unknown or no class(es) {unknown}. "
                f"Known classes: {sorted(SELECTABLE_CLASSES)}. "
                "THE GATE DID NOT RUN.",
                file=sys.stderr,
            )
            return 2

    try:
        added_lines: AddedLines | None = None
        if args.diff_base is not None:
            added_lines = added_lines_from_base(repo_root, args.diff_base)
        elif args.diff_staged:
            added_lines = added_lines_staged(repo_root)
        exit_code, blocking, informational = run(
            repo_root,
            vocab_path,
            args.mode,
            args.paths if args.staged else None,
            lab_vocab_path=lab_vocab_path,
            only_classes=only_classes,
            added_lines=added_lines,
        )
    except ConfigError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        print(f"::error::git failed: {exc}. THE GATE DID NOT RUN.", file=sys.stderr)
        return 2

    config = load_repo_config(repo_root / CONFIG_BASENAME)
    config_mode = args.mode if only_classes is not None else (config.mode or args.mode)
    _print_report(blocking, informational, config_mode)
    if lab_vocab_path is None:
        print(
            "\n  NOT EVALUATED: lab-config (no lab vocabulary was given or found "
            "beside the vocabulary; the caller predates OMN-19766)."
        )
    if only_classes is not None:
        print(f"\n  restricted to: {', '.join(sorted(only_classes))}")

    if config.enforce_scope == ADDED_LINES_SCOPE and (
        added_lines is not None or only_classes is None
    ):
        # Only paths and classes are printed for the failing set, never the
        # line's text: the report above already carries a snippet for the
        # first twenty per class, and this list must not double what a public
        # log repeats of a private name.
        failing = failing_findings(
            blocking,
            config,
            config_mode,
            added_lines,
            only_classes=only_classes,
        )
        source = added_lines.source if added_lines is not None else "none"
        print(
            f"\n  ENFORCE SCOPE: added lines ({source}). "
            f"{len(failing)} enforced finding(s) on lines this change adds fail "
            f"the run; {len(blocking) - len(failing)} other finding(s) are "
            "reported only."
        )
        for f in failing:
            loc = f"{f.path}:{f.line_no}" if f.line_no else f.path
            print(f"    ADDED {loc}: {f.class_name}")
    elif config_mode == "report" and (
        enforced := [f for f in blocking if f.class_name in config.enforce_classes]
    ):
        print(
            f"\n  ENFORCED CLASSES: {len(enforced)} finding(s) in "
            f"{sorted(config.enforce_classes)} fail the run in report mode, exit 1."
        )
    elif blocking and config_mode == "report":
        print(
            f"\n  REPORT MODE: {len(blocking)} blocking finding(s) recorded, exit 0. "
            "Flip to enforce once the residue is fixed — never by allowlisting it."
        )
    if added_lines is not None and config.enforce_scope != ADDED_LINES_SCOPE:
        print(
            f"\n  diff source ignored: {CONFIG_BASENAME} enforces the whole tree "
            f"(enforce_scope: {WHOLE_TREE_SCOPE})."
        )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
