---
name: curate-legacy
description: Canonicalize legacy docs, archived code, and feature ideas into a handler-first Ideas Registry with provenance, dedup, and executable specs
version: 1.0.0
category: workflow
tags:
  - curation
  - legacy
  - architecture
  - handler
  - registry
  - parallel
  - canonicalization
author: OmniClaude Team
args:
  - name: --corpus
    description: "Comma-separated corpus roots to scan (default: all known locations)"
    required: false
  - name: --output
    description: "Output root directory (default: omni_home/docs/registry)"
    required: false
  - name: --phase
    description: "Run a single phase: index | extract | cluster | specs | all (default: all)"
    required: false
  - name: --max-agents
    description: "Maximum parallel agents for extraction (default: 10)"
    required: false
  - name: --deep-read
    description: "Comma-separated category slugs to deep-read archive code for (default: none — catalog only)"
    required: false
  - name: --dry-run
    description: Run all phases but do not write output files
    required: false
---

# Curate Legacy

## Overview

Canonicalize all legacy documentation, archived code, and feature ideas across the OmniNode
ecosystem into a single, deduplicated Ideas Registry with handler-first specs.

**Announce at start:** "I'm using the curate-legacy skill to canonicalize legacy docs and
archived code into the Ideas Registry."

## Why This Exists

Ideas and implementations are scattered across 4+ locations:
- `doc_archive/` (514+ original vision docs)
- `Features and Ideas/` (44+ product vision docs)
- `Archive/` (37 archived repos with imperative code)
- `omni_home/docs/design/` (25+ current design docs)

Without canonicalization, the same idea appears in 3-5 places with no single source of truth,
no handler mapping, and no extraction plan. This skill produces:

1. **Corpus Index** — stable fingerprints for every source file
2. **IdeaCards** — structured extraction with strict schema (no prose)
3. **Canonical Clusters** — deduplicated feature entries with stable IDs
4. **Ideas Registry** — human-readable master index
5. **Archive Handler Catalog** — imperative code classified by handler type
6. **Execution Specs** — handler-first specs per feature area

## When to Use

**Use when:**
- Starting a new planning cycle and need to inventory all existing ideas
- Onboarding someone who needs to understand the full idea landscape
- After adding new docs to any corpus location (incremental update)
- Before creating Linear epics — ensures ideas have provenance and dedup

**Do NOT use when:**
- You need to implement a specific feature (use `ticket-work`)
- You want to audit live integration health (use `gap-analysis`)
- You're debugging a specific failure (use `root-cause-tracing`)

## CLI Args

```
/curate-legacy
/curate-legacy --phase index
/curate-legacy --phase extract --max-agents 5
/curate-legacy --deep-read infra,intelligence
/curate-legacy --corpus /path/to/custom/docs
/curate-legacy --dry-run
```

| Arg | Default | Description |
|-----|---------|-------------|
| `--corpus` | all known | Comma-separated corpus root paths |
| `--output` | `omni_home/docs/registry` | Output directory for all artifacts |
| `--phase` | all | Run single phase or all |
| `--max-agents` | 10 | Parallel agent cap for extraction |
| `--deep-read` | none | Categories to deep-read archive code |
| `--dry-run` | false | Preview without writing |

## Non-Negotiable Invariants

1. **Every output spec must map to the four-node handler model**:
   compute / effect / reducer / orchestrator. No spec without `handler_map`.

2. **Every idea must have provenance**: `source_files[]` and `source_code_paths[]`.
   No card without at least one source. No cluster without provenance union.

3. **Dedup must be deterministic**: same corpus input produces the same cluster IDs
   and canonical titles. Cluster ID = SHA-256 of sorted member card content hashes.

4. **Output is append-only with stable IDs**: reruns update existing specs by ID,
   never generate duplicates with new filenames.

5. **Idempotent**: rerun does not explode the repo with new files. Content-hash
   comparison before write — skip if unchanged.

6. **IdeaCards are structured, not prose**: agents output strict schema. Cards
   missing `handler_map` or provenance are rejected.

## The Four Phases

Full orchestration logic is in `prompt.md`. Summary:

**Phase 0 — Corpus Index**: Build file index with path, size, SHA-256, type guess,
handler candidacy tags. Output: `_corpus_index.json`. Fast, mechanical, no deep reading.

**Phase 1 — Parallel Extraction**: Dispatch agents to read corpus slices and produce
IdeaCards (strict schema). Output: `_idea_cards.ndjson`. Agents read files, not summarize.

**Phase 2 — Dedup & Cluster**: Deterministic clustering via content overlap + shared
source files + title similarity. Produces canonical FeatureEntries. Output:
`_clusters.json`, `IDEAS_REGISTRY.md`, `ARCHIVE_HANDLER_CATALOG.md`.

**Phase 3 — Spec Generation**: For each cluster, generate a handler-first execution spec
(2-3 pages). Output: `docs/specs/<domain>/<feature_id>_<slug>.md`.

## Output Artifacts

```
docs/registry/
├── _corpus_index.json              # Phase 0: file fingerprints
├── _idea_cards.ndjson              # Phase 1: structured extractions
├── _clusters.json                  # Phase 2: cluster definitions
├── IDEAS_REGISTRY.md               # Phase 2: human-readable master index
├── ARCHIVE_HANDLER_CATALOG.md      # Phase 2: code extraction reference
└── specs/                          # Phase 3: execution specs
    ├── INDEX.md                    # Spec index with impact/effort matrix
    ├── infrastructure/
    │   ├── kafka-adapter-effect.md
    │   └── ...
    ├── intelligence/
    │   ├── predictive-error-prevention.md
    │   └── ...
    ├── agent/
    │   └── ...
    ├── governance/
    │   └── ...
    └── learning/
        └── ...
```

## Verification

After completion, verify:
- `docs indexed` count matches corpus file count
- `cards emitted` count is reasonable (not 1:1 with files — many files produce 0 cards)
- `clusters formed` < `cards emitted` (dedup actually happened)
- `specs created` == `clusters formed`
- No spec exists without `handler_map` section
- No cluster exists without `source_files` provenance
- Rerun produces 0 new files (idempotency check)

## See Also

- `gap-analysis` skill (cross-repo integration health)
- `parallel-solve` skill (generic parallel dispatch)
- `pipeline-audit` skill (end-to-end pipeline verification)
- `decompose-epic` skill (breaking epics into tickets)
