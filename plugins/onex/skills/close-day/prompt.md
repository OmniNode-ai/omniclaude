# close-day — Authoritative Behavior Specification

> **CDQA-04 / OMN-2981**: Auto-generates a `ModelDayClose` YAML for end-of-day reconciliation.
> **Authoritative**: When `SKILL.md` and `prompt.md` conflict, `prompt.md` wins.

---

## Invocation

```
/close-day [--date YYYY-MM-DD] [--dry-run]
```

- `--date`: Override today's date (default: `date.today().isoformat()`)
- `--dry-run`: Print YAML to stdout only, do not write file even if `ONEX_CC_REPO_PATH` is set

---

## Execution Steps

### Step 1: Determine today's date

```python
TODAY = args.get("--date") or date.today().isoformat()
```

### Step 2: Pull merged PRs across all repos

For each repo in `OMNI_REPOS` (the 10 OmniNode-ai GitHub repos):

```bash
gh pr list --state merged --search "merged:>=${TODAY}" \
  --json number,title,headRefName,baseRefName \
  --repo OmniNode-ai/{repo} \
  --limit 200
```

- On any error (timeout, auth failure, rate limit) → skip repo, do not abort
- Result: `repo_prs: dict[str, list[dict]]`

### Step 3: Pull plan from Linear MCP (optional)

```python
# List active-sprint tickets, extract OMN-XXXX ids
# If Linear MCP unavailable → plan_items = []
plan_items = list_issues(state="In Progress") + list_issues(state="Todo")
```

### Step 4: Build actual_by_repo

Group PRs by repo. For each PR extract the first `OMN-XXXX` reference from title or branch name.

```python
actual_by_repo = build_actual_by_repo(repo_prs)
```

### Step 5: Detect drift

PRs with no `OMN-XXXX` ref in title or branch name → `drift_detected` entry:

```python
drift_detected = detect_drift(repo_prs)
# Each entry: {drift_id, category="scope", evidence, impact, correction_for_tomorrow}
```

### Step 6: Run invariant probes

Use `scripts/check_arch_invariants.py` (CDQA-07 / OMN-2977). **Do not reimplement.**

```bash
# For each repo checked out under omni_home:
uv run python /path/to/check_arch_invariants.py {repo}/src/
# PASS if exit 0, FAIL if exit 1, UNKNOWN if repo not checked out / script missing
```

```python
invariant_statuses = probe_invariants(omni_home, script_path)
# Returns: {"reducers_pure": "pass"|"fail"|"unknown",
#            "orchestrators_no_io": "pass"|"fail"|"unknown"}
# effects_do_io_only is always "unknown" (cannot be probed via AST)
```

### Step 7: Detect golden-path progress

**Read `emitted_at` from artifact JSON** — do NOT use directory creation time or directory name.

```python
# Scan ~/.claude/golden-path/TODAY/ for *.json files
# Count files where artifact.status == "pass" AND artifact.emitted_at starts with TODAY
# real_infra_proof_progressing: "pass" if count > 0, "unknown" if dir missing or no passing files
golden_path_status = detect_golden_path_progress(TODAY)
```

### Step 8: Handle unknowns

Any `"unknown"` status → add actionable correction to `corrections_for_tomorrow`:

```python
if invariant_statuses["reducers_pure"] == "unknown":
    corrections.append("Verify reducers_pure: run check_arch_invariants.py against all repos.")
if invariant_statuses["orchestrators_no_io"] == "unknown":
    corrections.append("Verify orchestrators_no_io: run check_arch_invariants.py against all repos.")
if golden_path_status == "unknown":
    corrections.append(
        "Verify real_infra_proof_progressing: check ~/.claude/golden-path/ for today's artifacts."
    )
```

### Step 9: Assemble and validate

