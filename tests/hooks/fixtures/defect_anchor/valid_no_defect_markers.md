# Evidence: Bus Integration — 2026-06-13

## Summary

All paths verified green. No known issues.

## Detail

Kafka consumer group lag: 0 messages behind on all partitions.
Projection endpoint returned fresh data within 2s of publish.
Delegation orchestrator completed 5/5 test cases successfully.

## Verification

```
uv run pytest tests/integration/ -v -m integration
42 passed in 31.4s
```
