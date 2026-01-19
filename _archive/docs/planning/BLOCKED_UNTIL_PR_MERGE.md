# BLOCKED: Universal Agent Router Implementation

**Status**: ⛔ BLOCKED - DO NOT START
**Blocked By**: PR #22 (Observability infrastructure)
**Blocking Since**: 2025-11-07
**Last Updated**: 2025-11-07

---

## ⚠️ IMPORTANT: DO NOT START THIS WORK YET

The Universal Agent Router implementation is **BLOCKED** until PR #22 merges.

**This document serves as a gate** to ensure proper sequencing of work.

---

## Blocking PR Details

### PR #22: Complete Observability Infrastructure

**Link**: https://github.com/OmniNode-ai/omniclaude/pull/22

**Title**: "feat: Complete observability infrastructure with action logging and pattern cleanup"

**Branch**: `fix/observability-data-flow-gaps`

**Current Status** (as of 2025-11-07):
- **State**: OPEN, MERGEABLE
- **CI/CD**: ❌ 3 checks failing
  1. Code Quality Checks - FAIL (4m59s)
  2. Python Security Scan - FAIL (4m10s)
  3. Run Tests - FAIL (5m13s)
- **Review**: CodeRabbit review with 25 comments
  - 9 actionable (must address)
  - 4 critical outside-diff (high priority)
  - 12 nitpick (recommended)

**Estimated Resolution Time**: 1-2 days

**Target Merge Date**: 2025-11-08 or 2025-11-09

---

## Why Universal Router is Blocked

The Universal Agent Router depends on infrastructure from PR #22:

### 1. Observability Infrastructure

**Required from PR #22**:
- ✅ Action logging framework with correlation tracking
- ✅ Manifest injection traceability
- ✅ Database schemas for event logging
- ✅ PostgreSQL event storage patterns

**Why needed**:
- Universal Router needs to log routing events with same patterns
- Correlation ID tracking must be consistent across systems
- Database schemas must exist before Universal Router tables are created

### 2. Type-Safe Configuration

**Required from PR #22**:
- ✅ Pydantic Settings framework
- ✅ 90+ validated configuration variables
- ✅ Environment variable loading patterns
- ✅ Configuration validation helpers

**Why needed**:
- Universal Router will use Pydantic Settings for configuration
- Must follow same configuration patterns as rest of codebase
- Type safety and validation are critical for production system

### 3. Docker Compose Consolidation

**Required from PR #22**:
- ✅ Consolidated `deployment/docker-compose.yml`
- ✅ Environment-based deployment
- ✅ Profile-based service selection
- ✅ External network references

**Why needed**:
- Universal Router will integrate into same docker-compose file
- Must follow same deployment patterns
- Network architecture must be established first

### 4. Kafka Event Patterns

**Required from PR #22**:
- ✅ Event bus communication patterns
- ✅ Event schema designs
- ✅ Correlation ID propagation
- ✅ Event-driven architecture examples

**Why needed**:
- Universal Router uses Kafka for multi-protocol support
- Must follow same event patterns as other services
- Event schemas must be consistent

---

## Issues Blocking PR #22 Merge

### Critical Issues (Must Fix)

**1. CI/CD Failures**:
- Code quality checks failing (linting, formatting)
- Security scan failures (Bandit warnings)
- Unit/integration tests failing

**2. CodeRabbit Review Comments**:
- `routing_event_client.py` cleanup logic needs fix
- `omninode_template_engine.py` Kafka URL normalization (2 locations)
- `agent_coder.py` model metadata mismatch
- Multiple sys.path mutations (should use package-relative imports)

### Recommended Fixes

**3. Nitpick Comments** (12 total):
- Defensive coding patterns
- Configuration validation
- Timestamp handling
- Import patterns

---

## Action Plan to Unblock

### Immediate Actions (Day 1)

1. **Fix CI/CD Failures**
   ```bash
   # Run linters locally
   black . --check
   ruff check .
   mypy .

   # Fix issues
   black .
   ruff check . --fix

   # Run tests
   pytest tests/ -v

   # Fix failing tests
   ```

2. **Address CodeRabbit Critical Comments**
   - Fix `routing_event_client.py` stop() method cleanup
   - Fix Kafka URL normalization in `omninode_template_engine.py`
   - Fix model metadata in `agent_coder.py`
   - Replace sys.path mutations with package-relative imports

3. **Run Full Test Suite**
   ```bash
   pytest tests/ --cov=. --cov-report=html
   ```

4. **Push Fixes and Re-run CI/CD**
   ```bash
   git add .
   git commit -m "fix: resolve CI/CD failures and CodeRabbit critical issues"
   git push
   ```

### Day 2 (if needed)

5. **Address Remaining Review Comments**
   - Optional: Fix nitpick comments for code quality

6. **Final Verification**
   ```bash
   # Full test suite
   pytest tests/ -v

   # Load tests (if applicable)
   # ...

   # Manual verification
   ./scripts/health_check.sh
   ```

