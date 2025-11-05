# Container Configuration Synchronization Analysis

**Date**: 2025-11-05
**Repositories**: omniclaude ↔ omniarchon
**Context**: Post-Priority 2 Docker Compose consolidation in omniclaude

---

## Executive Summary

**Status**: ⚠️ **SIGNIFICANT DIVERGENCE DETECTED**

Both repositories have recently undergone Docker Compose consolidation efforts, but they have taken **different architectural approaches**. OmniArchon (completed Nov 5) follows a **functional composition pattern** (4 files: base infrastructure → services → frontend → monitoring), while OmniClaude (just completed) follows an **environment-based pattern** with **profile-driven service activation**.

**Key Findings**:
- ✅ Both use modern 12-Factor App principles with environment parameterization
- ✅ Both connect to shared infrastructure (PostgreSQL @ 192.168.86.200, Kafka/Redpanda)
- ⚠️ **Different consolidation philosophies**: Functional composition vs. profile-based activation
- ⚠️ **Environment variable naming inconsistencies** across repositories
- ⚠️ **Network configuration differences**: OmniArchon uses explicit external networks
- ❌ **Missing documentation cross-references** between repositories

---

## Recent Changes Summary

### OmniArchon (November 5, 2025)

**Commit**: `fix: Post-PR#20 Comprehensive Fixes - 34 Issues Resolved (#21)` (232fa8d)

**Major Changes**:
1. **Docker Compose Consolidation**: 9 files → 4 files
   - `docker-compose.yml` - Base infrastructure (Qdrant, Memgraph, Valkey)
   - `docker-compose.services.yml` - Application services (Intelligence, Bridge, Search, Kafka consumers)
   - `docker-compose.frontend.yml` - Frontend services (archon-agents, archon-frontend)
   - `docker-compose.monitoring.yml` - Monitoring stack (Prometheus, Grafana, Loki, Jaeger, etc.)

2. **Environment File Strategy**:
   - `.env.example` (424 lines, master reference)
   - `.env.development` (255 lines)
   - `.env.staging` (created but not in repo)
   - `.env.production` (created but not in repo)
   - **No environment-specific compose files** - uses `--env-file` flag

3. **Network Architecture**:
   - Named network: `omniarchon_app-network` (explicit name for composition)
   - External networks: `omninode-bridge-network`, `omninode_bridge_omninode-bridge-network`
   - Monitoring network: `omniarchon-monitoring`

4. **Deployment Scripts**: 4 helper scripts
   - `start-dev.sh` - Full development stack
   - `start-services-only.sh` - Core services without frontend
   - `start-prod.sh` - Production deployment
   - `stop-all.sh` - Stop all services

5. **Configuration Variables**: 130+ parameterized variables including:
   - Comprehensive timeout configuration (HTTP, DB, cache, async, background, test, service restart)
   - Tree + Stamping event adapter configuration
   - Auto-indexing configuration
   - Bulk ingestion defaults
   - Consul service discovery

### OmniClaude (November 4-5, 2025)

**Commit**: Recent work on `fix/agent-system-infrastructure` branch

**Major Changes**:
1. **Docker Compose Consolidation**: Single file approach
   - `deployment/docker-compose.yml` (621 lines)
   - Profile-based service activation (default, test, debug, monitoring)
   - All services in one file with conditional profiles

2. **Environment File Strategy**:
   - `.env.example` (302 lines)
   - `.env.dev` (created)
   - `.env.test` (created)
   - `.env.prod` (created)
   - Profile-driven architecture

3. **Services**: 15 services total
   - app (OmniClaude main application)
   - agent-observability-consumer
   - routing-adapter
   - archon-router-consumer
   - postgres (app-specific)
   - redpanda (test profile only)
   - redpanda-console (test/debug profiles)
   - test-runner (test profile)
   - valkey
   - prometheus
   - grafana
   - otel-collector
   - jaeger

4. **Network Architecture**:
   - `app_network` (172.30.0.0/16)
   - `monitoring_network` (172.31.0.0/16)
   - No explicit external network references

5. **Configuration Variables**: 130+ parameterized variables

---

## Container Configuration Comparison Matrix

### Service Comparison

