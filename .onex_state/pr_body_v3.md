## Phase 4a — migrate 24 dispatch shims to the single-command `onex skill` receipt pattern

Part of the Skill Output Suppression epic (Quiet Receipts With Durable Capture). Plan: `docs/plans/2026-06-12-skill-output-suppression-plan.md` (Phase 4 item 1).

A dispatch skill IS one CLI call (user directive 2026-06-12). All 23 remaining dispatch-only shims (delegate landed in Phase 2b) now dispatch via ONE command — `uv run onex skill <name> [args]` — printing exactly one `ModelSkillResult[T]`. The `onex skill` subcommand + declarative `skill_mapping.yaml` (omnibase_infra **PR #1968**, merged to dev) and all 23 node-side typed result models already landed; **this PR carries the omniclaude markdown migration only.**

### What changed
- **SKILL.md**: declares `skill_kind: dispatch` (delegation-enforcer exemption); body trimmed to the proven delegate shape — one command + result presentation.
- **prompt.md**: procedure bodies **DELETED** — frontmatter-free, ~30 lines: the single `onex skill` command + how to present the typed `ModelSkillResult`. No bare `onex run/node/run-node`, no `cat workflow_result.json`, no "surface verbatim".
- **Skill-local executable logic REMOVED** (markdown only — deliverable 5 / F12): `merge_sweep/_lib/run.py` + `run.sh`, `hostile_reviewer/_lib/aggregate_reviews.py`, `pr_review/*` sub-skill shell scripts, `delegate/_lib`.
- **Tests**: new parametrized contract suite `tests/unit/skills/test_dispatch_skill_receipt_contract.py` validates all 24 skills against the new single-command receipt invariants (the same checks the Phase 4b validator will gate). Stale per-skill shim-contract tests encoding the deleted `onex run-node` procedure-body pattern removed (`test_compliance_sweep_shim`, `test_platform_readiness_shim`, `test_merge_sweep_shim`, `test_s21_shims`, hostile_reviewer prose tests, `aislop_sweep` + `data_flow_sweep` content tests) plus tests of removed code (merge_sweep run.sh/_lib round-trip + ingress, hostile_reviewer aggregator). `conftest` sys.path for the removed `_lib` dropped.

**omnimarket: no change** — all 23 result-model FQNs in `skill_mapping.yaml` verified present and importable on origin/dev (the infra PR was built against them).

### dod_evidence
- `uv run pytest tests/unit/skills/test_dispatch_skill_receipt_contract.py -q` → **120 passed**
- `uv run pytest tests/unit/skills/ tests/unit/hooks/ -q` → **2650 passed, 1 skipped**
- `uv run mypy src/omniclaude/` → **Success: no issues found in 711 source files**
- `uv run ruff format src/ tests/ && uv run ruff check src/ tests/` → all checks passed
- `pre-commit run --all-files` → **51 hooks passed** (incl skill-mcp-ref-lint, aislop, skill hygiene, instructional-skill enforcement, imperative-pattern guard)

Evidence-Source: 867635d18fe6e7fc53ba7185ad1fc807377b2be8
Evidence-Ticket: OMN-13097

Paired OCC receipt PR: OmniNode-ai/onex_change_control#2597
