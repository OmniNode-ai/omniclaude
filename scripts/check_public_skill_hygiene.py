#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Public-repository hygiene gate — detect OmniNode-internal operating detail
leaking into this public repository (OMN-14105, widened by OMN-17993).

This repository is public. Operator identity, real hostnames/IPs,
machine-specific paths, collaborator names and internal doc citations do not
belong in anything a stranger can read here.

## Scanned surface — the whole tracked tree (OMN-17993)

Until OMN-17993 this gate scanned ``plugins/onex/skills/`` only: 465 of the
repository's 3,203 tracked files. Every one of the repository's HIGH
public-exposure findings in the 2026-09-06 inventory lived outside that
subtree, and the gate reported green over all of them. A gate that reports
green over an unscanned directory is worse than no gate, so the scanned
surface is now the **tracked set** — ``git ls-files`` — not a subtree and not
the ignore rules (an ignore file neither untracks an existing path nor stops
``git add -f``).

Two surfaces, different tolerances:

* **Published surface** (``PUBLISHED_ROOTS`` — ``plugins/onex/skills/``):
  published agent-skill content a stranger reads directly. Every detection
  class blocks, budget permanently zero. This is the pre-OMN-17993 behaviour,
  unchanged.
* **Tree surface** (everything else tracked): the disclosure classes block
  against a **ratchet budget** (see below). Nothing is waived per line and no
  path is excluded.

## The ratchet, and why not an allowlist

Widening the scan surfaced a large pre-existing residue that is being
remediated separately (epic OMN-17992, wave A). Waiving it per line would
reproduce the exact recurrence mechanism this programme exists to remove:
self-granted suppression annotations, written by the author of the violation,
approved by nobody.

Instead ``scripts/public_skill_hygiene_ratchet.yaml`` carries a per-class
maximum count for the tree surface. Every hit is still scanned, printed and
counted. The gate fails when a class exceeds its budget (a NEW violation) and
also when a class is under its budget (the residue shrank — lower the budget
so the ground gained is held). ``--tighten`` rewrites the budgets to the
current counts.

Nothing is exempt: the budget is a monotone burndown, not a waiver, and it
names no file.

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

``specific-ticket`` blocks on the **published surface only**. Internal ticket
ids in public source are an accepted convention, not a violation — operator
ruling of 2026-09-06 (P3), recorded in the OMN-17992 prevention plan. On the
tree surface the class is counted and reported as information, never blocked.

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
    python3 scripts/check_public_skill_hygiene.py --list      # dump the full residue
    python3 scripts/check_public_skill_hygiene.py --tighten   # rewrite the budgets

Whole-tree invariant, no changed-files mode.

## Exit codes

- 0 — no un-allowlisted violations, and every tree-surface class is exactly at
  its ratchet budget
- 1 — a published-surface violation, a tree-surface class over or under its
  budget, or a malformed config
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Published/public agent-skill content: zero tolerance, every class, no budget.
PUBLISHED_ROOTS: tuple[str, ...] = ("plugins/onex/skills/",)

ALLOWLIST_PATH = Path("scripts/public_skill_hygiene_allowlist.yaml")
RATCHET_PATH = Path("scripts/public_skill_hygiene_ratchet.yaml")

INLINE_MARKER = "public-skill-ok"

# Counted and reported on the tree surface, never blocked there. Operator
# ruling P3 (2026-09-06): internal ticket ids in public source are a
# convention, not a violation. Still blocks on the published surface.
PUBLISHED_SURFACE_ONLY_CLASSES = frozenset({"specific-ticket"})

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
            r"\b192\.168\.\d{1,3}\.\d{1,3}\b" r"|\b100\.(?:109|99)\.\d{1,3}\.\d{1,3}\b"
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

    @property
    def is_published_surface(self) -> bool:
        return is_published_surface(self.path)


def is_published_surface(rel_path: str) -> bool:
    """True when ``rel_path`` is published agent-skill content."""
    return any(rel_path.startswith(root) for root in PUBLISHED_ROOTS)


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


def _load_ratchet(path: Path) -> dict[str, int]:
    """Load the per-class tree-surface budgets. Fails loud on a malformed
    file — a broken ratchet is a config error, never an implicit zero (which
    would fail every class) or an implicit infinity (which would pass every
    class).
    """
    if not path.exists():
        raise FileNotFoundError(f"ratchet config not found: {path}")

    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    budgets = data.get("tree_surface_budgets")
    if not isinstance(budgets, dict):
        raise ValueError("ratchet config: 'tree_surface_budgets' must be a mapping")
    parsed: dict[str, int] = {}
    for class_name, value in budgets.items():
        if not isinstance(class_name, str) or not isinstance(value, int) or value < 0:
            raise ValueError(
                "ratchet config: 'tree_surface_budgets' must map a class name "
                f"to a non-negative integer (got {class_name!r}: {value!r})"
            )
        parsed[class_name] = value
    return parsed


