# CI/CD Standards

## Pipeline Overview

Single consolidated workflow: `.github/workflows/ci.yml` (OMN-2228).

Replaces the previous `ci-cd.yml` + `enhanced-ci.yml` split. All jobs are defined in one
file with three gate aggregators that branch protection references by name.

Triggers: `push` and `pull_request` on `main` and `develop`; `workflow_dispatch`.

---

## Jobs

### Quality Gate Jobs

These jobs must pass for the **Quality Gate** aggregator to succeed.

| Job ID | Display Name | What it does |
|--------|-------------|--------------|
| `quality` | Code Quality | `ruff format --check`, `ruff check`, `mypy` (non-blocking for now — reports errors but does not fail CI) |
| `pyright` | Pyright Type Checking | `pyright src/omniclaude` — strict type checking; timeout 10 minutes |
| `check-handshake` | Architecture Handshake | Checks out `omnibase_core` and runs `check-handshake.sh` to verify the architecture handshake is current; skipped on forks |
| `enum-governance` | Enum Governance | `scripts/validation/validate_enum_governance.py` — ONEX enum casing, literal-vs-enum rules, duplicate detection |
| `exports-validation` | Exports Validation | `scripts/validation/validate_exports.py` — `__all__` exports match actual definitions |
| `cross-repo-validation` | Kafka Import Guard | `omnibase_core.validation.cross_repo --policy .cross-repo-policy.yaml` — enforces ARCH-002 (no direct Kafka imports); timeout 5 minutes |
| `migration-freeze` | Migration Freeze | `scripts/check_migration_freeze.sh --ci` — blocks new migrations when `.migration_freeze` exists; bypassable with `db-split-bypass` PR label |
| `onex-validation` | ONEX Compliance | Validates ONEX naming conventions (`Node<Name><Type>`), contract usage (`ModelContract`), and method signatures (`execute_effect` etc.) for all `node_*.py` files |

### Security Gate Jobs

These jobs must pass for the **Security Gate** aggregator to succeed.

| Job ID | Display Name | What it does |
|--------|-------------|--------------|
| `security-python` | Python Security Scan | Bandit at medium confidence + medium severity; uploads JSON report as artifact; text output determines pass/fail |
| `detect-secrets` | Secret Detection | `detect-secrets scan --baseline .secrets.baseline`; fails if new secrets are found that are not in the baseline |

### Tests Gate Jobs

These jobs must pass for the **Tests Gate** aggregator to succeed.

| Job ID | Display Name | What it does |
|--------|-------------|--------------|
| `test` | Tests (Split N/5) | `pytest tests/` with 5-way parallel matrix split (`pytest-split`); PostgreSQL 16 + Redis 7 service containers; excludes `integration` marked tests; produces per-shard coverage files |
| `hooks-tests` | Hooks System Tests | `pytest tests/hooks/` — hook scripts and handler module tests; PostgreSQL 16 service container; skips gracefully if `tests/hooks/` is empty |
| `agent-framework-tests` | Agent Framework Tests | `pytest tests/test_enhanced_router.py tests/test_quality_gates.py tests/test_performance_thresholds.py` — skips gracefully if files do not exist; timeout 10 minutes |
| `database-validation` | Database Schema Validation | Runs `scripts/init-db.sh` and validates that `schema_migrations`, `claude_session_snapshots`, `claude_session_prompts`, and `claude_session_tools` tables and their indexes exist |

### Downstream Jobs

These jobs run after the gates pass. They are not part of branch protection.

| Job ID | Display Name | Trigger | What it does |
|--------|-------------|---------|--------------|
| `merge-coverage` | Merge Test Coverage | After `test` succeeds | Downloads all 5 coverage shards, combines with `coverage combine`, generates `coverage.xml`, uploads to Codecov |
| `build` | Build Docker Image | After all three gates pass | `docker/build-push-action` with `./deployment/Dockerfile`; runs Trivy vulnerability scanner (CRITICAL + HIGH); pushes to `ghcr.io` on non-PR runs; timeout 20 minutes |
| `deploy-staging` | Deploy to Staging | After `build`; `develop` branch push only | Deploys to staging environment |
| `deploy-production` | Deploy to Production | After `build`; `main` branch push only | Deploys to production environment |