| Service | OmniClaude | OmniArchon | Status | Notes |
|---------|-----------|------------|--------|-------|
| **Core Application** | app (8000) | N/A | ⚠️ OmniClaude-only | Main OmniClaude web app |
| **Intelligence** | N/A | archon-intelligence (8053) | ⚠️ OmniArchon-only | Core intelligence APIs |
| **Bridge** | N/A | archon-bridge (8054) | ⚠️ OmniArchon-only | Event translation, metadata stamping |
| **Search** | N/A | archon-search (8055) | ⚠️ OmniArchon-only | RAG and vector search |
| **Agent Router** | routing-adapter (8070) | N/A | ⚠️ OmniClaude-only | Event-driven agent routing |
| **Router Consumer** | archon-router-consumer | N/A | ⚠️ OmniClaude-only | Kafka-based routing service |
| **Agent Observability** | agent-observability-consumer | N/A | ⚠️ OmniClaude-only | Agent tracking and logging |
| **Kafka Consumer** | N/A | archon-kafka-consumer (8059) | ⚠️ OmniArchon-only | ONEX Kafka event consumer |
| **Intelligence Consumers** | N/A | 4 instances (8060-8063) | ⚠️ OmniArchon-only | Parallel intelligence processing |
| **LangExtract** | N/A | archon-langextract (8156) | ⚠️ OmniArchon-only | Language-aware extraction |
| **Agents** | N/A | archon-agents (8052) | ⚠️ OmniArchon-only | ML/Reranking, profile: agents |
| **PostgreSQL** | postgres (5432→5432) | N/A | ⚠️ Different | OmniClaude: app-specific DB, OmniArchon: uses remote |
| **Qdrant** | N/A | archon-qdrant (6333/6334) | ⚠️ OmniArchon-only | Vector database |
| **Memgraph** | N/A | archon-memgraph (7687/7444) | ⚠️ OmniArchon-only | Knowledge graph |
| **Valkey/Redis** | valkey (6379) | archon-valkey (6379) | ✅ Similar | Redis-compatible cache |
| **Redpanda** | redpanda (29092) | N/A | ⚠️ Different | OmniClaude: test profile, OmniArchon: uses remote |
| **Redpanda Console** | redpanda-console (8080) | N/A | ⚠️ Different | OmniClaude: test/debug, OmniArchon: uses remote console |
| **Prometheus** | prometheus (9090) | prometheus (9090) | ✅ Similar | Metrics collection |
| **Grafana** | grafana (3000) | grafana (3000) | ✅ Similar | Visualization dashboards |
| **Jaeger** | jaeger (16686) | jaeger (16686) | ✅ Similar | Distributed tracing |
| **OpenTelemetry** | otel-collector (4317/4318) | N/A | ⚠️ OmniClaude-only | OTEL collector |
| **Loki** | N/A | loki (3100) | ⚠️ OmniArchon-only | Log aggregation |
| **Promtail** | N/A | promtail | ⚠️ OmniArchon-only | Log collection agent |
| **Alertmanager** | N/A | alertmanager (9093) | ⚠️ OmniArchon-only | Alert management |
| **Node Exporter** | N/A | node-exporter (9100) | ⚠️ OmniArchon-only | System metrics |
| **cAdvisor** | N/A | cadvisor (8080) | ⚠️ OmniArchon-only | Container metrics |
| **Uptime Kuma** | N/A | uptime-kuma (3001) | ⚠️ OmniArchon-only | Service monitoring |

### Shared Infrastructure Services (Remote @ 192.168.86.200)

| Service | OmniClaude Config | OmniArchon Config | Status |
|---------|------------------|------------------|--------|
| **PostgreSQL** | 192.168.86.200:5436 | omninode-bridge-postgres:5436 | ✅ Consistent |
| **Kafka/Redpanda** | 192.168.86.200:29092 (host scripts), omninode-bridge-redpanda:9092 (Docker) | omninode-bridge-redpanda:9092 (Docker) | ✅ Consistent |
| **OnexTree** | N/A | omninode-bridge-onextree:8058 | ⚠️ OmniArchon-only |
| **Metadata Stamping** | N/A | omninode-bridge-metadata-stamping:8057 | ⚠️ OmniArchon-only |
| **Consul** | N/A | 192.168.86.200:8500 | ⚠️ OmniArchon-only |

---

## Network Configuration Comparison

