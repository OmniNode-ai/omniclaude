<!-- persona: plugins/onex/skills/_lib/assistant-profile/persona.md -->
<!-- persona-scope: this-skill-only — do not re-apply if polymorphic agent wraps this skill -->
Apply the persona profile above when generating outputs.

# Curate Legacy Orchestration

You are executing the curate-legacy skill. This prompt defines the complete orchestration logic
for canonicalizing legacy docs and archived code into a handler-first Ideas Registry.

---

## Step 0: Parse Arguments

Parse from `$ARGUMENTS`:

| Argument | Default | Description |
|----------|---------|-------------|
| `--corpus` | all known locations | Comma-separated corpus root paths |
| `--output` | `/Volumes/PRO-G40/Code/omni_home/docs/registry` | Output directory | <!-- local-path-ok -->
| `--phase` | all | `index`, `extract`, `cluster`, `specs`, or `all` |
| `--max-agents` | 10 | Parallel agent cap |
| `--deep-read` | none | Categories for deep archive code reading |
| `--dry-run` | false | Preview only |

### Default Corpus Roots

If `--corpus` not specified, use all of these:

```
CORPUS_ROOTS:
  doc_archive: /Volumes/PRO-G40/Code/doc_archive  # local-path-ok
  features: /Users/jonah/OmniNode/Features and Ideas  # local-path-ok
  archive: /Volumes/PRO-G40/Code/Archive  # local-path-ok
  design: /Volumes/PRO-G40/Code/omni_home/docs/design  # local-path-ok
  plans: /Volumes/PRO-G40/Code/omni_home/docs/plans  # local-path-ok
  reference: /Volumes/PRO-G40/Code/omni_home/docs/reference  # local-path-ok
  tracking: /Volumes/PRO-G40/Code/omni_home/docs/tracking  # local-path-ok
```

### Output Root

```
OUTPUT_ROOT: /Volumes/PRO-G40/Code/omni_home/docs/registry  # local-path-ok
```

Generate a `run_id` = first 12 chars of a UUID4.

---

## Phase 0 — Corpus Index

**Goal**: Build a stable, fingerprinted file index. No deep reading. Fast and mechanical.

### 0.1 Scan All Corpus Roots

For each corpus root, recursively list all files. For each file, record:

```json
{
  "path": "/absolute/path/to/file.md",
  "corpus": "doc_archive",
  "size_bytes": 4523,
  "sha256": "a1b2c3...",
  "extension": ".md",
  "type_guess": "design|notes|checklist|code|readme|config|unknown",
  "frontmatter": {"title": "...", "tags": [...]},
  "handler_candidacy": null
}
```

**Type guess heuristics**:
- `.md` files: check first 50 lines for `# Design`, `## Architecture`, `TODO`, `- [ ]`
- `.py` files: `type_guess = "code"`, then classify handler candidacy
- `.yaml`/`.json`: `type_guess = "config"`
- `.txt`: `type_guess = "notes"`

### 0.2 Handler Candidacy (Archive Code Only)

For Python files under the `archive` corpus, add handler candidacy classification:

```json
"handler_candidacy": {
  "type": "effect|compute|reducer|orchestrator|unknown",
  "confidence": "high|medium|low",
  "signals": ["imports asyncio", "has FSM states", "pure function", "Kafka producer"]
}
```

**Classification heuristics**:
- **effect**: imports `asyncio`, `httpx`, `psycopg`, `kafka`, `qdrant`; has I/O operations
- **compute**: no I/O imports, pure transforms, scoring functions, matchers
- **reducer**: has state machine patterns, FSM, `transition`, `guard`, `delta`
- **orchestrator**: has scheduling, batch processing, workflow, priority queue patterns

### 0.3 Write Corpus Index

Write to `{OUTPUT_ROOT}/_corpus_index.json`:

```json
{
  "run_id": "abc123def456",
  "created_at": "2026-02-26T...",
  "corpus_roots": {...},
  "total_files": 612,
  "by_corpus": {"doc_archive": 514, "features": 44, ...},
  "by_type": {"design": 89, "code": 200, ...},
  "files": [...]
}
```

