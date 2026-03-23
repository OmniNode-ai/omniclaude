# PR Validation Path

> The complete ordered list of checks a PR goes through in omniclaude.

## Local (before push)

| Order | Check | Tool | What It Catches |
|-------|-------|------|----------------|
| 1 | `ruff format` | pre-commit | Formatting |
| 2 | `ruff check` | pre-commit | Lint violations |
| 3 | `mypy` | pre-commit | Type errors |

## CI (after push)

### Quality Gate

| Order | Check | Workflow | What It Catches |
|-------|-------|----------|----------------|
| 1 | Code Quality (ruff + mypy) | `ci.yml` | Format, lint, types |
| 2 | Pyright Type Checking | `ci.yml` | Strict type errors |
| 3 | Markdown Link Check | `ci.yml` | Broken doc links |
| 4 | Architecture Handshake | `ci.yml` | Incompatibility with omnibase_core |
| 5 | Enum Governance | `ci.yml` | Casing, duplicates, literal-vs-enum |
| 6 | Exports Validation | `ci.yml` | `__all__` mismatches |
| 7 | Kafka Import Guard | `ci.yml` | Direct Kafka imports in nodes (ARCH-002) |
| 8 | Migration Freeze | `ci.yml` | New DB migrations during freeze |
| 9 | ONEX Compliance | `ci.yml` | Naming, contracts, signatures |
| 10 | 12 Architecture Checks | `ci.yml` | DB in orchestrator, git outside effects, hardcoded IPs, etc. |
| 11 | F5.1 No compact cmd topic | `ci.yml` | cmd topics with compact cleanup policy |
| 12 | Architecture Invariants | `ci.yml` | Cross-cutting invariant violations |
| 13 | Stale TODO Gate | `ci.yml` | Stale TODO/FIXME without tickets |

### Tests Gate

| Order | Check | Workflow | What It Catches |
|-------|-------|----------|----------------|
| 1 | Unit Tests (5-way split) | `ci.yml` | Functional regressions |
| 2 | Hooks System Tests | `ci.yml` | Hook registration/execution |
| 3 | Agent Framework Tests | `ci.yml` | Agent YAML loading |
| 4 | Database Schema Validation | `ci.yml` | Schema drift |
| 5 | Mode Metadata Integrity | `ci.yml` | Mode metadata consistency |
| 6 | Skill Hygiene | `ci.yml` | Skill definition compliance |
| 7 | Version Pin Compliance | `ci.yml` | Unpinned dependencies |
| 8 | Cross-Repo Boundary Parity | `ci.yml` | Cross-repo interface drift |

### Security Gate

| Order | Check | Workflow | What It Catches |
|-------|-------|----------|----------------|
| 1 | Python Security Scan (Bandit) | `ci.yml` | Security vulnerabilities |
| 2 | Secret Detection | `ci.yml` | Leaked credentials |
| 3 | AI-Slop Pattern Check | `ci.yml` | AI-generated boilerplate in PR diffs |

### Omni Standards Gate

| Order | Check | Workflow | What It Catches |
|-------|-------|----------|----------------|
| 1 | Repository Structure | `omni-standards-compliance.yml` | Missing required directories |
| 2 | Agent YAML Compliance | `omni-standards-compliance.yml` | Schema version, naming |
| 3 | Ecosystem Integration | `omni-standards-compliance.yml` | CLAUDE.md, hooks.json |
| 4 | Legacy Compatibility | `omni-standards-compliance.yml` | Forbidden patterns |
| 5 | PR Safety Mutation Surface | `omni-standards-compliance.yml` | Unauthorized PR mutations |

### Cross-Repo Checks

| Order | Check | Workflow | What It Catches |
|-------|-------|----------|----------------|
| 1 | Contract Validation | `contract-validation.yml` | Invalid ticket contracts |
| 2 | Schema Compatibility | `onex-schema-compat.yml` | Breaking schema changes |

## Branch Protection

All four gates (Quality, Tests, Security, Omni Standards) must pass before merge.
Gate names are API-stable per `.github/required-checks.yaml`.
