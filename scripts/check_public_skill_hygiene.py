#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Public-skill hygiene gate — detect OmniNode-internal operating detail
leaking into published/public skill content (OMN-14105).

``plugins/onex/skills/`` is published/public. ``aislop_sweep`` (OMN-8573)
intentionally *tolerates* internal-tooling detail there — ticket refs,
``omni_home`` paths, ``# local-path-ok`` escapes — because that sweep exists
to keep our own dev-loop clean, not to gate what a reader outside OmniNode
sees. This is a **separate, stricter** gate for that outward-facing surface:
operator identity, real hostnames/IPs, machine-specific paths, and internal
doc citations do not belong in a skill a stranger might read.

DETECT-ONLY. No auto-fix. Exit non-zero on any un-allowlisted hit.

## Detection classes

| class            | what it flags                                                          |
|-------------------|------------------------------------------------------------------------|
| operator-name     | ``Jonah Gray``, ``jonahgabriel``, ``jonah.gabriel``, bare ``jonah``     |
| person-name       | configurable roster (see ``person_names:`` in the allowlist config)    |
| operator-email    | ``jonah@…``, ``…@omninode.ai``                                         |
| real-lan-ip       | ``192.168.x.x``, ``100.109.x.x``, ``100.99.x.x``                       |
| host-nick         | ``.201``/``.200`` as a host nickname, ``*.ts.net``, ``omninode-pc``, ``stickybeatz`` |
| memory-cite       | backticked or "memory"-adjacent ``feedback_…``/``project_…``/``reference_…`` doc names |
| specific-ticket   | ``OMN-<digits>`` (does not match the literal placeholder ``OMN-XXXX``) |
| machine-path      | ``/Volumes/``, ``/Users/jonah``, ``PRO-G40``, ``${HOME}/Code/omni_home``, ``/Code/omni_home/omni_save``, the two CLAUDE.md-canonical interpreter paths |
| omni_home-prose   | bare lowercase ``omni_home`` token (not ``$OMNI_HOME``/``OMNI_HOME``/``--omni-home``) |

Global token exemptions (masked out before any class regex runs, so they can
never trip any class above): ``OMN-XXXX``, ``$OMNI_HOME``, ``OMNI_HOME``,
``--omni-home``, ``OmniNode-ai``.

## Allowlisting a decided keep

Two mechanisms, both requiring a *reason* — this is a hygiene gate, not a
silence switch:

1. **Inline** (text files that support comments): put ``# public-skill-ok:
   <reason>`` on the offending line. The whole line is exempt from every
   class.
2. **Config entry** (also the only option for files without comments, e.g.
   JSON): add an entry to ``scripts/public_skill_hygiene_allowlist.yaml``
   under ``entries:``:

   ```yaml
   - path_glob: "plugins/onex/skills/foo/**/*.json"
     class: specific-ticket   # optional — omit to allowlist every class at this path
     value_regex: "OMN-1234"  # optional — omit to allowlist any value at this path/class
     reason: "why this is fine to publish"
   ```

   ``path_glob`` supports ``*`` (matches within one path segment) and
   ``/**/`` (matches zero or more path segments) — no other glob syntax.

The ``person_names:`` list in the same config file is the configurable
roster for the ``person-name`` class — add a name there, no script change
needed.

## Usage

    python3 scripts/check_public_skill_hygiene.py

Scans the entire ``plugins/onex/skills/`` tree unconditionally (no
changed-files mode) — this is a whole-tree invariant, not a diff check.

## Exit codes

- 0 — no un-allowlisted violations
- 1 — one or more un-allowlisted violations, or a malformed allowlist config
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

SKILLS_ROOT = Path("plugins/onex/skills")
ALLOWLIST_PATH = Path("scripts/public_skill_hygiene_allowlist.yaml")

INLINE_MARKER = "public-skill-ok"

# Files/dirs that are never source text worth scanning.
_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "node_modules"})
_SKIP_SUFFIXES = frozenset(
    {
        ".pyc",
        ".pyo",
        ".so",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".pdf",
        ".zip",
        ".gz",
        ".whl",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
    }
)

