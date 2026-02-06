# Proposal: Fuzzy Matcher Improvements for Agent Routing

**Date**: 2026-02-06
**Branch**: `feat/polymorphic-agent-restoration`
**Ticket**: OMN-1980
**Status**: Proposal (reviewed, ready for implementation)

---

## Scoring Semantics Contract

Scores produced by `TriggerMatcher` are **relative ranking signals only**.

- Scores are ordinal, not cardinal. A score of 0.8 does not mean "80% confidence" — it means "ranked higher than 0.7."
- **Scores are not comparable across prompts.** A 0.75 for prompt A and 0.75 for prompt B do not indicate equivalent match quality.
- Scores exist solely to sort candidates within a single routing call. Downstream consumers (Phase 1 Claude selector, Phase 2 local model) make the actual selection.
- Internal variable naming uses `rank_score` to reinforce this semantic.

### Threshold Semantics

| Threshold | Purpose | Semantic |
|-----------|---------|----------|
| `hard_floor` (0.55) | Minimum for inclusion in candidate list | Below this, the match is noise |
| `fuzzy_threshold` (tiered) | Minimum SequenceMatcher similarity to count as fuzzy match | Prevents character-level false positives |
| `dispatch_threshold` (0.7) | Minimum for automatic agent dispatch (legacy) | Phase 1 bypasses this — Claude picks regardless |

---

## Determinism Guarantees

`TriggerMatcher` is **deterministic given identical registry + prompt**.

Implementation requirements:
- Agents are sorted by name before scoring (`sorted(self.registry["agents"].items())`)
- Triggers within each agent are processed in YAML-defined order (list ordering preserved)
- IDF weights are computed once at registry load time and frozen
- No randomness, no time-dependent logic, no external calls
- `dict` iteration order is CPython-stable but we sort explicitly to be safe

**Replay contract**: Given the same `agent_router.py` code, the same set of agent YAML files, and the same user prompt, `TriggerMatcher.match()` returns identical results across runs, processes, and machines.

---

## Non-Goals

The following are explicitly **out of scope** for `TriggerMatcher`:

- Semantic understanding of user intent
- Natural language paraphrase detection
- Cross-sentence reasoning or conversational context
- Agent disambiguation beyond trigger/capability surface matching
- Embedding-based similarity (cosine similarity, vector search)
- LLM calls of any kind

**Architectural guardrail**: `TriggerMatcher` MUST NOT incorporate semantic embeddings or LLM calls. This layer is a cheap, deterministic filter — not a decision-maker. Semantic matching belongs exclusively in:
- Phase 1: Claude as selector (current)
- Phase 2: Local Qwen 14B as selector (future)

Without this guardrail, this code will inevitably accrete "just one embedding call" and destroy both latency (<100ms budget) and debuggability (deterministic replay).

---

## Problem Statement

The `TriggerMatcher` in `agent_router.py` produces high-confidence false positives that pollute the candidate list. Even with Phase 1 candidate list injection (where Claude makes the final selection), bad candidates waste context tokens and create noise.

### Observed False Positives

| Prompt | Matched Agent | Score | Cause |
|--------|--------------|-------|-------|
| "Commit the changes" | `agent-commit` | 0.54 | Correct, but low confidence |
| "Review PR 92" | `agent-contract-validator` | 0.77 | "review" fuzzy-matches validator triggers |
| "Create a proposal for the fuzzy matcher" | `agent-frontend-developer` | 0.71 | "create" fuzzy-matches "react" at 73% |
| "Are you sure you're dispatching?" | `agent-frontend-developer` | 0.74 | "react" fuzzy-match from unrelated words |
| Model-level assessment text (long) | `agent-python-fastapi-expert` | 0.75 | "python" exact match in technical prose |

### Root Cause Analysis

**`_fuzzy_match()` (line 516-528)** compares each trigger against every word in the prompt using `SequenceMatcher.ratio()`. The 0.7 threshold is too permissive for short words:

```python
# "create" vs "react" → SequenceMatcher gives 0.727 (5 of 6 chars overlap)
SequenceMatcher(None, "react", "create").ratio()  # 0.727

# "review" vs "remove" → 0.667 (just under threshold, but close)
SequenceMatcher(None, "review", "remove").ratio()  # 0.667

# "debug" vs "rebug" → 0.8 (high match for nonsense)
```