### OmniClaude

```yaml
networks:
  app_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16
  monitoring_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.31.0.0/16
```

**Characteristics**:
- ❌ No explicit external network references
- ❌ No external network connections defined
- ⚠️ Relies on DNS resolution via `/etc/hosts` for remote services
- ✅ Segregated networks for security (app vs. monitoring)

### OmniArchon

```yaml
networks:
  app-network:
    driver: bridge
    name: omniarchon_app-network  # Explicit name for composition

  omninode-bridge-network:
    external: true  # PostgreSQL traceability DB network
    name: omninode-bridge-network

  omninode_bridge_omninode-bridge-network:
    external: true  # Redpanda/Kafka event bus network
    name: omninode_bridge_omninode-bridge-network

  monitoring:
    driver: bridge
    name: omniarchon-monitoring
```

**Characteristics**:
- ✅ Explicit external network references
- ✅ Named network pattern for composition
- ✅ Clear separation: app-network, monitoring, external bridges
- ✅ Services can connect to remote infrastructure directly

**Verdict**: ⚠️ **OmniArchon's network architecture is more explicit and robust**

---

## Environment Variable Comparison

### Shared Infrastructure Variables

| Variable | OmniClaude | OmniArchon | Status | Notes |
|----------|-----------|------------|--------|-------|
| **PostgreSQL Host** | POSTGRES_HOST | POSTGRES_HOST | ✅ Consistent | Both use 192.168.86.200 |
| **PostgreSQL Port** | POSTGRES_PORT | POSTGRES_PORT | ✅ Consistent | Both use 5436 |
| **PostgreSQL Database** | POSTGRES_DATABASE | POSTGRES_DB | ⚠️ Different | omniclaude vs omninode_bridge |
| **PostgreSQL User** | POSTGRES_USER | POSTGRES_USER | ✅ Consistent | postgres |
| **PostgreSQL Password** | POSTGRES_PASSWORD | POSTGRES_PASSWORD | ✅ Consistent | Required placeholder |
| **Kafka Bootstrap** | KAFKA_BOOTSTRAP_SERVERS | KAFKA_BOOTSTRAP_SERVERS | ✅ Consistent | Context-dependent ports |
| **Qdrant Host** | QDRANT_HOST | QDRANT_HOST | ✅ Consistent | localhost vs archon-qdrant |
| **Qdrant Port** | QDRANT_PORT | QDRANT_PORT | ✅ Consistent | 6333 |
| **Qdrant URL** | QDRANT_URL | QDRANT_URL | ✅ Consistent | http://localhost:6333 vs http://archon-qdrant:6333 |

### Service-Specific Variables

| Variable | OmniClaude | OmniArchon | Status | Notes |
|----------|-----------|------------|--------|-------|
| **App Port** | APP_PORT (8000) | N/A | ⚠️ OmniClaude-only | |
| **Intelligence Port** | N/A | INTELLIGENCE_SERVICE_PORT (8053) | ⚠️ OmniArchon-only | |
| **Bridge Port** | N/A | BRIDGE_SERVICE_PORT (8054) | ⚠️ OmniArchon-only | |
| **Search Port** | N/A | SEARCH_SERVICE_PORT (8055) | ⚠️ OmniArchon-only | |
| **Routing Adapter Port** | ROUTING_ADAPTER_PORT (8070) | N/A | ⚠️ OmniClaude-only | |
| **Valkey URL** | VALKEY_URL | VALKEY_URL | ✅ Consistent | Redis URL format |
| **Valkey Password** | Via VALKEY_URL | VALKEY_PASSWORD | ⚠️ Different | OmniClaude: inline, OmniArchon: separate var |
| **Log Level** | LOG_LEVEL | LOG_LEVEL | ✅ Consistent | |
| **Environment** | APP_ENV | ENVIRONMENT | ⚠️ Different naming | |

### Naming Inconsistencies

| Concept | OmniClaude | OmniArchon | Impact |
|---------|-----------|------------|--------|
| **Environment** | APP_ENV | ENVIRONMENT | ⚠️ Medium - Scripts need different vars |
| **Database Name** | POSTGRES_DATABASE | POSTGRES_DB | ⚠️ Medium - Both patterns valid |
| **Valkey Auth** | In VALKEY_URL | VALKEY_PASSWORD | ⚠️ Low - Different but functional |
| **Container Prefix** | CONTAINER_PREFIX | N/A | ⚠️ Low - OmniClaude-specific |

