# Standard Documentation Layout

## Required Directory Structure

```
docs/
├── INDEX.md                  # Required: navigation hub
├── SECURITY.md               # Security policy
├── getting-started/          # Installation and first steps
├── architecture/             # System design and data flows
├── guides/                   # Step-by-step how-to docs
├── reference/                # API and schema reference
│   └── migrations/           # Schema migration guides
├── decisions/                # ADRs (Architecture Decision Records)
│   └── README.md             # ADR index
└── standards/                # This directory
```

---

## File Naming Rules

| Pattern | Usage |
|---------|-------|
| `UPPER_SNAKE_CASE.md` | All documents (default) |
| `README.md` | Directory index files only |
| `ADR-NNN-<slug>.md` | Architecture Decision Records in `decisions/` |
| `kebab-case.md` | Historical exceptions only — do not use for new documents |

Examples:
- `HOOK_LIB_REFERENCE.md` — correct
- `AGENT_YAML_SCHEMA.md` — correct
- `agent-yaml-schema.md` — do not create new files in this format
- `README.md` — correct as a directory index in `decisions/`

---

## Document Authority Model

Documents have two distinct purposes. Never mix them.

| Document | Authority | Contains |
|----------|-----------|---------|
| `CLAUDE.md` | Operational | Rules, invariants, constraints, performance budgets, failure modes |
| `docs/` | Educational | Architecture diagrams, guides, tutorials, schema reference |

### Rules

**Do NOT duplicate content between `CLAUDE.md` and `docs/`.**

- If it is a rule Claude must follow during execution: put it in `CLAUDE.md`.
- If it is explanatory or educational: put it in `docs/`.
- If it is a reference table (topics, modules, schemas): put it in `docs/reference/`.

**Do NOT put tutorials in `CLAUDE.md`.**
`CLAUDE.md` is read on every hook invocation. Tutorials bloat the context window.

**Do NOT put operational constraints in `docs/`.**
Constraints in `docs/` are easy to miss. Operational constraints belong in `CLAUDE.md` where
Claude will always read them.

---

## Directory Purposes

### `getting-started/`

Installation, setup, and first-run guides. Audience: developers new to the repo.

Contents:
- Installation and dependency setup
- First hook invocation walkthrough
- Development environment configuration
- Plugin deployment instructions

### `architecture/`

System design documents, data flow diagrams, and component overviews.
Audience: engineers understanding how the system works.

Contents:
- Hook data flow diagrams
- Event emission architecture
- Agent routing pipeline description
- Daemon architecture
- Component interaction diagrams

### `guides/`

Step-by-step how-to documents for specific tasks.
Audience: engineers performing specific operations.

Contents:
- How to add a new hook
- How to add a new agent YAML
- How to author a skill
- How to debug hook failures
- How to extend the routing pipeline

### `reference/`

Authoritative reference for APIs, schemas, and module lists.
Audience: engineers writing code that integrates with these interfaces.

Contents:
- `HOOK_LIB_REFERENCE.md` — all modules in `plugins/onex/hooks/lib/`
- `AGENT_YAML_SCHEMA.md` — agent YAML schema and authoring guide
- `KAFKA_TOPICS_REFERENCE.md` — all Kafka topics with access control
- `SKILL_AUTHORING_GUIDE.md` — skill file format and best practices
- `migrations/` — schema migration guides per PR or release

### `decisions/`

Architecture Decision Records (ADRs). Audience: engineers understanding why things are
the way they are.

Naming: `ADR-NNN-<short-slug>.md`
Index: `decisions/README.md` (required)

### `standards/`

Standards documents for how this repository is structured and operated.
This directory. Audience: contributors.

Contents:
- `STANDARD_DOC_LAYOUT.md` — this file
- `CI_CD_STANDARDS.md` — CI pipeline jobs, gates, and branch protection

---

## Deleted Content Policy

When a document becomes stale or is superseded:

1. **Delete it outright** if no active files reference it by path.
2. **Add a deprecation banner** if active files reference it:
   ```markdown
   > **DEPRECATED**: This document is superseded by [NEW_DOCUMENT.md](./NEW_DOCUMENT.md).
   > It will be removed once all references are updated.
   ```
3. **Never** keep stale docs "for historical reference" without a deprecation banner.
4. **Never** create `archive/` directories. Stale content belongs in git history, not in the
   working tree.

---

## INDEX.md Requirements

Every `docs/` directory must have an `INDEX.md` with these four sections:

### 1. Documentation Authority Model

A table showing which document type has authority for which kind of content.
(See the authority model table above.)

### 2. Quick Navigation by Intent

A table organized by what a developer is trying to do:

| I want to... | Go to |
|--------------|-------|
| Set up my dev environment | getting-started/SETUP.md |
| Understand the hook data flow | architecture/HOOK_DATA_FLOW.md |
| Add a new agent | reference/AGENT_YAML_SCHEMA.md |
| ...etc | ... |

### 3. Per-Section Structure Tables

One table per directory, listing every document in that directory with a one-line description.

### 4. Document Status Summary

A table listing documents with status: `Current`, `Draft`, or `Deprecated`.

---

## Checklist for New Documents

Before adding a new document:

- [ ] Is this content appropriate for `docs/` (educational) vs `CLAUDE.md` (operational)?
- [ ] Does a document covering this topic already exist?
- [ ] Does the filename follow `UPPER_SNAKE_CASE.md`?
- [ ] Is it placed in the correct subdirectory?
- [ ] Is `docs/INDEX.md` updated to reference the new document?
- [ ] If in `reference/`: is the content authoritative and kept in sync with code?
- [ ] If in `decisions/`: does it follow `ADR-NNN-<slug>.md` naming?
