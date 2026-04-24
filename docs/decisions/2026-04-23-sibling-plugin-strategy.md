# Decision: Sibling Plugin Strategy (omnigemini, omnimemory, omniintelligence)

**Date**: 2026-04-23
**Status**: Recorded (traceable artifact; formal entry in `decision_store` is a follow-up — see "Pending formalization" below)
**Context ticket**: OMN-8799 (SD-12: Marketplace package — `onex` CLI version pin)
**Plan reference**: `docs/plans/2026-04-14-standalone-plugin-distribution.md` § 10 (Open Question: Sibling Plugin Strategy)
**Gate**: The SD-12 implementation of marketplace packaging depends on this decision being recorded in writing before a standalone marketplace install is promoted to users.

---

## Question

Three sibling plugins exist or are in development: `omnigemini`, `omnimemory`, and
potentially `omniintelligence`. How should a standalone user install and discover
the capabilities of a plugin that depends on a sibling?

## Options (verbatim from plan § 10)

- **A — Monolithic**: Package all sibling plugins into the single `onex@omninode-tools`
  marketplace entry. One install, all capabilities. Risk: large package, cross-plugin
  coupling.
- **B — Separate installs**: Each plugin is independently installable. `hostile_reviewer`
  gracefully degrades without omnigemini; `recall` gracefully degrades without
  omnimemory. Risk: user confusion about which plugins to install.
- **C — Runtime-absorbed**: omnigemini and omnimemory functionality is absorbed into
  omnimarket nodes. The plugin only dispatches; model selection is the runtime's
  concern. This aligns with the contract-driven model routing policy. Risk: higher
  coupling to runtime, loses local-model flexibility.

## Decision

**Option C for new capabilities; Option B for existing sibling plugins until a
migration plan is finalized.**

This is the plan's recommended posture and is adopted verbatim. Rationale:

1. **C aligns with contract-first policy.** Model routing and memory access already
   have canonical dispatch paths (omnimarket nodes + cloud runtime). Adding a
   secondary plugin-side router would duplicate the authority and drift from the
   "one pattern" rule (`feedback_contract_driven_handlers.md`).
2. **B preserves gradual migration.** Existing sibling plugins (omnigemini,
   omnimemory) have install footprints and user expectations today. Forcing them
   into C immediately would be a destructive rewrite. Keeping them separately
   installable lets downstream skills degrade gracefully and ship independently
   until their capabilities are absorbed.
3. **A was rejected** because packaging everything into one marketplace entry
   recreates the monorepo-inside-a-plugin coupling the plan exists to eliminate.

## Consequences

- The `onex@omninode-tools` marketplace entry published in SD-12 contains **only**
  the `onex` plugin. It does not bundle omnigemini or omnimemory.
- Skills that depend on sibling plugins (`hostile_reviewer`, `recall`) must already
  or soon degrade gracefully when the sibling plugin is absent and log a
  `SkillRoutingError` with a clear remediation message (per OMN-8737 / plan § 8.3).
- New capabilities that were candidates for sibling plugins (e.g. model-family
  selection policy, memory projection) are routed through omnimarket nodes
  instead of into new Claude plugins.
- SD-13 (version skew alerting) covers sibling-plugin/plugin-compat skew too —
  the alerting surface is topic-based, so it fires whenever a consumer subscribes
  with an incompatible schema regardless of which plugin owns it.

## Pending formalization

This markdown record serves as the traceable artifact required by the SD-12 gate.
The formal entry must also be recorded via the `/onex:decision_store` skill, which
requires runtime dispatch (R-class). That invocation is tracked as a follow-up and
should happen from a session with runtime access. Until that entry lands in the
decision store, consumers of the decision can cite this file (and the linked
plan § 10) as the authoritative record.