---

## Port Mapping Comparison

### OmniClaude Port Allocations

| Service | Internal | External | Profile |
|---------|----------|----------|---------|
| app | 8000 | 8000 | default |
| app-metrics | 8001 | 8001 | default |
| agent-observability-consumer health | 8080 | 8080 | default |
| routing-adapter | 8070 | 8070 | default |
| postgres | 5432 | 5432 | default |
| redpanda-kafka | 9092/29092 | 29092 | test |
| redpanda-proxy | 8082/28082 | 28082 | test |
| redpanda-schema | 8081/28081 | 28081 | test |
| redpanda-admin | 9644 | 9644 | test |
| redpanda-console | 8080 | 8080 | test/debug |
| valkey | 6379 | 6379 | default |
| prometheus | 9090 | 9090 | monitoring |
| grafana | 3000 | 3000 | monitoring |
| otel-collector-grpc | 4317 | 4317 | monitoring |
| otel-collector-http | 4318 | 4318 | monitoring |
| otel-metrics | 8888 | 8888 | monitoring |
| otel-health | 13133 | 13133 | monitoring |
| jaeger-ui | 16686 | 16686 | monitoring |
| jaeger-collector | 14268 | 14268 | monitoring |

### OmniArchon Port Allocations

| Service | Internal | External | Profile |
|---------|----------|----------|---------|
| archon-intelligence | 8053 | 8053 | default |
| archon-bridge | 8054 | 8054 | default |
| archon-search | 8055 | 8055 | default |
| archon-langextract | 8156 | 8156 | default |
| archon-kafka-consumer | 8057 | 8059 | default |
| archon-intelligence-consumer-1 | 8080 | 8060 | default |
| archon-intelligence-consumer-2 | 8080 | 8061 | default |
| archon-intelligence-consumer-3 | 8080 | 8062 | default |
| archon-intelligence-consumer-4 | 8080 | 8063 | default |
| archon-agents | 8052 | 8052 | agents |
| archon-qdrant | 6333/6334 | 6333/6334 | default |
| archon-memgraph | 7687/7444 | 7687/7444 | default |
| archon-valkey | 6379 | 6379 | default |
| prometheus | 9090 | 9090 | monitoring |
| grafana | 3000 | 3000 | monitoring |
| loki | 3100 | 3100 | monitoring |
| alertmanager | 9093 | 9093 | monitoring |
| node-exporter | 9100 | 9100 | monitoring |
| cadvisor | 8080 | 8080 | monitoring |
| jaeger-ui | 16686 | 16686 | monitoring |
| jaeger-http | 14268 | 14268 | monitoring |
| jaeger-grpc | 14250 | 14250 | monitoring |
| uptime-kuma | 3001 | 3001 | monitoring |

**Port Conflicts**: ⚠️ **NONE DETECTED** - Services use different port ranges

---

## Volume Mount Comparison

### OmniClaude Volumes

```yaml
volumes:
  app_data:           # Application data
  postgres_data:      # App-specific PostgreSQL
  redpanda_data:      # Test Redpanda
  valkey_data:        # Valkey cache
  prometheus_data:    # Prometheus metrics
  grafana_data:       # Grafana dashboards
```

### OmniArchon Volumes

```yaml
volumes:
  memgraph_data:       # Knowledge graph
  qdrant_data:         # Vector database storage
  qdrant_snapshots:    # Vector database snapshots
  valkey_data:         # Valkey cache
  prometheus_data:     # Prometheus metrics
  grafana_data:        # Grafana dashboards
  loki_data:           # Loki log aggregation
  alertmanager_data:   # Alertmanager configuration
  elasticsearch_data:  # Elasticsearch (optional, profile: full)
  jaeger_data:         # Jaeger tracing
  uptime_kuma_data:    # Uptime Kuma monitoring
```

**Verdict**: ✅ No conflicts, complementary volume strategies

---

## Health Check Comparison

### Health Check Consistency