7. **Request Final Review**
   - Comment on PR: "All CI/CD checks passing, CodeRabbit issues resolved"
   - Request approval from maintainers

8. **Merge PR**
   ```bash
   # Squash and merge (recommended)
   # or
   # Rebase and merge
   ```

---

## When Unblocked: Start Universal Router

### Prerequisites Checklist

Before starting Universal Router Phase 1, verify:

- [x] PR #22 merged to main
- [ ] All CI/CD checks passing on main
- [ ] No breaking changes in main branch
- [ ] Documentation updated (if needed)

### Infrastructure Verification

Before starting Phase 1, verify infrastructure is ready:

```bash
# 1. PostgreSQL connectivity
psql -h 192.168.86.200 -p 5436 -U postgres -d omninode_bridge -c "SELECT 1"
# Expected: Returns 1

# 2. Kafka/Redpanda health
docker exec omninode-bridge-redpanda rpk cluster health
# Expected: Healthy cluster

# 3. vLLM endpoint
curl http://192.168.86.200:11434/v1/models
# Expected: Returns model list (including Llama-3.1-8B-Instruct)

# 4. Agent registry exists
ls ~/.claude/agent-definitions/
# Expected: YAML files present

# 5. Type-safe config works
python3 -c "from config import settings; print(settings.validate_required_services())"
# Expected: No errors or empty list
```

### Then Start Phase 1

Once all prerequisites are met:

1. Read: `docs/architecture/UNIVERSAL_AGENT_ROUTER.md`
2. Read: `docs/planning/ROUTER_IMPLEMENTATION_PLAN.md`
3. Start: Phase 1, Day 1 (Service Scaffold)

---

## Monitoring Progress

### How to Check PR #22 Status

```bash
# From command line
gh pr view 22

# Check CI/CD status
gh pr checks 22

# View in browser
open https://github.com/OmniNode-ai/omniclaude/pull/22
```

### Notification Strategy

**Automated Alerts** (if available):
- GitHub PR notifications (watch PR #22)
- Slack/Discord webhook when PR #22 merges

**Manual Checks**:
- Check PR status daily at 9:00 AM
- Review CI/CD checks after each push
- Monitor CodeRabbit review comments

---

## Escalation Path

If PR #22 is not merged by **2025-11-09 EOD**:

1. **Escalate to Project Lead**
   - Identify blockers preventing merge
   - Request additional resources if needed
   - Adjust timeline for Universal Router

2. **Alternative Plan** (if necessary):
   - Start Universal Router documentation work
   - Prepare infrastructure (Valkey, vLLM config)
   - Design architecture in parallel (without implementation)

3. **Timeline Adjustment**
   - Universal Router Phase 1 start date shifts by N days
   - Update project timeline
   - Communicate to stakeholders

---

## Stakeholder Communication

### Who Needs to Know

**Internal Team**:
- Technical Lead: Jonah Gray
- Developers working on Universal Router
- QA/Testing team

**External Stakeholders**:
- Project sponsors (if any)
- Dependent teams/projects

### Communication Template

```
Subject: Universal Agent Router Implementation - Blocked

Hi [Name],

The Universal Agent Router implementation is currently BLOCKED pending merge of PR #22
(Observability infrastructure).

Current Status:
- PR #22 is open with 3 failing CI/CD checks
- Estimated resolution: 1-2 days
- Target merge: 2025-11-08 or 2025-11-09

Impact:
- Universal Router Phase 1 cannot start until PR #22 merges
- Total project timeline may shift by 1-2 days

Next Steps:
- Prioritizing PR #22 fixes immediately
- Will update when PR #22 merges
- Universal Router Phase 1 to begin immediately after

Questions or concerns? Please let me know.

Thanks,
[Your Name]
```

---

## Document History

| Date | Change | Author |
|------|--------|--------|
| 2025-11-07 | Initial creation | Polly (Polymorphic Agent) |

---

## Related Documents

- [Universal Agent Router Architecture](../architecture/UNIVERSAL_AGENT_ROUTER.md)
- [Universal Router Implementation Plan](ROUTER_IMPLEMENTATION_PLAN.md)
- [PR #22: Complete Observability Infrastructure](https://github.com/OmniNode-ai/omniclaude/pull/22)
- [CLAUDE.md](../../CLAUDE.md) - Project documentation

---

**⚠️ REMINDER: DO NOT START UNIVERSAL ROUTER WORK UNTIL THIS FILE IS DELETED**

This file will be deleted when PR #22 merges and prerequisites are verified.

Delete this file only when:
1. PR #22 is merged to main
2. All infrastructure verification checks pass
3. Universal Router Phase 1 is ready to begin

---

**Status**: ⛔ BLOCKED
**Next Review**: 2025-11-08 09:00 AM
**Expected Unblock**: 2025-11-08 or 2025-11-09
