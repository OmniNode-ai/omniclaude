#!/usr/bin/env bash
# validate-skill-names.sh — CI enforcement for skill naming conventions
#
# Rules enforced:
#   1. FAIL if any SKILL.md `name:` field starts with a namespace prefix (e.g., "onex:")
#   2. FAIL if any prompt.md, SKILL.md, or commands/*.md contains Skill(skill="onex:...
#      (lines containing "subagent_type" are excluded — onex:polymorphic-agent is allowed)
#   3. FAIL if any shell script contains `exec claude --skill namespace:slug`
#
# Exemptions:
#   - subagent_type="onex:polymorphic-agent" is ALLOWED (agent namespace, not skill)
#
# Exit codes:
#   0 — All checks pass
#   1 — One or more violations found

set -euo pipefail

SKILLS_DIR="${1:-plugins/onex/skills}"
COMMANDS_DIR="${2:-plugins/onex/commands}"

# Canonicalize to repo root if running from a subdirectory
if [[ ! -d "$SKILLS_DIR" ]]; then
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"
    SKILLS_DIR="${REPO_ROOT}/plugins/onex/skills"
    COMMANDS_DIR="${REPO_ROOT}/plugins/onex/commands"
fi

VIOLATIONS=0

fail() {
    echo "FAIL: $*" >&2
    VIOLATIONS=$((VIOLATIONS + 1))
}

# --- Rule 1: SKILL.md name: fields must use bare slugs (no namespace prefix) ---
# A namespace prefix is any identifier followed by a colon, e.g., "onex:ticket-work".
# A bare slug like "ticket-work" or "action-logging" contains hyphens but no colon.
# Only check frontmatter name: fields (first 20 lines of each SKILL.md).
echo "Checking SKILL.md name: fields for namespace prefixes..."
while IFS= read -r filepath; do
    name_val=$(head -20 "$filepath" | grep -E '^name:[[:space:]]' | head -1 \
               | sed 's/^name:[[:space:]]*//' | tr -d '"'"'" | xargs 2>/dev/null || true)
    if [[ -z "$name_val" ]]; then
        continue
    fi
    # A namespace prefix means the value contains a colon
    if [[ "$name_val" == *:* ]]; then
        fail "$filepath: name: field uses namespace prefix '$name_val' (expected bare slug)"
    fi
done < <(find "$SKILLS_DIR" -maxdepth 2 -name "SKILL.md" 2>/dev/null | sort || true)

# --- Rule 2: Skill(skill="namespace:slug") must use bare slugs ---
# Use grep to find all matches at once, then filter out subagent_type lines.
echo "Checking Skill(skill=...) references for namespace prefixes..."

# Pattern: Skill( with skill= keyword arg using a namespace prefix
# Also matches positional: Skill("namespace:slug" or Skill('namespace:slug'
SKILL_PATTERN='Skill\((skill=)?["\'"'"'][A-Za-z][A-Za-z0-9_-]*:[A-Za-z]'

# Find all matches, filter out subagent_type lines (those use onex:polymorphic-agent legitimately)
skill_violations=$(grep -rn --include="*.md" -E "$SKILL_PATTERN" \
    "$SKILLS_DIR" "$COMMANDS_DIR" 2>/dev/null \
    | grep -v "subagent_type" \
    || true)

if [[ -n "$skill_violations" ]]; then
    while IFS= read -r line; do
        fail "Skill() uses namespace prefix: $line"
    done <<< "$skill_violations"
fi

# --- Rule 3: exec claude --skill must use bare slugs ---
echo "Checking 'exec claude --skill' for namespace prefixes..."
claude_skill_violations=$(grep -rn --include="*.md" --include="*.sh" \
    -E 'exec claude --skill [A-Za-z][A-Za-z0-9_-]*:' \
    "$SKILLS_DIR" "$COMMANDS_DIR" 2>/dev/null \
    | grep -v '^.*:#' \
    || true)  # Exclude comment lines (lines where content after filename:lineno: starts with #)

if [[ -n "$claude_skill_violations" ]]; then
    while IFS= read -r line; do
        fail "exec claude --skill uses namespace prefix: $line"
    done <<< "$claude_skill_violations"
fi

# --- Summary ---
echo ""
if [[ $VIOLATIONS -eq 0 ]]; then
    echo "validate-skill-names: All checks passed."
    exit 0
else
    echo "validate-skill-names: $VIOLATIONS violation(s) found." >&2
    echo "" >&2
    echo "Fix: Remove namespace prefixes from Skill() calls and SKILL.md name: fields." >&2
    echo "     Bare slug examples: 'ticket-work', 'local-review', 'ci-fix-pipeline'" >&2
    echo "     Note: subagent_type=\"onex:polymorphic-agent\" is ALLOWED (agent, not skill)." >&2
    exit 1
fi
