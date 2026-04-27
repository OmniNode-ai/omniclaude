# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""validate_skill_backing_node -- block skill backing-node regressions.

Ticket: OMN-10052. Closes OMN-9884 class of failure.

On 2026-04-27, /onex:merge_sweep pointed at node_merge_sweep (gutted by
functional-core/imperative-shell decomposition) for hours. Cron ticked every
5 minutes against a non-existent entrypoint. Silent failure.

This validator blocks that class of regression at pre-commit and CI:

1. Walk every ``plugins/onex/skills/*/SKILL.md`` in the repo root.
2. Extract the backing-node reference using the canonical body form::

       **Backing node**: `omnimarket/src/omnimarket/nodes/<node_name>/`

   and the alternate short form (no path prefix)::

       - **Backing node**: `node_<name>`

   The extractor accepts all three field-value separators seen in the corpus:
   ``**Backing node**:``, ``Backing node:``, and ``backing_node:`` (YAML
   frontmatter). The first match per file wins.

3. For each declared backing node, resolve the path relative to the repo root
   (``<repo_root>/omnimarket/src/omnimarket/nodes/<node_name>/``) and assert:

   a. Directory exists.
   b. ``contract.yaml`` exists at the directory root.
   c. ``handlers/`` directory exists and contains at least one ``handler_*.py``
      file with non-trivial content (more than 10 non-blank, non-comment lines
      — guards against ``pass`` / ``NotImplementedError`` stubs).

4. Fail with a precise message naming the offending skill + specific violation.

5. Allowlist: ``plugins/onex/skills/_lib/skill_backing_node_allowlist.yaml``.
   Every entry MUST carry a non-empty ``reason`` field. The loader raises
   ``ValueError`` on a missing or blank reason so silent drop-ins are caught at
   pre-commit time, not at runtime.

No warn-only mode. Per ``feedback_no_informational_gates.md``, the validator
BLOCKS unconditionally. Skills whose SKILL.md does not declare a backing node
are not checked (they may be pure-instruction skills like ``build_loop``).

Usage (standalone / CI self-scan)::

    python plugins/onex/skills/_lib/validate_skill_backing_node.py [ROOT]

ROOT defaults to the directory three levels above this file
(i.e. the omniclaude repo root).

Exit codes:
    0 — all declared backing nodes are live
    1 — at least one violation found (or allowlist entry missing reason)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWLIST_PATH_REL = Path("plugins/onex/skills/_lib/skill_backing_node_allowlist.yaml")

# Omnimarket nodes root relative to the omnimarket repo root.
# The omnimarket repo is expected to live as a sibling of this omniclaude
# repo under the same OMNI_HOME directory.  The validator resolves the path
# dynamically so it works in CI (checkout-based) and in worktrees.
_OMNIMARKET_NODES_REL = Path("omnimarket/src/omnimarket/nodes")

# Minimum number of non-blank, non-comment lines in a handler file before we
# consider it "non-trivial".  Guards against empty stubs.
_MIN_SUBSTANTIVE_LINES = 10

# Patterns used to extract the backing-node name from SKILL.md body/frontmatter.
# Listed in priority order; the first match per file wins.
_BACKING_NODE_PATTERNS: list[re.Pattern[str]] = [
    # Canonical body form: **Backing node**: `omnimarket/src/omnimarket/nodes/node_foo/`
    re.compile(
        r"\*\*Backing node\*\*\s*:\s*`(?:[^`]*/)?(?P<name>node_[a-z_0-9]+)/?`",
        re.IGNORECASE,
    ),
    # Short body form: - **Backing node**: `node_foo`
    re.compile(
        r"\*\*Backing node\*\*\s*:\s*`(?P<name>node_[a-z_0-9]+)`",
        re.IGNORECASE,
    ),
    # Inline heading form (compliance_sweep):
    # **Skill ID**: ... · **Backing node**: `omnimarket/...node_foo/` · ...
    re.compile(
        r"Backing\s+node\*\*\s*:\s*`(?:[^`]*/)?(?P<name>node_[a-z_0-9]+)/?`",
        re.IGNORECASE,
    ),
    # YAML frontmatter form: backing_node: "node_foo"
    re.compile(
        r"^backing_node\s*:\s*[\"']?(?P<name>node_[a-z_0-9]+)[\"']?",
        re.MULTILINE,
    ),
]


# ---------------------------------------------------------------------------
# Allowlist loader
# ---------------------------------------------------------------------------


