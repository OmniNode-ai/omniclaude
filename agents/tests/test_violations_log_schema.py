import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "claude_hooks" / "logs"
SUMMARY_PATH = LOG_DIR / "violations_summary.json"
SCHEMA_PATH = LOG_DIR / "violations_summary.schema.json"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", [SCHEMA_PATH])
def test_schema_file_exists(path: Path) -> None:
    assert path.exists(), f"Missing schema file: {path}"


def test_summary_matches_schema_if_present() -> None:
    if not SUMMARY_PATH.exists():
        pytest.skip(
            "violations_summary.json not present; producer may not have run yet"
        )

    schema = json.loads(_read_text(SCHEMA_PATH))
    validator = Draft202012Validator(schema)
    instance = json.loads(_read_text(SUMMARY_PATH))
    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    assert not errors, "\n".join(
        f"{e.message} at path: {'/'.join(map(str, e.path))}" for e in errors
    )


def test_summary_trailing_newline_if_present() -> None:
    if not SUMMARY_PATH.exists():
        pytest.skip(
            "violations_summary.json not present; producer may not have run yet"
        )

    content = _read_text(SUMMARY_PATH)
    assert content.endswith("\n"), "violations_summary.json must end with a newline"
