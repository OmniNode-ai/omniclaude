# OmniClaude Enhanced CI/CD Pipeline Documentation

## Overview

The OmniClaude repository uses a comprehensive, multi-layered CI/CD pipeline designed specifically for ONEX architecture compliance and production-ready deployments. This document provides a complete reference for understanding, using, and maintaining the CI/CD infrastructure.

## Pipeline Architecture

### Available Workflows

1. **enhanced-ci.yml** - Comprehensive testing and validation pipeline
2. **ci-cd.yml** - Standard CI/CD with Docker build and deployment
3. **security-scan.yml** - Security scanning and vulnerability assessment

### Enhanced CI Pipeline Jobs

The enhanced-ci.yml workflow provides 11 specialized jobs organized into validation, testing, and deployment phases:

#### Phase 1: Validation Jobs (Parallel Execution)

##### 1. `quality-strict` - Code Quality (Strict Mode)
**Purpose**: Enforce code quality standards with zero tolerance for violations

**Tools**:
- **Black**: Code formatting validation (must pass)
- **Ruff**: Python linting with strict rules
- **MyPy**: Type checking in strict mode with comprehensive flags

**Strict MyPy Configuration**:
```bash
--strict                    # Enable all optional checks
--show-error-codes          # Show error codes for easier debugging
--disallow-untyped-defs     # All functions must have type hints
--warn-redundant-casts      # Warn about unnecessary casts
--warn-unused-ignores       # Warn about unused type: ignore comments
--no-implicit-optional      # Strict None checking
```

**Success Criteria**: All checks must pass with zero errors

**Artifacts**:
- MyPy cache and report

---

##### 2. `onex-validation` - ONEX Architecture Compliance
**Purpose**: Validate ONEX architectural standards and naming conventions

**Validations**:

1. **ONEX Naming Conventions**:
   - Effect nodes: `Node<Name>Effect` in `*_effect.py`
   - Compute nodes: `Node<Name>Compute` in `*_compute.py`
   - Reducer nodes: `Node<Name>Reducer` in `*_reducer.py`
   - Orchestrator nodes: `Node<Name>Orchestrator` in `*_orchestrator.py`

2. **Contract Usage Validation**:
   - Verify `ModelContract` usage in all nodes
   - Check proper contract definitions

3. **Method Signature Validation**:
   - Effect nodes: `async def execute_effect(self, contract: ModelContractEffect)`
   - Compute nodes: `async def execute_compute(self, contract: ModelContractCompute)`
   - Reducer nodes: `async def execute_reduction(self, contract: ModelContractReducer)`
   - Orchestrator nodes: `async def execute_orchestration(self, contract: ModelContractOrchestrator)`

**Success Criteria**: All ONEX patterns must be followed

---

##### 3. `database-validation` - Database Schema Validation
**Purpose**: Validate PostgreSQL schema initialization and migrations

**Process**:
1. Start PostgreSQL 16 service
2. Run `scripts/init-db.sh` initialization script
3. Validate tables (post DB-SPLIT-07):
   - `schema_migrations`
   - `claude_session_snapshots`
   - `claude_session_prompts`
   - `claude_session_tools`
4. Validate indexes and constraints
5. Verify schema integrity

**Services**:
- PostgreSQL 16-alpine with health checks

**Success Criteria**: All tables, indexes, and constraints created successfully

---

##### 4. `docker-compose-validation` - Stack Validation
**Purpose**: Validate full Docker Compose stack deployment

**Process**:
1. Validate docker-compose.yml syntax
2. Build all services in parallel
3. Start complete stack
4. Validate service health:
   - PostgreSQL: `pg_isready`
   - Redis: `redis-cli ping`
   - App: `/health` endpoint
5. Cleanup

**Services Validated**:
- App container
- PostgreSQL
- Redis
- Prometheus
- Grafana
- OpenTelemetry Collector
- Jaeger

**Success Criteria**: All services start and pass health checks

---

#### Phase 2: Testing Jobs (Comprehensive Coverage)

##### 5. `unit-tests` - Fast Unit Tests
**Purpose**: Run isolated unit tests without external dependencies

**Coverage**:
- All tests in `agents/tests/` (excluding integration tests)
- Tests marked with `-m "not integration"`
- Fast execution (<2 minutes)

