# Architectural Issues To Fix

**Created**: 2025-11-04
**Priority**: HIGH
**Status**: NEEDS INVESTIGATION

---

## Long-Term Solution: ADR-001 Service Ownership Boundaries

**Location**: `/Volumes/PRO-G40/Code/omniarchon/docs/architecture/ADR-001-SERVICE-OWNERSHIP-BOUNDARIES.md`

**Status**: APPROVED - 8-week implementation plan in progress

### Overview

ADR-001 provides a comprehensive architectural solution that addresses **all five issues** documented below. The ADR establishes clear service ownership boundaries, configuration management patterns, and deployment strategies across the entire OmniNode platform.

**⚠️ Important**: The band-aid fixes documented in this file are **temporary measures** to restore immediate functionality. All permanent solutions should follow the ADR-001 implementation plan.

### Issue Mapping to ADR-001 Solutions

| Issue | ADR-001 Solution | Implementation Phase |
|-------|------------------|---------------------|
| **Issue 1**: Docker Compose Anti-Pattern | **Phase 2**: Configuration Consolidation<br>- Single docker-compose.yml per repo<br>- Environment-based configuration (.env.dev/.staging/.prod)<br>- Pydantic Settings for validation | Weeks 3-4 |
| **Issue 2**: Cross-Repository Boundaries | **Service Ownership Matrix**<br>- Clear ownership: omniarchon owns archon-* services<br>- omniclaude consumes via external dependencies<br>- Consul-based service discovery | Weeks 1-2 |
| **Issue 3**: Hardcoded Configuration | **Pydantic Settings Framework**<br>- Type-safe configuration with validation<br>- Environment variable precedence<br>- No hardcoded values in code | Weeks 3-4 |
| **Issue 4**: Service Health Dependencies | **Consul Service Discovery**<br>- Health check integration<br>- Automatic DNS resolution<br>- Dependency management | Weeks 5-6 |
| **Issue 5**: Router Consumer Not Deployed | **Phase 3**: Service Relocation<br>- Move archon-router-consumer to omniclaude<br>- Proper ownership boundaries<br>- Independent deployment | Weeks 7-8 |

### Implementation Timeline

**Total Duration**: 8 weeks across 3 phases

**Phase 1** (Weeks 1-2): Service Ownership & Discovery
- Define ownership matrix
- Implement Consul integration
- Document external dependency patterns

**Phase 2** (Weeks 3-4): Configuration Management
- Consolidate docker-compose files
- Implement Pydantic Settings
- Create environment templates

**Phase 3** (Weeks 5-8): Service Health & Relocation
- Health check standardization
- Relocate misplaced services
- Validation and documentation

### Key Benefits

1. **Single Source of Truth**: Pydantic Settings replaces scattered configuration
2. **Clear Boundaries**: Service ownership matrix prevents cross-repo confusion
3. **Type Safety**: Configuration validation at startup prevents runtime errors
4. **Service Discovery**: Consul eliminates hardcoded hostnames/ports
5. **Maintainability**: Standardized patterns across all OmniNode repositories

### Relationship to This Document

This document (ARCHITECTURAL_ISSUES_TO_FIX.md) serves as:
- **Immediate action tracker** for band-aid fixes to restore functionality
- **Problem statement** documenting why ADR-001 is necessary
- **Validation evidence** that ADR-001 addresses real production issues

**Do not implement long-term solutions in this document** - refer to ADR-001 implementation plan.

---

## Issue 1: Docker Compose Anti-Pattern

### Problem
Multiple docker-compose files with hardcoded configuration violating 12-factor app principles.

**Current (Bad) State:**
```
omniarchon/deployment/
├── docker-compose.yml              ❌ Hardcoded memgraph:7687
├── docker-compose.staging.yml      ❌ Hardcoded memgraph:7687
├── docker-compose.test.yml         ❌ Hardcoded (unknown)
├── docker-compose.performance.yml  ❌ Hardcoded (unknown)
└── docker-compose.prod.yml         ❌ Hardcoded (unknown)

omniclaude/deployment/
├── docker-compose.yml              ❌ Hardcoded ports/URLs
└── docker-compose.test.yml         ❌ Hardcoded ports/URLs
```

