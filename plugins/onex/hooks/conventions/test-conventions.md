# Test Conventions

## Inject

- All test files must use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`.
- Unit tests must have zero external dependencies (no DB, no Kafka, no network).
- Integration tests should use real services, not mocks -- mock only at unit level.
- Follow the Arrange-Act-Assert pattern with clear section separation.
- Test file names must match `test_<module_name>.py` for the module under test.
- Use `tmp_path` fixture for file system operations, never write to the source tree.
- Parametrize tests with `@pytest.mark.parametrize` when testing multiple inputs.
- Keep individual test functions under 30 lines; extract fixtures for shared setup.
