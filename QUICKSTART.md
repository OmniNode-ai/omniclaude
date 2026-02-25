# OmniClaude Quickstart

OmniClaude supports three integration tiers. **No tier selection is required** — the plugin
detects available services automatically at every SessionStart and injects a banner:

```
─── OmniClaude: STANDALONE (73 skills) (probe: 4s ago) ───
─── OmniClaude: EVENT_BUS (routing + telemetry) (probe: 12s ago) ───
─── OmniClaude: FULL_ONEX (enrichment + memory) (probe: 8s ago) ───
```

Pick the tier that matches your setup:

---

## Tier 0 — Standalone (5 min, zero config)

No backend services required. Skills, agents, and hooks work immediately; events are
silently dropped when no Kafka is reachable.

```bash
git clone https://github.com/OmniNode-ai/omniclaude && cd omniclaude
uv sync
# In Claude Code: /deploy-local-plugin
```

**What you get:** 73 skills, 54 agents, all hooks fire, Kafka events silently dropped.

> **Seeing STANDALONE but expected EVENT\_BUS?**
> Set `KAFKA_BOOTSTRAP_SERVERS` in `.env` and restart your Claude Code session.
> The probe runs at every SessionStart — no plugin reload needed.

---

## Tier 1 — Event Bus (15 min, host-only local dev)

Start a local Redpanda instance to enable routing telemetry and Kafka event emission.

```bash
docker run -d --name redpanda -p 29092:29092 \
  docker.redpanda.com/redpandadata/redpanda:v23.3.5 \
  redpanda start \
  --kafka-addr PLAINTEXT://0.0.0.0:29092 \
  --advertise-kafka-addr PLAINTEXT://localhost:29092 \
  --smp 1 --memory 512M --overprovisioned

echo "KAFKA_BOOTSTRAP_SERVERS=localhost:29092" >> .env
# Restart Claude Code session — tier banner shows EVENT_BUS
```

**What you get:** Everything in Standalone, plus agent routing events, session telemetry,
and Kafka-backed observability.

> **Host-only local dev.** For Docker network deployments (where Claude Code runs inside
> a container) replace `localhost:29092` with the container-accessible address and set
> `--advertise-kafka-addr` accordingly. See the [Advanced setup](docs/advanced-setup.md)
> guide.

---

## Tier 2 — Full ONEX (30 min)

Bring up the complete intelligence stack to enable enrichment, memory retrieval, and
compliance enforcement.

> `omnibase_core` and `omnibase_spi` are pulled automatically by `uv sync` — no manual
> clone required.

```bash
git clone https://github.com/OmniNode-ai/omniclaude
git clone https://github.com/OmniNode-ai/omnibase_infra
git clone https://github.com/OmniNode-ai/omnimemory
git clone https://github.com/OmniNode-ai/omniintelligence

# Start core infra (Postgres, Redpanda, Valkey)
docker compose -f omnibase_infra/docker/docker-compose.infra.yml up -d

# Start memory service
docker compose -f omnimemory/docker-compose.yml up -d

# Start intelligence service
cd omniintelligence && uv sync --group all
# (see omniintelligence README for service startup)

# Deploy the plugin
cd omniclaude && uv sync
# In Claude Code: /deploy-local-plugin
# Banner shows FULL_ONEX
```

**What you get:** Everything in Event Bus, plus context enrichment from Qdrant, semantic
memory retrieval via OmniMemory, and ONEX pattern compliance enforcement.

---

## Troubleshooting

| Banner | Likely cause | Fix |
|--------|-------------|-----|
| `UNKNOWN (re-probing...)` | First SessionStart or stale probe | Wait for next prompt — probe runs in background |
| `STANDALONE` (unexpected) | `KAFKA_BOOTSTRAP_SERVERS` not set or unreachable | Set env var and restart Claude Code session |
| `EVENT_BUS` instead of `FULL_ONEX` | Intelligence service not reachable | Check `INTELLIGENCE_SERVICE_URL` and service health |

Probe results are cached at `~/.claude/.onex_capabilities` with a 5-minute TTL.
Delete the file to force an immediate re-probe on the next SessionStart.

---

## Next Steps

- [CLAUDE.md](CLAUDE.md) — development guide and architecture reference
- [plugins/onex/agents/configs/](plugins/onex/agents/configs/) — 54 agent YAML definitions
- [plugins/onex/skills/](plugins/onex/skills/) — 73 skill definitions
- [docs/](docs/) — architecture decision records and proposals