**Issues:**
- Configuration duplicated across 5+ files per repository
- Port numbers hardcoded in compose files
- Service URLs hardcoded in compose files
- Changes require editing multiple files
- Dev/staging/prod drift over time
- Impossible to validate consistency

### Correct Architecture
```
deployment/
├── docker-compose.yml              ✅ Single source of truth
├── .env.dev                        ✅ Dev configuration
├── .env.staging                    ✅ Staging configuration
├── .env.prod                       ✅ Production configuration
└── .env.example                    ✅ Template with documentation
```

**Deployment:**
```bash
# Development
docker-compose --env-file .env.dev up -d

# Staging
docker-compose --env-file .env.staging up -d

# Production
docker-compose --env-file .env.prod up -d
```

### Action Items
- [ ] Consolidate docker-compose files into single file with variable substitution
- [ ] Create .env.dev, .env.staging, .env.prod templates
- [ ] Document migration path from current to new structure
- [ ] Update deployment scripts to use --env-file flag
- [ ] Add validation script to check .env files against .env.example

---

## Issue 2: Cross-Repository Boundary Violation

### Problem
omniclaude remediation requires editing omniarchon configuration files.

**Boundary Violation:**
```
Task: Fix omniclaude agent system
Action Taken: Edited /Volumes/PRO-G40/Code/omniarchon/deployment/docker-compose.yml
Problem: Crossing repository boundaries for configuration
```

**Services and Ownership:**
```
omniarchon services (running):
├── archon-bridge           (unhealthy - memgraph connection issue)
├── archon-search           (unhealthy - memgraph connection issue)
├── archon-langextract      (unhealthy - memgraph connection issue)
├── archon-memgraph         (healthy)
├── archon-intelligence     (healthy)
└── archon-kafka-consumer   (healthy)

omniclaude services (should exist):
└── archon-router-consumer  ❌ NOT RUNNING (missing from deployment)
```

### Questions
1. **Should omniclaude have its own docker-compose?**
   - Or should it reference omniarchon services as external dependencies?

2. **Are archon services shared infrastructure?**
   - If yes: They should be deployed independently
   - If no: They should be in omniclaude docker-compose

3. **How should service discovery work?**
   - Service mesh?
   - Environment variables?
   - DNS/Consul?

### Action Items
- [ ] Define clear service ownership boundaries
- [ ] Document which repository owns which services
- [ ] Decide on shared infrastructure deployment model
- [ ] Create dependency diagram showing repository relationships
- [ ] Implement proper service discovery mechanism

---

## Issue 3: Hardcoded Configuration Throughout Codebase

### Problem
Ports, URLs, hostnames hardcoded in multiple locations.

**Instances Found:**
```yaml
# docker-compose files
- MEMGRAPH_URI=bolt://memgraph:7687          ❌ Hardcoded hostname
- ports: "8053:8053"                         ❌ Hardcoded port
- POSTGRES_PORT=5436                         ❌ Hardcoded port
- KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092 ❌ Hardcoded IP:port
```

**Should Be:**
```yaml
# docker-compose.yml
- MEMGRAPH_URI=${MEMGRAPH_URI}
- ports: "${ARCHON_INTELLIGENCE_PORT}:8053"
- POSTGRES_PORT=${POSTGRES_PORT}
- KAFKA_BOOTSTRAP_SERVERS=${KAFKA_BOOTSTRAP_SERVERS}

# .env.dev
MEMGRAPH_URI=bolt://archon-memgraph:7687
ARCHON_INTELLIGENCE_PORT=8053
POSTGRES_PORT=5436
KAFKA_BOOTSTRAP_SERVERS=192.168.86.200:9092
```

### Action Items
- [ ] Audit all docker-compose files for hardcoded values
- [ ] Extract all configuration to environment variables
- [ ] Create comprehensive .env.example with documentation
- [ ] Add validation to prevent hardcoding in future PRs
- [ ] Document environment variable naming conventions

---

## Issue 4: Service Health Dependencies

### Current Problem
Three services (archon-bridge, archon-search, archon-langextract) are unhealthy because:

**Root Cause:**
```bash
docker logs archon-bridge --tail 20
# ValueError: Cannot resolve address memgraph:7687
```

