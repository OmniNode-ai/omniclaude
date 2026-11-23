# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Rule 9 and rule 15 resolve a ledger row stamp through the reader node (OMN-26567).

Every test runs with the ledger path variable unset and no ledger file on disk. The bus is a fake
executable standing in for the reader node's interpreter (``ONEX_LEDGER_READER_PYTHON``): it records
its argv and answers the rows whose first line holds ``--term``, as the real reader does. Rule 9's
approved-edit lookup and rule 15's ``Diagnosis:`` lookup must each call it with their own reader
name and must never open a ledger file; a reader that does not answer, or a stamp it does not
return, resolves nothing and the rewrite or the create stays refused.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
GUARD_PY = REPO / "plugins/onex/hooks/lib/ticket_creation_guard.py"
HANDLERS = [
    REPO / "src/omniclaude/handlers/handler_ticket_ledger_lookup.py",
    REPO / "src/omniclaude/handlers/handler_defect_diagnosis.py",
    REPO / "plugins/onex/hooks/config/ticket_creation_policy.json",
]
#: Spelled in two halves: this file names neither, so the census does not count it.
PATH_VARIABLE = "ONEX_LEDGER_" + "PATH"
LEDGER_FILE = "ROLLING_WORK_" + "LEDGER"

RULING_STAMP = "2026-10-08T22:53:25Z"
RULING_ROW = (
    f"{RULING_STAMP} | RULING | lane=orchestrator-9f8a | ticket=OMN-18387 | "
    'question=May AC2 be corrected? | kind=decision | "You do it."'
)
DIAGNOSIS_STAMP = "2026-11-14T14:43:55Z"
DIAGNOSIS_ROW = (
    f"{DIAGNOSIS_STAMP} | RULING | lane=orchestrator-31d9-swarm | ticket=OMN-26567 | "
    '"the work ledger on the bus"'
)
AC_BODY = (
    "Some preamble.\n\n## Acceptance criteria\n\n"
    "* AC1: the classifier publishes a rebuild for a projection-only merge "
    "-- falsifier: a unit test with that path set returns no rebuild.\n"
    "* AC2: the up-target list equals RUNTIME_SERVICES "
    "-- falsifier: the two lists can be edited apart without a red test.\n"
)
CITATION = f"Criterion-edit ruling: {RULING_STAMP}"
DEFECT_TITLE = "Fix the stale binding the closer reads"
BODY = (
    "Gate: OMN-16729 AC-5\n\n"
    "- [ ] AC1: The guard refuses it -- falsifier: uv run pytest tests/hooks -q\n"
)


class Bus:
    """The fake reader node: records every call and answers rows from a file."""

    def __init__(self, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.root = root
        self.log = root / "bus.log"
        self.rows = root / "rows.txt"
        self.rows.write_text("", encoding="utf-8")
        reader = root / "reader-python"
        reader.write_text(
            "#!/bin/sh\n"
            'printf \'%s\\n\' "$*" >> "$FAKE_BUS_LOG"\n'
            "term=\n"
            'while [ $# -gt 0 ]; do [ "$1" = --term ] && term=$2; shift; done\n'
            'grep -F -- "$term" "$FAKE_BUS_ROWS"\n'
            'exit "${FAKE_BUS_EXIT:-0}"\n',
            encoding="utf-8",
        )
        reader.chmod(reader.stat().st_mode | stat.S_IXUSR)
        self.reader = reader
        monkeypatch.delenv(PATH_VARIABLE, raising=False)
        monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(reader))
        monkeypatch.setenv("FAKE_BUS_LOG", str(self.log))
        monkeypatch.setenv("FAKE_BUS_ROWS", str(self.rows))
        monkeypatch.setenv("OMNI_HOME", str(root / "home"))

    def answer(self, *rows: str) -> None:
        self.rows.write_text("".join(f"{row}\n" for row in rows), encoding="utf-8")

    def calls(self) -> list[str]:
        return (
            self.log.read_text(encoding="utf-8").splitlines()
            if self.log.exists()
            else []
        )

    def ledger_files(self) -> list[Path]:
        return [p for p in self.root.rglob(f"{LEDGER_FILE}*") if p.is_file()]


