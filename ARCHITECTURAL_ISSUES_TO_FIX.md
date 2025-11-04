# Architectural Issues To Fix

**Created**: 2025-11-04
**Priority**: HIGH
**Status**: NEEDS INVESTIGATION

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
- [Agent System Remediation Plan](AGENT_SYSTEM_REMEDIATION_PLAN.md)
- [Documentation Audit Report](DOCUMENTATION_AUDIT_REPORT_2025-11-04.md)
- [Security Audit](SECURITY_AUDIT_HARDCODED_PASSWORDS.md)

---

## Notes
- This document was created during investigation of agent system failures
- Cross-repository editing revealed deeper architectural issues
- Proper fix requires architectural refactoring, not band-aids
- Following 12-factor app principles will prevent future issues

---

**Next Action:** Review with team and prioritize fixes based on risk/impact.
