# Quality Enforcement System - Test Suite

Comprehensive test suite for the AI-enhanced quality enforcement system.

## Test Structure

```
tests/
├── README.md                      # This file
├── __init__.py                    # Package initialization
├── test_naming_validator.py       # Unit tests for naming validator
├── test_integration.py            # Integration tests for end-to-end validation
└── manual_test.sh                 # Manual test script with visual output
```

## Running Tests

### All Tests

Run all unit and integration tests:

```bash
cd ~/.claude/hooks
python3 -m pytest tests/ -v
```

### Unit Tests Only

Test the naming validator in isolation:

```bash
python3 -m pytest tests/test_naming_validator.py -v
```

### Integration Tests Only

Test end-to-end validation workflows:

```bash
python3 -m pytest tests/test_integration.py -v
```

### Manual Tests

Run the manual test script for visual validation:

```bash
bash tests/manual_test.sh
```

## Test Coverage

### Unit Tests (test_naming_validator.py)

**19 test cases** covering:

1. **Python Naming Validation** (5 tests)
   - Valid snake_case functions
   - Invalid camelCase functions (violations detected)
   - Valid PascalCase classes
   - Invalid snake_case classes (violations detected)
   - Multiple violations in one file

2. **TypeScript Naming Validation** (6 tests)
   - Valid camelCase functions
   - Invalid snake_case functions (violations detected)
   - Valid PascalCase classes
   - Invalid snake_case classes (violations detected)
   - Valid PascalCase interfaces
   - Invalid non-PascalCase interfaces (violations detected)

3. **Case Conversion Helpers** (4 tests)
   - snake_case conversion (camelCase → snake_case)
   - camelCase conversion (snake_case → camelCase)
   - PascalCase conversion (snake_case → PascalCase)
   - UPPER_SNAKE_CASE conversion

4. **Edge Cases** (4 tests)
   - Invalid Python syntax (graceful handling)
   - Empty files
   - Non-existent files
   - Private methods (underscore prefix ignored)

### Integration Tests (test_integration.py)

**10 test cases** covering:

1. **End-to-End Python** (2 tests)
   - Complete validation pipeline with violations
   - Clean code with no violations

2. **End-to-End TypeScript** (2 tests)
   - Complete validation pipeline with violations
   - Clean code with no violations

3. **Performance** (2 tests)
   - Small file performance (<100ms target)
   - Medium file performance (<500ms target)

4. **Multi-Language** (2 tests)
   - JavaScript validation
   - TSX validation

5. **Real-World Scenarios** (2 tests)
   - Mixed valid/invalid code
   - Nested classes and methods

### Manual Tests (manual_test.sh)

**8 test scenarios** with visual output:

1. Python function naming (camelCase violation)
2. Python class naming (snake_case violation)
3. TypeScript function naming (snake_case violation)
4. TypeScript class naming (snake_case violation)
5. TypeScript interface naming (snake_case violation)
6. Python clean code (no violations)
7. TypeScript clean code (no violations)
8. Multiple violations in one file

## Test Results

### Latest Test Run

```
Unit Tests:        19/19 PASSED (100%)
Integration Tests: 10/10 PASSED (100%)
Total:            29/29 PASSED (100%)
```

### Performance Metrics

- Unit test execution: **~60-80ms**
- Integration test execution: **~40-60ms**
- Single file validation: **<10ms** (well under 100ms target)
- Medium file validation: **<50ms** (well under 500ms target)

## Writing New Tests

### Adding Unit Tests

Add new test methods to existing test classes in `test_naming_validator.py`:

```python
class TestPythonNaming:
    def test_new_validation_rule(self):
        validator = NamingValidator()
        code = """
        # Your test code here
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            f.flush()
            violations = validator.validate_file(f.name)

        assert len(violations) == expected_count
```

### Adding Integration Tests

Add new test methods to existing test classes in `test_integration.py`:

```python
class TestEndToEndPython:
    def test_new_integration_scenario(self):
        validator = NamingValidator()
        # Test implementation
```

### Adding Manual Tests

Add new test cases to `manual_test.sh`:

```bash
run_test "Test Name" \
    "/tmp/test_file.py" \
    "Code content here"
```

## Requirements

- Python 3.12+
- pytest
- pytest-asyncio
- tempfile (standard library)

## Continuous Integration

These tests are designed to run in CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run Tests
  run: |
    cd ~/.claude/hooks
    python3 -m pytest tests/ -v --tb=short
```

## Performance Budget

All tests must complete within these targets:

- **Unit tests**: <100ms per test
- **Integration tests**: <500ms per test
- **Manual tests**: <5s total

## Troubleshooting

### Tests Fail to Import Modules

Ensure you're in the hooks directory:

```bash
cd ~/.claude/hooks
python3 -m pytest tests/ -v
```

### Permission Errors

Make sure test script is executable:

```bash
chmod +x tests/manual_test.sh
```

### Pytest Not Found

Install pytest:

```bash
pip install pytest pytest-asyncio
```

## Contributing

When adding new tests:

1. Follow existing test patterns
2. Add docstrings to test methods
3. Ensure tests run in <100ms (unit) or <500ms (integration)
4. Update this README with new test coverage

## Related Documentation

- **Design Document**: External Archon project - `${ARCHON_ROOT}/docs/agent-framework/ai-quality-enforcement-system.md`
- **Validator Implementation**: `~/.claude/hooks/lib/validators/naming_validator.py`
- **Main Hook Script**: `~/.claude/hooks/user-prompt-submit-enhanced.sh`