| Aspect | OmniClaude | OmniArchon | Status |
|--------|-----------|------------|--------|
| **Interval** | 30s | 30s | ✅ Consistent |
| **Timeout** | 10s | 10s | ✅ Consistent |
| **Retries** | 3-5 | 3-5 | ✅ Consistent |
| **Start Period** | 40s-120s | 40s-120s | ✅ Consistent |
| **Test Commands** | curl -f | curl -f / wget | ⚠️ Slightly different |

**Verdict**: ✅ Health check strategies are aligned

---

## Discrepancies & Misalignments

### Critical Issues

#### 1. ❌ Network Architecture Divergence

**Issue**: OmniClaude does not use external network references for remote services

**Impact**:
- OmniClaude services cannot natively connect to OmniArchon services
- Cross-repository service discovery is harder
- Requires manual DNS resolution via `/etc/hosts`

**Recommendation**: **CRITICAL** - Add external network references to OmniClaude

```yaml
# Add to omniclaude/deployment/docker-compose.yml
networks:
  app_network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.30.0.0/16

  # Add external networks
  omninode-bridge-network:
    external: true
    name: omninode-bridge-network

  omninode_bridge_omninode-bridge-network:
    external: true
    name: omninode_bridge_omninode-bridge-network
```

**Priority**: 🔴 **CRITICAL**

#### 2. ⚠️ Consolidation Philosophy Divergence

**Issue**: Different approaches to compose file organization

**OmniClaude**:
- Single file with profiles (default, test, debug, monitoring)
- 621 lines in one file
- Profile-driven service activation

**OmniArchon**:
- 4 functional files (base, services, frontend, monitoring)
- Compose file composition (`-f docker-compose.yml -f docker-compose.services.yml`)
- Functional separation of concerns

**Impact**:
- Different mental models for developers switching between repos
- Different deployment commands
- Harder to maintain consistency

**Recommendation**: **IMPORTANT** - Align on single approach across all OmniNode repositories

**Options**:
1. **Adopt OmniArchon's functional composition** (recommended)
   - Clearer separation of concerns
   - More flexible (can start subsets independently)
   - Matches omninode_bridge pattern

2. **Adopt OmniClaude's profile-based approach**
   - Single file simplicity
   - Profile-driven activation

**Priority**: 🟠 **IMPORTANT**

#### 3. ⚠️ Environment Variable Naming Inconsistencies

**Issue**: Same concepts use different variable names

**Examples**:
- Environment: `APP_ENV` (OmniClaude) vs `ENVIRONMENT` (OmniArchon)
- Database: `POSTGRES_DATABASE` vs `POSTGRES_DB`
- Valkey auth: `VALKEY_URL` (inline password) vs `VALKEY_PASSWORD` (separate)

**Impact**:
- Scripts need different variables per repository
- Shared tooling becomes harder
- Developer confusion

**Recommendation**: **IMPORTANT** - Standardize variable names across all repos

**Priority**: 🟠 **IMPORTANT**

### Important Issues

#### 4. ⚠️ Missing Documentation Cross-References

**Issue**: OmniClaude CLAUDE.md references shared infrastructure but not OmniArchon's consolidation

**Missing References**:
- OmniArchon's recent consolidation (Nov 5)
- OmniArchon's deployment scripts
- OmniArchon's functional composition pattern

**Recommendation**: Add cross-references to both CLAUDE.md files

**Priority**: 🟡 **NICE-TO-HAVE**

#### 5. ⚠️ Hardcoded Values Still Present

**Issue**: Some hardcoded values remain in both repositories

**OmniClaude**:
- Subnet CIDRs: `172.30.0.0/16`, `172.31.0.0/16` (should be parameterized)

**OmniArchon**:
- Example CORS origins in comments
- Some service URLs in documentation

**Recommendation**: Final parameterization pass

**Priority**: 🟡 **NICE-TO-HAVE**

### Nice-to-Have

#### 6. ℹ️ Monitoring Stack Differences

**Issue**: Different monitoring service selections

**OmniClaude**:
- OpenTelemetry Collector
- Jaeger only
- No Loki/Promtail

**OmniArchon**:
- Loki + Promtail
- Alertmanager
- Node Exporter
- cAdvisor
- Uptime Kuma
- Optional Elasticsearch/Kibana

**Recommendation**: Consider adopting OmniArchon's comprehensive monitoring stack in OmniClaude