# Token exemptions applied to every line before any class regex runs. Masked
# out (replaced with NUL of equal length) rather than special-cased per
# class, so a global exemption can never be re-litigated per detector.
_GLOBAL_EXEMPT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"OMN-XXXX"),
    re.compile(r"\$OMNI_HOME\b"),
    re.compile(r"\bOMNI_HOME\b"),
    re.compile(r"--omni-home\b"),
    re.compile(r"\bOmniNode-ai\b"),
)


def _mask_global_exempt(line: str) -> str:
    masked = line
    for pattern in _GLOBAL_EXEMPT_PATTERNS:
        masked = pattern.sub(lambda m: "\0" * len(m.group(0)), masked)
    return masked


def _build_class_patterns(person_names: list[str]) -> dict[str, re.Pattern[str]]:
    person_alt = "|".join(re.escape(name) for name in person_names) or r"(?!)"
    return {
        "operator-name": re.compile(r"\bjonah\b|jonahgabriel", re.IGNORECASE),
        "person-name": re.compile(rf"\b(?:{person_alt})\b", re.IGNORECASE),
        "operator-email": re.compile(
            r"jonah@[\w.+-]+|[\w.+-]+@omninode\.ai", re.IGNORECASE
        ),
        "real-lan-ip": re.compile(
            r"\b192\.168\.\d{1,3}\.\d{1,3}\b"
            r"|\b100\.(?:109|99)\.\d{1,3}\.\d{1,3}\b"
        ),
        "host-nick": re.compile(
            r"(?<!\d)\.(?:200|201)\b|\.ts\.net\b|omninode-pc|stickybeatz",
            re.IGNORECASE,
        ),
        "memory-cite": re.compile(
            r"`(?:feedback|project|reference)_[a-zA-Z0-9_]+`"
            r"|\bmemory\b[^\n]{0,40}?(?:feedback|project|reference)_[a-zA-Z0-9_]+",
            re.IGNORECASE,
        ),
        "specific-ticket": re.compile(r"\bOMN-\d+\b"),
        "machine-path": re.compile(
            r"/Volumes/"
            r"|/Users/jonah\b"
            r"|PRO-G40"
            r"|\$\{HOME\}/Code/omni_home"
            r"|/Code/omni_home/omni_save"
            r"|/opt/homebrew/bin/python3\.13"
            r"|/usr/local/bin/python3\.13"
        ),
        "omni_home-prose": re.compile(r"\bomni_home\b"),
    }


@dataclass(frozen=True)
class Hit:
    path: str
    line_no: int
    class_name: str
    snippet: str


