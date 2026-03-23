# Kafka Consumer Conventions

## Inject

- Each consumer handler must be isolated to a single topic subscription.
- Use the projection pattern: consume event, transform, upsert into read-model table.
- Never perform writes to Kafka from inside a consumer handler (no produce-in-consume).
- Consumer group IDs must follow the pattern: `{service}.{topic-short-name}.consumer`.
- Handle deserialization errors gracefully: log and skip malformed messages, never crash.
- All consumer handlers must be idempotent -- duplicate delivery must not corrupt state.
- Use explicit offset commits after successful processing, not auto-commit.
- Keep handler logic under 50ms per message; offload heavy work to background tasks.
