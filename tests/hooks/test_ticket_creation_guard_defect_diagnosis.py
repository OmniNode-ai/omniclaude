# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Rule 15: a defect-shaped create binds to a diagnosis before its criteria (OMN-17427).

Criteria written before a defect is understood describe a defect that may not
exist (81 of 1,122 terminal rows in 7 days, 7.2 %, reported a falsified
premise). These tests run the guard the way the hook runs it -- ``python
ticket_creation_guard.py`` with the PreToolUse payload on stdin -- because the
rule lives in a handler the guard loads by path, and only the real command
exercises that load.

Every refusal case has a positive control beside it: the same create, fixed, is
admitted, so a refusal is never a guard that refuses everything.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_GUARD_PY = _REPO_ROOT / "plugins/onex/hooks/lib/ticket_creation_guard.py"
_POLICY_JSON = _REPO_ROOT / "plugins/onex/hooks/config/ticket_creation_policy.json"
_HANDLER_PY = _REPO_ROOT / "src/omniclaude/handlers/handler_defect_diagnosis.py"

_BODY = (
    "Gate: OMN-16729 AC-5\n"
    "\n"
    "- [ ] AC1: The guard refuses it -- falsifier: uv run pytest tests/hooks -q\n"
)

#: A stand-in rolling ledger: five rows live, the sixth line blank, and one
#: rolled archive file of three rows.
_LIVE_ROWS = [f"2026-10-17T00:0{n}:00Z | CLAIM | row {n}" for n in range(1, 6)]


def _create(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "team": "Omninode",
        "title": "Refuse a Linear create with no binding",
        "parentId": "OMN-16729",
        "description": _BODY,
    }
    payload.update(overrides)
    return payload


def _with_diagnosis(citation: str, prefix: str = "") -> str:
    return f"{prefix}Diagnosis: {citation}\n{_BODY}"


@pytest.fixture
def ledger(tmp_path: Path) -> Path:
    live = tmp_path / "docs" / "tracking" / "ROLLING_WORK_LEDGER.md"
    live.parent.mkdir(parents=True)
    live.write_text("\n".join([*_LIVE_ROWS, ""]) + "\n", encoding="utf-8")
    archive = live.parent / "archive"
    archive.mkdir()
    (archive / "ROLLING_WORK_LEDGER_2026-10-16-split.md").write_text(
        "a\nb\nc\n", encoding="utf-8"
    )
    return live