def _write_ratchet(path: Path, budgets: dict[str, int]) -> None:
    header = (
        "# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.\n"
        "# SPDX-License-Identifier: MIT\n"
        "#\n"
        "# Public-repo hygiene ratchet (OMN-17993).\n"
        "#\n"
        "# Per-class maximum blocked-hit count on the TREE surface (every\n"
        "# tracked file outside PUBLISHED_ROOTS). The published surface is\n"
        "# permanently zero and is not configurable here.\n"
        "#\n"
        "# This is a burndown budget, not an allowlist: it names no file, waives\n"
        "# no line, and only ever goes down. The residue it accounts for is the\n"
        "# pre-existing public-exposure inventory being remediated under epic\n"
        "# OMN-17992 (wave A). Exceeding a budget fails the gate; dropping below\n"
        "# one also fails it, so ground gained is held.\n"
        "#\n"
        "# Regenerate after a remediation lands:\n"
        "#   python3 scripts/check_public_skill_hygiene.py --tighten\n"
        "\n"
        "tree_surface_budgets:\n"
    )
    # Each budget line carries the inline marker: a class name is the gate's
    # own vocabulary, not prose, and `omni_home-prose` would otherwise match
    # itself and make the ratchet unrepresentable.
    body = "".join(
        f"  {name}: {budgets[name]}"
        f"  # public-skill-ok: detection-class name, not prose\n"
        for name in sorted(budgets)
    )
    path.write_text(header + body, encoding="utf-8")


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


def _tracked_files(root: Path) -> list[Path]:
    """The tracked set, per ``git ls-files``.

    The tracked set — not a directory walk and not the ignore rules — is the
    scanned surface: an ignore rule neither untracks an existing path nor stops
    ``git add -f``, so ignore state proves nothing about what is published.

    Fails loud when git cannot answer; a hygiene gate that silently scans
    nothing is the defect this widening exists to fix.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    files: list[Path] = []
    for rel in result.stdout.split("\0"):
        if not rel:
            continue
        path = root / rel
        if any(part in _SKIP_DIR_NAMES for part in Path(rel).parts):
            continue
        if path.suffix in _SKIP_SUFFIXES:
            continue
        # Symlinks and gitlinks resolve to directories or to nothing.
        if not path.is_file() or path.is_symlink():
            continue
        files.append(path)
    return sorted(files)


def _scan_file(
    path: Path,
    class_patterns: dict[str, re.Pattern[str]],
    entries: list[AllowlistEntry],
    rel_path: str | None = None,
) -> tuple[list[Hit], list[Hit]]:
    """Return ``(blocked_hits, allowlisted_hits)`` for one file."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], []  # binary asset, not a hygiene concern
    except OSError as exc:
        sys.stderr.write(f"WARN: could not read {path}: {exc}\n")
        return [], []

    rel = rel_path if rel_path is not None else path.as_posix()
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


def _repo_root() -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip())


def scan_tree(root: Path) -> tuple[list[Hit], list[Hit], int]:
    """Scan the tracked set under ``root``.

    Returns ``(blocked, allowlisted, files_scanned)``. ``blocked`` carries
    every non-allowlisted hit on both surfaces; the caller applies the
    surface policy.
    """
    entries, person_names = _load_allowlist(root / ALLOWLIST_PATH)
    class_patterns = _build_class_patterns(person_names)

    blocked: list[Hit] = []
    allowlisted: list[Hit] = []
    files_scanned = 0
    for path in _tracked_files(root):
        files_scanned += 1
        rel = path.relative_to(root).as_posix()
        file_blocked, file_allowlisted = _scan_file(
            path, class_patterns, entries, rel_path=rel
        )
        blocked.extend(file_blocked)
        allowlisted.extend(file_allowlisted)
    return blocked, allowlisted, files_scanned