### 0.4 Implementation Strategy

---

## Phase 0.5 — Live Repo Status Scan

**Goal**: Classify each design doc's implementation status by scanning the live codebase for substantive evidence. Runs after Phase 0.3 and before Phase 1. Write output to `{OUTPUT_ROOT}/_implementation_status.json`.

**Phase coupling**: `--skip-status-scan` skips this phase entirely. All cards then default to `status: planned`. The INDEX remains valid but has no status badges.

### Signal Extraction

Signal extraction is doc-driven, not title-driven. For each design doc, extract signals in this priority order:

1. Code identifiers in backticks within the document body
2. Filenames explicitly referenced in the document
3. Capitalized proper nouns from "Key Components" or "Architecture" headings

Fall back to title tokens only if the above yield nothing.

### Substantive Evidence Definition

A matching file counts as substantive evidence **only if ALL** of the following are true:

- Contains `class ` or `def ` or `pydantic.BaseModel` or `@dataclass`
- Is NOT under `tests/`, `docs/`, `SKILL.md`, `prompt.md`, or design directories
- Is NOT a comment-only match

### Misleading Match Suppression List

Never match on these generic tokens (too common to be meaningful signals):
`Handler`, `Contract`, `Schema`, `Registry`, `Gateway`, `Node`, `Base`, `Config`

### Status Classification

| Evidence | Status |
|----------|--------|
| 2+ substantive matching files | `implemented` |
| 1 substantive matching file | `partial` |
| Doc contains "blocked by OMN-" | `blocked` |
| No substantive code, no explicit blocker | `planned` |
| Doc says "superseded", "deprecated", or "no longer pursued" | `deprecated` |
| Vision-only doc with no handler contracts, no stepwise plan, no mechanism | `aspirational` |

`aspirational` is reserved for pure vision docs — no handler contracts, no stepwise implementation plan, no concrete mechanism described.

### Output

Write `{OUTPUT_ROOT}/_implementation_status.json`:

```json
{
  "run_id": "...",
  "created_at": "...",
  "status_by_doc": {
    "doc_archive/omnibus_event_bus_design.md": "implemented",
    "features/nl_intent_compiler.md": "partial",
    "features/context_scoring.md": "planned"
  }
}
```

Use Bash to compute SHA-256 hashes efficiently:
```bash
find "$CORPUS_ROOT" -type f \( -name "*.md" -o -name "*.py" -o -name "*.yaml" -o -name "*.json" -o -name "*.txt" \) -exec sha256sum {} \;
```

Use Glob + Read for frontmatter extraction and type guessing. Dispatch up to 3 parallel
agents for different corpus roots if the corpus is large.

**If `--phase index`**: Stop here after writing `_corpus_index.json`.

---

## Phase 1 — Parallel Extraction

**Goal**: Read corpus files and produce structured IdeaCards. No prose summaries.

### 1.1 Load Corpus Index

Read `{OUTPUT_ROOT}/_corpus_index.json`. If it doesn't exist, run Phase 0 first.

### 1.2 Partition Work

Group files into slices for parallel agents:
- Each agent gets ~50-100 files (tunable via `--max-agents`)
- Group by corpus first, then alphabetically
- Each agent receives its file list + the IdeaCard schema

### 1.3 IdeaCard Schema (Strict — Agents Must Follow Exactly)