@dataclass(frozen=True)
class AllowlistEntry:
    path_glob: str
    class_name: str | None
    value_regex: str | None
    reason: str
    path_regex: re.Pattern[str]


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


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate a restricted glob (``*``, ``?``, ``/**/``) to a regex.

    ``/**/`` matches zero or more path segments (so ``a/**/*.json`` matches
    both ``a/x.json`` and ``a/b/x.json``). ``*``/``?`` never cross a ``/``.
    No other glob syntax (leading/trailing ``**``, ``[...]`` classes) is
    supported — not needed by this gate's allowlist today.
    """
    chunks = pattern.split("/**/")
    joined = "/(?:.*/)?".join(_escape_glob_segment(c) for c in chunks)
    return re.compile("^" + joined + "$")


def _load_allowlist(path: Path) -> tuple[list[AllowlistEntry], list[str]]:
    """Load the allowlist config. Fails loud (raises) on a malformed file —
    a broken allowlist is a config error, not a reason to silently pass
    everything or silently allow nothing.
    """
    if not path.exists():
        raise FileNotFoundError(f"allowlist config not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    person_names = data.get("person_names") or []
    if not isinstance(person_names, list) or not all(
        isinstance(n, str) for n in person_names
    ):
        raise ValueError("allowlist config: 'person_names' must be a list of strings")

    entries: list[AllowlistEntry] = []
    for idx, raw in enumerate(data.get("entries") or []):
        if "path_glob" not in raw or "reason" not in raw:
            raise ValueError(
                f"allowlist config: entries[{idx}] missing required "
                "'path_glob' and/or 'reason'"
            )
        entries.append(
            AllowlistEntry(
                path_glob=raw["path_glob"],
                class_name=raw.get("class"),
                value_regex=raw.get("value_regex"),
                reason=raw["reason"],
                path_regex=_glob_to_regex(raw["path_glob"]),
            )
        )
    return entries, person_names


def _is_allowlisted(hit: Hit, line: str, entries: list[AllowlistEntry]) -> bool:
    for entry in entries:
        if not entry.path_regex.match(hit.path):
            continue
        if entry.class_name is not None and entry.class_name != hit.class_name:
            continue
        if entry.value_regex is not None and not re.search(entry.value_regex, line):
            continue
        return True
    return False


def _iter_skill_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in path.parts):
            continue
        if path.suffix in _SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def _scan_file(
    path: Path,
    class_patterns: dict[str, re.Pattern[str]],
    entries: list[AllowlistEntry],
) -> tuple[list[Hit], list[Hit]]:
    """Return ``(blocked_hits, allowlisted_hits)`` for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], []  # binary asset, not a hygiene concern
    except OSError as exc:
        sys.stderr.write(f"WARN: could not read {path}: {exc}\n")
        return [], []

    rel = path.as_posix()
    blocked: list[Hit] = []
    allowlisted: list[Hit] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        if INLINE_MARKER in raw_line:
            continue
        masked = _mask_global_exempt(raw_line)
        for class_name, pattern in class_patterns.items():
            if not pattern.search(masked):
                continue
            hit = Hit(
                path=rel,
                line_no=line_no,
                class_name=class_name,
                snippet=raw_line.strip()[:160],
            )
            if _is_allowlisted(hit, raw_line, entries):
                allowlisted.append(hit)
            else:
                blocked.append(hit)
    return blocked, allowlisted


def main(argv: list[str]) -> int:  # noqa: ARG001 - whole-tree gate, no per-file args
    try:
        entries, person_names = _load_allowlist(ALLOWLIST_PATH)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    class_patterns = _build_class_patterns(person_names)

    all_blocked: list[Hit] = []
    all_allowlisted: list[Hit] = []
    files_scanned = 0
    for path in _iter_skill_files(SKILLS_ROOT):
        files_scanned += 1
        blocked, allowlisted = _scan_file(path, class_patterns, entries)
        all_blocked.extend(blocked)
        all_allowlisted.extend(allowlisted)

    for hit in all_blocked:
        print(f"{hit.path}:{hit.line_no}:{hit.class_name}: {hit.snippet}")

    blocked_by_class: dict[str, int] = {}
    for hit in all_blocked:
        blocked_by_class[hit.class_name] = blocked_by_class.get(hit.class_name, 0) + 1
    allowlisted_by_class: dict[str, int] = {}
    for hit in all_allowlisted:
        allowlisted_by_class[hit.class_name] = (
            allowlisted_by_class.get(hit.class_name, 0) + 1
        )

    print(
        f"\npublic-skill-hygiene: {files_scanned} file(s) scanned, "
        f"{len(all_blocked)} blocked hit(s), "
        f"{len(all_allowlisted)} allowlisted hit(s)."
    )
    if blocked_by_class:
        print("Blocked by class:")
        for class_name in sorted(blocked_by_class):
            print(f"  {class_name}: {blocked_by_class[class_name]}")
    if allowlisted_by_class:
        print("Allowlisted by class:")
        for class_name in sorted(allowlisted_by_class):
            print(f"  {class_name}: {allowlisted_by_class[class_name]}")

    if all_blocked:
        print(
            "\nBLOCKED: public-skill hygiene violation(s) found in "
            f"{SKILLS_ROOT}/ (see file:line:class above).\n"
            "Fix the content, or allowlist a decided keep — see the module "
            "docstring in scripts/check_public_skill_hygiene.py."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