**Output**:
- JUnit XML report
- Code coverage report (XML format)
- Coverage uploaded to Codecov

**Excluded Tests**:
- `test_integration_smoke.py`
- `test_phase4_integration.py`
- `test_phase5_integration.py`
- `test_framework_integration.py`
- `test_end_to_end_workflows.py`

**Success Criteria**: All unit tests pass with >80% coverage

---

##### 6. `integration-tests` - Integration Tests with Services
**Purpose**: Test component integration with real PostgreSQL and Redis

**Services**:
- PostgreSQL 16-alpine
- Redis 7-alpine

**Process**:
1. Start database and cache services
2. Initialize test database schema
3. Run integration test suite
4. Collect coverage metrics

**Tests Included**:
- `test_integration_smoke.py`
- `test_phase4_integration.py`
- `test_phase5_integration.py`
- `test_framework_integration.py`
- `test_end_to_end_workflows.py`

**Environment Variables**:
```bash
DATABASE_URL=postgresql://test:test@localhost:5432/test_db
REDIS_URL=redis://localhost:6379/0
```

**Success Criteria**: All integration tests pass

---

##### 7. `hooks-tests` - Hooks System Tests
**Purpose**: Validate Claude hooks system with database integration

**Services**:
- PostgreSQL 16-alpine (dedicated instance)

**Coverage**:
- All tests in `claude_hooks/tests/`
- Hook lifecycle management
- Database integration
- Event memory store
- AST correction
- Agent detection
- Naming validation

**Database**: `hooks_test_db` with separate credentials

**Success Criteria**: All hooks tests pass with database integration

---

##### 8. `agent-framework-tests` - Agent Framework Validation
**Purpose**: Test agent coordination and routing framework

**Tests Included**:
- `test_agent_router.py` - Intelligent agent routing
- `test_quality_gates.py` - Quality gate validation
- `test_performance_thresholds.py` - Performance threshold compliance

**Coverage Focus**:
- Enhanced router fuzzy matching
- Confidence scoring
- Quality gate execution
- Performance threshold validation

**Success Criteria**: All agent framework tests pass

---

##### 9. `performance-benchmarks` - Performance Testing
**Purpose**: Run performance benchmarks and prevent regressions

**Benchmarks**:
1. **Template Cache Benchmark**: `agents/tests/benchmark_template_cache.py`
   - Cache hit/miss rates
   - Lookup performance
   - Memory usage

2. **Parallel Execution Benchmark**: `agents/parallel_execution/parallel_benchmark.py`
   - Parallel workflow performance
   - Coordination overhead
   - Throughput metrics

3. **General Benchmarks**: `agents/benchmark_improvements.py`
   - Overall system performance
   - Optimization effectiveness

**Artifacts**:
- `benchmark-results.json`
- `performance-report.txt`

**Success Criteria**: Benchmarks complete without regressions

---

#### Phase 3: Build and Deployment

##### 10. `build` - Docker Image Build
**Purpose**: Build and push production Docker images

**Dependencies**: All validation and testing jobs must pass

**Process**:
1. Build Docker image with BuildKit
2. Extract metadata (tags, labels)
3. Push to GitHub Container Registry
4. Use layer caching for efficiency

**Tags Generated**:
- Branch name (e.g., `main`, `develop`)
- PR number (e.g., `pr-123`)
- Semantic version (if tagged)
- Git SHA (short form)
- `latest` (for main branch only)

**Build Args**:
```dockerfile
BUILD_DATE=<timestamp>
VCS_REF=<git-sha>
VERSION=<version>
```

**Success Criteria**: Image builds and pushes successfully

---

##### 11. `test-summary` - Test Summary Report
**Purpose**: Aggregate and report all test results

**Process**:
1. Download all test artifacts
2. Generate summary in GitHub Step Summary
3. Report pass/fail status for each test suite

**Always Runs**: Even if previous jobs fail

---

## Workflow Triggers

### Push Events
```yaml
on:
  push:
    branches: [main, develop, feature/**]
```
- Triggers on commits to main, develop, or any feature branch

### Pull Request Events
```yaml
  pull_request:
    branches: [main, develop]
```
- Triggers on PRs targeting main or develop

