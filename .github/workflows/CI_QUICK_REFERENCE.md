# OmniClaude CI/CD Quick Reference

## 🚀 Quick Start

### Running All Checks Locally
```bash
# Install dependencies
poetry install --with dev

# Run all quality checks
poetry run black --check .
poetry run ruff check .
poetry run mypy agents/ claude_hooks/ --strict --ignore-missing-imports

# Run all tests
poetry run pytest -v --cov=agents --cov=claude_hooks
```

### Running Specific Test Suites
```bash
# Unit tests only
poetry run pytest agents/tests/ -m "not integration" -v

# Integration tests (requires Docker)
docker-compose up -d postgres redis
poetry run pytest agents/tests/ -m integration -v
docker-compose down

# Hooks tests
poetry run pytest claude_hooks/tests/ -v

# Agent framework tests
poetry run pytest agents/tests/test_enhanced_router.py \
  agents/tests/test_quality_gates.py \
  agents/tests/test_performance_thresholds.py -v
```

---

## 📋 CI Pipeline Jobs

| Job | Purpose | Duration | Dependencies |
|-----|---------|----------|--------------|
| `quality-strict` | Code formatting, linting, type checking (strict) | 3 min | None |
| `onex-validation` | ONEX architecture compliance validation | 2 min | None |
| `unit-tests` | Fast unit tests without external dependencies | 5 min | None |
| `integration-tests` | Integration tests with PostgreSQL & Redis | 8 min | None |
| `hooks-tests` | Claude hooks system tests with database | 6 min | None |
| `agent-framework-tests` | Agent routing and coordination tests | 4 min | None |
| `performance-benchmarks` | Performance regression testing | 5 min | None |
| `database-validation` | PostgreSQL schema validation | 3 min | None |
| `docker-compose-validation` | Full stack deployment validation | 10 min | None |
| `build` | Docker image build and push | 15 min | All tests |
| `test-summary` | Aggregate test results and reporting | 1 min | All tests |

**Total Pipeline Time**: ~30 minutes (jobs run in parallel)

---

## 🎯 ONEX Compliance Rules

### File Naming
```
node_<name>_<type>.py
```

### Class Naming
| File Pattern | Class Pattern | Example |
|--------------|---------------|---------|
| `*_effect.py` | `Node<Name>Effect` | `NodeDatabaseWriterEffect` |
| `*_compute.py` | `Node<Name>Compute` | `NodeDataTransformerCompute` |
| `*_reducer.py` | `Node<Name>Reducer` | `NodeStateAggregatorReducer` |
| `*_orchestrator.py` | `Node<Name>Orchestrator` | `NodeWorkflowCoordinatorOrchestrator` |

### Method Signatures
```python
# Effect
async def execute_effect(self, contract: ModelContractEffect) -> Any:
    ...

# Compute
async def execute_compute(self, contract: ModelContractCompute) -> Any:
    ...

# Reducer
async def execute_reduction(self, contract: ModelContractReducer) -> Any:
    ...

# Orchestrator
async def execute_orchestration(self, contract: ModelContractOrchestrator) -> Any:
    ...
```

---

## 🔧 Troubleshooting

### Type Checking Failures
```bash
# Run locally to see detailed errors
poetry run mypy agents/ claude_hooks/ --strict --show-error-codes

# Install missing type stubs
poetry run pip install types-<package>
```

### Integration Test Failures
```bash
# Check if services are running
docker-compose ps

# View service logs
docker-compose logs postgres
docker-compose logs redis

# Restart services
docker-compose down && docker-compose up -d
```

### ONEX Validation Failures
```bash
# Check node naming
find agents/ claude_hooks/ -name "node_*.py" -exec basename {} \;

# Validate class names
grep -r "class Node" agents/ claude_hooks/

# Check method signatures
grep -r "async def execute_" agents/ claude_hooks/
```

### Performance Regression
```bash
# Run benchmarks locally
poetry run python agents/tests/benchmark_template_cache.py
poetry run python agents/parallel_execution/parallel_benchmark.py

# Profile specific tests
poetry run pytest --profile agents/tests/test_performance.py
```

---

## 📊 Coverage Targets

| Test Suite | Coverage Target | Current |
|------------|----------------|---------|
| Unit Tests | ≥80% | TBD |
| Integration Tests | ≥70% | TBD |
| Hooks Tests | ≥75% | TBD |
| Agent Framework | ≥85% | TBD |
| **Overall** | **≥80%** | **TBD** |

---

## 🛡️ Quality Gates

All gates must pass for CI to succeed:

✅ **Code Formatting**: Black (100% compliance)
✅ **Linting**: Ruff (zero violations)
✅ **Type Safety**: MyPy strict mode (zero errors)
✅ **ONEX Compliance**: 100% adherence
✅ **Unit Tests**: All pass
✅ **Integration Tests**: All pass
✅ **Hooks Tests**: All pass
✅ **Database Schema**: Valid and initialized
✅ **Docker Stack**: Healthy deployment

---

## 🚨 Common Errors and Fixes

### Error: `Black would reformat <file>`
```bash
# Fix
poetry run black .
```

