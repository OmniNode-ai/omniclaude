# Integration Test Execution Runbook
## Agent Observability Framework - Stream 8

---

## Quick Start

### 1. Check Dependency Status
```bash
cd /Volumes/PRO-G40/Code/omniclaude/agents/tests
python monitor_dependencies.py
```

### 2. Run All Integration Tests (When Ready)
```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov=agents --cov-report=html -v

# Run specific test suite
pytest test_quality_gates.py -v
pytest test_performance_thresholds.py -v
pytest test_end_to_end_workflows.py -v
```

### 3. Generate Reports
```bash
# Performance report
pytest test_performance_thresholds.py --benchmark-only -v

# Quality gate compliance report
pytest test_quality_gates.py --html=report_quality_gates.html -v

# Full integration report
pytest --html=report_integration.html --self-contained-html -v
```

---

## Detailed Execution Plan

### Phase 1: Pre-Execution Verification

#### 1.1 Check Dependencies
```bash
python monitor_dependencies.py
```

**Expected Output**: All 7 streams show "done" or "review" status

#### 1.2 Verify Database Schema
```bash
# Connect to PostgreSQL and verify tables exist
psql -h localhost -d archon_db -c "\dt agent_*"
```

**Expected Tables**:
- `agent_definitions`
- `agent_transformation_events`
- `router_performance_metrics`

#### 1.3 Verify Enhanced Router
```python
# Test enhanced router import
python -c "from agents.lib.enhanced_router import EnhancedAgentRouter; print('✅ Enhanced router available')"
```

#### 1.4 Verify Agent Loader
```bash
# Check agent configs directory
ls ~/.claude/agents/configs/ | wc -l
# Should show 50+ agent YAML files
```

---

### Phase 2: Component-Level Integration Tests

#### 2.1 Database Integration
```bash
# Test database connection
pytest tests/test_database_integration.py -v
```

**Validates**:
- Connection pooling
- Async operations
- Query performance (<50ms)
- Batch operations (1000+ events/second)

#### 2.2 Enhanced Router Integration
```bash
# Test routing decisions
pytest tests/test_enhanced_router.py -v
```

**Validates**:
- Fuzzy matching accuracy
- Confidence scoring
- Cache hit rates (>60%)
- Routing decision time (<100ms)

#### 2.3 Dynamic Agent Loader
```bash
# Test agent loading
pytest tests/test_agent_loader.py -v
```

**Validates**:
- YAML parsing
- Agent validation
- Hot-reload capability
- Lifecycle management

---

### Phase 3: Quality Gate Validation

#### 3.1 Run All Quality Gate Tests
```bash
pytest tests/test_quality_gates.py -v --tb=short
```

**Expected Results**:
- 23/23 quality gates pass (100% required)
- 22/23 meet performance targets (95% required)
- 21/23 fully automated (90% required)

#### 3.2 Generate Quality Gate Report
```bash
pytest tests/test_quality_gates.py --html=reports/quality_gates.html --self-contained-html -v
```

#### 3.3 Quality Gate Categories

**Sequential Validation (4 gates)**:
- SV-001: Input Validation (<50ms)
- SV-002: Process Validation (<30ms)
- SV-003: Output Validation (<40ms)
- SV-004: Integration Testing (<60ms)

**Parallel Validation (3 gates)**:
- PV-001: Context Synchronization (<80ms)
- PV-002: Coordination Validation (<50ms)
- PV-003: Result Consistency (<70ms)

**Intelligence Validation (3 gates)**:
- IV-001: RAG Query Validation (<100ms)
- IV-002: Knowledge Application (<75ms)
- IV-003: Learning Capture (<50ms)

**Coordination Validation (3 gates)**:
- CV-001: Context Inheritance (<40ms)
- CV-002: Agent Coordination (<60ms)
- CV-003: Delegation Validation (<45ms)

**Quality Compliance (4 gates)**:
- QC-001: ONEX Standards (<80ms)
- QC-002: Anti-YOLO Compliance (<30ms)
- QC-003: Type Safety (<60ms)
- QC-004: Error Handling (<40ms)

**Performance Validation (2 gates)**:
- PF-001: Performance Thresholds (<30ms)
- PF-002: Resource Utilization (<25ms)