### Manual Trigger
```yaml
  workflow_dispatch:
```
- Can be triggered manually from GitHub UI

---

## Environment Variables

### Global Variables
```yaml
REGISTRY: ghcr.io                           # GitHub Container Registry
IMAGE_NAME: ${{ github.repository }}        # Repository full name
PYTHON_VERSION: '3.12'                      # Python version
POETRY_VERSION: '1.8.3'                     # Poetry version
```

### Job-Specific Variables

#### Database Connections
```bash
# Integration Tests
DATABASE_URL=postgresql://test:test@localhost:5432/test_db
REDIS_URL=redis://localhost:6379/0

# Hooks Tests
DATABASE_URL=postgresql://hooks_test:hooks_test@localhost:5432/hooks_test_db

# Schema Validation
POSTGRES_USER=schema_test
POSTGRES_PASSWORD=schema_test
POSTGRES_DB=schema_test_db
```

---

## Caching Strategy

### Dependency Caching
```yaml
- name: Load cached venv
  uses: actions/cache@v4
  with:
    path: .venv
    key: venv-${{ runner.os }}-${{ hashFiles('**/poetry.lock') }}
```

**Benefits**:
- Faster job execution (30-60 seconds saved per job)
- Reduced network traffic
- Consistent dependencies across jobs

### Docker Layer Caching
```yaml
cache-from: type=gha
cache-to: type=gha,mode=max
```

**Benefits**:
- Faster Docker builds (5-10 minutes saved)
- Reduced build time for unchanged layers

---

## Service Health Checks

All database services use health checks to ensure readiness:

### PostgreSQL Health Check
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U <user> -d <database>"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

### Redis Health Check
```yaml
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 5s
  retries: 5
```

---

## Artifacts and Reports

### Uploaded Artifacts

1. **Type Checking Report** (`mypy-report`)
   - MyPy cache directory
   - Full type checking results

2. **Unit Test Results** (`unit-test-results`)
   - JUnit XML report
   - Coverage data

3. **Integration Test Results** (`integration-test-results`)
   - JUnit XML report
   - Coverage data

4. **Hooks Test Results** (`hooks-test-results`)
   - JUnit XML report
   - Coverage data

5. **Agent Framework Test Results** (`agent-framework-test-results`)
   - JUnit XML report
   - Coverage data

6. **Performance Benchmarks** (`performance-benchmarks`)
   - `benchmark-results.json`
   - `performance-report.txt`

### Codecov Integration

Coverage reports are uploaded to Codecov with different flags:
- `unittests` - Unit test coverage
- `integration` - Integration test coverage
- `hooks` - Hooks system coverage
- `agent-framework` - Agent framework coverage

---

## ONEX Compliance Checks

### Naming Convention Validation

The ONEX validation job enforces strict naming conventions:

#### File-to-Class Mapping
| File Pattern | Required Class Pattern | Example |
|--------------|------------------------|---------|
| `node_*_effect.py` | `Node<Name>Effect` | `NodeDatabaseWriterEffect` |
| `node_*_compute.py` | `Node<Name>Compute` | `NodeDataTransformerCompute` |
| `node_*_reducer.py` | `Node<Name>Reducer` | `NodeStateAggregatorReducer` |
| `node_*_orchestrator.py` | `Node<Name>Orchestrator` | `NodeWorkflowCoordinatorOrchestrator` |

#### Method Signature Requirements
| Node Type | Required Method | Signature |
|-----------|----------------|-----------|
| Effect | `execute_effect` | `async def execute_effect(self, contract: ModelContractEffect) -> Any` |
| Compute | `execute_compute` | `async def execute_compute(self, contract: ModelContractCompute) -> Any` |
| Reducer | `execute_reduction` | `async def execute_reduction(self, contract: ModelContractReducer) -> Any` |
| Orchestrator | `execute_orchestration` | `async def execute_orchestration(self, contract: ModelContractOrchestrator) -> Any` |

### Contract Validation

All nodes must:
1. Import appropriate `ModelContract` types
2. Use contracts in method signatures
3. Follow contract inheritance patterns

---

## Troubleshooting

### Common Issues

#### 1. Type Checking Failures
**Problem**: MyPy strict mode fails with type errors