---

## Gate Aggregators

Three gate aggregator jobs per CI/CD Standards v2 (`required-checks.yaml`):

| Aggregator Job ID | Display Name | Aggregates |
|------------------|-------------|-----------|
| `quality-gate` | Quality Gate | `quality`, `pyright`, `check-handshake`, `enum-governance`, `exports-validation`, `cross-repo-validation`, `migration-freeze`, `onex-validation` |
| `tests-gate` | Tests Gate | `test`, `hooks-tests`, `agent-framework-tests`, `database-validation` |
| `security-gate` | Security Gate | `security-python`, `detect-secrets` |

Aggregators use `if: always()` so they report failure even when upstream jobs are skipped.
A result of `skipped` is treated as passing (e.g., `check-handshake` skips on fork PRs).

### API Stability Invariant

**Gate display names are API-stable.** Branch protection references these exact strings:
- `"Quality Gate"`
- `"Tests Gate"`
- `"Security Gate"`

**Do NOT rename these jobs** without following the Branch Protection Migration Safety procedure.
Renaming a gate aggregator while branch protection still references the old name will make
all PRs unmergeable.

### Branch Protection Migration Safety Procedure

When renaming a gate aggregator:

1. Add the new aggregator job name alongside the old one (both exist temporarily).
2. Update `required-checks.yaml` to require both names.
3. Merge and confirm the new name appears in GitHub branch protection settings.
4. Update `required-checks.yaml` to remove the old name.
5. Remove the old aggregator job.
6. Merge.

Never rename and remove in the same PR.

---

## Branch Protection

Required status checks (configured in GitHub repository settings):
- `Quality Gate`
- `Tests Gate`
- `Security Gate`

All three must pass before merging to `main` or `develop`.

---

## Branch Naming

Linear generates branch names automatically:

```
jonahgabriel/omn-XXXX-short-description
```

Branches not tied to Linear tickets: use `kebab-case-description`.

---

## Commit Format

```
type(scope): description [OMN-XXXX]
```

| Type | Usage |
|------|-------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `chore` | Maintenance, dependency updates, CI changes |
| `refactor` | Code restructuring without behavior change |
| `docs` | Documentation only changes |

Examples:
```
feat(routing): add LLM fallback for unmatched prompts [OMN-2273]
fix(hooks): handle malformed stdin JSON gracefully [OMN-2051]
chore(ci): consolidate quality and enhanced CI workflows [OMN-2228]
```

Scope is optional but recommended. Use the component or subsystem being changed
(e.g., `routing`, `hooks`, `context`, `emission`, `delegation`).

---

## Local Quality Commands

Run these before pushing to catch issues early:

```bash
uv run ruff format src/ tests/          # Auto-format
uv run ruff check src/ tests/           # Lint
uv run mypy src/ --config-file mypy.ini # Type check
uv run pyright src/omniclaude           # Pyright type check
uv run pytest tests/ -m unit -v         # Unit tests only
```

For full pre-push validation:

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run pytest tests/ -m "not integration" -v
```

---

## Artifacts

| Artifact | Job | Retention |
|----------|-----|-----------|
| `bandit-security-report` | `security-python` | Default |
| `coverage-test-group-N` (5 shards) | `test` | 1 day |
| `test-results-N` (5 JUnit XML) | `test` | Default |
| `hooks-test-results` (JUnit XML) | `hooks-tests` | Default |
| `agent-framework-test-results` (JUnit XML) | `agent-framework-tests` | Default |
| `coverage-merged` | `merge-coverage` | Default |

---

## Migration Freeze

When `.migration_freeze` exists at the repository root, `migration-freeze` job blocks any
PR that adds new files under `migrations/`. This is active during DB-SPLIT operations (OMN-2055).

To bypass for an approved migration: add the `db-split-bypass` label to the PR.

Check freeze status:

```bash
ls .migration_freeze   # File exists = freeze active
```
