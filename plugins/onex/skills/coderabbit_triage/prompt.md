<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -->
Apply the persona profile above when generating outputs.

# CodeRabbit Thread Auto-Triage

You are executing the coderabbit-triage skill. This skill auto-triages CodeRabbit
review threads on a PR.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the coderabbit-triage skill to auto-triage CodeRabbit review threads."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Required | Description |
|----------|----------|-------------|
| `repo` | Yes | GitHub repo in owner/name format |
| `pr` | Yes | PR number |
| `--dry-run` | No | Classify only, no replies |

---

## Step 2: Run Triage <!-- ai-slop-ok: skill-step-heading -->

```bash
PYTHONPATH="$ONEX_CC_REPO_PATH/src:$PYTHONPATH" \
  python3 -m omniclaude.hooks.handlers.coderabbit_triage \
    {repo} {pr} {--dry-run if set}
```

---

## Step 3: Report Results <!-- ai-slop-ok: skill-step-heading -->

Parse the JSON output and present a summary:

```
CodeRabbit Auto-Triage Report — {repo}#{pr}

Total CodeRabbit threads: {total}
  Auto-replied (minor/nitpick): {auto_replied}
  Requires fix (critical/major): {requires_fix}
  Already resolved: {already_resolved}
  Errors: {errors}

{if requires_fix > 0}
Threads requiring substantive fixes:
  - Comment #{id}: {severity} — {body_preview}
{/if}
```

---

## Execution Rules

- NEVER auto-reply to Critical or Major threads.
- If `--dry-run` is set, report classification but take no action.
- Always exit 0 — triage failures are advisory, not blocking.
