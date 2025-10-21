#!/usr/bin/env python3
"""
Fix agent YAML configuration files to match expected schema.
Fixes intelligence_integration string → null conversions.
"""

import sys
from pathlib import Path

# Agents that need intelligence_integration → null
INTELLIGENCE_FIX_AGENTS = [
    "agent-testing",
    "agent-ticket-manager",
    "agent-pr-ticket-writer",
    "agent-repository-setup",
    "agent-documentation-architect",
    "agent-security-audit",
    "agent-onex-readme",
    "agent-rag-update",
]

CONFIGS_DIR = Path.home() / ".claude/agents/configs"


def fix_intelligence_integration(agent_name: str) -> bool:
    """Remove intelligence_integration multi-line string, set to null."""
    file_path = CONFIGS_DIR / f"{agent_name}.yaml"

    if not file_path.exists():
        print(f"❌ File not found: {file_path}")
        return False

    print(f"📝 Fixing {agent_name}...")

    try:
        # Read the file
        with open(file_path, "r") as f:
            lines = f.readlines()

        # Find the intelligence_integration line
        intel_line_idx = None
        for i, line in enumerate(lines):
            if line.startswith("intelligence_integration:"):
                intel_line_idx = i
                break

        if intel_line_idx is None:
            print("  ℹ️  No intelligence_integration field found")
            return True

        # Check if it's a multi-line string (|) or a file reference
        if "intelligence_integration: |" in lines[intel_line_idx]:
            # Multi-line string - find where it ends (next top-level key or EOF)
            end_idx = len(lines)
            for i in range(intel_line_idx + 1, len(lines)):
                # Check if line starts with a top-level key (no indentation)
                if (
                    lines[i].strip()
                    and not lines[i].startswith(" ")
                    and not lines[i].startswith("\t")
                ):
                    if ":" in lines[i]:
                        end_idx = i
                        break

            # Replace with null
            new_lines = lines[:intel_line_idx]
            new_lines.append("intelligence_integration: null\n")
            if end_idx < len(lines):
                new_lines.append("\n")
                new_lines.extend(lines[end_idx:])

        elif ".md" in lines[intel_line_idx]:
            # File reference - just replace with null
            new_lines = lines[:]
            new_lines[intel_line_idx] = "intelligence_integration: null\n"

        else:
            print("  ℹ️  intelligence_integration is not a string")
            return True

        # Write back
        with open(file_path, "w") as f:
            f.writelines(new_lines)

        print(f"  ✅ Fixed {agent_name}")
        return True

    except Exception as e:
        print(f"  ❌ Error fixing {agent_name}: {e}")
        return False


def main():
    print("🔧 Fixing agent YAML intelligence_integration fields...\n")

    fixed = 0
    failed = 0

    for agent in INTELLIGENCE_FIX_AGENTS:
        if fix_intelligence_integration(agent):
            fixed += 1
        else:
            failed += 1

    print(f"\n✨ Fixed {fixed}/{len(INTELLIGENCE_FIX_AGENTS)} agents")
    if failed > 0:
        print(f"⚠️  {failed} agents failed to fix")
        sys.exit(1)

    print("\n✅ All intelligence_integration fields fixed!")


if __name__ == "__main__":
    main()