**Priority**: 🟢 **NICE-TO-HAVE**

---

## Recommended Synchronization Actions

### Priority: 🔴 CRITICAL (Immediate Action Required)

| Action | Repository | Effort | Impact | Reason |
|--------|-----------|--------|--------|--------|
| **Add external network references** | OmniClaude | 2 hours | High | Enable native cross-repository service communication |
| **Update CLAUDE.md with OmniArchon references** | OmniClaude | 1 hour | Medium | Document shared infrastructure properly |
| **Verify Kafka bootstrap server configuration** | Both | 1 hour | High | Ensure correct ports (9092 vs 29092) based on context |

**Total Effort**: ~4 hours

### Priority: 🟠 IMPORTANT (Next Sprint)

| Action | Repository | Effort | Impact | Reason |
|--------|-----------|--------|--------|--------|
| **Align consolidation approach** | Both | 8 hours | High | Single mental model across repos |
| **Standardize environment variable names** | Both | 4 hours | Medium | Shared tooling and scripts |
| **Create deployment script parity** | OmniClaude | 2 hours | Medium | Match OmniArchon's deployment scripts |
| **Document network architecture** | Both | 2 hours | Medium | Clear external network dependencies |

**Total Effort**: ~16 hours

### Priority: 🟡 NICE-TO-HAVE (Backlog)

| Action | Repository | Effort | Impact | Reason |
|--------|-----------|--------|--------|--------|
| **Adopt comprehensive monitoring** | OmniClaude | 4 hours | Medium | Loki, Alertmanager, Uptime Kuma |
| **Final parameterization pass** | Both | 2 hours | Low | Remove all remaining hardcoded values |
| **Create unified .env.example** | Both | 2 hours | Low | Shared configuration template |
| **Add ADR for consolidation patterns** | Both | 2 hours | Low | Document architectural decisions |

**Total Effort**: ~10 hours

---

## Shared Infrastructure Verification

### PostgreSQL Configuration

| Aspect | OmniClaude | OmniArchon | Status |
|--------|-----------|------------|--------|
| **Host** | 192.168.86.200 | omninode-bridge-postgres (resolves to 192.168.86.200) | ✅ Consistent |
| **Port** | 5436 | 5436 | ✅ Consistent |
| **Database** | omninode_bridge | omninode_bridge | ✅ Consistent |
| **User** | postgres | postgres | ✅ Consistent |
| **Password Source** | .env POSTGRES_PASSWORD | .env POSTGRES_PASSWORD | ✅ Consistent |
| **Connection String** | Environment variable | Environment variable | ✅ Consistent |

**Verdict**: ✅ **PostgreSQL configuration is aligned**

### Kafka/Redpanda Configuration

| Aspect | OmniClaude | OmniArchon | Status |
|--------|-----------|------------|--------|
| **Docker Services** | omninode-bridge-redpanda:9092 | omninode-bridge-redpanda:9092 | ✅ Consistent |
| **Host Scripts** | 192.168.86.200:29092 | 192.168.86.200:29092 | ✅ Consistent |
| **Topics** | agent.routing.*, intelligence.* | codegen.*, tree.*, intelligence.* | ⚠️ Different (expected) |
| **Consumer Groups** | agent-router-service, etc. | archon-intelligence, etc. | ⚠️ Different (expected) |

**Verdict**: ✅ **Kafka configuration is aligned** (different topics are expected)

### Qdrant Configuration

| Aspect | OmniClaude | OmniArchon | Status |
|--------|-----------|------------|--------|
| **Deployment** | N/A (references remote) | Local container (archon-qdrant) | ⚠️ Different |
| **Host** | localhost | archon-qdrant | ⚠️ Different |
| **Port** | 6333 | 6333 | ✅ Consistent |
| **Collections** | code_patterns, execution_patterns | archon_vectors, quality_vectors | ⚠️ Different (expected) |

**Verdict**: ⚠️ **Different deployment strategies** (OmniArchon self-hosted, OmniClaude uses remote)

---

## Testing Recommendations

### Integration Testing

**Test Scenario 1**: Cross-Repository Service Communication
```bash
# Verify OmniClaude can reach OmniArchon services
docker exec omniclaude_app curl http://archon-intelligence:8053/health
docker exec omniclaude_app curl http://archon-bridge:8054/health
docker exec omniclaude_app curl http://archon-search:8055/health
```