```json
{
  "card_id": "019...",
  "title": "Kafka Adapter Effect Handler",
  "category": "infrastructure|intelligence|governance|devex|agent|learning|platform",
  "core_claim": "Production-grade Kafka adapter with batching, circuit breaker, and snappy compression that can be ported directly as a NodeEffect handler.",
  "source_files": [
    "/Volumes/PRO-G40/Code/doc_archive/omnibus_event_bus_design.md"  // local-path-ok
  ],
  "source_code_paths": [
    "/Volumes/PRO-G40/Code/Archive/omnibase_5/src/omnibase/tools/infrastructure/tool_kafka_adapter/"  // local-path-ok
  ],
  "what_exists_today": [
    "omnibase_infra has Kafka integration via Redpanda",
    "omniclaude emit daemon publishes to Kafka topics"
  ],
  "missing_capabilities": [
    "No reusable NodeEffect handler for Kafka",
    "No circuit breaker pattern in current implementation",
    "No batch processing with adaptive strategies"
  ],
  "handler_map": [
    {
      "handler_type": "effect",
      "description": "Kafka publish/subscribe with batching and circuit breaker",
      "candidate_paths": [
        "/Volumes/PRO-G40/Code/Archive/omnibase_5/src/omnibase/tools/infrastructure/tool_kafka_adapter/"  // local-path-ok
      ],
      "port_notes": "Wrap existing producer/consumer classes in NodeEffect contract. Add ONEX error codes."
    }
  ],
  "dependencies": ["Redpanda running on 192.168.86.200:29092"],  <!-- onex-allow-internal-ip -->
  "risk_notes": "Archive code uses older omnibase patterns — needs adapter to current NodeEffect base class",
  "effort_band": "S",
  "status": "partial",
  "depends_on": ["omnibus_event_bus_design.md"],
  "rejected_alternatives": ["Direct HTTP adapter — breaks async contract"],
  "implementation_gap": "Circuit breaker and batch processing logic not yet ported to NodeEffect contract",
  "impact_band": "high"
}
```

**New fields (v1.1)**:

- `status`: `implemented|partial|planned|aspirational|blocked|deprecated` — sourced from `_implementation_status.json`, default `planned`
- `depends_on`: hard prerequisites — **other design docs only** (never runtime systems)
- `rejected_alternatives`: explicit discarded approaches found in the document
- `implementation_gap`: non-empty only when `status` is `partial` or `implemented`; describes what the current code cannot yet do
- `impact_band`: `high|medium|low` — inferred from cross-references, category, handler count, and effort

**`depends_on` vs `dependencies` disambiguation**:
- `depends_on` = design prerequisites (other spec filenames, e.g. `"omnibus_event_bus_design.md"`)
- `dependencies` = runtime systems (existing field, unchanged — e.g. `"Redpanda running on ..."`)
- Never mix them.

### 1.4 Extraction Rules for Agents

Each extraction agent receives these instructions:

```
You are extracting IdeaCards from a corpus of legacy documents and archived code.

RULES:
1. Output ONLY valid IdeaCards as JSON (one per line, NDJSON format)
2. A single source file may produce 0, 1, or multiple cards
3. Do NOT produce a card for trivial/boilerplate files (READMEs with no ideas, empty configs)
4. Every card MUST have:
   - At least one entry in source_files OR source_code_paths
   - At least one entry in handler_map (how does this become a handler?)
   - A core_claim that is 1-2 sentences, not a paragraph
5. If a file describes multiple distinct ideas, create separate cards
6. If a file is a duplicate/near-duplicate of something you already carded, skip it
7. For archive code files: focus on extractable functionality, not file structure
8. effort_band values: XS (<1 day), S (1-2 days), M (3-5 days), L (1-2 weeks)
9. category MUST be one of: infrastructure, intelligence, governance, devex, agent, learning, platform
10. `status`: source from `_implementation_status.json` for this doc path. Also scan doc body: "blocked by OMN-" → `blocked`; "superseded" or "deprecated" or "no longer pursued" → `deprecated`. `aspirational` is reserved for vision-only docs with no handler contracts, no stepwise plan, no concrete mechanism.
11. `depends_on`: scan for explicit filename references (e.g. "see omnibus_event_bus_design.md") and language like "requires X to be defined first". List other DESIGN DOCS only — never runtime systems.
12. `rejected_alternatives`: scan for any of these patterns: "we considered X but", "previous approach was", "this replaces", "unlike X", "not chosen because", "alternative considered". Extract the alternative and reason.
13. `implementation_gap`: REQUIRED if status is `partial` or `implemented`. Describe what the current codebase cannot yet do relative to the spec. Leave empty for `planned`/`aspirational`/`deprecated`.
14. `impact_band`: infer as `high` if: category is intelligence or agent AND multiple cross-references exist, OR handler_map has 3+ entries, OR effort_band is L or M with high cross-reference count. `low` if effort_band is XS or S AND no cross-references. Otherwise `medium`.
15. `core_claim` QUALITY GATE (enforced at card creation): REJECT the card if ANY of the following are true:
    - `core_claim` contains banned strings: "Archive package", "Dominant pattern:", "Signals: has", path fragments like "/Volumes/", "type_guess"
    - `core_claim` is under 40 characters
    - `core_claim` does not contain at least one verb describing what the feature DOES (not just what it IS)

HANDLER_MAP RULES:
- handler_type MUST be: effect, compute, reducer, or orchestrator
- If the idea is purely conceptual with no clear handler mapping, set handler_type
  to the CLOSEST match and explain in port_notes why it's approximate
- candidate_paths should point to actual archive code that can be ported (if any)
- If no archive code exists, candidate_paths can be empty but port_notes must
  describe what would need to be built from scratch

SKIP these file types entirely:
- Package __init__.py files
- requirements.txt / pyproject.toml (unless they document unusual dependencies)
- .gitignore, .env.example, Dockerfile (unless architecturally significant)
- Test files (unless they document behavior worth preserving)
- Generated code
```

