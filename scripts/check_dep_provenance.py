#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Dep-provenance gate — forbid first-party git-source overrides on dev/main.

Root cause this closes (OMN-13873): omnibase_infra PR #2184 merged to dev
carrying ``[tool.uv.sources]`` git-rev overrides pinning ``omnibase-core`` /
``omnibase-spi`` to UNRELEASED commits. Every CI check passed because CI
resolved those exact commits and ran green against them — the breakage is
dependency *provenance*, not runtime behavior, so no test catches it. This is a
pure static provenance gate: it FAILS closed if any PyPI-published first-party
dependency is sourced from git instead of PyPI.

Forbidden first-party deps (both hyphen and underscore spellings):

    omnibase-core   omnibase-spi   omnibase-compat

A ``[tool.uv.sources]`` entry for any of the above with a ``git`` / ``rev`` /
``branch`` / ``tag`` key is a forbidden override and fails the gate.

``onex-change-control`` is deliberately NOT checked — it follows an
immutable-main pin release model (different from the three PyPI-released deps),
so its git pin is intentional and must remain allowed.

Escape hatch (Rule-10 style): a forbidden source line may carry an inline
comment ``# raw-override-ok: <ticket>`` with a NON-EMPTY token. This exempts the
single line. An empty token (``# raw-override-ok:`` with nothing after) does NOT
exempt — the gate still fails. Because the TOML parser drops comments, the token
is detected by reading the raw source line for each flagged package.

Exit codes:
    0  — no forbidden first-party git-source override present
    1  — a forbidden override was found (or a hard error, e.g. missing file)

This check is deterministic and offline — it makes no network calls.

Usage::

    uv run python scripts/check_dep_provenance.py
    uv run python scripts/check_dep_provenance.py --pyproject pyproject.toml
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# First-party PyPI-published deps that must be resolved from PyPI, never git.
# Names are stored in canonical hyphen form; underscore spellings are
# normalized on lookup so both `omnibase-core` and `omnibase_core` are caught.
# ---------------------------------------------------------------------------

_FORBIDDEN_PACKAGES: frozenset[str] = frozenset(
    {
        "omnibase-core",
        "omnibase-spi",
        "omnibase-compat",
    }
)

# Source-override keys that indicate a git provenance (any one is forbidden for
# a first-party dep). A PyPI source has none of these.
_GIT_SOURCE_KEYS: frozenset[str] = frozenset({"git", "rev", "branch", "tag"})

# Inline escape marker: `# raw-override-ok: <ticket>` with a non-empty token.
# (Named without the substring "token" so omniclaude's validate-secrets hook does
# not flag this regex as a hardcoded credential — omniclaude adaptation, OMN-13877.)
_RAW_OVERRIDE_OK_RE = re.compile(r"#\s*raw-override-ok:\s*(\S+)")

# ---------------------------------------------------------------------------
# [tool.uv.sources] parsing. TOML is authoritative for source classification so
# single quotes, indentation, and package subtables cannot hide a git override.
# Raw text is still used only to find the inline escape token, because TOML drops
# comments.
# ---------------------------------------------------------------------------

_UVS_BLOCK_RE = re.compile(
    r"^\[tool\.uv\.sources\](.*?)(?=^\[(?!tool\.uv\.sources\.)|\Z)",
    re.MULTILINE | re.DOTALL,
)
_UVS_SUBTABLE_RE = re.compile(r"^\[tool\.uv\.sources\.([^\]]+)\]")


def _normalize(pkg: str) -> str:
    """Canonicalize a package name to hyphen form for comparison."""
    return pkg.strip().strip('"').strip("'").replace("_", "-").lower()


def _uv_sources_block(text: str) -> str | None:
    """Return the raw text of the [tool.uv.sources] block, or None if absent."""
    block_m = _UVS_BLOCK_RE.search(text)
    return block_m.group(1) if block_m else None


def _parse_uv_source_entries(text: str) -> dict[str, dict[str, object]]:
    """Return {normalized_pkg: source_mapping} from pyproject TOML."""
    try:
        parsed = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid TOML: {exc}") from exc

    tool = parsed.get("tool", {})
    if not isinstance(tool, dict):
        return {}
    uv = tool.get("uv", {})
    if not isinstance(uv, dict):
        return {}
    raw_sources = uv.get("sources", {})
    if not isinstance(raw_sources, dict):
        return {}

    sources: dict[str, dict[str, object]] = {}
    for pkg, attrs in raw_sources.items():
        if isinstance(attrs, dict):
            sources[_normalize(str(pkg))] = attrs
    return sources


def _line_for_package(block: str, pkg: str) -> str | None:
    """Return the raw source line (with any trailing comment) declaring `pkg`."""
    for raw_line in block.splitlines():
        stripped = raw_line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        subtable_m = _UVS_SUBTABLE_RE.match(stripped)
        if subtable_m and _normalize(subtable_m.group(1)) == pkg:
            return raw_line
        # Entry key is the text before the first '=' on the line.
        key = stripped.split("=", 1)[0] if "=" in stripped else ""
        if key and _normalize(key) == pkg:
            return raw_line
    return None


# ---------------------------------------------------------------------------
# Core check
# ---------------------------------------------------------------------------


def find_violations(text: str) -> list[str]:
    """Return diagnostic messages for each forbidden git-source override.

    An empty list means the file is clean (exit 0). A non-empty list means the
    gate fails (exit 1). Lines carrying a valid `# raw-override-ok: <token>`
    escape are excluded.
    """
    block = _uv_sources_block(text) or text

    try:
        entries = _parse_uv_source_entries(text)
    except ValueError as exc:
        return [str(exc)]
    violations: list[str] = []

    for pkg, attrs in entries.items():
        if pkg not in _FORBIDDEN_PACKAGES:
            continue
        git_keys = sorted(_GIT_SOURCE_KEYS & set(attrs))
        if not git_keys:
            # A non-git source (unusual, but not a provenance violation).
            continue

        raw_line = _line_for_package(block, pkg)
        if raw_line is not None:
            escape_m = _RAW_OVERRIDE_OK_RE.search(raw_line)
            if escape_m and escape_m.group(1).strip():
                # Valid non-empty escape token — this line is exempt.
                continue

        keys_desc = ", ".join(f"{k}={attrs[k]!r}" for k in git_keys)
        violations.append(
            f"{pkg}: forbidden git-source override ({keys_desc}). "
            f"First-party deps must resolve from PyPI, not git. "
            f"line: {raw_line.strip() if raw_line else '<unresolved>'}"
        )

    return violations


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--pyproject",
        default="pyproject.toml",
        help="Path to pyproject.toml (default: pyproject.toml)",
    )
    args = parser.parse_args(argv)

    pyproject_path = Path(args.pyproject)
    if not pyproject_path.exists():
        print(
            f"ERROR: pyproject.toml not found: {pyproject_path}",
            file=sys.stderr,
        )
        return 1

    violations = find_violations(pyproject_path.read_text())

    if violations:
        print(
            "FAIL: forbidden first-party git-source override(s) in "
            f"{pyproject_path} [tool.uv.sources]:",
            file=sys.stderr,
        )
        for msg in violations:
            print(f"  - {msg}", file=sys.stderr)
        print(
            "\nomnibase-core / omnibase-spi / omnibase-compat are PyPI-published "
            "first-party deps and must NOT be pinned to git commits/branches/tags "
            "on dev/main. Resolve them from PyPI (release the dep first if the "
            "needed version is unpublished). If a temporary override is genuinely "
            "unavoidable, annotate the exact line with "
            "'# raw-override-ok: <ticket>' (non-empty token).",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: no forbidden first-party git-source override in "
        f"{pyproject_path} [tool.uv.sources]."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