The problem: **SequenceMatcher measures character-level similarity, not semantic similarity.** Short triggers (4-6 chars) with common letter patterns produce false matches against unrelated words.

**`_keyword_overlap_score()` (line 530-541)** compounds the issue by matching common English words that appear in both triggers and prompts (e.g., "test", "create", "build").

**`_capability_match_score()` (line 543-556)** has the same problem — broad capability descriptions match nearly any technical prompt.

**Full-text SequenceMatcher (line 527-528)** compares a 5-char trigger against a 50-char prompt — this is pure noise and should be removed unconditionally.

---

## Proposed Fixes (Ranked by Impact/Effort)

### Fix 1: Tiered Fuzzy Threshold by Trigger Length (Quick Win)

**Impact**: High | **Effort**: 30 min | **Risk**: Low

Short triggers need a higher similarity threshold because character overlap is less meaningful with fewer characters. Tiered thresholds prevent both short-trigger false positives and long-trigger over-permissiveness.

```python
def _fuzzy_threshold(self, trigger: str) -> float:
    """Dynamic threshold: shorter triggers need higher similarity."""
    n = len(trigger)
    if n <= 6:
        return 0.85
    elif n <= 10:
        return 0.78
    else:
        return 0.72

def _fuzzy_match(self, trigger: str, text: str) -> float:
    if self._exact_match_with_word_boundaries(trigger, text):
        return 1.0

    min_threshold = self._fuzzy_threshold(trigger)

    words = re.findall(r"\b\w+\b", text.lower())
    best_word_score = 0.0
    for word in words:
        word_score = SequenceMatcher(None, trigger, word).ratio()
        if word_score >= min_threshold:
            best_word_score = max(best_word_score, word_score)

    return best_word_score  # full-text score removed (see Fix 6)
```

**Effect on observed false positives:**
- "create" vs "react": 0.727 < 0.85 (6 chars) -> BLOCKED
- "review" vs "remove": 0.667 < 0.85 (6 chars) -> BLOCKED
- "commit" vs "commit": 1.0 exact match -> PASSES
- "kubernetes" vs "kubernetes": 1.0 exact, threshold 0.72 (10 chars) -> PASSES

### Fix 2: Require Minimum Bigram Overlap (Medium Win)

**Impact**: High | **Effort**: 1 hour | **Risk**: Low

Gate SequenceMatcher behind a bigram check. Two words must share meaningful character subsequences before expensive similarity computation runs.

```python
def _has_meaningful_overlap(self, trigger: str, word: str) -> bool:
    """Check if trigger and word share meaningful character sequences."""
    trigger_bigrams = {trigger[i:i+2] for i in range(len(trigger) - 1)}
    word_bigrams = {word[i:i+2] for i in range(len(word) - 1)}

    shared = trigger_bigrams & word_bigrams
    min_shared = 2 if len(trigger) <= 6 else 3

    return len(shared) >= min_shared
```

### Fix 3: Multi-Word Trigger Bonus (Medium Win)

**Impact**: Medium | **Effort**: 30 min | **Risk**: Low

Multi-word triggers ("pr review", "code quality") are more specific than single-word triggers. Apply a monotonic additive bonus *after* thresholding to preserve ordering semantics.

```python
import math

# In match(), after fuzzy thresholding:
for trigger in triggers:
    similarity = self._fuzzy_match(trigger.lower(), user_lower)
    if similarity > 0.7:
        word_count = len(trigger.split())
        # Monotonic transform, capped: log(1)=0, log(2)=0.035, log(3)=0.055
        # Cap at 0.08 to prevent pathological long triggers from dominating similarity
        specificity_bonus = min(math.log(word_count) * 0.05, 0.08) if word_count > 1 else 0.0
        rank_score = similarity + specificity_bonus

        scores.append((rank_score, f"Fuzzy match: '{trigger}' ({similarity:.0%})"))
```

### Fix 4: Negative Triggers / Exclusion Patterns (Medium Win)

**Impact**: Medium | **Effort**: 1 hour | **Risk**: Low

Allow agents to declare patterns that should NOT match.

```yaml
# In agent YAML
activation_patterns:
  explicit_triggers: ["react", "frontend", "component"]
  negative_triggers: ["backend", "routing", "commit", "git", "deploy"]
```

