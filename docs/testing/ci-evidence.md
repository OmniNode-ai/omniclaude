# CI test evidence — OMN-18784

The Agent Framework Tests job runs the restored `tests/test_enhanced_router.py`
suite and the CI evidence checks directly. Missing files, empty selection and
failing assertions fail pytest. The hooks job also runs pytest directly; it no
longer writes a synthetic zero-test report when its selection disappears.

The evidence checks run in the agent job and in pre-commit. They inspect every
workflow's executable steps for literal zero-test JUnit writers and exercise the
actual agent job shell with missing, empty, failing and valid test fixtures.
The existing skip-count ratchet rejects each empty report before pooling shards,
and its evaluator derives a failure from zero collection. Real reports with no
skips remain valid. This does not measure coverage adequacy or detect every
possible program that computes fabricated XML dynamically.

## Coverage retained and previously lost

`test_enhanced_router.py` was removed historically and restored before this
change. Its 30 tests and 74 assertions cover TriggerMatcher, ConfidenceScorer,
CapabilityIndex, ResultCache and AgentRouter. The existing restoration and
nonzero collection baseline are retained.

The former `test_quality_gates.py` and `test_performance_thresholds.py` contained
26 and 36 bare skip placeholders respectively, with no assertions. They remain
deleted; they provided no executed quality-gate or performance-threshold coverage.

## Integration surfaces retired

The ticket explicitly permits deletion in AC4 and AC5. This change chooses that
option rather than activating external-service workflows with unproven setup.
Conditional runtime rollouts remain gated.

The deleted `.github/workflows/integration-tests.yml` was dispatch-only and named
absent test files and migrations. Removing it retires its advertised database,
Kafka, observability and full-pipeline jobs; it supplied no automated execution
path for the two suites below.

- `tests/hooks/test_integration_kafka.py`: 18 test methods removed. Their intended
  assertions covered live broker delivery of session, prompt and tool events;
  ordering and envelope shape; broker failures and rapid publishing; prompt
  sanitization; hook-event partition keys, full prompts, correlation and
  timestamps; and command/event session outcomes. These live delivery assertions
  are removed. No replacement live-broker coverage is claimed.
- `tests/e2e/test_omniclaw_proof_of_life.py`: two tests removed, for a Discord
  message roundtrip and a correlated Kafka chain. The probe sent bot-authored
  messages, which the current inbound adapter ignores, and never passed its
  chosen Kafka correlation identifier to the adapter. These external-service
  assertions are removed.

`tests/hooks/test_handler_event_emitter.py` and
`tests/unit/nodes/node_channel_discord_adapter/` retain unit coverage. They do
not establish live delivery or replace the removed external-service probes.
Restoring live probes requires a workflow with real files and an exercised
service setup; retaining skipped fixtures would not establish that coverage.