**Why This Happened:**
1. Service name is `memgraph` in docker-compose.yml
2. Container name is `archon-memgraph`
3. Docker DNS should resolve both, but doesn't
4. Services configured with `MEMGRAPH_URI=bolt://memgraph:7687`
5. DNS resolution failing

**Attempted Fix (WRONG APPROACH):**
- Edited multiple docker-compose files to change `memgraph:7687` → `archon-memgraph:7687`
- This crosses repository boundaries
- Perpetuates the hardcoding anti-pattern

**Correct Fix:**
```yaml
# docker-compose.yml
services:
  memgraph:
    container_name: archon-memgraph
    networks:
      app-network:
        aliases:
          - memgraph          # ✅ Add alias for backward compatibility
          - archon-memgraph   # ✅ New canonical name
```

OR:

```yaml
# .env.dev
MEMGRAPH_URI=bolt://archon-memgraph:7687

# docker-compose.yml
environment:
  - MEMGRAPH_URI=${MEMGRAPH_URI}  # ✅ No hardcoding
```

### Action Items
- [ ] Revert hardcoded changes to omniarchon docker-compose files
- [ ] Implement network alias solution OR environment variable solution
- [ ] Verify all three services become healthy
- [ ] Document the correct pattern for service discovery
- [ ] Add health check validation to deployment pipeline

---

## Issue 5: Agent Router Consumer Not Deployed

### Problem
The `archon-router-consumer` service exists in docker-compose but isn't running.

**Status:**
```bash
docker ps | grep router-consumer
# (no output - service not running)
```

**Expected:**
```
omniclaude_archon_router_consumer   Up 2 minutes (healthy)
```

**Root Cause:**
- Missing environment variables in .env file?
- Service not started during initial deployment?
- Dependency on database tables (migration 008)?

### Action Items
- [ ] Verify all required environment variables are in .env
- [ ] Check docker-compose service definition for router-consumer
- [ ] Start the service: `docker-compose up -d archon-router-consumer`
- [ ] Verify service health and Kafka connectivity
- [ ] Add to deployment automation

---

## Priority Order for Fixes

### Phase 1: Critical Infrastructure (This Week)
1. ✅ Apply database migration 008 (COMPLETED)
2. ✅ Environment variables in .env (COMPLETED)
3. ⏳ Revert cross-repository changes to omniarchon
4. ⏳ Fix memgraph DNS resolution (network alias approach)
5. ⏳ Start archon-router-consumer service
6. ⏳ Verify all services healthy

### Phase 2: Architecture Refactoring (Next 2 Weeks)
1. Consolidate docker-compose files to single file per repository
2. Create .env.dev, .env.staging, .env.prod templates
3. Extract all hardcoded configuration to environment variables
4. Document service ownership and boundaries
5. Implement proper service discovery

### Phase 3: Process Improvements (Ongoing)
1. Add linter to prevent hardcoded configuration
2. Add validation for .env files
3. Create deployment runbooks
4. Implement infrastructure-as-code validation
5. Set up automated health checks

---

## Related Documents
- **[ADR-001: Service Ownership Boundaries](../omniarchon/docs/architecture/ADR-001-SERVICE-OWNERSHIP-BOUNDARIES.md)** - Long-term architectural solution
- [Agent System Remediation Plan](AGENT_SYSTEM_REMEDIATION_PLAN.md)
- [Documentation Audit Report](DOCUMENTATION_AUDIT_REPORT_2025-11-04.md)
- [Security Audit](SECURITY_AUDIT_HARDCODED_PASSWORDS.md)

---

## Notes
- This document was created during investigation of agent system failures
- Cross-repository editing revealed deeper architectural issues
- **ADR-001 provides the proper architectural solution** - see mapping above
- Band-aid fixes in this document are temporary until ADR-001 implementation
- Following 12-factor app principles will prevent future issues
- ADR-001 timeline: 8 weeks across 3 phases

---

**Next Action:**
1. Apply band-aid fixes from Phase 1 to restore immediate functionality
2. Begin ADR-001 Phase 1 implementation (Service Ownership & Discovery)
3. Track long-term progress in ADR-001 implementation plan
