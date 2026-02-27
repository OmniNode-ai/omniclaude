# Event Envelope Canonical Field Names

**Decision**: OMN-2932
**Status**: Active
**Date**: 2026-02-27

## Summary

The ONEX platform uses a single canonical naming convention for event envelope
fields, derived from `ModelEventEnvelope` in `omnibase_core`.

## Canonical Names

| Field | Canonical Name | Type | Description |
|-------|---------------|------|-------------|
| Envelope identifier | `envelope_id` | UUID string | Unique ID for this envelope instance |
| Envelope timestamp | `envelope_timestamp` | ISO-8601 UTC string | When the envelope was created |
| Correlation ID | `correlation_id` | UUID string | Request tracing ID |
| Causation ID | `causation_id` | UUID string (optional) | Parent event ID |
| Payload | `payload` | object | The wrapped event data |

## Legacy Aliases (Accepted, Deprecated)

The following field names were used in earlier omniclaude hook events. They are
still accepted by `omnidash/shared/schemas/event-envelope.ts` during the
transition period, but should not be used in new code.

| Legacy Name | Canonical Replacement |
|-------------|----------------------|
| `entity_id` | `envelope_id` |
| `emitted_at` | `envelope_timestamp` |

## Domain Fields vs Envelope Fields

`entity_id` and `emitted_at` may still appear as **domain-level payload fields**
inside the event payload object (not as top-level envelope fields). This is
legitimate:

- `entity_id` inside a payload may refer to a domain entity (e.g., the session
  being tracked), not the envelope identifier.
- `emitted_at` inside a payload may record when a hook ran.

These domain uses are separate from the envelope wrapper and do not conflict
with the canonical envelope field names.

## Producer Requirements (omniclaude)

Hook events emitted via `embedded_publisher` that use `ModelEventEnvelope`
wrapping must use:

```python
{
    "envelope_id": str(uuid4()),        # unique ID for this envelope
    "envelope_timestamp": datetime.now(UTC).isoformat(),
    "correlation_id": ...,
    "payload": { ... }
}
```

## Consumer Requirements (omnidash)

`omnidash/shared/schemas/event-envelope.ts` normalizes both naming conventions
into the canonical names via Zod transform. All code that accesses parsed
envelopes must use `envelope_id` and `envelope_timestamp`.

The OR detection checks in `event-consumer.ts` for canonical envelope format
detection use only `envelope_id` and `envelope_timestamp`.

## References

- `omnibase_core/src/omnibase_core/models/events/model_event_envelope.py`
- `omnidash/shared/schemas/event-envelope.ts`
- Gap fingerprint: `a319201c` (CONTRACT_DRIFT: event-envelope-field-names)
