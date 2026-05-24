#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Detect hardcoded LLM model IDs, endpoints, and routing bypasses in runtime paths.

Catches:
  - Hardcoded model ID strings (claude-sonnet-4-*, qwen3-coder-*, deepseek-*, etc.)
  - LLM endpoint URLs (http://192.168.86.x:800x/v1/...)
  - Timeout literals inside LLM call paths (timeout=30, request_timeout=60)
  - Direct provider construction bypassing the router
  - Undeclared routing fallbacks (model= kwarg outside contract-driven context)

Suppression: add `# llm-hardcode-ok: <reason>` to the flagged line.
Allowlist: scripts/validation/llm_hardcode_allowlist.json (structured, per-violation).

Exit codes:
    0: No violations found
    1: Violations detected

[OMN-11944]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Known model ID fragments — match the literal slug that appears in code
_MODEL_ID_FRAGMENTS = [
    # Anthropic
    r"claude-(?:opus|sonnet|haiku)-\d",
    r"claude-3-\d",
    # Qwen / local
    r"qwen\d*[-/]coder",
    r"qwen\d*[-/]next",
    r"qwen\d*[-/]embedding",
    # DeepSeek
    r"deepseek[-/]r\d",
    r"deepseek[-/]v\d",
    r"deepseek[-/]coder",
    # Mistral / Codestral
    r"mistral[-/](?:7b|nemo|large|small)",
    r"codestral",
    # Gemini
    r"gemini-\d",
    r"gemini-pro",
    r"gemini-flash",
    # GPT
    r"gpt-4(?:o|-\d)",
    r"gpt-3\.5",
    # GLM / Zhipu
    r"glm-\d",
    r"glm-4",
]

_MODEL_ID_RE = re.compile(
    r"(?:\"|\')(" + "|".join(_MODEL_ID_FRAGMENTS) + r")[^\"\']*(?:\"|\')",
    re.IGNORECASE,
)

# LLM endpoint URLs — LAN addresses on inference ports
_LLM_ENDPOINT_RE = re.compile(
    r"""(?:https?://)?192\.168\.\d{1,3}\.\d{1,3}:(?:800\d|8100|8101|8102)\b""",
    re.IGNORECASE,
)

# Timeout literals in LLM call context — look for timeout= kw in lines that
# also contain common LLM client signals.
_LLM_TIMEOUT_RE = re.compile(
    r"""(?:request_timeout|timeout|connect_timeout|read_timeout)\s*=\s*\d+""",
)

_LLM_CALL_SIGNALS = re.compile(
    r"""(?:openai|anthropic|AsyncOpenAI|Anthropic|chat\.completions|generate|
    completions\.create|v1/chat|v1/completions|v1/embeddings|llm_client|
    LLMClient|model_router|call_llm|ask_llm)""",
    re.VERBOSE | re.IGNORECASE,
)

# Direct provider construction (bypassing router)
_DIRECT_PROVIDER_RE = re.compile(
    r"""(?:openai\.OpenAI|openai\.AsyncOpenAI|anthropic\.Anthropic|
    anthropic\.AsyncAnthropic)\s*\(""",
    re.VERBOSE,
)

# Undeclared routing fallbacks — model= kwarg with a literal string value
_UNDECLARED_FALLBACK_RE = re.compile(
    r"""model\s*=\s*(?:\"|\')""",
)

# ---------------------------------------------------------------------------
# Suppression / allowlist
# ---------------------------------------------------------------------------

_SUPPRESS_MARKER = "llm-hardcode-ok"

# Allowlist file path relative to repo root
_ALLOWLIST_PATH = Path("scripts/validation/llm_hardcode_allowlist.json")

# ---------------------------------------------------------------------------
# Paths to scan (runtime paths only — not test fixtures, docs, generated)
# ---------------------------------------------------------------------------

_SCAN_DIRS = [
    Path("src"),
    Path("plugins"),
    Path("scripts"),
]

_SCAN_EXTENSIONS = frozenset({".py"})

# Patterns that mark a path segment as non-runtime (skip entirely).
# Anchored to segment boundaries using a path-component approach so that
# pytest tmp directories (which embed test names like "test_foo0") do not
# produce false positives on files that are genuinely in runtime src/.
_SKIP_SEGMENTS: frozenset[str] = frozenset(
    {
        "tests",
        "test",
        "fixtures",
        "fixture",
        ".venv",
        "__pycache__",
        "docs",
        "evidence",
        "generated",
    }
)

# Additional file-name patterns to skip (no path-component anchoring needed)
_SKIP_FILENAME_RE = re.compile(
    r"""(?:
        /conftest\.py$|
        _test\.py$|
        ^test_|
        validate_no_hardcoded_llm_refs\.py$  # self-exclusion
    )""",
    re.VERBOSE,
)


def _is_skip_path(path: Path) -> bool:
    """Return True if the path should be excluded from scanning."""
    # Check each path component against the skip-segment set
    for part in path.parts:
        if part in _SKIP_SEGMENTS:
            return True
    # Check filename patterns
    return bool(_SKIP_FILENAME_RE.search(path.name))


# ---------------------------------------------------------------------------
# Violation types
# ---------------------------------------------------------------------------

_CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("hardcoded_model_id", _MODEL_ID_RE),
    ("llm_endpoint_url", _LLM_ENDPOINT_RE),
    ("direct_provider_construction", _DIRECT_PROVIDER_RE),
    ("undeclared_routing_fallback", _UNDECLARED_FALLBACK_RE),
]