def _counts_by_class(hits: list[Hit]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for hit in hits:
        counts[hit.class_name] = counts.get(hit.class_name, 0) + 1
    return counts


def main(argv: list[str]) -> int:
    tighten = "--tighten" in argv[1:]
    list_all = "--list" in argv[1:]

    try:
        root = _repo_root()
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.stderr.write(f"ERROR: not inside a git work tree: {exc}\n")
        return 1

    try:
        blocked, allowlisted, files_scanned = scan_tree(root)
    except (
        FileNotFoundError,
        ValueError,
        yaml.YAMLError,
        subprocess.CalledProcessError,
    ) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    published_hits = [h for h in blocked if h.is_published_surface]
    tree_hits = [
        h
        for h in blocked
        if not h.is_published_surface
        and h.class_name not in PUBLISHED_SURFACE_ONLY_CLASSES
    ]
    tree_informational = [
        h
        for h in blocked
        if not h.is_published_surface and h.class_name in PUBLISHED_SURFACE_ONLY_CLASSES
    ]

    tree_counts = _counts_by_class(tree_hits)

    if tighten:
        # The ratchet file is itself part of the tracked set, so writing it can
        # change the counts. Converge rather than leaving a budget that the
        # very next run rejects.
        for _ in range(3):
            _write_ratchet(root / RATCHET_PATH, tree_counts)
            blocked, _allowlisted, _files = scan_tree(root)
            recount = _counts_by_class(
                [
                    h
                    for h in blocked
                    if not h.is_published_surface
                    and h.class_name not in PUBLISHED_SURFACE_ONLY_CLASSES
                ]
            )
            if recount == tree_counts:
                break
            tree_counts = recount
        else:
            sys.stderr.write("ERROR: ratchet counts did not converge in 3 passes\n")
            return 1
        print(f"Ratchet rewritten to current tree-surface counts: {RATCHET_PATH}")
        for class_name in sorted(tree_counts):
            print(f"  {class_name}: {tree_counts[class_name]}")
        if published_hits:
            print(
                "\nNOTE: --tighten does not budget the published surface; "
                f"{len(published_hits)} published-surface violation(s) remain."
            )
        return 0

    try:
        budgets = _load_ratchet(root / RATCHET_PATH)
    except (FileNotFoundError, ValueError, yaml.YAMLError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 1

    over_classes = {
        class_name
        for class_name, actual in tree_counts.items()
        if actual > budgets.get(class_name, 0)
    }

    # Published-surface violations always print. Tree-surface hits print for
    # a class that is OVER budget (the actionable signal) or under ``--list``
    # (the full residue). At-budget residue is reported by count, not by 947
    # lines that would bury a real regression.
    for hit in published_hits:
        print(f"PUBLISHED {hit.path}:{hit.line_no}:{hit.class_name}: {hit.snippet}")
    for hit in tree_hits:
        if list_all or hit.class_name in over_classes:
            print(f"TREE {hit.path}:{hit.line_no}:{hit.class_name}: {hit.snippet}")

    print(
        f"\npublic-repo-hygiene: {files_scanned} tracked file(s) scanned, "
        f"{len(published_hits)} published-surface violation(s), "
        f"{len(tree_hits)} tree-surface hit(s), "
        f"{len(tree_informational)} informational hit(s), "
        f"{len(allowlisted)} allowlisted hit(s)."
    )

    over: list[str] = []
    under: list[str] = []
    print("Tree surface vs ratchet budget:")
    for class_name in sorted(set(tree_counts) | set(budgets)):
        actual = tree_counts.get(class_name, 0)
        budget = budgets.get(class_name, 0)
        marker = "ok"
        if actual > budget:
            marker = "OVER"
            over.append(f"{class_name}: {actual} > {budget}")
        elif actual < budget:
            marker = "UNDER"
            under.append(f"{class_name}: {actual} < {budget}")
        print(f"  {class_name}: {actual}/{budget} {marker}")

    if tree_informational:
        info_counts = _counts_by_class(tree_informational)
        print(
            "Informational (operator ruling P3, 2026-09-06 — internal ticket "
            "ids in public source are a convention, not a violation):"
        )
        for class_name in sorted(info_counts):
            print(f"  {class_name}: {info_counts[class_name]}")

    failed = False

    if published_hits:
        failed = True
        print(
            "\nBLOCKED: public-skill hygiene violation(s) on the published "
            f"surface ({', '.join(PUBLISHED_ROOTS)}).\n"
            "Fix the content, or allowlist a decided keep — see the module "
            "docstring in scripts/check_public_skill_hygiene.py."
        )

    if over:
        failed = True
        print("\nBLOCKED: tree-surface class(es) over the ratchet budget:")
        for line in over:
            print(f"  {line}")
        print(
            "A new public-exposure violation landed. Fix it — the budget is a "
            "burndown of the pre-existing residue (epic OMN-17992), never a "
            "place to book new debt."
        )

    if under:
        failed = True
        print("\nBLOCKED: tree-surface class(es) under the ratchet budget:")
        for line in under:
            print(f"  {line}")
        print(
            "The residue shrank — hold the ground. Run:\n"
            "  python3 scripts/check_public_skill_hygiene.py --tighten\n"
            "and commit the updated scripts/public_skill_hygiene_ratchet.yaml."
        )

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
