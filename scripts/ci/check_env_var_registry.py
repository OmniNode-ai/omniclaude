#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Scan production Python code for os.getenv/os.environ references and compare
against .env.example as the canonical env var registry.

Exit 0 if all referenced vars are registered or allowlisted.
Exit 1 if unregistered vars are found.

Usage:
    python scripts/ci/check_env_var_registry.py \\
        --scan-dirs src/omniclaude plugins/onex/hooks/lib \\
        --registry .env.example \\
        --format text
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Framework/system vars that should never be in .env.example.
BUILTIN_ALLOWLIST = {
    "PATH",
    "HOME",
    "USER",
    "SHELL",
    "TERM",
    "LANG",
    "LC_ALL",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "UV_CACHE_DIR",
    "DEBUG",
    "LOG_LEVEL",
    "ENVIRONMENT",
    "DEPLOYMENT_ENV",
    "ENV",
    "REPL_ID",
    "CI",
    "GITHUB_ACTIONS",
    "CLAUDE_SESSION_ID",
    "CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PROJECT_DIR",
    "OMNICLAUDE_PROJECT_ROOT",
    "PLUGIN_PYTHON_BIN",
    "DISABLE_MANIFEST_DB_LOGGING",
}

# Patterns to detect env var references in Python code.
ENV_VAR_PATTERNS = [
    re.compile(r"""os\.getenv\(\s*["']([A-Z_][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z_][A-Z0-9_]*)["']"""),
    re.compile(r"""os\.environ\[["']([A-Z_][A-Z0-9_]*)["']\]"""),
]

# Directory names to skip when scanning.
SKIP_DIRS = {"tests", "__pycache__"}

# File name patterns to skip.
SKIP_FILE_PREFIXES = ("test_",)
SKIP_FILE_SUFFIXES = ("_test.py", ".pyc")


def parse_registry(registry_path: Path) -> set[str]:
    """Parse .env.example to extract registered var names.

    Both active vars (KEY=value) and commented-out vars (# KEY=value)
    are considered registered.
    """
    registered: set[str] = set()
    active_pattern = re.compile(r"^([A-Z_][A-Z0-9_]*)=")
    commented_pattern = re.compile(r"^#\s*([A-Z_][A-Z0-9_]*)=")

    for line in registry_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue

        match = active_pattern.match(line)
        if match:
            registered.add(match.group(1))
            continue

        match = commented_pattern.match(line)
        if match:
            registered.add(match.group(1))

    return registered


def scan_python_files(scan_dirs: list[Path]) -> dict[str, list[str]]:
    """Scan Python files for env var references.

    Returns:
        Dict mapping var_name -> list of file:line references.
    """
    found: dict[str, list[str]] = {}

    for scan_dir in scan_dirs:
        if not scan_dir.exists():
            continue

        for py_file in scan_dir.rglob("*.py"):
            # Skip test directories and test files
            if any(part in SKIP_DIRS for part in py_file.parts):
                continue
            fname = py_file.name
            if fname.startswith(SKIP_FILE_PREFIXES) or fname.endswith(
                SKIP_FILE_SUFFIXES
            ):
                continue

            try:
                content = py_file.read_text(errors="replace")
            except OSError:
                continue

            for i, line in enumerate(content.splitlines(), 1):
                # Skip comment lines
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue

                for pattern in ENV_VAR_PATTERNS:
                    for match in pattern.finditer(line):
                        var_name = match.group(1)
                        ref = f"{py_file}:{i}"
                        found.setdefault(var_name, []).append(ref)

    return found


def main() -> int:
    parser = argparse.ArgumentParser(description="Check env var registry completeness")
    parser.add_argument(
        "--scan-dirs",
        nargs="+",
        required=True,
        help="Directories to scan for Python files",
    )
    parser.add_argument(
        "--registry",
        required=True,
        help="Path to .env.example registry file",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--allowlist-file",
        help="Additional allowlist file (one var per line)",
    )
    args = parser.parse_args()

    registry_path = Path(args.registry)
    if not registry_path.exists():
        print(f"Registry file not found: {args.registry}", file=sys.stderr)
        return 1

    # Build allowlist
    allowlist = set(BUILTIN_ALLOWLIST)
    if args.allowlist_file:
        al_path = Path(args.allowlist_file)
        if al_path.exists():
            for line in al_path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    allowlist.add(line)

    # Parse registry
    registered = parse_registry(registry_path)

    # Scan code
    scan_dirs = [Path(d) for d in args.scan_dirs]
    found = scan_python_files(scan_dirs)

    # Classify
    registered_found: list[str] = []
    unregistered_found: list[str] = []
    allowlisted_found: list[str] = []

    for var_name in sorted(found.keys()):
        if var_name in registered:
            registered_found.append(var_name)
        elif var_name in allowlist:
            allowlisted_found.append(var_name)
        else:
            unregistered_found.append(var_name)

    # Output
    if args.format == "json":
        result = {
            "registered": sorted(registered_found),
            "unregistered": sorted(unregistered_found),
            "allowlisted": sorted(allowlisted_found),
        }
        print(json.dumps(result, indent=2))
    else:
        if unregistered_found:
            print("UNREGISTERED env vars (must be added to .env.example or allowlist):")
            for var in unregistered_found:
                refs = found[var]
                print(f"  {var}")
                for ref in refs[:3]:  # Show up to 3 references
                    print(f"    -> {ref}")
            print()

        print(f"Registered: {len(registered_found)}")
        print(f"Unregistered: {len(unregistered_found)}")
        print(f"Allowlisted: {len(allowlisted_found)}")

    return 1 if unregistered_found else 0


if __name__ == "__main__":
    sys.exit(main())