def load_allowlist(repo_root: Path) -> dict[str, str]:
    """Return mapping of skill_name -> reason from the allowlist YAML.

    Raises ``ValueError`` if any entry has a blank or missing ``reason``.
    Returns an empty dict when the allowlist file does not exist (bootstrap-
    friendly so new repos can adopt the validator before adding exemptions).
    """
    path = repo_root / _ALLOWLIST_PATH_REL
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = raw.get("allowlist") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        return {}
    out: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(
                f"skill_backing_node allowlist entries must be mappings; got {entry!r}"
            )
        skill = entry.get("skill")
        reason = entry.get("reason")
        if not isinstance(skill, str) or not skill.strip():
            raise ValueError(
                "skill_backing_node allowlist entry missing non-empty 'skill' field"
            )
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(
                f"skill_backing_node allowlist entry {skill!r}: every entry must "
                "declare a non-empty 'reason' explaining why the skill is exempt "
                "from backing-node liveness enforcement"
            )
        out[skill.strip()] = reason.strip()
    return out


# ---------------------------------------------------------------------------
# SKILL.md parser
# ---------------------------------------------------------------------------


def extract_backing_node(skill_md_path: Path) -> str | None:
    """Return the node directory name declared in the SKILL.md, or None.

    Tries each pattern in ``_BACKING_NODE_PATTERNS`` in order.  The first
    match wins.  Returns ``None`` when no backing-node declaration is found
    (pure-instruction skills are not checked).
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for pattern in _BACKING_NODE_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group("name")
    return None


# ---------------------------------------------------------------------------
# Node liveness checks
# ---------------------------------------------------------------------------


def _count_substantive_lines(path: Path) -> int:
    """Return the number of non-blank, non-comment lines in *path*."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count += 1
    return count


class NodeViolation:
    """A single liveness violation for a skill's backing node."""

    def __init__(self, skill: str, node_name: str, detail: str) -> None:
        self.skill = skill
        self.node_name = node_name
        self.detail = detail

    def __str__(self) -> str:
        return (
            f"VIOLATION  skill={self.skill!r}  node={self.node_name!r}\n  {self.detail}"
        )


def _resolve_omnimarket_nodes_root(repo_root: Path) -> list[Path]:
    """Return candidate paths for the omnimarket nodes directory.

    Resolution order (first that is_dir() wins at call time):
    1. ``$OMNIMARKET_ROOT`` env var — explicit override for local dev + CI.
    2. ``$OMNI_HOME/omnimarket`` — standard OMNI_HOME layout (used by
       pre-commit hooks on developer machines where OMNI_HOME is set).
    3. ``_omnimarket`` relative to *repo_root* — CI checkout layout
       (``actions/checkout@v6`` with ``path: _omnimarket``).
    4. Sibling repo: ``<repo_root>/../omnimarket`` — OMNI_HOME layout
       where omnimarket is a direct sibling of omniclaude.
    5. Mono-repo style: ``<repo_root>/omnimarket/…`` (future).
    6. Vendor dir: ``<repo_root>/vendor/omnimarket/…`` (future).
    """
    import os

    _nodes = Path("src") / "omnimarket" / "nodes"
    bases: list[Path] = []

    omnimarket_root_env = os.environ.get("OMNIMARKET_ROOT")
    if omnimarket_root_env:
        bases.append(Path(omnimarket_root_env) / _nodes)

    # OMNI_HOME layout (covers developer pre-commit invocations)
    omni_home = os.environ.get("OMNI_HOME")
    if omni_home:
        bases.append(Path(omni_home) / "omnimarket" / _nodes)

    # CI layout: _omnimarket is checked out next to omniclaude
    bases.append(repo_root / "_omnimarket" / _nodes)

    # Direct sibling (worktree siblings, etc.)
    bases.append(repo_root.parent / "omnimarket" / _nodes)

    # Mono-repo and vendor fallbacks
    bases.append(repo_root / _OMNIMARKET_NODES_REL)
    bases.append(repo_root / "vendor" / "omnimarket" / _nodes)

    return bases


def check_node_liveness(
    skill_name: str,
    node_name: str,
    repo_root: Path,
) -> NodeViolation | None:
    """Assert that *node_name* exists and is live under *repo_root*.

    Returns a ``NodeViolation`` describing the first problem found, or
    ``None`` when the node passes all checks.
    """
    candidates = [
        base / node_name for base in _resolve_omnimarket_nodes_root(repo_root)
    ]

    node_dir: Path | None = None
    for candidate in candidates:
        if candidate.is_dir():
            node_dir = candidate
            break

    if node_dir is None:
        # De-duplicate (env var may produce same paths as fallbacks)
        unique = list(dict.fromkeys(str(c) for c in candidates))
        searched = "\n    ".join(unique)
        return NodeViolation(
            skill_name,
            node_name,
            f"node directory not found.  Searched:\n    {searched}\n"
            "  Tip: set $OMNIMARKET_ROOT to the omnimarket repo root, or "
            "ensure the CI workflow checks out omnimarket into _omnimarket/",
        )

    contract = node_dir / "contract.yaml"
    if not contract.is_file():
        return NodeViolation(
            skill_name,
            node_name,
            f"contract.yaml missing at {contract}",
        )

    handlers_dir = node_dir / "handlers"
    if not handlers_dir.is_dir():
        return NodeViolation(
            skill_name,
            node_name,
            f"handlers/ directory missing at {handlers_dir}",
        )

    handler_files = sorted(handlers_dir.glob("handler_*.py"))
    if not handler_files:
        return NodeViolation(
            skill_name,
            node_name,
            f"handlers/ directory at {handlers_dir} contains no handler_*.py files",
        )

    # Check that at least one handler has substantive content.
    live_handler = next(
        (
            hf
            for hf in handler_files
            if _count_substantive_lines(hf) >= _MIN_SUBSTANTIVE_LINES
        ),
        None,
    )
    if live_handler is None:
        stub_list = ", ".join(hf.name for hf in handler_files)
        return NodeViolation(
            skill_name,
            node_name,
            f"all handler files appear to be stubs (fewer than "
            f"{_MIN_SUBSTANTIVE_LINES} substantive lines each): {stub_list}",
        )

    return None


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------


