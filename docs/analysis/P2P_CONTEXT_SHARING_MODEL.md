# P2P Context Sharing Model - Decentralized Intelligence Network

**Date**: 2025-11-09
**Related**: DEBUG_REWARDS_CLARIFICATION_ANALYSIS.md (Phase 3 expansion)
**Model**: BitTorrent-like tracker + compute token incentives

---

## Executive Summary

**Vision**: A decentralized, peer-to-peer knowledge graph where participants earn compute tokens by sharing context/intelligence with other nodes. Instead of sending full context to LLMs (expensive), store metadata/pointers in a distributed graph and use RAG to retrieve only what's needed.

**Economic Model**:
- **Earn tokens**: By serving context to peers (outgoing bandwidth/queries)
- **Spend tokens**: On compute (LLM inference, embeddings, etc.)
- **Self-sustaining**: Network participants fund each other through natural usage

**Architecture**: BitTorrent-like tracker + distributed hash table (DHT) + compute token ledger

---

## The Problem (Current State)

### LLM Context Costs

**Current approach**: Send full context to LLM with every request
- Expensive: $3-15 per 1M input tokens depending on model
- Slow: Large context = longer processing time
- Wasteful: Most context is irrelevant to specific query
- Centralized: All context must go through central LLM provider

**Example**:
```
User query: "How do I implement ONEX Effect node?"

Current: Send entire ONEX docs (500KB) → LLM → response
Cost: ~$2-5 per query (500K tokens @ $4-10/1M)

P2P model: Query graph → Find relevant nodes → Retrieve 50KB → LLM → response
Cost: ~$0.20-0.50 per query (50K tokens)
Savings: 90% cost reduction
```

### Centralized Knowledge Storage

**Current issues**:
- Single point of failure (if Qdrant goes down, no intelligence)
- No incentive to contribute (altruism only)
- Limited by single organization's storage capacity
- No way to discover knowledge outside your system

---

## The Solution: P2P Context Sharing Network

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER QUERY                                    │
│          "How do I implement ONEX Effect node?"                  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  Local Intelligence  │
            │  - Metadata graph    │
            │  - Pointers to peers │
            │  - Cache layer       │
            └──────────┬───────────┘
                       │
                       ▼
            ┌──────────────────────┐
            │  P2P Tracker         │
            │  "Who has ONEX docs?"│
            │  → Peer A, B, C      │
            └──────────┬───────────┘
                       │
                       ▼
         ┌─────────────┴─────────────┐
         │                           │
    ┌────▼─────┐  ┌────▼─────┐  ┌───▼──────┐
    │ Peer A   │  │ Peer B   │  │ Peer C   │
    │ (online) │  │ (online) │  │ (offline)│
    │ Earns 10 │  │ Earns 10 │  │ Earns 0  │
    │ tokens   │  │ tokens   │  │ tokens   │
    └────┬─────┘  └────┬─────┘  └──────────┘
         │             │
         └──────┬──────┘
                │ (serve context)
                ▼
      ┌───────────────────┐
      │  RAG Retrieval    │
      │  50KB most        │
      │  relevant context │
      └────────┬──────────┘
               │
               ▼
      ┌───────────────────┐
      │  LLM (Gemini)     │
      │  Cost: $0.20      │
      │  vs $2.00         │
      │  (90% savings)    │
      └────────┬──────────┘
               │
               ▼
      ┌───────────────────┐
      │  Response         │
      │  to user          │
      └───────────────────┘
```

### Key Components

#### 1. P2P Tracker (BitTorrent-like)

**Purpose**: Discover which peers have which context

**Protocol**:
```json
{
  "announce": "https://tracker.omninode.ai/announce",
  "peers": [
    {
      "peer_id": "abc123...",
      "ip": "192.168.1.100",
      "port": 6881,
      "has_context": ["onex_docs", "python_stdlib", "agent_patterns"],
      "online": true,
      "reputation": 0.95,
      "uptime": "99.2%"
    }
  ]
}
```

**Operations**:
- `announce`: Register what context you have (heartbeat every 30s)
- `scrape`: Query who has specific context
- `peer_list`: Get list of peers with requested context
- `reputation`: Track peer reliability for token rewards

#### 2. Distributed Metadata Graph

**Storage**: Local graph database (Memgraph, Neo4j, or simple SQLite)

**Structure**:
```cypher
// Node: Knowledge chunk
(:Context {
  hash: "sha256:abc123...",
  title: "ONEX Effect Node Implementation",
  size_bytes: 4096,
  embedding_vector: [...],
  tags: ["onex", "effect", "node", "python"],
  peers_with_content: ["peer_a", "peer_b"],
  last_updated: "2025-11-09T10:30:00Z"
})

