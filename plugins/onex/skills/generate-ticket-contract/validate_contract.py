"""validate_contract.py — Validate a ModelTicketContract YAML file.

Usage:
    python validate_contract.py <path_to_yaml>

Exit codes:
    0 — valid contract
    1 — validation failed (field-level errors printed to stderr)
    2 — usage error (missing argument, file not found)
"""

from __future__ import annotations

import sys
from pathlib import Path


def _load_yaml(path: Path) -> object:
    """Load YAML from path. Returns parsed object or exits on error."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        print(
            "ERROR: PyYAML is not installed. Run: uv pip install pyyaml",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: Cannot read file: {exc}", file=sys.stderr)
        sys.exit(2)

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        print(f"ERROR: YAML parse error: {exc}", file=sys.stderr)
        sys.exit(1)

    return data


def _validate(data: object) -> list[str]:
    """Validate data against ModelTicketContract. Returns list of error strings."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"Expected mapping at top level, got {type(data).__name__}"]

    try:
        from omnibase_core.models.ticket.model_ticket_contract import (
            ModelTicketContract,
        )  # type: ignore[import-untyped]
        from pydantic import ValidationError
    except ImportError as exc:
        return [f"Import error — ensure omnibase_core is installed: {exc}"]

    try:
        ModelTicketContract.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = " -> ".join(str(part) for part in err["loc"])
            msg = err["msg"]
            errors.append(f"  {loc}: {msg}")

    return errors


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: validate_contract.py <path_to_yaml>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(2)

    data = _load_yaml(path)
    errors = _validate(data)

    if errors:
        print(f"INVALID: {len(errors)} error(s) found in {path}", file=sys.stderr)
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(1)

    ticket_id = (
        data.get("ticket_id", "unknown") if isinstance(data, dict) else "unknown"
    )  # type: ignore[union-attr]
    print(f"OK: contract for {ticket_id} is valid")
    sys.exit(0)


if __name__ == "__main__":
    main()