### Error: `Ruff found violations`
```bash
# Fix automatically
poetry run ruff check --fix .

# Manual fix required
poetry run ruff check . --show-fixes
```

### Error: `MyPy type error`
```bash
# Add type hints
def function(arg: str) -> int:
    return int(arg)

# Add type ignore (last resort)
result = some_function()  # type: ignore[misc]
```

### Error: `ONEX naming violation`
```bash
# Rename file to match pattern
mv node_writer.py node_database_writer_effect.py

# Update class name
class NodeDatabaseWriterEffect(NodeEffect):
    ...
```

### Error: `Database connection failed`
```bash
# Start PostgreSQL
docker-compose up -d postgres

# Wait for readiness
until docker-compose exec postgres pg_isready; do sleep 1; done

# Initialize schema
docker-compose exec postgres psql -U omniclaude -d omniclaude < scripts/init-db.sh
```

---

## 🔄 Workflow Triggers

### Automatic Triggers
- **Push to main**: Full pipeline + deployment to production
- **Push to develop**: Full pipeline + deployment to staging
- **Push to feature/***: Full pipeline (no deployment)
- **Pull Request**: Full pipeline (no push to registry)

### Manual Trigger
1. Go to Actions tab in GitHub
2. Select "Enhanced CI Pipeline with ONEX Validation"
3. Click "Run workflow"
4. Select branch and click "Run workflow"

---

## 📦 Artifacts

After each workflow run, download artifacts:

1. **MyPy Report** - Type checking cache and results
2. **Unit Test Results** - JUnit XML reports
3. **Integration Test Results** - JUnit XML reports
4. **Hooks Test Results** - JUnit XML reports
5. **Agent Framework Test Results** - JUnit XML reports
6. **Performance Benchmarks** - JSON results and text reports

---

## 🔗 Related Commands

### Docker Compose
```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop all services
docker-compose down

# Remove volumes
docker-compose down -v

# Rebuild services
docker-compose build --no-cache
```

### Poetry
```bash
# Install dependencies
poetry install --with dev

# Update dependencies
poetry update

# Add new dependency
poetry add <package>

# Add dev dependency
poetry add --group dev <package>

# Show installed packages
poetry show
```

### Database
```bash
# Connect to database
docker-compose exec postgres psql -U omniclaude -d omniclaude

# Run SQL file
docker-compose exec postgres psql -U omniclaude -d omniclaude < schema.sql

# Backup database
docker-compose exec postgres pg_dump -U omniclaude omniclaude > backup.sql

# Restore database
docker-compose exec postgres psql -U omniclaude -d omniclaude < backup.sql
```

---

## 📈 Performance Optimization

### Speed Up Local Testing
```bash
# Use pytest-xdist for parallel execution
poetry add --group dev pytest-xdist
poetry run pytest -n auto

# Run only modified tests
poetry run pytest --lf  # Last failed
poetry run pytest --ff  # Failed first

# Skip slow tests
poetry run pytest -m "not slow"
```

### Speed Up CI Pipeline
1. ✅ Use dependency caching (already configured)
2. ✅ Use Docker layer caching (already configured)
3. ✅ Run jobs in parallel (already configured)
4. Consider reducing test timeout values
5. Consider using faster test databases (e.g., SQLite for unit tests)

---

## 🎓 Best Practices

### Before Committing
```bash
# 1. Format code
poetry run black .

# 2. Fix linting issues
poetry run ruff check --fix .

# 3. Run type checking
poetry run mypy agents/ claude_hooks/ --strict

# 4. Run tests
poetry run pytest -v

# 5. Check ONEX compliance (manual)
# Verify naming conventions and method signatures
```

### Writing Tests
```python
# Use pytest fixtures
@pytest.fixture
def database():
    db = create_database()
    yield db
    db.cleanup()

# Mark integration tests
@pytest.mark.integration
def test_database_integration():
    ...

# Mark slow tests
@pytest.mark.slow
def test_expensive_operation():
    ...

# Use parametrize for multiple test cases
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_multiply(input, expected):
    assert multiply(input) == expected
```

### ONEX Node Development
```python
# 1. Create file with proper naming
# File: node_user_validator_compute.py

# 2. Define class with ONEX pattern
from omnibase_core.core.node_compute import NodeCompute
from model_contract_compute import ModelContractCompute

class NodeUserValidatorCompute(NodeCompute):
    """User validation compute node."""

    # 3. Implement required method
    async def execute_compute(
        self,
        contract: ModelContractCompute
    ) -> Any:
        """Execute user validation computation."""
        # Implementation
        return result
```

---

## 📞 Support

### Documentation
- Full documentation: `.github/workflows/CI_CD_DOCUMENTATION.md`
- This quick reference: `.github/workflows/CI_QUICK_REFERENCE.md`
- ONEX architecture: `/Volumes/PRO-G40/Code/Archon/docs/ONEX_ARCHITECTURE_PATTERNS_COMPLETE.md`

### Getting Help
1. Check workflow logs in GitHub Actions
2. Run failing job locally
3. Review error messages and stack traces
4. Search documentation for keywords
5. Open GitHub issue with reproduction steps

---

**Quick Reference Version**: 1.0.0
**Last Updated**: 2025-10-17