**Knowledge Validation (2 gates)**:
- KV-001: UAKS Integration (<50ms)
- KV-002: Pattern Recognition (<40ms)

**Framework Validation (2 gates)**:
- FV-001: Lifecycle Compliance (<35ms)
- FV-002: Framework Integration (<25ms)

---

### Phase 4: Performance Threshold Validation

#### 4.1 Run All Performance Tests
```bash
pytest tests/test_performance_thresholds.py -v --tb=short
```

**Expected Results**:
- 31/33 thresholds met (95% required)
- 100% monitoring coverage
- Alert response time <5 minutes

#### 4.2 Performance Categories

**Intelligence (6 thresholds)**:
- INT-001: RAG Query Response (<1500ms)
- INT-002: Intelligence Overhead (<100ms)
- INT-003: Pattern Recognition (<500ms)
- INT-004: Knowledge Capture (<300ms)
- INT-005: Cross-Domain Synthesis (<800ms)
- INT-006: Intelligence Application (<200ms)

**Parallel Execution (5 thresholds)**:
- PAR-001: Coordination Setup (<500ms)
- PAR-002: Context Distribution (<200ms)
- PAR-003: Sync Latency (<1000ms)
- PAR-004: Result Aggregation (<300ms)
- PAR-005: Efficiency Ratio (>0.6)

**Coordination (4 thresholds)**:
- COORD-001: Delegation Handoff (<150ms)
- COORD-002: Context Inheritance (<50ms)
- COORD-003: Multi-Agent Comm (<100ms)
- COORD-004: Coordination Overhead (<300ms)

**Context Management (6 thresholds)**:
- CTX-001: Initialization (<50ms)
- CTX-002: Preservation (<25ms)
- CTX-003: Refresh (<75ms)
- CTX-004: Memory Footprint (<10MB)
- CTX-005: Lifecycle (<200ms)
- CTX-006: Cleanup (<100ms)

**Template System (4 thresholds)**:
- TPL-001: Instantiation (<100ms)
- TPL-002: Parameter Resolution (<50ms)
- TPL-003: Config Overlay (<30ms)
- TPL-004: Cache Hit Ratio (>0.85)

**Lifecycle (4 thresholds)**:
- LCL-001: Initialization (<300ms)
- LCL-002: Integration (<100ms)
- LCL-003: Quality Gates (<200ms)
- LCL-004: Cleanup (<150ms)

**Dashboard (4 thresholds)**:
- DASH-001: Data Collection (<50ms)
- DASH-002: Update Latency (<100ms)
- DASH-003: Trend Analysis (<500ms)
- DASH-004: Recommendations (<300ms)

---

### Phase 5: End-to-End Workflow Tests

#### 5.1 Single Agent Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestSingleAgentWorkflow -v
```

**Validates**:
- Complete single agent lifecycle
- Input/output validation
- Intelligence gathering
- Error handling

#### 5.2 Multi-Agent Sequential Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestMultiAgentSequentialWorkflow -v
```

**Validates**:
- Agent delegation
- Context inheritance
- Handoff validation
- Result aggregation

#### 5.3 Parallel Coordination Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestParallelCoordinationWorkflow -v
```

**Validates**:
- Parallel execution
- Context isolation
- Synchronization
- Result consistency

#### 5.4 RAG-Enhanced Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestRAGEnhancedWorkflow -v
```

**Validates**:
- Intelligence gathering
- RAG query performance
- Knowledge application
- Learning capture

#### 5.5 Error Recovery Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestErrorRecoveryWorkflow -v
```

**Validates**:
- Error capture
- Graceful degradation
- Retry logic
- Recovery mechanisms

#### 5.6 Performance Monitoring Workflow
```bash
pytest tests/test_end_to_end_workflows.py::TestPerformanceMonitoringWorkflow -v
```

**Validates**:
- Baseline establishment
- Performance monitoring
- Degradation detection
- Optimization recommendations

---

### Phase 6: Load and Stress Testing

#### 6.1 Load Testing
```bash
# Test with 100 concurrent agents
pytest tests/test_load.py --load=100 -v