```python
# In match():
negative_triggers = agent_data.get("negative_triggers", [])
for neg in negative_triggers:
    if self._exact_match_with_word_boundaries(neg, user_lower):
        scores.clear()  # Cancel all positive matches
        break
```

### Fix 5: TF-IDF Weighted Scoring (Bigger Win, More Effort)

**Impact**: High | **Effort**: 3-4 hours | **Risk**: Medium

Common words across many agents' triggers should count less. Rare triggers are strong discriminators.

```python
def _build_idf_weights(self) -> dict[str, float]:
    """Compute inverse document frequency for trigger words.

    Computed once at registry load time and frozen.
    Agents are sorted by name for deterministic iteration.
    """
    word_doc_count: dict[str, int] = {}
    total_agents = len(self.registry.get("agents", {}))

    for _name, agent_data in sorted(self.registry.get("agents", {}).items()):
        triggers = agent_data.get("activation_triggers", [])
        words_in_agent = set()
        for trigger in triggers:
            words_in_agent.update(re.findall(r"\b\w+\b", trigger.lower()))
        for word in words_in_agent:
            word_doc_count[word] = word_doc_count.get(word, 0) + 1

    return {
        word: math.log(total_agents / count)
        for word, count in word_doc_count.items()
    }
```

Then weight keyword overlap scores by IDF:
```python
def _keyword_overlap_score(self, keywords, triggers) -> float:
    # ... existing logic ...
    weighted_overlap = sum(self.idf_weights.get(w, 1.0) for w in keyword_set & trigger_words)
    weighted_total = sum(self.idf_weights.get(w, 1.0) for w in keyword_set)
    return weighted_overlap / weighted_total if weighted_total else 0.0
```

### Fix 6: Remove Full-Text SequenceMatcher (Quick Win)

**Impact**: Medium | **Effort**: 15 min | **Risk**: None

Line 527-528 computes `SequenceMatcher(None, trigger, text).ratio()` against the FULL prompt text. This is pure noise. Remove unconditionally.

```python
def _fuzzy_match(self, trigger: str, text: str) -> float:
    if self._exact_match_with_word_boundaries(trigger, text):
        return 1.0

    words = re.findall(r"\b\w+\b", text.lower())
    best_word_score = 0.0
    for word in words:
        word_score = SequenceMatcher(None, trigger, word).ratio()
        best_word_score = max(best_word_score, word_score)

    # REMOVED: full_text_score = SequenceMatcher(None, trigger, text).ratio()
    return best_word_score
```

---

## No Confident Candidates Behavior

When all candidates score below a hard floor, the candidate list should be **empty** rather than populated with noise. This lets Claude fall back to general reasoning instead of bad routing.

### Hard Floor

`HARD_FLOOR` is a **safety invariant**, not a tuning knob:
- NOT agent-configurable
- NOT registry-configurable
- Changes require code review

If this becomes configurable too early, people will lower it to "fix routing" and reintroduce noise.

```python
HARD_FLOOR = 0.55  # Safety invariant. Changes require code review.

def match(self, user_request: str) -> list[tuple[str, float, str]]:
    # ... existing matching logic ...

    # Filter: remove matches below hard floor
    matches = [(name, score, reason) for name, score, reason in matches if score >= HARD_FLOOR]

    matches.sort(key=lambda x: x[1], reverse=True)
    return matches
```

### Tight Clustering Detection

When multiple candidates cluster within 0.05 of each other, the matcher cannot meaningfully discriminate. Signal this to downstream consumers:

```python
# In route_via_events_wrapper.py, when building candidates:
if len(candidates_list) >= 2:
    top_score = candidates_list[0]["score"]
    second_score = candidates_list[1]["score"]
    if abs(top_score - second_score) < 0.05:
        # Tight cluster — fuzzy best is unreliable
        # Downstream (Claude/LLM) should weight its own judgment higher
        result["cluster_warning"] = True
```

---

## Recommended Implementation Order