### 1.5 Dispatch Extraction Agents

Dispatch up to `max_agents` parallel agents, each via:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Extract IdeaCards: {corpus_name} slice {n}/{total}",
  prompt="You are extracting IdeaCards from legacy OmniNode documents and code.

    ## IdeaCard Schema
    {schema_json}

    ## Extraction Rules
    {rules_text}

    ## Your File List
    Read each file below and produce IdeaCards. Output ONLY valid JSON, one card per line.

    Files to process:
    {file_list}

    ## Category Reference
    - infrastructure: Kafka, DB, caching, networking, deployment, Docker
    - intelligence: Pattern learning, scoring, analysis, ML, NLP
    - governance: Security, compliance, audit, trust, signing
    - devex: CLI, dashboard, documentation, developer experience
    - agent: Agent orchestration, routing, autonomy, desktop automation
    - learning: Context scoring, feedback loops, prompt optimization
    - platform: Core runtime, contracts, node architecture, SPI

    ## Output Format
    Return your results as a JSON array of IdeaCard objects. Nothing else."
)
```

### 1.6 Collect and Validate Cards

After all agents return:
1. Parse each agent's output as JSON array
2. Validate every card against the schema
3. **Reject** cards missing `handler_map` — log rejection with reason
4. **Reject** cards missing all provenance (`source_files` and `source_code_paths` both empty)
5. Concatenate valid cards into `{OUTPUT_ROOT}/_idea_cards.ndjson`

Log summary:
```
Phase 1 Complete
---
Cards extracted: {N}
Cards rejected (no handler_map): {M}
Cards rejected (no provenance): {P}
Cards rejected (core_claim quality gate): {Q}
Files processed: {F}
Files skipped (trivial): {S}
```

### 1.6.5 Pre-Dedup Pass

Run immediately after Phase 1.6, before writing `_idea_cards.ndjson`.

**Goal**: Remove near-duplicate cards produced by different agents processing overlapping corpus slices. This is a title-similarity pass only — full clustering happens in Phase 2.

**Algorithm**:

1. Normalize titles: lowercase, strip punctuation, build bigram shingle sets.
2. Remove hyper-common tokens before comparing (too generic to be signal): `"design"`, `"system"`, `"architecture"`, `"pipeline"`, `"framework"`, `"node"`, `"handler"`
3. Compute Jaccard similarity on bigram sets for all card pairs.

**Thresholds**:

| Similarity | Action |
|------------|--------|
| >= 0.92 | Auto-discard the lower-provenance card (fewer `source_files`). Log as "near-duplicate removed: {title_a} vs {title_b} (score={score:.2f})" |
| 0.75–0.92 | Flag as "needs merge review". Keep both. Log pair with similarity score. |
| < 0.75 | No action. |

**Critical rule**: Auto-discard ONLY when similarity >= 0.92. Never silently delete cards in the 0.75–0.92 range.

Log output appended to Phase 1 summary:
```
Pre-Dedup Pass
---
Near-duplicates auto-removed: {R}
Pairs flagged for merge review: {F}
```

**If `--phase extract`**: Stop here after writing `_idea_cards.ndjson`.

---

## Phase 2 — Dedup & Cluster

**Goal**: Collapse near-duplicate cards into canonical FeatureEntries with stable IDs.
This is the most critical phase — it determines the quality of the entire output.

### 2.1 Load IdeaCards

Read `{OUTPUT_ROOT}/_idea_cards.ndjson`. If it doesn't exist, run Phase 1 first.

### 2.2 Clustering Algorithm

Use a multi-signal similarity approach:

**Signal 1: Title Similarity** (weight: 0.3)
- Normalize titles: lowercase, remove punctuation, stem common words
- Jaccard similarity on word sets
- Threshold: 0.4 to be considered "similar"

**Signal 2: Source Overlap** (weight: 0.4)
- If two cards share ANY source file or source code path → strong cluster signal
- Shared source weight = number of shared sources / max(sources_a, sources_b)

**Signal 3: Category + Handler Type Match** (weight: 0.3)
- Same category AND overlapping handler_type → boost similarity
- Different category → penalty

**Clustering procedure**:
1. Compute pairwise similarity matrix for all cards
2. Apply agglomerative clustering with threshold 0.5
3. For each cluster, elect a canonical title:
   - Use the shortest precise title that appears in any member card
   - If tied, use the title from the card with the most source files
4. Compute stable cluster ID:
   ```
   cluster_id = SHA-256(sorted([card.card_id for card in cluster_members]))[:12]
   ```

### 2.3 Produce FeatureEntries

For each cluster, merge into a FeatureEntry:

```json
{
  "cluster_id": "a1b2c3d4e5f6",
  "canonical_title": "Kafka Adapter Effect Handler",
  "category": "infrastructure",
  "core_claim": "Best core_claim from member cards (longest, most specific)",
  "source_files": ["union of all member source_files"],
  "source_code_paths": ["union of all member source_code_paths"],
  "what_exists_today": ["union, deduplicated"],
  "missing_capabilities": ["union, deduplicated"],
  "handler_map": ["merged: unique handler entries only"],
  "dependencies": ["union"],
  "risk_notes": "merged risk notes",
  "effort_band": "most common band among members, or largest if tied",
  "member_card_ids": ["card_id_1", "card_id_2"],
  "member_count": 3,
  "impact_score": null,
  "ease_score": null
}
```

### 2.4 Score Impact and Ease

For each FeatureEntry, compute:

**Impact Score** (1-10):
- +3 if handler_map includes effect handlers (infrastructure capability)
- +2 if multiple source_code_paths exist (code already written)
- +2 if what_exists_today has integration points (compounds with existing)
- +2 if category is "intelligence" or "agent" (core differentiator)
- +1 if member_count > 2 (idea appears across multiple sources — validated)
- Cap at 10

**Ease Score** (1-10):
- +3 if effort_band is XS or S
- +2 if source_code_paths has port-ready code
- +2 if handler_map has specific candidate_paths
- +2 if what_exists_today shows existing infrastructure
- +1 if dependencies are few or already satisfied
- Cap at 10

### 2.5 Archive Handler Catalog

From the corpus index (Phase 0) and IdeaCards (Phase 1), produce a handler catalog
specifically for archive code:

For each archive code file with handler_candidacy:

| Archive Path | Handler Type | Port Notes | Dependencies | Effort | Referenced By |
|-------------|-------------|-----------|-------------|--------|--------------|
| `Archive/omnibase_5/src/.../tool_kafka_adapter/` | effect | Wrap in NodeEffect | Redpanda | S | cluster:a1b2c3 |

### 2.6 Write Phase 2 Artifacts

**`{OUTPUT_ROOT}/_clusters.json`**:
```json
{
  "run_id": "...",
  "created_at": "...",
  "total_clusters": 45,
  "total_cards_merged": 120,
  "clusters": [...]
}
```

**`{OUTPUT_ROOT}/IDEAS_REGISTRY.md`**:
```markdown
# OmniNode Ideas Registry

