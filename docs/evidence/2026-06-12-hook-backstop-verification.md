# Hook Backstop Rewrite: Verification Evidence

**Date:** 2026-06-12
**Plan:** `omni_home/docs/plans/2026-06-12-skill-output-suppression-plan.md` (Phase 3 — Skill Output Suppression)
**Mechanism source:** `docs/research/2026-06-12-updated-tool-output-shape-probe.md`

## What was verified

### 1. Protocol contract (unit + replay, this PR)

```text
uv run pytest tests/unit/hooks/test_skill_output_suppressor.py -v
37 passed, 1 skipped in 1.11s

uv run pytest tests/ -q -m "not integration"
11134 passed, 26 skipped, 84 deselected in 264.40s
```

Pinned by the suite:

- Suppress emission is EXACTLY
  `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": {"stdout", "stderr", "interrupted", "isImage"}}}`
  — the OBJECT form the tool-output-shape probe proved replaces the Bash tool
  result (string form is schema-rejected, fail-open + invisible).
- Every passthrough path (non-Bash, unmatched, small, error exit,
  interrupted, receipt-mode `ModelSkillResult`) emits NOTHING on stdout.
- Capture-before-suppress: store-unavailable, store-write-failure, and
  stripped `ONEX_ARTIFACT_STORE_ROOT` all pass the output through
  unmodified; event-emission failure after a successful artifact write
  still suppresses.
- Recorded probe-shaped fixtures (`tests/fixtures/hooks/post_tool_use/`)
  replay through the real CLI entrypoint as a subprocess.
- Single-`updatedToolOutput`-emitter guard over the hooks tree
  (probe verdict 3: last registered emitter wins).

### 2. Live wrapper smoke (shell hook, fixture stdin)

Suppress-eligible fixture (`bash_onex_node_large.json`, 62-line
RuntimeLocal log stream) piped through
`plugins/onex/hooks/scripts/post_tool_use_output_suppressor.sh` with a
fresh `ONEX_STATE_DIR`:

```text
exit=0 stdout_len=0
--- log:
[2026-06-12T22:18:23Z] Resolved python: .../omniclaude/.venv/bin/python3
[skill_output_suppressor] correlation lookup failed: No module named 'plugins'
[skill_output_suppressor] capture unavailable: artifact store unavailable:
  omnibase_core.artifacts not importable (core pin predates the artifact store module):
  No module named 'omnibase_core.artifacts'
exit=0 small_stdout_len=0
```

This is the designed fail-closed behavior: capture impossible ⇒ NO
suppression ⇒ the model sees the original output unchanged (no hidden
loss). The wrapper exports
`ONEX_ARTIFACT_STORE_ROOT=$ONEX_STATE_DIR/artifacts` (probe Probe 4) so
the store constructor never KeyErrors once the module is importable.

## Deferred: live transcript proof of an actual suppression

A live Claude-session suppression (transcript shows compact summary +
`artifact_ref`; artifact read-back hash-verifies) requires
`omnibase_core.artifacts.ArtifactStore` to be importable from
the hook runtime. That module is merged on omnibase_core **dev** but is
not in any released tag; omniclaude pins `omnibase-core` at git rev
`v0.43.0` (`<0.45.0`). Bumping the pin to a non-release dev SHA (28
unreleased core commits) was rejected as out-of-scope risk for this
ticket; the pin advances via the normal release propagation lane.

Until then the backstop is provably inert-but-correct:
`test_replay_suppress_fixture_without_store_passes_through` pins the
fail-closed default across BOTH pin generations (ImportError today,
KeyError-on-missing-env after the bump), and
`test_real_artifact_store_roundtrip` (importorskip) activates
automatically on pin bump — write → suppress → read-back → hash-verify
against the real store. The live transcript probe should be executed and
appended here when the pin lands.