// Edge: Relationships
(:Context)-[:REFERENCES]->(:Context)
(:Context)-[:PART_OF]->(:Document)
(:Context)-[:AUTHORED_BY]->(:Peer)
```

**Benefits**:
- Fast local queries (no network roundtrip for metadata)
- Stores pointers, not full content (minimal storage)
- Can query "who has X?" without downloading X
- RAG-optimized (embedding vectors for similarity search)

#### 3. Compute Token Ledger

**Database**: PostgreSQL table (or local SQLite)

```sql
CREATE TABLE token_ledger (
    id UUID PRIMARY KEY,
    peer_id TEXT NOT NULL,
    transaction_type TEXT, -- 'earned', 'spent'
    amount NUMERIC NOT NULL,
    reason TEXT,
    context_hash TEXT, -- What context was served/retrieved
    requester_peer_id TEXT, -- Who requested (if earned)
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE peer_balances (
    peer_id TEXT PRIMARY KEY,
    balance NUMERIC DEFAULT 0,
    total_earned NUMERIC DEFAULT 0,
    total_spent NUMERIC DEFAULT 0,
    contexts_served INT DEFAULT 0,
    contexts_retrieved INT DEFAULT 0,
    reputation NUMERIC DEFAULT 1.0
);
```

**Token Flow**:
1. Peer A requests context from Peer B
2. Peer B serves context (5KB)
3. Peer B earns 10 tokens (2 tokens per KB)
4. Peer A spends 10 tokens (deducted from balance)
5. Transaction logged in ledger

#### 4. Context Serving Protocol

**HTTP API** (or gRPC for efficiency):

```http
GET /context/{hash}
Authorization: Bearer {peer_token}
X-Requester-Peer-ID: peer_a

Response:
200 OK
Content-Type: application/json
X-Token-Cost: 10
X-Context-Size-Bytes: 5120

{
  "hash": "sha256:abc123...",
  "content": "...",
  "metadata": {...},
  "embedding": [...]
}
```

**Token Deduction**:
- Automatic via smart contract or API call
- Requester signs transaction with private key
- Server validates signature and deducts tokens
- Server credits tokens to serving peer

---

## Economic Model Details

### Token Earning (Supply Side)

**How peers earn tokens**:

| Activity | Tokens Earned | Notes |
|----------|---------------|-------|
| **Serve context** | 2 tokens/KB | Bandwidth incentive |
| **Contribute new context** | 100-1000 tokens | One-time reward for novel content |
| **Maintain high uptime** | 10 tokens/day | Reliability bonus |
| **Verify other peers' context** | 5 tokens/verification | Quality control |
| **Run tracker node** | 50 tokens/day | Infrastructure support |

**Example earnings**:
- Serve 100 KB/day → 200 tokens/day
- Contribute 10 new documents → 1000 tokens one-time
- 99% uptime → 10 tokens/day
- **Total**: ~210 tokens/day sustainable

### Token Spending (Demand Side)

**How peers spend tokens**:

| Activity | Tokens Spent | Notes |
|----------|--------------|-------|
| **Retrieve context from peer** | 2 tokens/KB | Matches serving rate |
| **LLM inference** | Variable | Based on provider pricing |
| **Embedding generation** | 0.1 tokens/doc | For new contributions |
| **Priority queries** | 2x normal | Fast lane for urgent requests |

**Example spending**:
- Retrieve 50 KB/day → 100 tokens/day
- 10 LLM queries/day → 100 tokens/day (avg 10 tokens/query)
- **Total**: ~200 tokens/day sustainable

**Equilibrium**: Average peer earns ~210 tokens/day, spends ~200 tokens/day → slight surplus encourages participation

### Token Economics Calibration

**Initial parameters** (adjustable dynamically):
```yaml
# Serving rates
tokens_per_kb_served: 2
new_context_bonus: 100-1000  # Based on uniqueness
uptime_bonus: 10/day
verification_reward: 5

# Retrieval costs
tokens_per_kb_retrieved: 2  # Matches serving
llm_cost_multiplier: 1.0    # 1:1 with provider pricing
embedding_cost_per_doc: 0.1

# Free tier
new_user_starter_tokens: 1000
daily_free_tier_tokens: 50  # For light usage

# Reputation
min_reputation_to_earn: 0.5
max_reputation_bonus: 1.5x
reputation_decay_rate: 0.01/day (if offline)
```

**Dynamic adjustments**:
- If token velocity too high → increase earning rates
- If token velocity too low → decrease earning rates
- If peers hoard tokens → add expiration (e.g., 10% decay/year)
- If peers run out → increase free tier allocation

---

## Implementation Phases

### Phase 1: Centralized P2P Tracker (2-3 weeks)

**Goal**: Prove P2P discovery works with centralized tracker

**Deliverables**:
- Tracker server (announce, scrape, peer_list endpoints)
- Peer client library (announce context, discover peers)
- Basic token ledger (PostgreSQL)
- Context serving protocol (HTTP API)
- Metadata graph (local SQLite or Memgraph)

**Architecture**:
```
┌──────────┐      ┌──────────┐      ┌──────────┐
│ Peer A   │◀────▶│ Tracker  │◀────▶│ Peer B   │
│ (client) │      │ (central)│      │ (client) │
└──────────┘      └──────────┘      └──────────┘
     │                                    │
     └────────── P2P content ────────────┘
              (direct connection)
```

**Success metrics**:
- 10+ peers register with tracker
- 100+ context chunks served peer-to-peer
- Token earning/spending works correctly
- 50%+ cost reduction vs full-context LLM queries

### Phase 2: DHT for Decentralization (3-4 weeks)

**Goal**: Remove centralized tracker dependency

**Deliverables**:
- Distributed Hash Table (Kademlia or Chord)
- Peer discovery without central tracker
- Content-addressable storage (IPFS-like)
- Reputation tracking across DHT
- Token ledger consensus (simple PoA or federated)

**Architecture**:
```
┌──────────┐      ┌──────────┐      ┌──────────┐
│ Peer A   │◀────▶│ Peer B   │◀────▶│ Peer C   │
│ (DHT)    │      │ (DHT)    │      │ (DHT)    │
└──────────┘      └──────────┘      └──────────┘
     ▲                  ▲                  ▲
     │                  │                  │
     └──────────────────┴──────────────────┘
              Fully decentralized P2P
```

**Success metrics**:
- No single point of failure
- 100+ peers in DHT
- Context discovery <500ms
- 99% uptime without central server

### Phase 3: Advanced Features (4-6 weeks)

**Goal**: Production-ready with advanced economics

**Deliverables**:
- Reputation-weighted token rewards
- Quality verification (peers validate each other's content)
- Context deduplication (same content from multiple peers)
- Caching layer (frequently accessed content cached locally)
- Analytics dashboard (token flow, peer stats, network health)
- Privacy controls (encrypted context, access control)

**Advanced economics**:
- Reputation multiplier (high-rep peers earn 1.5x)
- Staking (lock tokens for higher reputation)
- Slashing (bad actors lose staked tokens)
- Governance (token holders vote on parameter changes)

**Success metrics**:
- 1000+ peers in network
- 10,000+ context chunks served/day
- 90%+ cost reduction vs full-context LLM
- <5% bad actors (reputation filtering)

---

## Technical Specifications

### Peer Discovery Protocol

**Announce** (every 30s heartbeat):
```json
POST /announce
{
  "peer_id": "abc123...",
  "ip": "192.168.1.100",
  "port": 6881,
  "contexts": [
    {
      "hash": "sha256:...",
      "title": "ONEX Effect Node",
      "size_bytes": 4096,
      "tags": ["onex", "effect"]
    }
  ],
  "uptime_pct": 99.2,
  "reputation": 0.95,
  "token_balance": 5000
}

Response:
{
  "status": "ok",
  "peers_online": 127,
  "contexts_total": 4567
}
```

**Scrape** (find peers with context):
```json
GET /scrape?context_hash=sha256:abc123...

Response:
{
  "peers": [
    {
      "peer_id": "def456...",
      "ip": "192.168.1.101",
      "port": 6881,
      "reputation": 0.98,
      "uptime_pct": 99.5,
      "latency_ms": 12,
      "token_cost": 10
    }
  ],
  "total_peers": 3,
  "avg_latency_ms": 15
}
```

### Context Retrieval Protocol

**Request context**:
```http
GET /context/{hash}
Authorization: Bearer {peer_token}
X-Requester-Peer-ID: peer_a
X-Max-Token-Cost: 50

Response:
200 OK
Content-Type: application/json
X-Token-Cost: 10
X-Context-Size-Bytes: 5120
X-Peer-Reputation: 0.95

{
  "hash": "sha256:abc123...",
  "content": "...",
  "metadata": {
    "title": "ONEX Effect Node",
    "author": "peer_xyz",
    "created_at": "2025-10-01T00:00:00Z",
    "tags": ["onex", "effect"],
    "references": ["sha256:def456..."]
  },
  "embedding": [0.123, 0.456, ...]
}
```

**Token deduction flow**:
1. Requester includes signed transaction in request
2. Server validates signature
3. Server deducts tokens from requester's balance
4. Server credits tokens to own balance
5. Transaction logged to ledger
6. If requester has insufficient balance → 402 Payment Required

### Content Verification Protocol

**Submit verification**:
```json
POST /verify
{
  "verifier_peer_id": "ghi789...",
  "context_hash": "sha256:abc123...",
  "verification": "valid" | "invalid" | "outdated",
  "reason": "Content matches description, high quality",
  "signature": "..."
}

Response:
{
  "status": "ok",
  "reward_tokens": 5,
  "context_reputation_updated": true
}
```

**Reputation update**:
- Valid verification → Content author gains 0.01 reputation
- Invalid verification → Content author loses 0.05 reputation
- Verifier earns 5 tokens per verification
- Multiple verifications required for consensus (e.g., 3+ verifiers)

---

## Database Schema

### Peer Registry

```sql
CREATE TABLE peers (
    peer_id TEXT PRIMARY KEY,
    ip_address INET,
    port INT,
    public_key TEXT,
    reputation NUMERIC DEFAULT 1.0,
    uptime_pct NUMERIC,
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    total_contexts_served BIGINT DEFAULT 0,
    total_bytes_served BIGINT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_peers_reputation ON peers(reputation DESC);
CREATE INDEX idx_peers_last_seen ON peers(last_seen_at DESC);
```

### Context Registry

```sql
CREATE TABLE contexts (
    hash TEXT PRIMARY KEY,
    title TEXT,
    description TEXT,
    size_bytes BIGINT,
    embedding VECTOR(768), -- For RAG similarity
    tags TEXT[],
    author_peer_id TEXT REFERENCES peers(peer_id),
    reputation NUMERIC DEFAULT 1.0,
    verification_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_contexts_embedding ON contexts USING ivfflat(embedding);
CREATE INDEX idx_contexts_tags ON contexts USING GIN(tags);
CREATE INDEX idx_contexts_reputation ON contexts(reputation DESC);
```

### Peer-Context Mapping

```sql
CREATE TABLE peer_contexts (
    peer_id TEXT REFERENCES peers(peer_id),
    context_hash TEXT REFERENCES contexts(hash),
    announced_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (peer_id, context_hash)
);

CREATE INDEX idx_peer_contexts_peer ON peer_contexts(peer_id);
CREATE INDEX idx_peer_contexts_context ON peer_contexts(context_hash);
```

### Token Ledger

```sql
CREATE TABLE token_transactions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    peer_id TEXT REFERENCES peers(peer_id),
    transaction_type TEXT CHECK (transaction_type IN ('earned', 'spent')),
    amount NUMERIC NOT NULL,
    reason TEXT, -- 'context_served', 'context_retrieved', 'llm_query', etc.
    context_hash TEXT REFERENCES contexts(hash),
    counterparty_peer_id TEXT REFERENCES peers(peer_id),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_token_transactions_peer ON token_transactions(peer_id, created_at DESC);
CREATE INDEX idx_token_transactions_type ON token_transactions(transaction_type, created_at DESC);
```

---

## Cost-Benefit Analysis

### Current Full-Context LLM Approach

**Assumptions**:
- Average query: 500KB context
- Input cost: $5/1M tokens (Gemini Pro)
- Output cost: $15/1M tokens
- 1000 queries/day

**Costs**:
```
Input: 500KB × 1000 queries × $5/1M = $2500/day
Output: 50KB × 1000 queries × $15/1M = $750/day
Total: $3250/day = $97,500/month
```

### P2P Context-Sharing Approach

**Assumptions**:
- Average query: 50KB context (90% reduction via RAG)
- P2P retrieval cost: 50KB × 2 tokens/KB = 100 tokens
- Token value: $0.001 per token (based on compute cost)
- LLM cost reduced by 90%

**Costs**:
```
P2P retrieval: 50KB × 1000 queries × $0.001/KB = $50/day
Input: 50KB × 1000 queries × $5/1M = $250/day
Output: 50KB × 1000 queries × $15/1M = $750/day
Total: $1050/day = $31,500/month

Savings: $97,500 - $31,500 = $66,000/month (68% reduction)
```

**Additional benefits**:
- Decentralized (no single point of failure)
- Scales horizontally (more peers = more capacity)
- Community-driven (network effects)
- Privacy-preserving (can encrypt sensitive context)

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Sybil attacks** (fake peers) | Medium | High | Reputation system, stake requirements |
| **Freeloading** (consume without contributing) | High | Medium | Token economics (must earn to spend) |
| **Bad context quality** | Medium | Medium | Verification protocol, reputation filtering |
| **Network fragmentation** | Low | High | DHT ensures connectivity, tracker fallback |
| **Token economics imbalance** | Medium | Medium | Dynamic parameter adjustment, monitoring |
| **Privacy concerns** | Medium | Medium | Encryption, access controls, private contexts |
| **Scalability bottlenecks** | Low | Medium | Sharding, CDN-like edge nodes |

---

## Success Metrics

### Network Health

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Active peers** | >100 (3 months) | Peers announcing in last 24h |
| **Context chunks** | >10,000 | Total unique contexts in network |
| **Uptime** | >99% | Network available for queries |
| **Avg query latency** | <500ms | Time to discover + retrieve context |

### Economic Health

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Token velocity** | >1 cycle/week | Earn → spend → earn circulation |
| **Token supply/demand** | ±20% balance | Supply (earned) vs demand (spent) |
| **Peer profitability** | >80% profitable | % peers earning more than spending |
| **Cost reduction** | >60% vs baseline | Savings vs full-context LLM approach |

### Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| **Context quality score** | >0.8 | Average verification score |
| **Bad actor rate** | <5% | % peers with reputation <0.5 |
| **RAG precision** | >90% | % relevant context in retrievals |
| **User satisfaction** | >4/5 | Peer rating of network usefulness |

---

## Integration with Phase 3 (Reward System)

The P2P context-sharing model **enhances** the STF contribution reward system:

### Dual Token Earning Paths

1. **Contribute STFs** (transformation functions)
   - One-time reward: 100-1000 tokens
   - Ongoing: Earn when others use your STF

2. **Share context** (P2P bandwidth)
   - Ongoing: Earn 2 tokens/KB served
   - Passive income: Context served while you sleep

### Synergies

- **STF contributors** can share their implementation examples via P2P
- **Context sharers** can discover new STFs from network
- **Network effects**: More contributors → more context → more value → more contributors

### Combined Timeline

**Phase 1 (Debug Loop)** → **Phase 3a (STF Rewards)** → **Phase 3b (P2P Context Sharing)**

- Weeks 1-4: Debug Loop (STF registry foundation)
- Weeks 5-8: STF Rewards (contribution incentives)
- Weeks 9-14: P2P Context Sharing (bandwidth incentives)

**Total**: 14 weeks for full economic ecosystem

---

## Conclusion

The P2P context-sharing model transforms the compute token economy from a **single-sided market** (contributors earn tokens) to a **two-sided marketplace**:

**Supply side**:
- Contribute STFs (one-time + ongoing)
- Share context (ongoing passive income)
- Verify quality (ongoing active income)

**Demand side**:
- Retrieve context from peers
- Use LLM compute
- Generate embeddings

**Network effects**:
- More peers → more context → lower latency → more value
- More contributors → more STFs → more patterns → more value
- More verifiers → higher quality → more trust → more value

**This is how you build a sustainable, decentralized knowledge economy.**

---

**Document Version**: 1.0
**Last Updated**: 2025-11-09
**Status**: Proposal for Review
**Next Steps**:
1. Validate P2P tracker architecture
2. Define token economics parameters
3. Build Phase 1 prototype (centralized tracker)
4. Measure cost reduction vs full-context LLM