```python
raw = build_day_close(
    today=TODAY,
    plan_items=plan_items,
    actual_by_repo=actual_by_repo,
    drift_detected=drift_detected,
    invariant_statuses=invariant_statuses,
    golden_path_status=golden_path_status,
    corrections_for_tomorrow=corrections,
)

# MUST validate before writing — fails loudly on schema mismatch
from onex_change_control import ModelDayClose
ModelDayClose.model_validate(raw)  # raises ValidationError if invalid

yaml_str = yaml.dump(raw, default_flow_style=False, sort_keys=False)
```

### Step 10: Write or print

```python
onex_cc_repo_path = os.environ.get("ONEX_CC_REPO_PATH")

if not onex_cc_repo_path or dry_run:
    # Print with warning banner — DO NOT pretend the file was written
    print("=" * 72)
    print("WARNING: ONEX_CC_REPO_PATH not set — commit manually")
    print("=" * 72)
    print(yaml_str)
else:
    # Validate path exists
    repo_path = Path(onex_cc_repo_path)
    if not repo_path.exists():
        print(f"ERROR: ONEX_CC_REPO_PATH does not exist: {repo_path}")
        # Fall back to print with banner
        ...
    else:
        out_file = repo_path / "drift" / "day_close" / f"{TODAY}.yaml"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(yaml_str, encoding="utf-8")
        print(f"Written: {out_file}")
```

---

## ModelDayClose Schema Reference

```yaml
schema_version: "1.0.0"       # SemVer, required
date: "YYYY-MM-DD"             # ISO date, required
process_changes_today: []      # list of {change, rationale, replaces}
plan: []                       # list of {requirement_id, summary}
actual_by_repo:                # list of {repo, prs: [{pr, title, state, notes}]}
  - repo: "OmniNode-ai/omniclaude"
    prs:
      - pr: 101
        title: "[OMN-2981] feat(skills): add close-day"
        state: merged
        notes: "Ref: OMN-2981"
drift_detected:                # list of {drift_id, category, evidence, impact, correction_for_tomorrow}
  - drift_id: "DRIFT-0001"
    category: scope
    evidence: "PR #202 in omniclaude — title: 'chore: bump deps'"
    impact: "PR has no Linear ticket reference"
    correction_for_tomorrow: "Add OMN-XXXX ref to PR #202"
invariants_checked:            # required object
  reducers_pure: pass          # pass | fail | unknown
  orchestrators_no_io: pass    # pass | fail | unknown
  effects_do_io_only: unknown  # always unknown (not AST-checkable)
  real_infra_proof_progressing: unknown   # pass | unknown
corrections_for_tomorrow: []   # list of strings
risks: []                      # list of {risk, mitigation}
```

---

## Error Handling

| Condition | Behavior |
|-----------|----------|
| `gh` CLI unavailable | Skip that repo, continue |
| Repo not checked out locally | `status: unknown` for that probe |
| `check_arch_invariants.py` missing | `status: unknown` for both reducer/orchestrator probes |
| Golden-path dir missing | `real_infra_proof_progressing: unknown` |
| Malformed artifact JSON | Skip that file, continue |
| `ModelDayClose.model_validate()` fails | Print error to stderr, exit non-zero |
| `ONEX_CC_REPO_PATH` not set | Print YAML with warning banner, do NOT pretend file was written |
| `ONEX_CC_REPO_PATH` path missing | Print error + fall back to banner-print |

---

## Implementation Module

The core logic is in `close_day.py` (same directory). Import it for tests:

```python
import importlib.util
from pathlib import Path

_SKILL_DIR = Path(__file__).parent
_spec = importlib.util.spec_from_file_location("close_day", _SKILL_DIR / "close_day.py")
_close_day = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_close_day)
```

---

## Constraints

- **Do NOT reimplement** `check_arch_invariants.py` — use the shared script from CDQA-07
- **Do NOT** use directory name or creation time for golden-path detection — use `emitted_at` field
- **Always** call `ModelDayClose.model_validate()` before writing or printing
- **Never** print "file written" if `ONEX_CC_REPO_PATH` is not set