**Solution**:
```bash
# Run locally to see detailed errors
poetry run mypy agents/ claude_hooks/ --strict --show-error-codes

# Fix type hints in failing files
# Add type stubs if needed
poetry run pip install types-<package>
```

#### 2. ONEX Naming Convention Failures
**Problem**: ONEX validation fails on node naming

**Solution**:
- Ensure file names match pattern: `node_<name>_<type>.py`
- Ensure class names match pattern: `Node<Name><Type>`
- Verify method signatures match ONEX requirements

#### 3. Integration Test Failures
**Problem**: Integration tests fail to connect to database

**Solution**:
```bash
# Check service health in CI logs
# Wait for service to be healthy before running tests
until psql -h localhost -U test -d test_db -c '\q'; do
  sleep 2
done
```

#### 4. Docker Compose Validation Failures
**Problem**: Stack health checks fail

**Solution**:
- Increase health check timeout
- Verify service dependencies
- Check port conflicts
- Review service logs

#### 5. Performance Benchmark Regressions
**Problem**: Benchmarks show performance degradation

**Solution**:
- Review recent changes for performance impact
- Check for inefficient algorithms
- Verify database query optimization
- Review caching effectiveness

---

## Local Development

### Running CI Checks Locally

#### 1. Code Quality Checks
```bash
# Black formatting
poetry run black --check .

# Ruff linting
poetry run ruff check .

# Type checking (strict)
poetry run mypy agents/ claude_hooks/ \
  --strict \
  --show-error-codes \
  --ignore-missing-imports
```

#### 2. ONEX Validation
```bash
# Run ONEX naming validation
find agents/ claude_hooks/ -name "node_*.py" | while read file; do
  echo "Checking $file..."
  # Manual validation or use grep
done
```

#### 3. Unit Tests
```bash
poetry run pytest agents/tests/ \
  -m "not integration" \
  -v \
  --cov=agents
```

#### 4. Integration Tests (with Docker)
```bash
# Start services
docker-compose up -d postgres redis

# Wait for services
sleep 10

# Run integration tests
poetry run pytest agents/tests/ \
  -m integration \
  -v \
  --cov=agents

# Cleanup
docker-compose down
```

#### 5. Hooks Tests
```bash
# Start PostgreSQL
docker-compose up -d postgres

# Run hooks tests
poetry run pytest claude_hooks/tests/ -v --cov=claude_hooks

# Cleanup
docker-compose down
```

#### 6. Performance Benchmarks
```bash
# Run all benchmarks
poetry run python agents/tests/benchmark_template_cache.py
poetry run python agents/parallel_execution/parallel_benchmark.py
poetry run python agents/benchmark_improvements.py
```

#### 7. Docker Compose Validation
```bash
# Validate syntax
docker-compose config --quiet

# Build stack
docker-compose build

# Start stack
docker-compose up -d

# Check health
docker-compose ps

# Cleanup
docker-compose down -v
```

---

## Performance Targets

### Job Execution Times (Target)

| Job | Target Time | Acceptable Range |
|-----|-------------|------------------|
| quality-strict | 3 min | 2-5 min |
| onex-validation | 2 min | 1-3 min |
| unit-tests | 5 min | 3-7 min |
| integration-tests | 8 min | 5-10 min |
| hooks-tests | 6 min | 4-8 min |
| agent-framework-tests | 4 min | 3-6 min |
| performance-benchmarks | 5 min | 3-7 min |
| database-validation | 3 min | 2-4 min |
| docker-compose-validation | 10 min | 8-15 min |
| build | 15 min | 10-20 min |
| **Total Pipeline** | **30 min** | **25-40 min** |

### Optimization Tips

1. **Dependency Caching**: Ensure Poetry cache is working (30-60s savings)
2. **Parallel Execution**: Jobs run in parallel when possible
3. **Service Health Checks**: Optimize wait times for service readiness
4. **Docker Layer Caching**: Use GitHub Actions cache for Docker builds
5. **Test Parallelization**: Use pytest-xdist for parallel test execution

---

## Security Considerations

### Secrets Management
- Never commit API keys or passwords
- Use GitHub Secrets for sensitive data
- Rotate database passwords regularly
- Use separate credentials for each environment

