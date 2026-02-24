# System Status Skills - Test Suite Next Steps

**Date**: 2025-11-20
**Current Status**: 32.6% pass rate (45/138 tests)
**Target**: 95%+ pass rate (130+ tests)
**Timeline**: 5-8 days to completion

---

## Quick Links

- **[TEST_RESULTS_SUMMARY.md](TEST_RESULTS_SUMMARY.md)** - Complete test results and analysis
- **[SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md)** - Critical security issues to fix
- **[IMPORT_FIXES_NEEDED.md](IMPORT_FIXES_NEEDED.md)** - Test import path corrections

---

## Executive Summary

The test suite has successfully identified three categories of issues:

### 1. Critical Security Issues (Priority 1) 🔴

**Status**: 11.8% pass rate (4/34 security tests)
**Risk**: HIGH - Active vulnerabilities present
**Action Required**: IMMEDIATE

- **SQL Injection**: Direct vulnerability in check-agent-performance/execute.py
- **SSRF Protection**: Incomplete (internal IPs, file:// protocol not blocked)
- **Input Validation**: Missing bounds checking allows resource exhaustion

**DO NOT deploy to production until these are fixed.**

### 2. Test Infrastructure Issues (Priority 2) ⚠️

**Status**: 88 import errors blocking 58.7% of tests
**Impact**: Cannot accurately assess code quality
**Action Required**: Fix before proceeding with other testing

- All test files importing from wrong skill directories
- Mock/patch statements fail due to incorrect imports
- CLI argument names don't match actual implementation

### 3. Implementation Issues (Priority 3) 📊

**Status**: Unknown (blocked by import errors)
**Impact**: Medium - Functionality gaps and edge cases
**Action Required**: After import fixes are complete

- Schema mismatches (database columns don't match expectations)
- Missing error handling for null values
- Validation functions don't raise exceptions as expected

---

## Recommended Action Plan

### Week 1: Critical Security Fixes

**Goal**: Get all 34 security tests passing (100%)

#### Day 1-2: SQL Injection Vulnerabilities

**Tasks**:
1. Audit all SQL queries in all 8 skills
2. Replace f-strings with parameterized queries
3. Update `helpers/database_helper.py` to enforce parameterization
4. Run security tests: `pytest test_sql_injection_prevention.py test_sql_security.py -v`

**Success Criteria**:
- [ ] 0 f-strings in SQL queries
- [ ] All queries use `%s` placeholders
- [ ] 15/15 SQL security tests passing

**Owner**: Backend Developer
**Reviewer**: Security Team
**Estimated Time**: 6-8 hours

---

#### Day 3: SSRF Protection

**Tasks**:
1. Create `validate_qdrant_url()` in `helpers/qdrant_helper.py`
2. Define `ALLOWED_QDRANT_HOSTS` whitelist
3. Add IP pattern blocking (127.x, 10.x, 192.168.x, etc.)  <!-- onex-allow-internal-ip -->
4. Add protocol filtering (allow only http/https)
5. Add DNS resolution and IP validation
6. Run SSRF tests: `pytest test_ssrf_protection.py -v`

**Success Criteria**:
- [ ] Internal IPs blocked (127.x, 10.x, 192.168.x, 169.254.x)  <!-- onex-allow-internal-ip -->
- [ ] File protocol blocked (file://)
- [ ] DNS rebinding protection implemented
- [ ] 9/9 SSRF tests passing

**Owner**: Backend Developer
**Reviewer**: Security Team
**Estimated Time**: 4-6 hours

---

#### Day 4: Input Validation

**Tasks**:
1. Create `helpers/validators.py` with shared validation functions
2. Implement `validate_limit(min, max)`
3. Implement `validate_log_lines(min, max)`
4. Implement `validate_top_agents(min, max)`
5. Add numeric type checking and bounds enforcement
6. Add sanitization (reject special chars, unicode, null bytes)
7. Run validation tests: `pytest test_input_validation.py test_validators.py -v`

**Success Criteria**:
- [ ] All numeric inputs validated
- [ ] Bounds checking enforced (min/max values)
- [ ] Special characters rejected
- [ ] 28/28 validation tests passing

**Owner**: Backend Developer
**Reviewer**: QA Team
**Estimated Time**: 4-6 hours

---

#### Day 5: Security Review & Sign-Off

**Tasks**:
1. Run complete security test suite
2. Manual penetration testing
3. Code review for additional vulnerabilities
4. Document security fixes in CHANGELOG
5. Get sign-off from security team

**Success Criteria**:
- [ ] All 34 security tests passing (100%)
- [ ] Penetration testing shows no vulnerabilities
- [ ] Security team sign-off obtained
- [ ] Documentation complete

**Owner**: Security Team
**Estimated Time**: 4-6 hours

---

### Week 2: Test Infrastructure & Remaining Issues

#### Day 6: Fix Test Import Paths

**Goal**: Get import errors down to 0 (from 88)

**Tasks**:
1. Create `helpers/validators.py` (if not done in Day 4)
2. Update all test files to import from correct skill directories
3. Fix CLI argument names in tests (--since → --timeframe)
4. Re-run test suite and verify import errors eliminated

**File-by-File Checklist**:
- [ ] test_check_infrastructure.py → import from check-infrastructure
- [ ] test_check_kafka_topics.py → import from check-kafka-topics
- [ ] test_check_pattern_discovery.py → import from check-pattern-discovery
- [ ] test_check_service_status.py → import from check-service-status
- [ ] test_check_recent_activity.py → import from check-recent-activity
- [ ] test_check_database_health.py → import from check-database-health
- [ ] test_diagnose_issues.py → import from diagnose-issues
- [ ] test_generate_status_report.py → import from generate-status-report
- [ ] test_input_validation.py → import from helpers/validators
- [ ] test_validators.py → import from helpers/validators
- [ ] test_sql_injection_prevention.py → import from helpers/validators
- [ ] test_error_handling.py → import from check-infrastructure

**Success Criteria**:
- [ ] 0 import errors
- [ ] 0 attribute errors from wrong imports
- [ ] Pass rate increases to ~70-80%

**Owner**: QA Engineer
**Estimated Time**: 3-4 hours

---

#### Day 7: Fix Schema Mismatches

**Goal**: Align database expectations with actual schema

**Tasks**:
1. Review failing tests related to database schema
2. Check actual database schema (pg_dump or \d in psql)
3. Update tests to match actual schema OR fix schema to match tests
4. Handle null values in data processing
5. Re-run database tests

**Specific Issues**:
- [ ] `test_connection_pool_stats` expects `total_decisions` column
- [ ] `test_query_performance_metrics` expects `agent` column
- [ ] Null value handling in data processing

**Success Criteria**:
- [ ] Database schema documented
- [ ] Tests match actual schema
- [ ] Null values handled gracefully

**Owner**: Database Developer
**Estimated Time**: 4-6 hours

---

#### Day 8: Fix Remaining Logic Issues

**Goal**: Get pass rate to 95%+

**Tasks**:
1. Review all remaining failing tests
2. Categorize failures (implementation bug vs test bug)
3. Fix implementation issues
4. Fix test issues
5. Add missing edge case handling

**Common Issues**:
- [ ] Validation functions don't raise exceptions (need `raise` statements)
- [ ] Error handling doesn't set correct exit codes
- [ ] Edge cases not handled (empty results, null values)

**Success Criteria**:
- [ ] Pass rate >= 95% (130+ of 138 tests)
- [ ] All critical paths tested
- [ ] Edge cases covered

**Owner**: Development Team
**Estimated Time**: 6-8 hours

---

#### Day 9-10: Documentation & Cleanup

**Goal**: Production-ready test suite

**Tasks**:
1. Document test coverage and gaps
2. Add missing tests for uncovered code paths
3. Update skill READMEs with testing instructions
4. Create CI/CD integration plan
5. Write testing guidelines for future skills

**Deliverables**:
- [ ] Test coverage report (target: >80% line coverage)
- [ ] Testing documentation
- [ ] CI/CD pipeline configuration
- [ ] Testing guidelines document

**Owner**: QA Team + Tech Lead
**Estimated Time**: 8-10 hours

---

## Daily Standup Checklist

Use this during daily standups to track progress:

### Security Fixes (Days 1-5)

- [ ] Day 1: SQL injection audit complete
- [ ] Day 2: All SQL queries parameterized
- [ ] Day 3: SSRF protection implemented
- [ ] Day 4: Input validation complete
- [ ] Day 5: Security sign-off obtained

### Test Infrastructure (Days 6-8)

- [ ] Day 6: Import paths fixed, 0 import errors
- [ ] Day 7: Schema mismatches resolved
- [ ] Day 8: Logic issues fixed, 95%+ pass rate

### Finalization (Days 9-10)

- [ ] Day 9: Documentation complete
- [ ] Day 10: CI/CD integration ready

---

## Success Metrics

### Security (End of Week 1)

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| SQL Injection Tests | 0/15 (0%) | 15/15 (100%) | 🔴 |
| SSRF Protection Tests | 4/9 (44%) | 9/9 (100%) | 🟡 |
| Input Validation Tests | 0/28 (0%) | 28/28 (100%) | 🔴 |
| **Total Security Tests** | **4/34 (11.8%)** | **34/34 (100%)** | 🔴 |

### Test Infrastructure (End of Week 2)

| Metric | Current | Target | Status |
|--------|---------|--------|--------|
| Import Errors | 88 | 0 | 🔴 |
| Pass Rate | 32.6% | 95%+ | 🔴 |
| Tests Passing | 45/138 | 130+/138 | 🔴 |
| Test Coverage | Unknown | >80% | 🔴 |

---

## Risk Assessment

### High Risk Items

1. **SQL Injection (P1)** - Active vulnerability, exploit risk high
2. **SSRF (P1)** - Internal network accessible, metadata API exposure
3. **Resource Exhaustion (P2)** - Missing bounds checking allows DoS

### Medium Risk Items

1. **Test Infrastructure (P2)** - Cannot accurately test without fixing imports
2. **Schema Mismatches (P3)** - May indicate production issues
3. **Null Handling (P3)** - Edge cases may cause errors

### Low Risk Items

1. **Documentation (P4)** - Can be done after testing is complete
2. **CI/CD Integration (P4)** - Nice to have, not blocking

---

## Communication Plan

### Daily Updates

**To**: Development Team, Security Team, QA Team
**Format**: Slack message in #system-status-skills channel
**Content**:
- Tests fixed today
- Security issues resolved
- Blockers encountered
- Tomorrow's plan

### Weekly Report

**To**: Tech Lead, Product Owner
**Format**: Email or Confluence page
**Content**:
- Pass rate progress
- Security status
- Risks and blockers
- Timeline updates

### Final Report

**To**: All Stakeholders
**Format**: Presentation or document
**Content**:
- Final test results
- Security fixes implemented
- Code coverage achieved
- Production readiness assessment

---

## Useful Commands

### Run Security Tests

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/system-status/tests

# All security tests
pytest test_sql_injection_prevention.py test_sql_security.py test_ssrf_protection.py test_input_validation.py test_validators.py -v

# SQL injection only
pytest test_sql_injection_prevention.py test_sql_security.py -v

# SSRF only
pytest test_ssrf_protection.py -v

# Input validation only
pytest test_input_validation.py test_validators.py -v
```

### Run Full Test Suite

```bash
# Verbose output
pytest -v

# With coverage
pytest --cov=.. --cov-report=term --cov-report=html -v

# Generate summary
pytest -v > test_results_$(date +%Y%m%d).txt 2>&1
```

### Check SQL for Vulnerabilities

```bash
# Find f-strings in SQL queries (WRONG)
grep -rn "f\".*SELECT" ../*/execute.py

# Find parameterized queries (CORRECT)
grep -rn "execute_query.*%s" ../*/execute.py
```

### Check Import Paths

```bash
# Find all sys.path.insert statements
grep -n "sys.path.insert" test_*.py

# Verify correct skill directory
grep -A1 "sys.path.insert" test_check_infrastructure.py
```

---

## Getting Help

### Blocked on Security Fixes?

**Contact**: Security Team
**Slack**: #security
**Email**: security@company.com
**Response Time**: <4 hours

### Blocked on Test Infrastructure?

**Contact**: QA Team
**Slack**: #qa
**Email**: qa@company.com
**Response Time**: <8 hours

### Blocked on Implementation Issues?

**Contact**: Development Team
**Slack**: #dev-backend
**Email**: dev-backend@company.com
**Response Time**: <24 hours

---

## Appendix

### File Locations

- Test files: `${CLAUDE_PLUGIN_ROOT}/skills/system-status/tests/`
- Skill files: `${CLAUDE_PLUGIN_ROOT}/skills/system-status/*/`
- Helper modules: `${CLAUDE_PLUGIN_ROOT}/skills/system-status/helpers/`
- Reports: `${CLAUDE_PLUGIN_ROOT}/skills/system-status/tests/*.md`

### Test Result Files

- `test_results.txt` - Initial run (stopped at 20 failures)
- `test_results_full.txt` - Complete run (138 tests)
- `TEST_RESULTS_SUMMARY.md` - This file
- `SECURITY_CHECKLIST.md` - Security issues tracking
- `IMPORT_FIXES_NEEDED.md` - Import path fixes
- `NEXT_STEPS.md` - Action plan (you are here)

### Reference Documents

- [Pytest Documentation](https://docs.pytest.org/)
- [SQL Injection Prevention (OWASP)](https://owasp.org/www-community/attacks/SQL_Injection)
- [SSRF Prevention (OWASP)](https://owasp.org/www-community/attacks/Server_Side_Request_Forgery)
- [Python Input Validation Best Practices](https://realpython.com/python-data-validation/)

---

**Last Updated**: 2025-11-20
**Owner**: QA Team
**Status**: In Progress
**Next Review**: 2025-11-21 (daily standup)
