---
name: scope_lock
description: Optional session preamble that front-loads architectural constraints for cross-repo or enforcement-type sessions. Injects distributed-CI, evidence-based-status, and full-scope reminders at session start to reduce first-attempt architectural misalignment.
version: 1.0.0
level: basic
debug: false
category: workflow
tags: [preamble, scope, architecture, cross-repo, constraints]
author: OmniClaude Team
composable: true
---

# Scope Lock

## Purpose

Front-load architectural constraints at the start of sessions where misalignment on the
first attempt is the demonstrated pattern.

**This skill is optional and intentionally narrow.** It is a one-sentence constraint injection
at session start — not an enforcement layer, not a required step, and not part of automated
pipelines.

**Use it when:**
- Starting a cross-repo session (touching 2+ repos in the same task)
- Starting an enforcement task (new CI checks, policy gates, drift detection)
- Misalignment has occurred in a previous session for the same problem domain

**Do NOT use it for:**
- Single-repo feature work
- Automated pipeline invocations (epic-team, ticket-pipeline, merge-sweep)
- Always-on preamble injection

---

## Preamble Injection

When invoked, emit the following constraint block as the opening context for the session.
Announce: "Scope lock active." then inject the constraints.

---

**Scope Lock Active**

The following constraints apply to this session:

1. **Distributed CI validators over centralized scripts.** All new enforcement must be
   implemented as per-repo CI checks (GitHub Actions jobs, pre-commit hooks, or CI scripts
   inside each affected repo). Do not implement enforcement as a centralized script in
   `omni_home` or any shared meta-repo that directly modifies other repos.

2. **Evidence-based status only.** Before reporting that any service is running, PR is
   merged, ticket is complete, or branch is clean — run the relevant command or API call
   and verify the actual state. Never report conjectural status.

3. **Full scope including intelligence integration.** When executing cross-repo tasks,
   include the intelligence learning integration surface (omniintelligence event emission,
   Kafka topics, Qdrant patterns) in scope unless explicitly excluded by the task spec.
   Do not silently narrow scope.

---

## Invocation

```
/scope-lock
```

No arguments required. The skill emits the constraint block and exits. Subsequent skill
invocations (epic-team, ticket-pipeline, executing-plans) proceed normally with the
constraints active in the session context.

## Doctrine

Scope-lock is one narrow tool. It does not replace architectural judgment or detailed task specs.
If a task spec already encodes these constraints, scope-lock is redundant — skip it.
If a task spec contradicts these constraints, the task spec wins; scope-lock is advisory.
