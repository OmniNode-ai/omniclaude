<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only -- do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Env Parity Skill Orchestration

You are executing the env-parity skill. This prompt defines the complete orchestration
logic for multi-machine environment conformance checking backed by the machine registry.

---

## Step 0: Announce <!-- ai-slop-ok: skill-step-heading -->

Say: "I'm using the env-parity skill to check multi-machine environment conformance against the machine registry."

---

## Step 1: Parse Arguments <!-- ai-slop-ok: skill-step-heading -->

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| positional (subcommand) | `check` | `check` or `fix` |
| `--machine-id <id>` | (all machines) | Target a specific machine |
| `--fix-remote` | false | Allow auto-fix on remote machines (requires `fix` subcommand) |
| `--dry-run` | false | Preview fix without executing |
| `--create-tickets` | false | Create Linear tickets for FAIL findings |

---

## Step 2: Locate Registry and Run Check <!-- ai-slop-ok: skill-step-heading -->

```bash
REGISTRY="${OMNIBASE_INFRA_DIR:-/Volumes/PRO-G40/Code/omni_home/omnibase_infra}/config/machines.yaml"  # local-path-ok
```

If the registry does not exist at that path, emit:
```
ENV_PARITY ERROR: machine registry not found at $REGISTRY
Set OMNIBASE_INFRA_DIR to your omnibase_infra repo path.
```
and stop.

Build the command:
```bash
# Check mode (default):
uv run onex env check --registry "$REGISTRY" [--machine-id <id>]

# Fix mode:
uv run onex env check --registry "$REGISTRY" --fix [--fix-remote] [--machine-id <id>]
```

If `--dry-run` is set in fix mode, pass `--dry-run` to the command and report planned actions without executing.

Capture output. If the command exits non-zero, emit:
```
ENV_PARITY ERROR: onex env check failed — <stderr preview>
```
and stop.

---

## Step 3: Format Output <!-- ai-slop-ok: skill-step-heading -->

Parse the check results. Output is grouped by machine, then by check category, then by individual check.

### 3.1 Summary Line

```
ENV_PARITY: <CLEAN|DRIFT> — pass=<N> warn=<N> fail=<N> unreachable=<N>
```

- `CLEAN` if all checks PASS (no FAIL, no WARN)
- `DRIFT` if any FAIL or WARN exists

### 3.2 Per-Machine Results

For each machine, emit a grouped table:

```
## <machine_id> (<role>) — <ip>

| check_id | category | status | detail | fixable |
|----------|----------|--------|--------|---------|
| config.settings_exists | config | PASS | settings.json found | no |
| config.settings_paths | config | FAIL | OMNI_HOME mismatch | yes |
| env.no_duplicates | env | WARN | 3 duplicate keys | yes |
```

### 3.3 Unreachable Machines

If a machine is unreachable via SSH, report it as `UNREACHABLE` — not as a check failure:

```
## infra-server (infra) — 192.168.86.201

STATUS: UNREACHABLE — SSH connection timed out
All checks skipped for this machine.
```

### 3.4 Fix Hints for FAIL Findings

For each FAIL finding that is auto-fixable, print:

```
FIXABLE:
  [config.settings_paths] OMNI_HOME mismatch — run: /env_parity fix
  [env.no_duplicates] 3 duplicate keys — run: /env_parity fix
```

For each FAIL finding that is NOT auto-fixable, print:

```
MANUAL ACTION REQUIRED:
  [config.settings_exists] settings.json missing — run: onex env bootstrap --machine-id <id>
  [secrets.infisical_identity] Auth failed — run: onex env bootstrap --machine-id <id>
```

### 3.5 Clean Output

If all machines pass all checks:
```
All machines conformant — no drift detected
```

---

## Step 4: Ticket Creation (only if --create-tickets flag present) <!-- ai-slop-ok: skill-step-heading -->

If `--create-tickets` was NOT provided: skip this step entirely.

If `--create-tickets` was provided:

For each FAIL finding:

1. Search for existing tickets with exact prefix match:
   ```
   mcp__linear-server__list_issues(query="[env-parity:<check_id>]", team="Omninode")
   ```
2. If any ticket exists (any state), skip creation for this finding.
3. If no match, create ticket:
   ```
   mcp__linear-server__save_issue(
     title="[env-parity:<check_id>] <machine_id>: <finding.detail>",
     team="Omninode",
     priority=1,
     project="Active Sprint",
     description="Machine: <machine_id> (<role>)\nCheck: <check_id>\nDetail: <finding.detail>\n\nFix: <fix_hint or 'manual intervention required'>"
   )
   ```

Report created tickets as:
```
Linear tickets created:
  - OMN-XXXX: [env-parity:config.settings_paths] m2-ultra: OMNI_HOME mismatch
```

---

## Step 5: Emit Result Line <!-- ai-slop-ok: skill-step-heading -->

Always end with:

```
ENV_PARITY_RESULT: <CLEAN|DRIFT_DETECTED> machines=<total> pass=<n> warn=<n> fail=<n> unreachable=<n>
```

---

## Fix Mode Constraints

When `subcommand == "fix"`:

Auto-fixable checks: `config.settings_paths`, `config.no_hooks_block`, `env.no_duplicates`, `topology.plugin_symlink`.
Report-only checks: `config.settings_exists`, `secrets.infisical_identity`.

- `--fix` applies only to the local machine by default.
- `--fix-remote` is required to fix remote machines (explicit opt-in).
- Every fix creates a `.bak` backup first.
- Duplicate key resolution: last occurrence wins (matches bash `source` behavior).

If `--dry-run` is set, report planned actions without executing.