| Priority | Fix | Impact | Effort | Dependencies |
|----------|-----|--------|--------|--------------|
| 1 | Fix 6: Remove full-text SequenceMatcher | Medium | 15 min | None |
| 2 | Fix 1: Tiered threshold by trigger length | High | 30 min | None |
| 3 | Hard floor (0.55) + empty list behavior | High | 15 min | None |
| 4 | Fix 3: Multi-word trigger bonus (log transform) | Medium | 30 min | None |
| 5 | Fix 2: Bigram overlap gate | High | 1 hour | None |
| 6 | Fix 5: TF-IDF weighting | High | 3-4 hours | None |
| 7 | Fix 4: Negative triggers | Medium | 1 hour | Agent YAML changes |

**Fixes 6, 1, hard floor, and 3 can be implemented together in ~1.5 hours** and would eliminate all observed false positives. Fixes 2 and 5 provide additional precision but require more testing.

---

## Success Criteria

After implementing fixes, verify these cases:

| Prompt | Expected Top Candidate | Should NOT Match |
|--------|----------------------|------------------|
| "Review PR 92" | `agent-pr-review` | `agent-contract-validator` |
| "Commit the changes" | `agent-commit` | anything else above hard floor |
| "Create a proposal" | Empty candidate list | `agent-frontend-developer` |
| "Debug this test failure" | `agent-debug` or `agent-testing` | `agent-frontend-developer` |
| "Deploy to production" | `agent-devops` | `agent-pr-create` |
| "Help me write a React component" | `agent-frontend-developer` | (correct match) |
| "You have been restarted" | Empty candidate list | any agent |
| Long technical prose about Python | Empty or very low | `agent-python-fastapi-expert` (incidental word match) |

---

## Trigger Normalization

All text comparison paths (trigger preprocessing, prompt tokenization, keyword overlap, capability matching) MUST use a shared normalization function:

```python
import unicodedata

def _normalize(text: str) -> str:
    """Canonical normalization for trigger matching.

    Applied to both triggers and prompt tokens. Ensures deterministic
    comparison across platforms and input sources.
    """
    # Unicode NFKC normalization (compatibility decomposition + canonical composition)
    text = unicodedata.normalize("NFKC", text)
    # Lowercase
    text = text.lower()
    # Hyphens and underscores are word boundaries (not joined)
    text = text.replace("-", " ").replace("_", " ")
    # Strip non-alphanumeric except spaces
    text = re.sub(r"[^\w\s]", "", text)
    return text.strip()
```

This prevents subtle mismatches (e.g., curly quotes, en-dashes, Unicode whitespace) and keeps determinism intact across platforms.

---

## Testing Requirements

### Replay Determinism Tests

```python
def test_deterministic_across_runs():
    """Same registry + same prompt → identical ordering and scores."""
    router = AgentRouter(configs_dir=FIXTURES_DIR)
    result_1 = router.route("Review PR 92")
    result_2 = router.route("Review PR 92")
    assert [(r.agent_name, r.confidence.total) for r in result_1] == \
           [(r.agent_name, r.confidence.total) for r in result_2]
```

### Regression Lock Tests

```python
@pytest.mark.parametrize("prompt,blocked_agent", [
    ("Create a proposal", "agent-frontend-developer"),
    ("Review PR 92", "agent-contract-validator"),
    ("Are you sure you're dispatching?", "agent-frontend-developer"),
])
def test_known_false_positives_stay_blocked(prompt, blocked_agent):
    """Previously observed false positives must stay below HARD_FLOOR.

    These tests fail loudly if someone 'improves' matching later
    and reintroduces known bad matches.
    """
    router = AgentRouter(configs_dir=FIXTURES_DIR)
    recommendations = router.route(prompt)
    matched_names = [r.agent_name for r in recommendations]
    assert blocked_agent not in matched_names, \
        f"Regression: {blocked_agent} matched '{prompt}' — this was a known false positive"
```

---

## Interaction with Phase 1 (Candidate List)

These fixes improve the **candidate generation quality** that feeds into the Phase 1 candidate list. Even though Claude makes the final selection, better candidates mean:
- Less wasted context tokens on irrelevant agents
- Claude doesn't need to filter as much noise
- The "FUZZY BEST" indicator becomes more trustworthy
- Edge cases where all candidates are wrong become rarer
- Empty candidate lists for non-routing prompts → zero noise

## Interaction with Phase 2 (Local LLM Selector)

Better candidates also reduce the burden on the future Qwen 14B selector. A local model with a small context window benefits significantly from receiving 3-5 relevant candidates vs 3-5 noisy ones. The hard floor ensures the local model only sees matches above noise threshold.
