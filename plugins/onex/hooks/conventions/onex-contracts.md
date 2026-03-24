# ONEX Contract Conventions

## Contract YAML Structure
- Every node has a `contract.yaml` co-located with its Python module.
- Required fields: `name`, `version`, `node_type`, `config_requirements`, `state_machine`.
- `config_requirements` lists env vars the node needs; used by `seed-infisical.py`.
- `state_machine` defines valid FSM transitions (e.g., `IDLE -> RUNNING -> DONE`).

## Validator Patterns
- Validators live alongside the contract: `validator.py` next to `contract.yaml`.
- Use Pydantic `model_validator(mode="after")` for cross-field validation.
- Raise `ValueError` with descriptive messages; never silently coerce.
- All validators must be importable without side effects.

## Strict Typing
- PEP 604 unions only: `str | None`, never `Optional[str]` or `Union[str, None]`.
- All public functions fully annotated (params + return type).
- `mypy --strict` must pass. Use `# type: ignore[<code>]` sparingly with comment.
- Prefer `Sequence` over `list` in function signatures for covariance.

## Python Standards
- Python 3.12+ required. Use `uv run` for all commands (pytest, mypy, ruff).
- Never use bare `pip` or `python`. Always `uv run python`, `uv run pytest`.
- ruff handles formatting and import sorting. Run `uv run ruff check --fix`.
- Test markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.slow`.

## Node Implementation
- 4 node types: Effect (I/O), Compute (pure), Reducer (aggregate), Orchestrator (workflow).
- Naming: `Node<Name><Type>` class in `node_<name>_<type>.py`.
- All nodes use `ModelContract<Type>` with typed sub-contracts.
