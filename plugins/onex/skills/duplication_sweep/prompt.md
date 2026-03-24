# Duplication Sweep

You are executing the duplication-sweep skill. Follow these instructions exactly.

## Poly-Agent Fallback Doctrine

**If subagent dispatch fails** (auth error, "Not logged in", tool unavailable, Agent tool blocked,
or any subagent execution error): **STOP immediately. Do NOT fall back to direct Bash, Read, Edit,
Write, or Glob calls.** Report the exact error to the user and wait for direction.

## Argument Parsing

```
/duplication-sweep [--check D1,D2,D3,D4] [--omni-home /path] [--json]
```

```python
args = "$ARGUMENTS".split()
checks = ["D1", "D2", "D3", "D4"]  # default: all checks
omni_home = os.environ.get("OMNI_HOME", "/Volumes/PRO-G40/Code/omni_home")  # local-path-ok
json_mode = "--json" in args

for i, arg in enumerate(args):
    if arg == "--check" and i + 1 < len(args):
        checks = args[i + 1].split(",")
    if arg == "--omni-home" and i + 1 < len(args):
        omni_home = args[i + 1]
```

## Step 1: Announce <!-- ai-slop-ok: skill-step-heading -->

Print: `"Running duplication-sweep: checks={checks} omni_home={omni_home}"`

## Step 2: Execute Checks <!-- ai-slop-ok: skill-step-heading -->

For each enabled check, execute in order and collect results.

### D1: Drizzle Table Duplication

```bash
grep -rn 'pgTable("' "$OMNI_HOME/omnidash/shared/"*-schema.ts 2>/dev/null
```

Parse output: extract table names from `pgTable("TABLE_NAME"` patterns.
Group by table name. Flag any table name appearing in more than one schema file.

- No duplicates found: `check_id=D1, status=PASS, finding_count=0, detail="No duplicate Drizzle tables"`
- Duplicates found: `check_id=D1, status=FAIL, finding_count=N, detail="N duplicate table(s): {names}"`

### D2: Topic Registration Duplication

1. Parse TopicBase enum values from `$OMNI_HOME/omniclaude/src/omniclaude/hooks/topics.py`:
   ```bash
   grep -oP '= "([^"]+)"' "$OMNI_HOME/omniclaude/src/omniclaude/hooks/topics.py"
   ```

2. Parse topic entries from `$OMNI_HOME/onex_change_control/boundaries/kafka_boundaries.yaml`:
   ```bash
   grep "topic_name:" "$OMNI_HOME/onex_change_control/boundaries/kafka_boundaries.yaml"
   ```

3. Cross-reference: for each topic in both sources, check if kafka_boundaries.yaml
   asserts a single `producer_repo` that conflicts with omniclaude's claim.
   TopicBase values in omniclaude are canonical producer claims for omniclaude-owned emit paths.

- No conflicts: `check_id=D2, status=PASS, finding_count=0, detail="No topic registration conflicts"`
- Conflicts found: `check_id=D2, status=FAIL, finding_count=N, detail="N conflicting topic(s)"`
- Files not found: `check_id=D2, status=WARN, finding_count=0, detail="Topic source files not found"`

### D3: Migration Prefix Duplication

```bash
cd "$OMNI_HOME/onex_change_control" && uv run check-migration-conflicts --repos-root "$OMNI_HOME" 2>&1
```

Parse output for lines containing `EXACT_DUPLICATE` or `NAME_CONFLICT`.

- No conflicts: `check_id=D3, status=PASS, finding_count=0, detail="No migration prefix conflicts"`
- Conflicts found: `check_id=D3, status=FAIL, finding_count=N, detail="N migration conflict(s)"`
- Tool not available: `check_id=D3, status=WARN, finding_count=0, detail="check-migration-conflicts not available"`

### D4: Cross-Repo Model Name Collision

```bash
grep -rn "class Model[A-Z]" "$OMNI_HOME"/*/src/ --include="*.py" \
  | grep -v "/tests/" | grep -v "/fixtures/" | grep -v "omnibase_core/"
```

Parse output: extract class names (`class ModelXxx`), group by class name.
Collect (class_name, repo, file_path) for each match.

- For duplicate names appearing in production codepaths outside omnibase_core: `status=FAIL`
- For duplicate names in non-production paths: `status=WARN`
- No duplicates: `check_id=D4, status=PASS, finding_count=0, detail="No cross-repo model name collisions"`

## Step 3: Aggregate Results <!-- ai-slop-ok: skill-step-heading -->

Collect all check results. Determine overall status:
- Any FAIL → overall FAIL (exit 1)
- All PASS/WARN → overall PASS (exit 0)

## Step 4: Output <!-- ai-slop-ok: skill-step-heading -->

Print results in structured format:

```
DUPLICATION SWEEP RESULTS
=========================

D1: {status} — {detail}
D2: {status} — {detail}
D3: {status} — {detail}
D4: {status} — {detail}

Overall: {PASS|FAIL}
```

If `--json` mode, also output machine-readable JSON with findings arrays.

Emit result line:
```
DUPLICATION_SWEEP_RESULT: {overall_status}
```