> Auto-generated by `/curate-legacy` — do not edit manually.
> Run ID: {run_id} | Generated: {date} | Clusters: {N} | Sources: {M} files

## Impact/Effort Matrix

### High Impact + Easy (DO FIRST)
| ID | Title | Category | Impact | Ease | Effort | Sources |
|----|-------|----------|--------|------|--------|---------|
| a1b2c3 | Kafka Adapter Effect | infra | 9 | 8 | S | 3 files |

### High Impact + Hard (PLAN CAREFULLY)
...

### Low Impact + Easy (QUICK WINS)
...

### Low Impact + Hard (DEFER)
...

## Full Registry

{All clusters sorted by impact_score descending, with provenance links}

## Statistics

- Total ideas extracted: {cards}
- Unique features after dedup: {clusters}
- Dedup ratio: {cards/clusters:.1f}x
- Categories: {category breakdown}
- Handler types: {handler type breakdown}
- Effort bands: {effort breakdown}
```

**`{OUTPUT_ROOT}/ARCHIVE_HANDLER_CATALOG.md`**:
```markdown
# Archive Handler Catalog

> Imperative code in `/Volumes/PRO-G40/Code/Archive/` classified by ONEX handler type. <!-- local-path-ok -->
> Use this to find port-ready code when implementing handler tickets.

