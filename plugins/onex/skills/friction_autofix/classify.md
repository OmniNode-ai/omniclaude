# Friction Classification Rubric

## FIXABLE — Auto-fix without human judgment

These friction categories can be resolved with structural code changes:

| Surface Pattern | Fix Category | Example |
|----------------|-------------|---------|
| `config/missing-*` | CONFIG | Missing sidebar entry, missing route registration |
| `config/wrong-*` | CONFIG | Wrong port, wrong path, stale config value |
| `ci/broken-import` | IMPORT | ImportError, ModuleNotFoundError in CI |
| `ci/missing-workflow` | WIRING | Missing CI workflow file |
| `ci/missing-test-marker` | TEST_MARKER | Test missing @pytest.mark.unit |
| `tooling/missing-*` | CONFIG | Missing script, missing tool config |
| `tooling/stale-*` | STALE_REF | Reference to removed file or renamed function |
| `config/env-var-*` | ENV_VAR | Missing env var in .env template or docker-compose |
| `permissions/read-only-*` | CONFIG | File permission issue (non-security) |

## ESCALATE — Create ticket for human review

These categories require design decisions or have security implications:

| Surface Pattern | Escalation Reason |
|----------------|-------------------|
| `network/*` | Infrastructure/connectivity — may need ops intervention |
| `auth/*` | Security-sensitive — requires credential management |
| `unknown/*` | Unclassified — needs human triage |
| `permissions/*` (non-read-only) | Security-sensitive permission changes |
| `linear/*` | External service API issues |
| `kafka/schema-*` | Schema changes need design review |
| Any cross-repo architectural change | Scope too large for micro-plan |
| Any surface with 10+ occurrences | Indicates systemic issue, not point fix |

## Decision Rules

1. If surface category is in {network, auth, unknown}: ESCALATE
2. If description mentions "security", "credentials", "token": ESCALATE
3. If description mentions multiple repos: ESCALATE
4. If count > 10: ESCALATE (systemic, not point fix)
5. Otherwise: FIXABLE with category inferred from surface + description