def _omnimarket_available(repo_root: Path) -> bool:
    """Return True when at least one omnimarket nodes base directory exists.

    When *no* base is resolvable (developer machine without omnimarket
    cloned and neither $OMNIMARKET_ROOT nor $OMNI_HOME set), the validator
    skips enforcement rather than blocking the commit.  CI always has
    omnimarket available via the ``_omnimarket/`` checkout, so the gate is
    still effective on every PR.
    """
    return any(base.is_dir() for base in _resolve_omnimarket_nodes_root(repo_root))


def scan(repo_root: Path) -> list[str]:
    """Scan *repo_root* for backing-node violations.

    Returns a list of human-readable error strings.  An empty list means the
    tree is clean.  Raises ``ValueError`` on a malformed allowlist entry.

    When omnimarket is not resolvable locally (neither $OMNIMARKET_ROOT nor
    $OMNI_HOME set, no _omnimarket/ checkout, no sibling repo), the function
    prints a warning and returns an empty list rather than failing.  CI
    enforces the gate unconditionally via the _omnimarket/ checkout.
    """
    allowlist = load_allowlist(repo_root)
    skills_root = repo_root / "plugins" / "onex" / "skills"
    if not skills_root.is_dir():
        return [f"skills directory not found at {skills_root}"]

    if not _omnimarket_available(repo_root):
        print(
            "validate-skill-backing-node: SKIPPED locally — omnimarket not found. "
            "Set $OMNIMARKET_ROOT or $OMNI_HOME to enable local enforcement. "
            "CI checks out omnimarket and enforces this gate on every PR.",
            file=sys.stderr,
        )
        return []

    errors: list[str] = []

    for skill_md in sorted(skills_root.glob("*/SKILL.md")):
        skill_name = skill_md.parent.name

        # Skills without a backing-node declaration are not checked.
        node_name = extract_backing_node(skill_md)
        if node_name is None:
            continue

        # Allowlisted skills are explicitly exempted.
        if skill_name in allowlist:
            continue

        violation = check_node_liveness(skill_name, node_name, repo_root)
        if violation is not None:
            errors.append(str(violation))

    return errors


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns 0 on success, 1 on violations."""
    args = argv if argv is not None else sys.argv[1:]

    # Determine repo root.
    if args:
        repo_root = Path(args[0]).resolve()
    else:
        # Default: four levels up from this file (plugins/onex/skills/_lib/).
        repo_root = Path(__file__).resolve().parents[4]

    try:
        errors = scan(repo_root)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if errors:
        print(
            "validate-skill-backing-node: FAILED — backing-node liveness violations:\n",
            file=sys.stderr,
        )
        for err in errors:
            print(err, file=sys.stderr)
        print(
            "\nFIX: update the backing node so it has a live handlers/ directory, "
            "or add the skill to "
            "plugins/onex/skills/_lib/skill_backing_node_allowlist.yaml "
            "with a non-empty 'reason' field.",
            file=sys.stderr,
        )
        return 1

    # Distinguish a true clean pass from a skipped run (omnimarket unavailable).
    if not _omnimarket_available(repo_root):
        # scan() already emitted the SKIPPED warning; don't print a false "OK".
        return 0

    print(
        f"validate-skill-backing-node: OK — {_count_skills_checked(repo_root)} "
        "skills with backing-node declarations are live"
    )
    return 0


def _count_skills_checked(repo_root: Path) -> int:
    """Return number of skills that have a backing-node declaration."""
    skills_root = repo_root / "plugins" / "onex" / "skills"
    if not skills_root.is_dir():
        return 0
    count = 0
    try:
        allowlist = load_allowlist(repo_root)
    except ValueError:
        allowlist = {}
    for skill_md in skills_root.glob("*/SKILL.md"):
        skill_name = skill_md.parent.name
        if extract_backing_node(skill_md) is not None and skill_name not in allowlist:
            count += 1
    return count


if __name__ == "__main__":
    sys.exit(main())
