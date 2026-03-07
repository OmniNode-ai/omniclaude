# Failure Taxonomy

Reference document for the 12 failure classes detected by the gap skill's probe system.

## Categories

- **CONTRACT_DRIFT**: A declared contract (topic name, model field, FK target, API spec, topic registry) no longer matches reality across repos.
- **ARCHITECTURE_VIOLATION**: A structural boundary rule (DB access, env activation, projection lag, migration parity, legacy config) is violated.
- **INTEGRATION_HEALTH**: A cross-cutting integration concern (branch protection, CI configuration) has drifted from expected state.

## Auto-Fix Policy

| Policy | Meaning |
|--------|---------|
| NO (GATE) | Requires human decision before any change is made. The skill emits a decision gate and waits for `--choose`. |
| LOCAL-ONLY auto-fix | The skill can fix the local repo's registry file automatically, but cannot mutate the broker or remote registries. |
| YES (search-replace) | The skill can apply a deterministic search-and-replace fix without human review. |
| YES (gh api) | The skill can fix the issue via the GitHub API (e.g., removing stale branch protection check names). |

## Failure Classes

| # | boundary_kind | category | Auto-fix? | Description |
|---|---------------|----------|-----------|-------------|
| 1 | kafka_topic | CONTRACT_DRIFT | NO (GATE) | Producer and consumer disagree on a Kafka topic string (byte-for-byte mismatch). |
| 2 | model_field | CONTRACT_DRIFT | NO (GATE) | A Pydantic model field type differs between the producing and consuming repo. |
| 3 | fk_reference | CONTRACT_DRIFT | NO (GATE) | A foreign-key target table referenced in one repo does not exist in the dependent repo's schema. |
| 4 | api_contract | CONTRACT_DRIFT | NO (GATE) | The OpenAPI spec hash in the provider repo does not match what the consumer repo expects. |
| 5 | db_boundary | ARCHITECTURE_VIOLATION | NO (GATE) | A repo that must not access upstream databases contains DB driver imports or DB URL env vars. |
| 6 | topic_registry | CONTRACT_DRIFT | LOCAL-ONLY auto-fix | A topic declared in a contract YAML is missing from the local `TopicRegistry` enum but exists on the broker. The skill can add the enum member locally. |
| 7 | env_activation | ARCHITECTURE_VIOLATION | NO (GATE) | A node's contract YAML declares a required env var that is not present in the activation environment (`~/.omnibase/.env` or Infisical). |
| 8 | projection_lag | ARCHITECTURE_VIOLATION | NO (GATE) | A Kafka consumer group's lag on a topic partition exceeds the configured threshold, indicating stale read-model projections. |
| 9 | auth_config | CONTRACT_DRIFT | NO (GATE) | An Infisical or service-identity client configuration has drifted from the expected values declared in the contract. |
| 10 | migration_parity | ARCHITECTURE_VIOLATION | NO (GATE) | A repo's migration state (Alembic head, schema checksum) does not match the expected state after a cross-repo release. |
| 11 | legacy_config | ARCHITECTURE_VIOLATION | YES (search-replace) | A file contains a pattern from the legacy denylist (deprecated env vars, decommissioned endpoints, removed paths). |
| 12 | branch_protection | INTEGRATION_HEALTH | YES (gh api) | A branch protection required status check name does not match any actual CI job name, silently blocking all merges. |

## Probe-to-Class Mapping

Probes 2.1 through 2.5 (existing) map to failure classes 1-5.
Probes 2.6 through 2.11 map to failure classes 6-11.
Probe 2.12 maps to failure class 12.

| Probe | Failure Class | boundary_kind |
|-------|--------------|---------------|
| 2.1 | 1 | kafka_topic |
| 2.2 | 2 | model_field |
| 2.3 | 3 | fk_reference |
| 2.4 | 4 | api_contract |
| 2.5 | 5 | db_boundary |
| 2.6 | 6 | topic_registry |
| 2.7 | 7 | env_activation |
| 2.8 | 8 | projection_lag |
| 2.9 | 9 | auth_config |
| 2.10 | 10 | migration_parity |
| 2.11 | 11 | legacy_config |
| 2.12 | 12 | branch_protection |

## Severity Defaults

| boundary_kind | Default Severity | Notes |
|---------------|-----------------|-------|
| kafka_topic | WARNING | Upgrade to CRITICAL if affects production consumer group |
| model_field | WARNING | |
| fk_reference | WARNING | |
| api_contract | WARNING | |
| db_boundary | CRITICAL | Always CRITICAL for `no_upstream_db_repos` |
| topic_registry | WARNING | |
| env_activation | CRITICAL | Missing env var will cause runtime crash |
| projection_lag | WARNING | Upgrade to CRITICAL if lag exceeds 10x threshold |
| auth_config | CRITICAL | Auth drift can cause service authentication failures |
| migration_parity | WARNING | |
| legacy_config | WARNING | |
| branch_protection | CRITICAL | Stale required checks silently block all merges on the branch |