### Database Security
- Test databases use weak passwords (acceptable for CI)
- Production databases use strong, rotated passwords
- Database connections are isolated per job
- Services are cleaned up after job completion

### Container Security
- Use official images (PostgreSQL 16-alpine, Redis 7-alpine)
- Keep base images updated
- Scan containers with Trivy (separate security-scan.yml)
- Run containers with minimal privileges

---

## Maintenance

### Regular Maintenance Tasks

#### Weekly
- Review failed workflow runs
- Check coverage trends
- Monitor performance benchmarks
- Review security scan results

#### Monthly
- Update Poetry dependencies
- Update GitHub Actions versions
- Review and optimize job execution times
- Update Python base images

#### Quarterly
- Audit ONEX compliance rules
- Review and update quality gates
- Optimize caching strategies
- Update documentation

---

## Migration from Legacy CI

### Differences from ci-cd.yml

The enhanced-ci.yml workflow provides:

1. **Separated Test Suites**: Unit, integration, hooks, and agent framework tests run independently
2. **ONEX Validation**: Dedicated job for ONEX architecture compliance
3. **Strict Type Checking**: MyPy runs in strict mode (vs. permissive with || true)
4. **Database Validation**: Explicit schema validation job
5. **Docker Compose Validation**: Full stack testing in CI
6. **Performance Benchmarks**: Dedicated performance testing job
7. **Enhanced Reporting**: Better artifact collection and test summaries

### Migration Path

**Option 1: Replace ci-cd.yml**
```bash
# Rename old workflow
mv .github/workflows/ci-cd.yml .github/workflows/ci-cd.yml.old

# Rename enhanced workflow
mv .github/workflows/enhanced-ci.yml .github/workflows/ci-cd.yml
```

**Option 2: Run Both Workflows**
- Keep both workflows active
- Enhanced workflow for comprehensive validation
- Legacy workflow for quick checks
- Gradually migrate to enhanced workflow

**Option 3: Merge Workflows**
- Combine best features of both
- Keep legacy jobs that work well
- Add enhanced validation jobs
- Maintain single workflow file

---

## Success Metrics

### Coverage Targets
- **Unit Tests**: ≥80% code coverage
- **Integration Tests**: ≥70% code coverage
- **Hooks Tests**: ≥75% code coverage
- **Agent Framework**: ≥85% code coverage
- **Overall**: ≥80% combined coverage

### Quality Gates
- **Black**: 100% formatted correctly
- **Ruff**: Zero linting violations
- **MyPy**: Zero type errors (strict mode)
- **ONEX Compliance**: 100% adherence
- **Security Scans**: Zero critical/high vulnerabilities

### Performance Gates
- **Unit Tests**: <5 minutes
- **Integration Tests**: <10 minutes
- **Total Pipeline**: <40 minutes
- **Benchmark Regression**: <5% slowdown

---

## Support and Contact

### Getting Help

**CI Issues**:
1. Check GitHub Actions logs
2. Review this documentation
3. Run jobs locally first
4. Open GitHub issue with:
   - Workflow run URL
   - Error messages
   - Steps to reproduce

**ONEX Validation Issues**:
1. Review ONEX architecture documentation
2. Check naming convention requirements
3. Validate method signatures
4. Review contract definitions

**Performance Issues**:
1. Review benchmark results
2. Profile slow tests
3. Check database query performance
4. Optimize caching strategies

---

## Appendix

### Related Documentation
- [ONEX Architecture Patterns](https://github.com/OmniNode-ai/Archon/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md) - ONEX architecture reference (external)
- `pyproject.toml` - Project dependencies and tool configuration
- `docker-compose.yml` - Full stack deployment configuration
- `scripts/init-db.sh` - Database initialization script

### Workflow Files
- `.github/workflows/enhanced-ci.yml` - Enhanced CI pipeline
- `.github/workflows/ci-cd.yml` - Legacy CI/CD pipeline
- `.github/workflows/security-scan.yml` - Security scanning

### Test Directories
- `agents/tests/` - Agent framework tests
- `claude_hooks/tests/` - Hooks system tests
- `agents/parallel_execution/` - Parallel execution benchmarks

---

**Document Version**: 1.0.0
**Last Updated**: 2025-10-17
**Maintained By**: DevOps Infrastructure Team
