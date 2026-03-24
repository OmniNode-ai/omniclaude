# Omnidash Server Conventions

## Express Route Patterns
- Routes live in `server/routes/`. Each file exports a router mounted in `server/index.ts`.
- Use `router.get/post` with async handlers. Always wrap in try/catch returning 500 on error.
- Query params for filtering: `?team=`, `?status=`, `?since=` (ISO 8601).

## Two-Consumer Architecture
- **EventConsumer**: Real-time Kafka consumer for WebSocket push to frontend.
  Lives in `server/consumers/event-consumer.ts`. Stateless, fan-out only.
- **ReadModelConsumer**: Kafka consumer that projects events into PostgreSQL
  read-model tables (`omnidash_analytics` DB). Lives in `server/consumers/read-model-consumer.ts`.
- Never mix concerns: EventConsumer must NOT write to DB. ReadModelConsumer must NOT push WebSocket.

## DB Projection Patterns
- Projections live in `server/projections/`. One file per topic or aggregate.
- Use parameterized queries (never string interpolation for SQL).
- Upsert pattern: `INSERT ... ON CONFLICT DO UPDATE` for idempotent replay.
- Table names prefixed with topic domain: `epic_pipeline_runs`, `pr_watch_entries`.

## Consumer Handler Conventions
- Each handler receives `{ topic, partition, message }`.
- Parse `message.value` as JSON. Validate `event_type` field before processing.
- Log with structured fields: `{ topic, partition, offset, event_type }`.
- Return void; errors are caught and logged by the consumer framework.

## TypeScript Standards
- Strict mode enabled. No `any` types in new code.
- Use `interface` for data shapes, `type` for unions/intersections.
- Prefer `const` assertions for literal types.