def _load_allowlist() -> set[str]:
    """Return set of '<path>:<lineno>' strings from the structured allowlist."""
    if not _ALLOWLIST_PATH.exists():
        return set()
    try:
        data = json.loads(_ALLOWLIST_PATH.read_text())
        entries: set[str] = set()
        for entry in data.get("entries", []):
            path = entry.get("path", "")
            lineno = entry.get("lineno")
            if path and lineno is not None:
                entries.add(f"{path}:{lineno}")
        return entries
    except (json.JSONDecodeError, KeyError):
        return set()


def _check_timeout_in_llm_context(path: Path) -> list[tuple[int, str, str]]:
    """Detect timeout literals only in lines near LLM call expressions."""
    violations: list[tuple[int, str, str]] = []
    lines = path.read_text(errors="replace").splitlines()
    window = 5  # lines before/after to check for LLM context
    for i, line in enumerate(lines):
        if _LLM_TIMEOUT_RE.search(line):
            start = max(0, i - window)
            end = min(len(lines), i + window + 1)
            context = "\n".join(lines[start:end])
            if _LLM_CALL_SIGNALS.search(context):
                violations.append((i + 1, "llm_timeout_literal", line))
    return violations


def _scan_file(
    path: Path,
    allowlist: set[str],
    inventory: list[dict[str, object]],
) -> list[str]:
    rel = str(path)
    if _is_skip_path(path):
        return []

    try:
        text = path.read_text(errors="replace")
    except OSError:
        return []

    lines = text.splitlines()
    violations: list[str] = []

    for i, line in enumerate(lines, 1):
        if _SUPPRESS_MARKER in line:
            continue
        key = f"{rel}:{i}"
        if key in allowlist:
            continue

        for check_name, pattern in _CHECKS:
            if pattern.search(line):
                msg = f"  {rel}:{i} [{check_name}]: {line.strip()}"
                violations.append(msg)
                inventory.append(
                    {
                        "path": rel,
                        "lineno": i,
                        "check": check_name,
                        "line": line.strip(),
                    }
                )
                break  # one violation per line

    # Timeout check (contextual)
    for lineno, check_name, line in _check_timeout_in_llm_context(path):
        if _SUPPRESS_MARKER in line:
            continue
        key = f"{rel}:{lineno}"
        if key in allowlist:
            continue
        msg = f"  {rel}:{lineno} [{check_name}]: {line.strip()}"
        violations.append(msg)
        inventory.append(
            {
                "path": rel,
                "lineno": lineno,
                "check": check_name,
                "line": line.strip(),
            }
        )

    return violations


def main() -> int:
    existing_dirs = [d for d in _SCAN_DIRS if d.exists()]
    if not existing_dirs:
        print(  # noqa: T201
            "No scannable directories found — skipping LLM hardcode check",
            file=sys.stderr,
        )
        return 0

    allowlist = _load_allowlist()
    inventory: list[dict[str, object]] = []
    all_violations: list[str] = []

    for scan_dir in existing_dirs:
        for ext in _SCAN_EXTENSIONS:
            for path in scan_dir.rglob(f"*{ext}"):
                all_violations.extend(_scan_file(path, allowlist, inventory))

    # Write generated inventory artifact
    inventory_path = Path(".onex_state/llm_hardcode_detector_results.json")
    if inventory_path.parent.exists():
        inventory_path.write_text(
            json.dumps(
                {
                    "schema_version": "llm_hardcode_detector.v1",
                    "total_violations": len(all_violations),
                    "allowlisted_entries": len(allowlist),
                    "results": inventory,
                },
                indent=2,
            )
        )

    if all_violations:
        print(  # noqa: T201
            f"ERROR: {len(all_violations)} hardcoded LLM reference(s) found in runtime paths:"
        )
        for v in all_violations:
            print(v)  # noqa: T201
        print()  # noqa: T201
        print(  # noqa: T201
            "All LLM model IDs, endpoints, and routing decisions must come from the\n"
            "contract-driven model registry (node_model_router). Do not hardcode model\n"
            "IDs or endpoint URLs in runtime code.\n"
            "\n"
            "To suppress a legitimate use:\n"
            "  1. Add  # llm-hardcode-ok: <reason>  to the flagged line, OR\n"
            "  2. Add a structured entry to scripts/validation/llm_hardcode_allowlist.json\n"
            "     with: path, lineno, reason, ticket, owner fields.\n"
            "\n"
            "Ticket: OMN-11944"
        )
        return 1

    dirs_str = ", ".join(str(d) + "/" for d in existing_dirs)
    print(f"OK: no hardcoded LLM references found in {dirs_str}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
