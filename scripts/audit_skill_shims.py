#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Audit all deterministic skill shims in plugins/onex/skills/."""

import re
from pathlib import Path

import yaml

SKILLS_ROOT = Path(__file__).parent.parent / "plugins" / "onex" / "skills"
OMNI_HOME = Path(
    __import__("os").environ.get("OMNI_HOME", str(Path.home() / "Code" / "omni_home"))
)
OUTPUT_PATH = OMNI_HOME / ".onex_state" / "skill_shim_audit.yaml"

SKIP_DIRS = {"_bin", "_golden_path_validate", "_lib", "_shared"}

LLM_SDK_PATTERNS = [
    r"from anthropic import",
    r"import anthropic",
    r"from openai import",
    r"import openai",
    r"mcp__anthropic",
    r"mcp__openai",
    r"anthropic\.Anthropic",
    r"openai\.OpenAI",
]

ONEX_RUN_PATTERN = r"onex run\b"
AGENT_CALL_PATTERN = r"\bAgent\s*\("
SKILL_CALL_PATTERN = r'Skill\s*\(\s*skill\s*=\s*["\']'
HTTP_PATTERN = r"https?://[^\s]+/api/"
SUBPROCESS_PATTERN = r"\bsubprocess\b|\bos\.system\b"

# Inline orchestration: if/else branching, conditional dispatch in prose
BRANCH_PATTERNS = [
    r"^\s*[-*]\s+if\b",
    r"^\s*[-*]\s+when\b",
    r"^\s*[-*]\s+else\b",
    r"^\s*(if|when|else if|otherwise)\b.*then\b",
    r"^>\s*(if|when|otherwise)\b",
]


def count_prose_lines(text: str) -> int:
    """Count non-frontmatter, non-code-fence lines."""
    lines = text.split("\n")
    in_frontmatter = False
    in_code_fence = False
    prose_count = 0
    frontmatter_done = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if i == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
                frontmatter_done = True
            continue

        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue

        if stripped:
            prose_count += 1

    return prose_count


def detect_invocation_pattern(text: str) -> str:
    patterns = []
    if re.search(ONEX_RUN_PATTERN, text):
        patterns.append("onex_run")
    if re.search(AGENT_CALL_PATTERN, text):
        patterns.append("Agent()")
    if re.search(SKILL_CALL_PATTERN, text):
        patterns.append("Skill()")
    if re.search(HTTP_PATTERN, text):
        patterns.append("http_api")
    if re.search(SUBPROCESS_PATTERN, text):
        patterns.append("subprocess")
    if not patterns:
        patterns.append("prose_only")
    return "|".join(patterns)


def detect_llm_sdk_imports(text: str) -> list[str]:
    found = []
    for pattern in LLM_SDK_PATTERNS:
        if re.search(pattern, text):
            found.append(pattern.replace("\\b", "").replace("\\s*", " ").strip())
    return list(set(found))


def count_inline_orchestration_flags(text: str) -> int:
    count = 0
    for line in text.split("\n"):
        for pattern in BRANCH_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                count += 1
                break
    return count


def audit_skill(skill_dir: Path) -> dict:
    skill_name = skill_dir.name
    all_text = ""

    for fname in ["SKILL.md", "prompt.md", "README.md"]:
        fpath = skill_dir / fname
        if fpath.exists():
            all_text += fpath.read_text(encoding="utf-8", errors="replace") + "\n"

    prose_lines = count_prose_lines(all_text)
    invocation = detect_invocation_pattern(all_text)
    llm_imports = detect_llm_sdk_imports(all_text)
    inline_flags = count_inline_orchestration_flags(all_text)

    classification = "deterministic" if prose_lines <= 50 else "prose-heavy"

    return {
        "name": skill_name,
        "path": str(skill_dir.relative_to(SKILLS_ROOT.parent.parent.parent)),
        "invocation_pattern": invocation,
        "prose_fallback_lines": prose_lines,
        "llm_sdk_imports": llm_imports,
        "inline_orchestration_flags": inline_flags,
        "classification": classification,
    }


def main() -> None:
    skill_dirs = sorted(
        d
        for d in SKILLS_ROOT.iterdir()
        if d.is_dir() and d.name not in SKIP_DIRS and not d.name.startswith("_")
    )

    skills = [audit_skill(d) for d in skill_dirs]

    deterministic = sum(1 for s in skills if s["classification"] == "deterministic")
    prose_heavy = sum(1 for s in skills if s["classification"] == "prose-heavy")

    audit = {
        "audit_date": "2026-04-14",
        "total_skills": len(skills),
        "deterministic_count": deterministic,
        "prose_heavy_count": prose_heavy,
        "skills": skills,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        yaml.dump(
            audit, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )

    print(f"Wrote {OUTPUT_PATH}")
    print(
        f"Total: {len(skills)}, deterministic: {deterministic}, prose-heavy: {prose_heavy}"
    )


if __name__ == "__main__":
    main()