## Effect Handlers (External I/O)
{table}

## Compute Handlers (Pure Functions)
{table}

## Reducer Handlers (State Machines)
{table}

## Orchestrator Handlers (Workflow Coordination)
{table}
```

**If `--phase cluster`**: Stop here.

---

## Phase 3 — Spec Generation

**Goal**: For each FeatureEntry cluster, generate a handler-first execution spec.

### 3.1 Load Clusters

Read `{OUTPUT_ROOT}/_clusters.json`. If it doesn't exist, run Phase 2 first.

### 3.2 Determine Spec Domain Directory

Map category to directory:
```
infrastructure → specs/infrastructure/
intelligence   → specs/intelligence/
governance     → specs/governance/
devex          → specs/devex/
agent          → specs/agent/
learning       → specs/learning/
platform       → specs/platform/
```

### 3.3 Spec Template

Each spec follows this template:

```markdown
# {canonical_title}

> Cluster ID: {cluster_id} | Category: {category} | Impact: {impact}/10 | Ease: {ease}/10
> Sources: {member_count} documents | Effort: {effort_band}
> Generated by `/curate-legacy` run {run_id}

## Goal & Scope

{core_claim expanded to 2-3 sentences}

### Non-Goals
{What this spec explicitly does NOT cover}

## Existing Assets

### Current Repos
{what_exists_today as bullet list with repo:path references}

### Salvageable Archive Code
{source_code_paths with brief description of what each contains}

## Handler Decomposition

### {handler_type_1}: {handler_description}
- **Contract**: {input_type} → {output_type}
- **Events emitted**: {topic names if applicable}
- **Port from**: {candidate_paths or "new implementation"}
- **Key logic**: {what the handler actually does}

### {handler_type_2}: ...
{repeat for each handler in handler_map}

## Integration Points

### Kafka Topics
{topics this feature produces or consumes}

### Database Tables/Projections
{tables, projections, or read-models involved}

### Dashboard Widgets
{omnidash pages or widgets that would visualize this feature}

## Migration Plan

1. {first thing to port/build}
2. {second step}
3. {verification step}

## Risks & Non-Goals

{risk_notes from cluster}

## Provenance

Source documents:
{source_files as bullet list with full paths}

