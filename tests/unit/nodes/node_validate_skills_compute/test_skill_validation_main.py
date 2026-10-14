# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""CLI exit codes, byte formatting, JSON shape, and real skill tree checks."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from omniclaude.nodes.node_validate_skills_compute.__main__ import main


def _populate(root: Path, operation: str, scenario: str) -> dict[str, str] | None:
    skill_name = (
        "bad-name" if operation == "hygiene" and scenario == "error" else "sample"
    )
    skill = root / skill_name
    skill.mkdir()
    if operation == "hygiene" and scenario == "warning":
        return {
            "path": "sample",
            "check": "skill-md-required",
            "severity": "WARNING",
            "message": "Skill directory 'sample' is missing SKILL.md",
        }
    spec = f"---\nname: {skill_name}\n"
    if operation == "contracts" and scenario == "error":
        spec += "args:\n  - name: --missing\n"
    spec += "---\n"
    if operation == "contracts" and scenario == "warning":
        spec += "Output status: `needs_review`\n"
    (skill / "SKILL.md").write_text(spec, encoding="utf-8")
    (skill / "prompt.md").write_text("Do the work.\n", encoding="utf-8")
    if scenario == "clean":
        return None
    if operation == "hygiene":
        return {
            "path": "bad-name",
            "check": "underscore-names",
            "severity": "ERROR",
            "message": "Skill directory uses dashes: 'bad-name' — rename to 'bad_name'",
        }
    if scenario == "error":
        return {
            "path": "sample",
            "check": "args-parity",
            "severity": "ERROR",
            "message": "Arg '--missing' declared in SKILL.md but not found in prompt.md",
        }
    return {
        "path": "sample",
        "check": "spec-prompt-predicates",
        "severity": "WARNING",
        "message": "Predicate 'needs_review' found in SKILL.md but not in prompt.md",
    }


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["hygiene", "contracts"])
@pytest.mark.parametrize("scenario", ["clean", "error", "warning"])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("json_output", [False, True])
def test_cli_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    scenario: str,
    strict: bool,
    json_output: bool,
) -> None:
    violation = _populate(tmp_path, operation, scenario)
    if strict and violation is not None and scenario == "warning":
        violation["severity"] = "ERROR"
    violations = [violation] if violation is not None else []
    errors = sum(v["severity"] == "ERROR" for v in violations)
    warnings = sum(v["severity"] == "WARNING" for v in violations)
    argv = [operation, "--skills-root", str(tmp_path)]
    if strict:
        argv.append("--strict")
    if json_output:
        argv.append("--json")
    assert main(argv) == (1 if errors else 0)
    captured = capsys.readouterr()
    assert captured.err == ""
    if json_output:
        if operation == "hygiene":
            expected = {
                "strict": strict,
                "skills_root": str(tmp_path),
                "error_count": errors,
                "warning_count": warnings,
                "violations": violations,
            }
        else:
            expected = {
                "violation_count": len(violations),
                "error_count": errors,
                "warning_count": warnings,
                "violations": violations,
            }
        assert json.loads(captured.out) == expected
        assert captured.out == json.dumps(expected, indent=2) + "\n"
    elif violation is None:
        assert captured.out == (
            f"Skill hygiene: all checks passed ({tmp_path})\n"
            if operation == "hygiene"
            else "Skill contract validation: all checks passed\n"
        )
    else:
        line = (
            f"  {violation['severity']}: [{violation['check']}] "
            f"{violation['path']}: {violation['message']}\n"
        )
        if operation == "hygiene":
            expected_text = (
                f"\nSkill Hygiene Report ({tmp_path}):\n"
                f"  Mode: {'strict' if strict else 'migration'}\n\n"
                f"{line}\n  Errors: {errors}, Warnings: {warnings}\n"
            )
        else:
            expected_text = (
                f"Skill contract validation: {errors} error(s), {warnings} warning(s)\n\n"
                f"{line}\n"
            )
        assert captured.out == expected_text


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["hygiene", "contracts"])
@pytest.mark.parametrize("is_file", [False, True])
def test_bad_skills_root(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    operation: str,
    is_file: bool,
) -> None:
    root = tmp_path / "missing"
    if is_file:
        root.touch()
    assert main([operation, "--skills-root", str(root), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"ERROR: --skills-root path does not exist or is not a directory: {root}\n"
        if operation == "hygiene"
        else f"ERROR: skills root not found: {root}\n"
    )


@pytest.mark.unit
@pytest.mark.parametrize("operation", ["hygiene", "contracts"])
def test_module_entrypoint(tmp_path: Path, operation: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "omniclaude.nodes.node_validate_skills_compute",
            operation,
            "--skills-root",
            str(tmp_path),
            "--json",
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == b""
    assert json.loads(result.stdout)["violations"] == []


@pytest.mark.unit
def test_real_skills_tree(capsys: pytest.CaptureFixture[str]) -> None:
    skills_root = Path(__file__).resolve().parents[4] / "plugins" / "onex" / "skills"
    assert skills_root.is_dir()
    hygiene_exit = main(["hygiene", "--skills-root", str(skills_root), "--strict"])
    hygiene_output = capsys.readouterr()
    contracts_exit = main(["contracts", "--skills-root", str(skills_root)])
    contracts_output = capsys.readouterr()
    assert hygiene_exit == 0, hygiene_output.out + hygiene_output.err
    assert contracts_exit == 0, contracts_output.out + contracts_output.err