# Test with 1000 events/second
pytest tests/test_load.py --rate=1000 -v
```

#### 6.2 Stress Testing
```bash
# Test until failure
pytest tests/test_stress.py --stress-mode=increasing -v

# Test resource limits
pytest tests/test_stress.py --stress-mode=resource-limits -v
```

#### 6.3 Endurance Testing
```bash
# Run for 24 hours
pytest tests/test_endurance.py --duration=24h -v
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Failures
```bash
# Check database is running
docker ps | grep postgres

# Verify connection string
echo $POSTGRES_CONNECTION_STRING

# Test connection
psql $POSTGRES_CONNECTION_STRING -c "SELECT 1;"
```

#### 2. Import Errors
```bash
# Verify Python path
echo $PYTHONPATH

# Add project root to path
export PYTHONPATH=/Volumes/PRO-G40/Code/omniclaude:$PYTHONPATH

# Reinstall dependencies
poetry install
```

#### 3. Performance Test Failures
```bash
# Check system resources
top -l 1 | head -n 10

# Clear caches
pytest --cache-clear

# Run with increased timeouts
pytest --timeout=300 -v
```

#### 4. Agent Loading Failures
```bash
# Verify agent configs
ls ~/.claude/agents/configs/*.yaml

# Validate YAML syntax
python -c "import yaml; yaml.safe_load(open('~/.claude/agents/configs/agent-example.yaml'))"

# Check agent validation
pytest tests/test_agent_loader.py::test_agent_validation -v
```

---

## Reporting

### Generate Comprehensive Report
```bash
# Run all tests with reporting
pytest \
  --cov=agents \
  --cov-report=html \
  --html=reports/integration_report.html \
  --self-contained-html \
  --json-report \
  --json-report-file=reports/integration_report.json \
  -v

# Open HTML report
open reports/integration_report.html
```

### Report Sections

1. **Executive Summary**
   - Overall pass/fail rate
   - Quality gate compliance (target: 100%)
   - Performance compliance (target: 95%)
   - Critical issues found

2. **Quality Gate Results**
   - 23 quality gates validation
   - Performance targets met
   - Automation coverage

3. **Performance Threshold Results**
   - 33 performance thresholds validation
   - Threshold violations
   - Optimization recommendations

4. **End-to-End Workflow Results**
   - 6 workflow scenarios
   - Integration completeness
   - Error recovery effectiveness

5. **Recommendations**
   - Architecture improvements
   - Performance optimizations
   - Quality enhancements
   - Next steps

---

## Success Criteria Checklist

### Quality Gates
- [ ] All 23 quality gates pass (100%)
- [ ] 22/23 meet performance targets (95%)
- [ ] 21/23 fully automated (90%)

### Performance Thresholds
- [ ] 31/33 thresholds met (95%)
- [ ] 100% monitoring coverage
- [ ] Alert response <5 minutes

### Mandatory Functions
- [ ] All 47 functions implemented
- [ ] 100% integration tested
- [ ] No critical failures

### End-to-End Workflows
- [ ] All 6 workflows pass
- [ ] Error recovery functional
- [ ] Performance acceptable

### Documentation
- [ ] Integration test plan complete
- [ ] Runbook comprehensive
- [ ] Troubleshooting guide useful
- [ ] Reports generated

---

## Next Steps After Testing

### 1. Update Archon Task
```bash
# Mark task as review
python -c "
from archon_mcp import update_task
update_task(
    task_id='d0cdac49-4d07-406b-a144-20a4b113f864',
    status='review',
    description='Integration testing complete. All quality gates and performance thresholds validated.'
)
"
```

### 2. Create Summary Report
```bash
# Generate executive summary
python generate_summary_report.py > reports/EXECUTIVE_SUMMARY.md
```

### 3. Document Findings
```bash
# Create findings document
cat > reports/FINDINGS.md << 'EOF'
# Integration Testing Findings
## Quality Gate Results
## Performance Threshold Results
## Recommendations
EOF
```

### 4. Prepare Handoff
```bash
# Package reports for review
tar -czf integration_test_results.tar.gz reports/
```

---

**Last Updated**: 2025-10-09
**Version**: 1.0
**Status**: ⏸️ WAITING FOR DEPENDENCIES