Source code:
{source_code_paths as bullet list with full paths}
```

### 3.4 Dispatch Spec Writers

Spec generation can be parallelized. Group clusters by category and dispatch agents:

```
Task(
  subagent_type="onex:polymorphic-agent",
  description="Generate specs: {category} ({N} clusters)",
  prompt="Generate handler-first execution specs for these feature clusters.

    ## Spec Template
    {template}

    ## Clusters to Spec
    {cluster_json_list}

    ## Context: Current Architecture
    The platform uses a four-node handler pattern:
    - EFFECT: External I/O, gateway calls, Kafka producers
    - COMPUTE: Pure functions, deterministic, replay-safe
    - REDUCER: FSM state machines, guard projections
    - ORCHESTRATOR: Workflow coordination, conditional routing

    All behavior is contract-driven (YAML). Handlers are thin. Bus-only execution via Kafka.

    ## Rules
    1. Every spec MUST have a Handler Decomposition section
    2. Every handler MUST specify contract (input → output)
    3. Keep specs to 2-3 pages. Link to sources for depth.
    4. Migration Plan must be concrete (port order, tests, verification)
    5. Do NOT invent new architecture — map to existing four-node pattern
    6. If archive code exists, specify what to extract and what to discard

    Output each spec as a separate markdown document. Return as JSON:
    {\"specs\": [{\"cluster_id\": \"...\", \"slug\": \"...\", \"content\": \"...\"}]}"
)
```

### 3.5 Write Specs

For each spec:
1. Compute file path: `{OUTPUT_ROOT}/specs/{category}/{cluster_id}_{slug}.md`
2. Before writing, check if file exists with same content hash — skip if unchanged
3. Write the file
4. Track: new files created vs existing files updated vs unchanged

### 3.6 Generate Spec Index

**Invariant 1 — No telemetry in descriptions**: Before writing any entry to the INDEX, check `core_claim` for banned strings: `"Archive package"`, `"Dominant pattern:"`, `"Signals: has"`, path fragments (`"/Volumes/"`, `"/Users/"`), `"type_guess"`. Any entry with a banned string in `core_claim` is OMITTED from the INDEX and logged as "INDEX entry omitted (telemetry in description): {title}".

**Invariant 2 — Document source required**: Entries that exist only from archive code (no `source_files[]` pointing to a document) are OMITTED from the INDEX. Archive-code-only clusters belong in `ARCHIVE_HANDLER_CATALOG.md`, not in the INDEX.

**Invariant 3 — Description length cap**: Truncate `core_claim` to 240 characters before writing to any INDEX entry. Add `…` if truncated.

**Sort order within each category section**: `implemented → partial → planned → blocked → aspirational → deprecated`

**Status badges**:
- `✅ implemented`
- `🔶 partial`
- `🔲 planned`
- `🚫 blocked`
- `💡 aspirational`
- `⛔ deprecated`

Write `{OUTPUT_ROOT}/specs/INDEX.md`:

```markdown
# Spec Index

> {N} specs across {M} categories | Generated: {date}
> Run ID: {run_id} | Status scan: {ran|skipped}

## Implementation Status Summary

> Omit this table if Phase 0.5 was skipped (`--skip-status-scan`).

| Status | Count |
|--------|-------|
| ✅ implemented | {N} |
| 🔶 partial | {N} |
| 🔲 planned | {N} |
| 🚫 blocked | {N} |
| 💡 aspirational | {N} |
| ⛔ deprecated | {N} |

## Navigation

{Category links, one per line: [Infrastructure](#infrastructure-n-specs), [Intelligence](#intelligence-n-specs), ...}

## By Category

### Infrastructure ({N} specs)

| Status | Spec | Impact | Ease | Effort | Handlers |
|--------|------|--------|------|--------|----------|
| ✅ | [Kafka Adapter Effect](infrastructure/a1b2c3_kafka-adapter-effect.md) | 9 | 8 | S | effect |
| 🔶 | [Streaming Aggregator](infrastructure/b2c3d4_streaming-aggregator.md) | 7 | 6 | M | reducer |

### Intelligence ({N} specs)
...

{Repeat for each category, sorted: implemented → partial → planned → blocked → aspirational → deprecated}

---

## All Specs — Flat List

> Copy-paste this section into agent context for full spec discovery.

{One line per spec: `[Title](path/to/spec.md) — {core_claim truncated to 120 chars}` sorted by impact_score descending}

---

## Impact/Effort Quadrant

### Q1: High Impact + Easy (Top Priority)
{list with status badge}

### Q2: High Impact + Hard (Strategic Investment)
{list with status badge}

### Q3: Low Impact + Easy (Fill-in Work)
{list with status badge}

### Q4: Low Impact + Hard (Deprioritize)
{list with status badge}
```

**If `--phase specs`**: Stop here.

---

## Idempotency Protocol

### Content-Hash Guard

Before writing ANY output file:
1. If file exists, compute SHA-256 of current content
2. Compute SHA-256 of new content
3. If hashes match → skip write, log "unchanged: {path}"
4. If hashes differ → write, log "updated: {path}"
5. If file doesn't exist → write, log "created: {path}"

### Stable IDs

- Corpus index entries: keyed by file path (stable across runs)
- IdeaCards: `card_id` is generated fresh each run (cards are ephemeral)
- Clusters: `cluster_id` is computed from sorted member card content hashes
  - Same inputs → same cluster_id, even if card_ids change
- Specs: file path is `{cluster_id}_{slug}.md` — stable as long as cluster membership is stable

### Incremental Updates

When a corpus root has new files since last run:
1. Phase 0 detects new files (not in previous `_corpus_index.json`)
2. Phase 1 extracts cards for new files only (append to `_idea_cards.ndjson`)
3. Phase 2 reclusters ALL cards (existing + new)
4. Phase 3 regenerates only specs whose clusters changed

---

## Deep-Read Mode

When `--deep-read` is specified with category slugs:

1. After Phase 0, identify archive code files classified under those categories
2. In Phase 1, dispatch dedicated agents to deep-read those code files:
   - Read actual Python source
   - Identify public APIs, classes, functions
   - Classify side effects and dependencies
   - Assess test coverage availability
   - Produce enhanced IdeaCards with detailed `port_notes`

This is slower but produces much higher quality handler_map entries for the specified
categories.

Without `--deep-read`, archive code is classified by heuristics only (fast catalog pass).

---

## Output Summary

After completing all phases, print:

```
Curate Legacy Complete
---
Run ID: {run_id}
Corpus roots scanned: {N}
Files indexed: {total_files}
IdeaCards extracted: {cards_emitted}
IdeaCards rejected: {cards_rejected}
  - No handler_map: {rejected_no_handler}
  - No provenance: {rejected_no_provenance}
  - core_claim quality gate: {rejected_quality_gate}
Clusters formed: {total_clusters}
Dedup ratio: {cards/clusters:.1f}x
Specs created: {new}
Specs updated: {updated}
Specs unchanged: {unchanged}
Archive handlers cataloged: {handler_count}

Implementation Status (Phase 0.5):
  Status scan: {ran|skipped}
  implemented: {count_implemented}
  partial:     {count_partial}
  planned:     {count_planned}
  blocked:     {count_blocked}
  aspirational:{count_aspirational}
  deprecated:  {count_deprecated}

Quality Gate Counts:
  Cards rejected (core_claim): {rejected_quality_gate}
  Near-duplicates auto-removed: {dedup_auto_removed}
  Near-duplicate pairs flagged for review: {dedup_flagged}
  INDEX entries omitted (telemetry): {index_omitted_telemetry}
  INDEX entries omitted (missing doc source): {index_omitted_no_doc}

Output: {OUTPUT_ROOT}/
Registry: {OUTPUT_ROOT}/IDEAS_REGISTRY.md
Catalog: {OUTPUT_ROOT}/ARCHIVE_HANDLER_CATALOG.md
Specs: {OUTPUT_ROOT}/specs/INDEX.md
```

---

## Error Handling

| Error | Behavior |
|-------|----------|
| Corpus root doesn't exist | Skip with warning, continue other roots |
| Agent returns invalid JSON | Log error, skip that agent's output, continue |
| Card fails validation | Reject card, log reason, continue |
| File unreadable (permissions) | Skip with warning, continue |
| Phase prerequisite missing | Run prerequisite phase first |
| `--dry-run` | Log all writes that would happen, write nothing |

---

## Dispatch Contracts

**Rule: ALL Task() calls MUST use subagent_type="onex:polymorphic-agent".**
**Rule: NO git operations in spawned agents. Git is coordinator-only.**
**Rule: Coordinator may use Write/Edit for output artifacts only (registry files).**
**Rule: Spawned agents use Read/Glob/Grep/Bash(read-only) only — they extract, not write.**
