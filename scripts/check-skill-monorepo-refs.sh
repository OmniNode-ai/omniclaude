#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
#
# CI lint gate: fail if any skill file contains monorepo-local references.
# OMN-8795 (SD-08) — companion to tests/skills/test_no_monorepo_refs_in_plugin_skills.py
#
# Escape hatch: append "# local-path-ok" to the offending line to suppress.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_ROOT="$REPO_ROOT/plugins/onex/skills"

# Forbidden patterns (regex) and their replacement guidance.
# The path literals below are the patterns we're enforcing, not violations.
PAT_0='\$OMNI_HOME'
MSG_0='Use $ONEX_STATE_DIR or $ONEX_WORKTREES_ROOT instead'
PAT_1='uv run python -m omni'
MSG_1="Use 'onex run <node_name>' instead — see OMN-8770 standalone install"
PAT_2='\/Users\/jonah\/' # local-path-ok: pattern registry — enforcing this literal
MSG_2='Hardcoded user path — use environment variable instead'
PAT_3='\/Volumes\/PRO-G40\/' # local-path-ok: pattern registry — enforcing this literal
MSG_3='Hardcoded volume path — use environment variable instead'

PATTERNS=("$PAT_0" "$PAT_1" "$PAT_2" "$PAT_3")
MESSAGES=("$MSG_0" "$MSG_1" "$MSG_2" "$MSG_3")

ESCAPE_HATCH='# local-path-ok'
FAILED=false

mapfile -t SKILL_FILES < <(find "$SKILLS_ROOT" -name "*.md" -type f | sort)

if [ "${#SKILL_FILES[@]}" -eq 0 ]; then
  echo "No skill .md files found under $SKILLS_ROOT — skipping"
  exit 0
fi

for file in "${SKILL_FILES[@]}"; do
  lineno=0
  while IFS= read -r line; do
    lineno=$((lineno + 1))
    if [[ "$line" == *"$ESCAPE_HATCH"* ]]; then
      continue
    fi
    for i in "${!PATTERNS[@]}"; do
      if echo "$line" | grep -qE "${PATTERNS[$i]}"; then
        rel="${file#"$REPO_ROOT/"}"
        echo "::error file=$rel,line=$lineno::${PATTERNS[$i]} found — ${MESSAGES[$i]}"
        FAILED=true
      fi
    done
  done < "$file"
done

if [ "$FAILED" = "true" ]; then
  echo ""
  echo "Skill monorepo-ref gate FAILED."
  echo "Fix violations or add '# local-path-ok' with a reason to suppress."
  exit 1
fi

echo "Skill monorepo-ref gate PASSED (${#SKILL_FILES[@]} files checked)."
