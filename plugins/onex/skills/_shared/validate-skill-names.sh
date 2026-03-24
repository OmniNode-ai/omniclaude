#!/usr/bin/env bash
# validate-skill-names.sh — CI enforcement for skill naming conventions
#
# Rules enforced:
#   1. FAIL if any SKILL.md `name:` field starts with a namespace prefix (e.g., "onex:")
#      (name: fields use bare slugs — the plugin system auto-prefixes from the directory)
#   2. FAIL if any Skill() call uses a bare slug instead of "onex:<slug>"
#      (lines containing "subagent_type" are excluded — onex:polymorphic-agent is allowed as-is)
#   3. FAIL if any shell script contains `exec claude --skill <bare-slug>` instead of `exec claude --skill onex:<slug>`
#   4. WARN if any SKILL.md/prompt.md contains /skill-name cross-references outside fenced blocks
#      (should use onex: prefix or Skill() calls instead of slash-prefix dispatch)
#
# Exemptions:
#   - subagent_type="onex:polymorphic-agent" is ALLOWED (agent namespace, not skill)
#   - SKILL.md name: fields use bare slugs (Rule 1 enforces this)
#   - This file itself and other validation scripts are excluded
#
# Note: commands/ directory has been removed — all slash commands live in skills/.
#
# Exit codes:
#   0 — All checks pass
#   1 — One or more violations found

set -euo pipefail

SKILLS_DIR="${1:-plugins/onex/skills}"

# Canonicalize to repo root if running from a subdirectory
if [[ ! -d "$SKILLS_DIR" ]]; then
    REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo ".")"
    SKILLS_DIR="${REPO_ROOT}/plugins/onex/skills"
fi

VIOLATIONS=0

fail() {
    echo "FAIL: $*" >&2
    VIOLATIONS=$((VIOLATIONS + 1))
}

# --- Rule 1: SKILL.md name: fields must use bare slugs (no namespace prefix) ---
# The plugin system auto-prefixes from the directory name (onex/).
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

# --- Rule 2: Skill() calls must use onex: prefix ---
# Find Skill() calls that use bare slugs (no namespace prefix).
# Exclude: subagent_type lines, this validation script itself.
echo "Checking Skill() references for missing onex: prefix..."

# Match Skill(skill="<bare-slug>" or Skill("<bare-slug>" — i.e., no colon in the slug
# We look for Skill( followed by optional skill= then a quoted string without a colon before the closing quote
bare_skill_violations=$(grep -rn --include="*.md" \
    -E 'Skill\((skill=)?["\x27][a-z][a-z0-9_-]+["\x27]' \
    "$SKILLS_DIR" 2>/dev/null \
    | grep -v "subagent_type" \
    | grep -v "validate-skill-names" \
    | grep -v 'onex:' \
    || true)

if [[ -n "$bare_skill_violations" ]]; then
    while IFS= read -r line; do
        fail "Skill() missing onex: prefix: $line"
    done <<< "$bare_skill_violations"
fi

# --- Rule 3: exec claude --skill must use onex: prefix ---
echo "Checking 'exec claude --skill' for missing onex: prefix..."
bare_claude_violations=$(grep -rn --include="*.md" --include="*.sh" \
    -E 'exec claude --skill [a-z][a-z0-9_-]+' \
    "$SKILLS_DIR" 2>/dev/null \
    | grep -v 'onex:' \
    | grep -v 'validate-skill-names' \
    | grep -v '^.*:#' \
    || true)

if [[ -n "$bare_claude_violations" ]]; then
    while IFS= read -r line; do
        fail "exec claude --skill missing onex: prefix: $line"
    done <<< "$bare_claude_violations"
fi

# --- Rule 4: Warn on slash-prefix cross-skill references outside fenced blocks ---
# Catches /skill-name references that should use onex: prefix or Skill() calls.
# WARNING-ONLY: does not increment VIOLATIONS or change exit code.
# Promote to FAIL after slash-prefix fixes are merged and validated for one sprint
WARNINGS=0

warn() {
    echo "WARN: $*" >&2
    WARNINGS=$((WARNINGS + 1))
}

echo "Checking for slash-prefix cross-skill references..."

# Derives slugs from directory names (not name: frontmatter). This matches
# plugin system behavior where skill names are derived from directories.
known_slugs=()
while IFS= read -r dir; do
    dirname=$(basename "$dir")
    slug=$(echo "$dirname" | tr '_' '-')
    known_slugs+=("$slug")
done < <(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '_*' 2>/dev/null | sort)

if [[ ${#known_slugs[@]} -gt 0 ]]; then
    # Build ERE alternation pattern for single grep pass (avoids O(skills * files) loop)
    slug_pattern=$(IFS='|'; echo "${known_slugs[*]}")

    while IFS= read -r filepath; do
        # Determine self-slug from parent directory name
        parent_dir=$(basename "$(dirname "$filepath")")
        self_slug=$(echo "$parent_dir" | tr '_' '-')

        # Strip fenced code blocks, then emit line numbers with content
        # Note: handles indented fences but not nested fences (markdown parser out of scope for bash validator)
        stripped=$(awk '/^[[:space:]]*```/{skip=!skip; next} !skip{print NR": "$0}' "$filepath")

        if [[ -z "$stripped" ]]; then
            continue
        fi

        # Find slash-prefix references to known skills, excluding:
        #   - self-references (word-boundary match)
        #   - Usage: lines
        #   - Lines starting with # or > (headings/blockquotes)
        matches=$(echo "$stripped" \
            | grep -E "/(${slug_pattern})([^a-zA-Z0-9_-]|$)" \
            | grep -Ev "/${self_slug}([^a-zA-Z0-9_-]|$)" \
            | grep -Ev '^[0-9]+:[[:space:]]*Usage:' \
            | grep -Ev '^[0-9]+:[[:space:]]*#' \
            | grep -Ev '^[0-9]+:[[:space:]]*>' \
            || true)

        if [[ -n "$matches" ]]; then
            while IFS= read -r match; do
                warn "$filepath:$match — use onex: prefix or Skill(skill=\"onex:...\") instead of /slash-prefix"
            done <<< "$matches"
        fi
    done < <(find "$SKILLS_DIR" -maxdepth 2 \( -name "SKILL.md" -o -name "prompt.md" \) 2>/dev/null | sort)
fi

# --- Summary ---
echo ""
if [[ $WARNINGS -gt 0 ]]; then
    echo "validate-skill-names: $WARNINGS warning(s) — slash-prefix cross-references found (non-blocking)."
fi
if [[ $VIOLATIONS -eq 0 ]]; then
    echo "validate-skill-names: All checks passed."
    exit 0
else
    echo "validate-skill-names: $VIOLATIONS violation(s) found." >&2
    echo "" >&2
    echo "Fix: Add onex: prefix to Skill() calls and exec claude --skill invocations." >&2
    echo "     Examples: Skill(skill=\"onex:ticket_work\"), exec claude --skill onex:ci_watch" >&2
    echo "     Note: SKILL.md name: fields use bare slugs (plugin auto-prefixes)." >&2
    echo "     Note: subagent_type=\"onex:polymorphic-agent\" is ALLOWED (agent, not skill)." >&2
    exit 1
fi