def _run(
    tool_input: dict[str, Any], tmp_path: Path, ledger: Path | None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)}
    if ledger is not None:
        env["ONEX_LEDGER_PATH"] = str(ledger)
    payload = {"tool_name": "mcp__linear-server__save_issue", "tool_input": tool_input}
    return subprocess.run(
        [sys.executable, str(_GUARD_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def _reason(result: subprocess.CompletedProcess[str]) -> str:
    return str(json.loads(result.stdout)["reason"])


def _admitted(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _refused(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 3, result.stdout + result.stderr
    return _reason(result)


_DEFECT_TITLE = "Fix the stale binding the closer reads"


def test_a_defect_create_with_no_diagnosis_is_refused(
    tmp_path: Path, ledger: Path
) -> None:
    reason = _refused(_run(_create(title=_DEFECT_TITLE), tmp_path, ledger))
    assert "missing_diagnosis" in reason
    assert "Diagnosis:" in reason, "the fix shows the line it asks for"
    assert "docs/tracking/ROLLING_WORK_LEDGER.md:4120" in reason


def test_the_same_create_with_a_ledger_citation_is_admitted(
    tmp_path: Path, ledger: Path
) -> None:
    ok = _create(
        title=_DEFECT_TITLE,
        description=_with_diagnosis("docs/tracking/ROLLING_WORK_LEDGER.md:3"),
    )
    _admitted(_run(ok, tmp_path, ledger))


def test_a_citation_into_the_rolled_archive_resolves(
    tmp_path: Path, ledger: Path
) -> None:
    ok = _create(
        title=_DEFECT_TITLE,
        description=_with_diagnosis(
            "archive/ROLLING_WORK_LEDGER_2026-10-16-split.md:3"
        ),
    )
    _admitted(_run(ok, tmp_path, ledger))


@pytest.mark.parametrize(
    "citation",
    [
        "docs/tracking/ROLLING_WORK_LEDGER.md:9999",
        "docs/tracking/ROLLING_WORK_LEDGER.md:6",
        "archive/ROLLING_WORK_LEDGER_2026-10-16-split.md:4",
        "archive/ROLLING_WORK_LEDGER_1999-01-01-split.md:1",
    ],
    ids=["past-the-end", "blank-line", "past-archive-end", "absent-archive-file"],
)
def test_an_unresolvable_ledger_citation_is_refused_and_named(
    citation: str, tmp_path: Path, ledger: Path
) -> None:
    bad = _create(title=_DEFECT_TITLE, description=_with_diagnosis(citation))
    reason = _refused(_run(bad, tmp_path, ledger))
    assert "unresolvable_diagnosis" in reason
    assert f"'{citation}'" in reason, "the refusal names the citation it could not read"


def test_a_ledger_citation_with_no_readable_ledger_is_refused(tmp_path: Path) -> None:
    """Fail closed: an unreadable ledger resolves nothing."""
    bad = _create(
        title=_DEFECT_TITLE,
        description=_with_diagnosis("docs/tracking/ROLLING_WORK_LEDGER.md:1"),
    )
    reason = _refused(_run(bad, tmp_path, tmp_path / "absent" / "LEDGER.md"))
    assert "unresolvable_diagnosis" in reason


@pytest.mark.parametrize(
    "citation",
    [
        "OmniNode-ai/omniclaude#2836",
        "src/omniclaude/handlers/handler_lane_intake.py:60",
    ],
    ids=["pull-request", "file-line"],
)
def test_a_pull_request_or_file_line_citation_is_admitted(
    citation: str, tmp_path: Path, ledger: Path
) -> None:
    ok = _create(title=_DEFECT_TITLE, description=_with_diagnosis(citation))
    _admitted(_run(ok, tmp_path, ledger))


@pytest.mark.parametrize(
    "citation",
    ["see the incident", "OmniNode-ai/omniclaude", "handler_lane_intake.py", "#2836"],
)
def test_a_citation_matching_no_declared_form_is_refused(
    citation: str, tmp_path: Path, ledger: Path
) -> None:
    bad = _create(title=_DEFECT_TITLE, description=_with_diagnosis(citation))
    assert "unresolvable_diagnosis" in _refused(_run(bad, tmp_path, ledger))


def test_a_bulleted_diagnosis_line_is_not_read(tmp_path: Path, ledger: Path) -> None:
    """A bullet is how a line ends up inside a checklist that binds nothing."""
    bad = _create(
        title=_DEFECT_TITLE,
        description=_with_diagnosis("OmniNode-ai/omniclaude#2836", prefix="- "),
    )
    assert "missing_diagnosis" in _refused(_run(bad, tmp_path, ledger))


def test_one_resolving_line_among_several_admits(tmp_path: Path, ledger: Path) -> None:
    description = "Diagnosis: nothing yet\n" + _with_diagnosis(
        "docs/tracking/ROLLING_WORK_LEDGER.md:2"
    )
    _admitted(
        _run(_create(title=_DEFECT_TITLE, description=description), tmp_path, ledger)
    )


def test_a_defect_label_makes_a_create_defect_shaped(
    tmp_path: Path, ledger: Path
) -> None:
    labelled = _create(labels=["Bug"])
    assert "missing_diagnosis" in _refused(_run(labelled, tmp_path, ledger))
    cited = _create(
        labels=["Bug"], description=_with_diagnosis("OmniNode-ai/omniclaude#2836")
    )
    _admitted(_run(cited, tmp_path, ledger))


def test_a_feature_shaped_create_needs_no_diagnosis(
    tmp_path: Path, ledger: Path
) -> None:
    """AC4 control: the shipped example create carries no diagnosis and is admitted."""
    _admitted(_run(_create(), tmp_path, ledger))
    _admitted(
        _run(_create(title="Add a debugging hook to the prefix lane"), tmp_path, ledger)
    )


def test_defect_terms_match_on_word_boundaries(tmp_path: Path, ledger: Path) -> None:
    """`debugging` and `prefix` do not fire the `bug` and `fix` terms; `fix` does."""
    assert "missing_diagnosis" in _refused(
        _run(_create(title="Fix the debugging hook"), tmp_path, ledger)
    )


def _load_guard() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("tcg_defect_diagnosis", _GUARD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_checker_without_a_ledger_seam_resolves_no_ledger_citation() -> None:
    guard = _load_guard()
    policy = guard.load_policy()
    bad = _create(
        title=_DEFECT_TITLE,
        description=_with_diagnosis("docs/tracking/ROLLING_WORK_LEDGER.md:1"),
    )
    codes = {f.code for f in guard.check_save_issue(bad, policy)}
    assert codes == {"unresolvable_diagnosis"}


def test_every_declared_example_matches_the_form_that_declares_it() -> None:
    """The refusal quotes these examples, so a drifted one teaches a wrong line."""
    guard = _load_guard()
    handler_policy = guard.load_policy().defect_diagnosis
    assert handler_policy.forms, "positive control: the shipped policy declares forms"
    for form in handler_policy.forms:
        assert form.pattern.match(form.example), (form.id, form.example)


def _policy_with(mutate: Any, tmp_path: Path) -> Path:
    raw = json.loads(_POLICY_JSON.read_text(encoding="utf-8"))
    mutate(raw)
    written = tmp_path / "policy.json"
    written.write_text(json.dumps(raw), encoding="utf-8")
    return written


def _drop(raw: dict[str, Any]) -> None:
    del raw["defect_diagnosis"]


def _drop_forms(raw: dict[str, Any]) -> None:
    raw["defect_diagnosis"]["citation_forms"] = []


def _bad_resolution(raw: dict[str, Any]) -> None:
    raw["defect_diagnosis"]["citation_forms"][0]["resolution"] = "trust-me"


def _ledger_form_without_line(raw: dict[str, Any]) -> None:
    raw["defect_diagnosis"]["citation_forms"][0]["pattern"] = "^(?P<path>.+)$"


def _no_citation_group(raw: dict[str, Any]) -> None:
    raw["defect_diagnosis"]["line_pattern"] = "^Diagnosis:.*$"


def _no_terms(raw: dict[str, Any]) -> None:
    del raw["defect_diagnosis"]["defect_title_terms"]


@pytest.mark.parametrize(
    "mutate",
    [
        _drop,
        _drop_forms,
        _bad_resolution,
        _ledger_form_without_line,
        _no_citation_group,
        _no_terms,
    ],
    ids=lambda f: f.__name__,
)
def test_a_malformed_defect_diagnosis_policy_refuses_rather_than_defaulting(
    mutate: Any, tmp_path: Path
) -> None:
    guard = _load_guard()
    with pytest.raises(guard.PolicyError):
        guard.load_policy(_policy_with(mutate, tmp_path))


def test_the_handler_is_stdlib_only() -> None:
    """The guard runs under a bare interpreter with no `omniclaude` package."""
    imported = {
        line.split()[1].split(".")[0]
        for line in _HANDLER_PY.read_text(encoding="utf-8").splitlines()
        if line.startswith(("import ", "from "))
    }
    assert imported <= {"__future__", "re", "collections", "pathlib", "typing"}, (
        imported
    )