@pytest.fixture
def bus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Bus:
    return Bus(tmp_path, monkeypatch)


def run_guard(
    tool_input: dict[str, Any], home: Path
) -> subprocess.CompletedProcess[str]:
    """The hook as registered: ``python ticket_creation_guard.py`` with the payload on stdin."""
    home.mkdir(exist_ok=True)
    env = {
        key: value
        for key, value in os.environ.items()
        if key.startswith(("FAKE_BUS_", "ONEX_LEDGER_READER", "OMNI_HOME"))
    }
    env.update({"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home)})
    payload = {"tool_name": "mcp__linear-server__save_issue", "tool_input": tool_input}
    return subprocess.run(
        [sys.executable, str(GUARD_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=False,
    )


def create(description: str) -> dict[str, Any]:
    return {
        "team": "Omninode",
        "title": DEFECT_TITLE,
        "parentId": "OMN-16729",
        "description": description,
    }


def diagnosis(citation: str) -> str:
    return f"Diagnosis: {citation}\n{BODY}"


def reason(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 3, result.stdout + result.stderr
    return str(json.loads(result.stdout)["reason"])


# ---------------------------------------------------------------------------
# Rule 15 -- the Diagnosis: line cites a row stamp
# ---------------------------------------------------------------------------


def test_a_diagnosis_stamp_the_reader_returns_is_admitted(
    bus: Bus, tmp_path: Path
) -> None:
    bus.answer(DIAGNOSIS_ROW)
    done = run_guard(create(diagnosis(DIAGNOSIS_STAMP)), tmp_path / "h")
    assert done.returncode == 0, done.stdout + done.stderr
    [call] = bus.calls()
    assert "--reader ticket-diagnosis" in call
    assert "--query rows" in call
    assert f"--term {DIAGNOSIS_STAMP}" in call
    assert "--window-hours" in call
    assert bus.ledger_files() == []


def test_a_diagnosis_stamp_the_reader_does_not_return_is_refused(
    bus: Bus, tmp_path: Path
) -> None:
    bus.answer(RULING_ROW)
    text = reason(run_guard(create(diagnosis(DIAGNOSIS_STAMP)), tmp_path / "h"))
    assert "unresolvable_diagnosis" in text
    assert f"'{DIAGNOSIS_STAMP}'" in text, (
        "the refusal names the stamp it could not read"
    )
    assert len(bus.calls()) == 1, "positive control: the reader was asked"


def test_a_row_that_only_mentions_the_diagnosis_stamp_does_not_resolve(
    bus: Bus, tmp_path: Path
) -> None:
    """The reader's term matches inside the first line; the first cell must be the stamp."""
    bus.answer(f"2026-11-15T00:00:00Z | MSG | lane=x | re={DIAGNOSIS_STAMP} | cites it")
    assert "unresolvable_diagnosis" in reason(
        run_guard(create(diagnosis(DIAGNOSIS_STAMP)), tmp_path / "h")
    )


@pytest.mark.parametrize("exit_code", ["69", "3"], ids=["unreadable", "not-moved"])
def test_a_reader_that_does_not_answer_resolves_no_diagnosis(
    exit_code: str,
    bus: Bus,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus.answer(DIAGNOSIS_ROW)
    monkeypatch.setenv("FAKE_BUS_EXIT", exit_code)
    assert "unresolvable_diagnosis" in reason(
        run_guard(create(diagnosis(DIAGNOSIS_STAMP)), tmp_path / "h")
    )


def test_an_absent_reader_interpreter_resolves_no_diagnosis(
    bus: Bus, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus.answer(DIAGNOSIS_ROW)
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(tmp_path / "no-such-python"))
    assert "unresolvable_diagnosis" in reason(
        run_guard(create(diagnosis(DIAGNOSIS_STAMP)), tmp_path / "h")
    )


def test_the_file_line_ledger_form_is_no_longer_a_diagnosis_form(
    bus: Bus, tmp_path: Path
) -> None:
    bus.answer(DIAGNOSIS_ROW)
    old_form = f"docs/tracking/{LEDGER_FILE}.md:4120"
    text = reason(run_guard(create(diagnosis(old_form)), tmp_path / "h"))
    assert "unresolvable_diagnosis" in text
    assert bus.calls() == [], (
        "a form the policy no longer declares never reaches the bus"
    )


def test_the_diagnosis_refusal_teaches_the_stamp_form_not_the_file_form(
    bus: Bus, tmp_path: Path
) -> None:
    text = reason(run_guard(create(BODY), tmp_path / "h"))
    assert "missing_diagnosis" in text
    assert "2026-" in text and "Z'" in text, "the fix shows a row stamp"
    assert LEDGER_FILE not in text and ".md:" not in text


@pytest.mark.parametrize(
    "citation", ["OmniNode-ai/omniclaude#2836", "src/omniclaude/handlers/x.py:60"]
)
def test_a_pull_request_or_file_line_diagnosis_is_still_admitted_without_the_bus(
    citation: str, bus: Bus, tmp_path: Path
) -> None:
    done = run_guard(create(diagnosis(citation)), tmp_path / "h")
    assert done.returncode == 0, done.stdout + done.stderr
    assert bus.calls() == []


# ---------------------------------------------------------------------------
# Rule 9 -- the approved-edit lookup
# ---------------------------------------------------------------------------


def load_guard() -> Any:
    spec = importlib.util.spec_from_file_location("tcg_ledger_bus", GUARD_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def rewrite(
    monkeypatch: pytest.MonkeyPatch, citation: str | None = CITATION
) -> tuple[int, str]:
    """``main`` over an UPDATE that corrects AC2 and cites ``citation``."""
    guard = load_guard()
    monkeypatch.setattr(guard, "_resolve_api_key", lambda: "k")
    monkeypatch.setattr(guard, "_fetch_issue_body", lambda _ref, _key: AC_BODY)
    body = AC_BODY.replace("RUNTIME_SERVICES", "RUNTIME_SERVICES_AND_PROJECTIONS")
    if citation is not None:
        body += f"\n{citation}\n"
    payload = {
        "tool_name": "mcp__linear-server__save_issue",
        "tool_input": {"id": "OMN-18387", "description": body},
    }
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    written = io.StringIO()
    monkeypatch.setattr(sys, "stdout", written)
    return guard.main([]), written.getvalue()


def test_an_approved_rewrite_resolves_its_ruling_through_the_reader(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus.answer(RULING_ROW)
    assert rewrite(monkeypatch) == (0, "")
    [call] = bus.calls()
    assert "--reader ticket-ruling" in call
    assert f"--term {RULING_STAMP}" in call
    assert bus.ledger_files() == []


def test_a_ruling_the_reader_does_not_return_leaves_the_rewrite_refused(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    code, out = rewrite(monkeypatch)
    assert code == 3
    assert "criterion_ruling_unresolved" in json.loads(out)["reason"]
    assert len(bus.calls()) == 1, "positive control: the reader was asked"


def test_an_unanswering_reader_leaves_the_rewrite_refused(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus.answer(RULING_ROW)
    monkeypatch.setenv("FAKE_BUS_EXIT", "69")
    code, out = rewrite(monkeypatch)
    assert code == 3
    assert "criterion_ruling_unresolved" in json.loads(out)["reason"]


def test_a_reader_that_hangs_is_bounded(
    bus: Bus, monkeypatch: pytest.MonkeyPatch
) -> None:
    hang = bus.root / "hang-python"
    hang.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
    hang.chmod(hang.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("ONEX_LEDGER_READER_PYTHON", str(hang))
    guard = load_guard()
    handler = guard._handler("handler_ticket_ledger_lookup")
    started = time.monotonic()
    rows = handler.rows_for_stamp(handler.RULING_READER, RULING_STAMP, " | ", 1)
    assert rows == []
    assert time.monotonic() - started < 20


# ---------------------------------------------------------------------------
# No moved file opens or names the ledger file
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", HANDLERS, ids=lambda p: p.name)
def test_no_moved_file_names_the_ledger_file_or_its_path_variable(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert LEDGER_FILE not in text, path
    assert PATH_VARIABLE not in text, path