**Expected**: ❌ Will fail without external network references

**Test Scenario 2**: Shared Infrastructure Access
```bash
# Verify both repos can access PostgreSQL
docker exec omniclaude_app psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
docker exec archon-intelligence psql -h omninode-bridge-postgres -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"

# Verify both repos can access Kafka
docker exec omniclaude_routing_adapter kafkacat -L -b 192.168.86.200:29092
docker exec archon-intelligence kafkacat -L -b omninode-bridge-redpanda:9092
```

**Expected**: ✅ Should succeed (both repos configured correctly)

### Network Isolation Testing

**Test Scenario 3**: Network Segmentation
```bash
# Verify monitoring network isolation
docker network inspect omniclaude_monitoring_network
docker network inspect omniarchon-monitoring

# Verify app network connectivity
docker network inspect omniclaude_app_network
docker network inspect omniarchon_app-network
```

**Expected**: ⚠️ Different network configurations (by design)

---

## Conclusion

### Summary of Findings

**Strengths**:
- ✅ Both repos follow 12-Factor App principles
- ✅ Both use modern environment-based configuration
- ✅ Shared infrastructure (PostgreSQL, Kafka) is consistently configured
- ✅ Health check strategies are aligned
- ✅ No port conflicts between repositories

**Critical Issues**:
- ❌ OmniClaude lacks external network references for cross-repo communication
- ⚠️ Different consolidation philosophies (functional vs. profile-based)
- ⚠️ Environment variable naming inconsistencies

**Recommended Path Forward**:

1. **Immediate (Week 1)**:
   - Add external network references to OmniClaude
   - Update CLAUDE.md with OmniArchon cross-references
   - Verify Kafka bootstrap server configurations

2. **Short-term (Next Sprint)**:
   - Align on single consolidation approach (recommend OmniArchon's functional composition)
   - Standardize environment variable names
   - Create deployment script parity

3. **Long-term (Backlog)**:
   - Adopt comprehensive monitoring stack
   - Create unified configuration templates
   - Document architectural decisions (ADRs)

**Overall Assessment**: ⚠️ **MODERATE DIVERGENCE** - Requires coordinated effort to align

---

## Appendix

### OmniClaude Docker Compose Structure

```
omniclaude/
└── deployment/
    ├── docker-compose.yml          # Consolidated single file (621 lines)
    ├── .env.dev                    # Development environment
    ├── .env.test                   # Test environment
    ├── .env.prod                   # Production environment
    └── Dockerfile*                 # Multiple Dockerfiles for services
```

### OmniArchon Docker Compose Structure

```
omniarchon/
└── deployment/
    ├── docker-compose.yml          # Base infrastructure (173 lines)
    ├── docker-compose.services.yml # Application services (650 lines)
    ├── docker-compose.frontend.yml # Frontend services (82 lines)
    ├── docker-compose.monitoring.yml # Monitoring stack (297 lines)
    ├── docker-compose.test.yml     # Test infrastructure (unchanged)
    ├── .env.example                # Master reference (424 lines)
    ├── .env.development            # Development config (255 lines)
    ├── .env.staging                # Staging config
    ├── .env.production             # Production config
    ├── start-dev.sh                # Development deployment
    ├── start-services-only.sh      # Core services deployment
    ├── start-prod.sh               # Production deployment
    ├── stop-all.sh                 # Stop all services
    └── DOCKER_COMPOSE_CONSOLIDATION.md  # Consolidation documentation
```

### Related Documentation

- OmniClaude CLAUDE.md: `/Volumes/PRO-G40/Code/omniclaude/CLAUDE.md`
- OmniArchon DOCKER_COMPOSE_CONSOLIDATION.md: `/Volumes/PRO-G40/Code/omniarchon/deployment/DOCKER_COMPOSE_CONSOLIDATION.md`
- Shared Infrastructure CLAUDE.md: `~/.claude/CLAUDE.md`
- OmniNode Bridge: `/Volumes/PRO-G40/Code/omninode_bridge` (pattern source)

---

**Report Generated**: 2025-11-05
**Analysis Tool**: Claude Code (Sonnet 4.5)
**Correlation ID**: analysis-container-sync-20251105
