<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Env Parity Skill Orchestration

You are executing the env-parity skill. This prompt defines the complete orchestration
logic for checking local Docker vs onex-dev k8s environment parity.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the env-parity skill to check local Docker vs onex-dev k8s environment parity."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| positional (subcommand) | `check` | `check` or `fix` |
| `--checks <ids>` | `credential,ecr,infisical` | Comma-separated check IDs |
| `--all-checks` | false | Run all 8 checks |
| `--namespace <ns>` | `onex-dev` | k8s namespace |
| `--dry-run` | false | Preview fix without executing |
| `--create-tickets` | false | Create Linear tickets for CRITICAL findings |

Build the check list:
- If `--all-checks`: use `credential,ecr,infisical,schema,services,flags,kafka,packages`
- Otherwise: use `--checks` value (default: `credential,ecr,infisical`)

---

## Step 2: Locate Script <!-- ai-slop-ok: skill-step-heading -->

```bash
SCRIPT="${OMNIBASE_INFRA_DIR:-/Volumes/PRO-G40/Code/omni_home/omnibase_infra}/scripts/compare_environments.py"  # local-path-ok
```

If the script does not exist at that path, emit:
```
ENV_PARITY ERROR: script not found at $SCRIPT
Set OMNIBASE_INFRA_DIR to your omnibase_infra repo path.
```
and stop.

---

## Step 3: Run Script <!-- ai-slop-ok: skill-step-heading -->

```bash
source ~/.omnibase/.env
uv run python "$SCRIPT" \
  --mode <subcommand> \
  --checks <checks> \
  --namespace <namespace> \
  [--dry-run] \
  --json
```

Capture stdout as JSON. If the script exits non-zero or stdout is not valid JSON, emit:
```
ENV_PARITY ERROR: script failed — <stderr preview>
```
and stop.

---

## Step 4: Format Output <!-- ai-slop-ok: skill-step-heading -->

Parse the JSON report. Never pass raw JSON to the user.

### 4.1 Summary Line

```
ENV_PARITY: <CLEAN|DRIFT> — critical=<N> warning=<N> info=<N>
```

- `CLEAN` if `critical_count == 0 AND warning_count == 0`
- `DRIFT` if any findings exist

### 4.2 Findings Table

If findings exist, emit a table:

```
| check_id | severity | title | auto_fixable |
|----------|----------|-------|-------------|
| credential_parity | CRITICAL | Wrong POSTGRES_USER for omniintelligence-credentials | no |
```

### 4.3 Fix Hints for CRITICAL Findings

For each CRITICAL finding, print the `fix_hint` prominently:

```
CRITICAL ACTION REQUIRED:
  [credential_parity] Wrong POSTGRES_USER for omniintelligence-credentials
  Fix: Re-seed /dev/omniintelligence/ in Infisical and force-resync the InfisicalSecret
```

### 4.4 Clean Output

If no findings:
```
✓ All checks clean — no drift detected
```

---

## Step 5: Ticket Creation (only if --create-tickets flag present) <!-- ai-slop-ok: skill-step-heading -->

If `--create-tickets` was NOT provided: skip this step entirely.

If `--create-tickets` was provided:

For each CRITICAL finding:

1. Search for existing tickets with exact prefix match:
   ```
   mcp__linear-server__list_issues(query="[env-parity:<check_id>]", team="Omninode")
   ```
2. If any ticket exists (any state), skip creation for this finding.
3. If no match, create ticket:
   ```
   mcp__linear-server__save_issue(
     title="[env-parity:<check_id>] <finding.title verbatim>",
     team="Omninode",
     priority=1,
     project="Active Sprint",
     description="<finding.detail>\n\nFix hint: <finding.fix_hint>"
   )
   ```

Report created tickets as:
```
Linear tickets created:
  - OMN-XXXX: [env-parity:credential_parity] Wrong POSTGRES_USER for omniintelligence-credentials
```

---

## Step 6: Emit Result Line <!-- ai-slop-ok: skill-step-heading -->

Always end with:

```
ENV_PARITY_RESULT: <CLEAN|DRIFT_DETECTED> findings=<total> critical=<n> warning=<n>
```

---

## Fix Mode Constraint

When `subcommand == "fix"`:

Only `infisical_path_completeness` findings are auto-fixable. The script enforces this via
`AUTO_FIXABLE_CHECKS = {"infisical_path_completeness"}`. Do not attempt to fix other finding types.

If `--dry-run` is set, pass `--dry-run` to the script and report planned actions without executing.
