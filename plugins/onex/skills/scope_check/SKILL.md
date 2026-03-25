---
description: Extract and confirm scope boundaries from a plan or task before execution begins
mode: full
version: 1.0.0
level: intermediate
debug: false
category: workflow
tags:
  - scope
  - planning
  - enforcement
  - safety
author: OmniClaude Team
args:
  - name: plan-file
    description: "Path to plan markdown file or task description"
    required: true
  - name: --confirm
    description: "Skip confirmation prompt and proceed immediately"
    required: false
  - name: --output
    description: "Path to write scope manifest (default: ~/.claude/scope-manifest.json)"
    required: false
---

# Scope Check

Extract declared scope from a plan or task description and produce a scope manifest
that the scope gate hook can reference for enforcement.

**Usage:** `/onex:scope_check <plan-file> [--confirm] [--output <path>]`

**Announce at start:** "Extracting scope boundaries from: {plan-file}"

---

## Step 1: Read the Plan or Task <!-- ai-slop-ok: skill step structure -->

Read the file at the provided path. If the file does not exist, report an error and stop.

---

## Step 2: Extract Scope <!-- ai-slop-ok: skill step structure -->

Parse the plan content and extract:

1. **Files in scope**: Any file paths mentioned explicitly (e.g., `omniclaude/CLAUDE.md`,
   `plugins/onex/hooks/scope_gate.sh`)
2. **Directories in scope**: Any directory paths or glob patterns (e.g., `plugins/onex/hooks/`,
   `src/omniclaude/`)
3. **Repos in scope**: Any repository names mentioned (e.g., `omniclaude`, `omnibase_core`)
4. **Systems in scope**: Any subsystems referenced (e.g., "hooks", "skills", "CLAUDE.md",
   "CI pipeline")

**Extraction heuristics:**
- Look for "Files affected" / "Files Affected" sections
- Look for file paths in backticks (`` `path/to/file` ``)
- Look for "Scope:" fields in structured task descriptions
- Look for repo names from the known registry (omniclaude, omnibase_core, omnibase_infra,
  omnibase_spi, omniintelligence, omnimemory, omnidash, omninode_infra, omniweb,
  onex_change_control)

---

## Step 3: Present Scope <!-- ai-slop-ok: skill step structure -->

Display the extracted scope clearly:

```
=== SCOPE MANIFEST ===

IN SCOPE:
  Repos: omniclaude
  Files:
    - plugins/onex/hooks/scope_gate.sh
    - plugins/onex/hooks/hooks.json
    - CLAUDE.md
  Directories:
    - plugins/onex/hooks/
  Systems:
    - hooks
    - CLAUDE.md

OUT OF SCOPE: Everything not listed above.

Adjacent files (may need modification as support):
  - plugins/onex/hooks/scripts/common.sh
  - tests/unit/test_scope_gate.py
```

---

## Step 4: Confirm or Adjust <!-- ai-slop-ok: skill step structure -->

If `--confirm` was NOT passed:
- Ask the user: "Does this scope look correct? Reply 'yes' to proceed, or describe adjustments."
- If the user provides adjustments, update the manifest accordingly.

If `--confirm` was passed:
- Skip confirmation and proceed to Step 5.

---

## Step 5: Write Scope Manifest <!-- ai-slop-ok: skill step structure -->

Write the scope manifest to the output path (default: `~/.claude/scope-manifest.json`).

The manifest format:

```json
{
  "version": "1.0.0",
  "created_at": "2026-03-25T16:00:00Z",
  "plan_file": "docs/plans/2026-03-25-insights-plan.md",
  "repos": ["omniclaude"],
  "files": [
    "plugins/onex/hooks/scope_gate.sh",
    "plugins/onex/hooks/hooks.json",
    "CLAUDE.md"
  ],
  "directories": [
    "plugins/onex/hooks/"
  ],
  "systems": [
    "hooks",
    "CLAUDE.md"
  ],
  "adjacent_files": [
    "plugins/onex/hooks/scripts/common.sh",
    "tests/unit/test_scope_gate.py"
  ]
}
```

Report: "Scope manifest written to {output_path}. The scope gate hook will reference this
manifest for enforcement during this session."

---

## Step 6: Return Result <!-- ai-slop-ok: skill step structure -->

Output a structured summary:

```
Scope check complete.
  - {N} files in scope
  - {N} directories in scope
  - {N} repos in scope
  - {N} systems in scope
  - Manifest: {output_path}
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Plan file not found | Report path, stop |
| No scope extractable | Warn that no explicit scope was found; ask user to provide one manually |
| Manifest write fails | Fall back to printing manifest to stdout |
