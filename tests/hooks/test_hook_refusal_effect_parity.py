# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The hook refusal effect node records exactly what the old recorder recorded (OMN-20685).

``tests/fixtures/hook_refusal_effect_golden.json`` was captured by running this
scenario driver against the standalone recorder and lane-resolver scripts as
they stood at omniclaude 8d694c72e, before either moved into
``node_hook_refusal_record_effect``. The node's handler replays the
same scenarios and must produce the same exit codes, ledger rows, refusal-log
lines, rate-limit state files, extracted details and resolved lanes.

Timestamps and the temporary directory are normalised out of every recorded
value; nothing else is.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.unit

GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures/hook_refusal_effect_golden.json"
)
_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")

SECRET_GUARD = "subagent_stop_secret_leak_guard.sh"

#: (name, argv, clock) steps. A scenario shares one state directory.
RECORD_SCENARIOS: dict[str, list[tuple[list[str], float]]] = {
    "window_then_new_row": [
        (["--guard", "g.sh", "--reason", "same class", "--detail", "d1"], 100.0),
        (["--guard", "g.sh", "--reason", "same class", "--detail", "d2"], 110.0),
        (["--guard", "g.sh", "--reason", "same class", "--detail", "d3"], 120.0),
        (["--guard", "g.sh", "--reason", "same class", "--detail", "d4"], 4000.0),
    ],
    "different_keys_do_not_share_a_window": [
        (["--guard", "a.sh", "--reason", "one"], 100.0),
        (["--guard", "b.sh", "--reason", "one"], 101.0),
        (["--guard", "a.sh", "--reason", "two /tmp/x/123"], 102.0),
        (["--guard", "a.sh", "--reason", "two /tmp/y/456"], 103.0),
    ],
    "secret_guard_surfaces_the_fourth": [
        (
            [
                "--guard",
                SECRET_GUARD,
                "--reason",
                "leak",
                "--detail",
                "rule=r1 line=3",
                "--session-id",
                "s-1",
            ],
            100.0 + i,
        )
        for i in range(6)
    ],
    "secret_guard_sessions_are_separate": [
        (["--guard", SECRET_GUARD, "--reason", "leak", "--session-id", "s-1"], 100.0),
        (["--guard", SECRET_GUARD, "--reason", "leak", "--session-id", "s-2"], 101.0),
        (["--guard", SECRET_GUARD, "--reason", "leak", "--session-id", "s-1"], 102.0),
    ],
    "redaction_and_field_breakers": [
        (
            [
                "--guard",
                "g.sh",
                "--reason",
                "token=abcdef0123456789 | forged",
                "--detail",
                "ghp_abcdefghijklmnopqrstuvwx | cell\nnext row",
            ],
            100.0,
        ),
    ],
    "custom_window": [
        (["--guard", "g.sh", "--reason", "w", "--window-seconds", "10"], 100.0),
        (["--guard", "g.sh", "--reason", "w", "--window-seconds", "10"], 105.0),
        (["--guard", "g.sh", "--reason", "w", "--window-seconds", "10"], 111.0),
    ],
    "print_row_writes_nothing": [
        (["--guard", "g.sh", "--reason", "p", "--print-row"], 100.0),
        (["--guard", "g.sh", "--reason", "p", "--print-row"], 101.0),
    ],
}

EXTRACT_INPUTS = [
    '{"decision": "block", "reason": "plain reason token=abc123"}',
    '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "ctx line"}}',
    '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecisionReason": "why"}}',
    '{"decision": "block"}',
    "not json",
    '{"decision": "block", "reason": 7}',
    json.dumps(
        {
            "reason": "preamble What is missing: no_bound_dod_receipt for OMN-12345 "
            "x Ticked boxes: a b c"
        }
    ),
    json.dumps({"reason": "ghp_abcdefghijklmnopqrstuvwx " + "y" * 400}),
]


def _norm(text: str, tmp: Path) -> str:
    return _TS.sub("<ts>", text.replace(str(tmp), "<tmp>"))


def _record(
    module: ModuleType,
    tmp: Path,
    monkeypatch: pytest.MonkeyPatch,
    steps: list[tuple[list[str], float]],
) -> list[dict[str, object]]:
    state = tmp / "state"
    monkeypatch.setenv("OMNI_HOME", str(tmp / "registry"))
    monkeypatch.setenv("OMNIBASE_INTERNAL_HOME", str(tmp / "internal"))
    monkeypatch.setenv("ONEX_STATE_DIR", str(state))
    monkeypatch.delenv("ONEX_HOOK_REFUSAL_STATE_DIR", raising=False)
    appended: list[str] = []

    def append(row: str, **_kw: object) -> bool:
        appended.append(row)
        return True

    monkeypatch.setattr(module, "append_row", append)
    monkeypatch.setattr(
        module, "resolve_lane_fields", lambda *a, **k: ("lane-a", "env")
    )
    clock = {"now": 0.0}
    monkeypatch.setattr(module.time, "time", lambda: clock["now"])
    out: list[dict[str, object]] = []
    for argv, now in steps:
        clock["now"] = now
        before = len(appended)
        rc = module.main(argv)
        log = state / "hooks/logs/hooks.log"
        files = {
            p.name: json.loads(p.read_text())
            for p in sorted((state / "hook_refusals").glob("*.json"))
        }
        out.append(
            {
                "rc": rc,
                "appended": [_norm(r, tmp) for r in appended[before:]],
                "log_lines": len(log.read_text().splitlines()) if log.exists() else 0,
                "state": files,
            }
        )
    return out


def _lanes(module: ModuleType, tmp: Path) -> dict[str, list[str]]:
    wt = tmp / "wt"
    (wt / "OMN-111" / "repo").mkdir(parents=True)
    (wt / "OMN-222" / "repo").mkdir(parents=True)
    (wt / "OMN-333" / "repo").mkdir(parents=True)
    ledger = tmp / "ledger.md"
    ledger.write_text(
        "2026-10-09T00:00:00Z | CLAIM | lane=alpha | ticket=OMN-111 | "
        "worktree=omni_worktrees/OMN-111/repo | x\n"
        "2026-10-09T00:00:01Z | CLAIM | lane=beta | ticket=OMN-222 | x\n"
        "2026-10-09T00:00:02Z | CLAIM | lane=gamma | ticket=OMN-222 | x\n"
        "2026-10-09T00:00:03Z | CLAIM | lane=delta | ticket=OMN-333 | x\n"
        "2026-10-09T00:00:04Z | TERMINAL | lane=delta | ticket=OMN-333 | x\n"
    )
    env = {"OMNI_HOME": str(tmp), "ONEX_WORKTREES_ROOT": str(wt), "HOME": str(tmp)}
    cases: dict[str, tuple[dict[str, object] | None, dict[str, str]]] = {
        "env_lane": ({"cwd": str(tmp)}, {**env, "ONEX_LANE": "from-env"}),
        "env_ignored_for_subagent": (
            {"cwd": str(tmp), "agent_id": "a1"},
            {**env, "ONEX_LANE": "parent"},
        ),
        "claim_by_worktree": ({"cwd": str(wt / "OMN-111" / "repo")}, env),
        "claim_ambiguous_by_ticket": ({"cwd": str(wt / "OMN-222" / "repo")}, env),
        "terminated_claim_falls_to_worktree": (
            {"cwd": str(wt / "OMN-333" / "repo")},
            env,
        ),
        "command_names_worktree": (
            {
                "cwd": str(tmp),
                "tool_input": {"command": f"git -C {wt}/OMN-111/repo status"},
            },
            env,
        ),
        "file_path_names_worktree": (
            {"cwd": str(tmp), "tool_input": {"file_path": f"{wt}/OMN-333/repo/a.py"}},
            env,
        ),
        "unresolved": ({"cwd": str(tmp)}, env),
        "no_payload": (None, env),
    }
    out: dict[str, list[str]] = {}
    for name, (payload, environment) in cases.items():
        lane, source = module.resolve_refusal_lane(
            payload, env=environment, ledger=str(ledger)
        )
        out[name] = [_norm(lane, tmp), source]
    return out


def run_all(
    record_module: ModuleType,
    lane_module: ModuleType,
    tmp_factory: Callable[[str], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    result: dict[str, object] = {"record": {}}
    for name, steps in RECORD_SCENARIOS.items():
        recorded = result["record"]
        assert isinstance(recorded, dict)
        recorded[name] = _record(record_module, tmp_factory(name), monkeypatch, steps)
    result["extract_detail"] = [
        record_module.extract_detail(raw) for raw in EXTRACT_INPUTS
    ]
    result["lane"] = _lanes(lane_module, tmp_factory("lanes"))
    return result


def test_the_node_replays_the_old_recorder_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from omniclaude.nodes.node_hook_refusal_record_effect.handlers import (
        handler_hook_refusal_lane,
        handler_hook_refusal_record,
    )

    def make(name: str) -> Path:
        path = tmp_path / name
        path.mkdir()
        return path

    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(
            str(Path(__file__).resolve().parents[2] / "plugins/onex/hooks/lib")
        )
        got = run_all(
            handler_hook_refusal_record, handler_hook_refusal_lane, make, scoped
        )
    # Round-trip through JSON so tuples compare as lists, as the golden holds them.
    assert json.loads(json.dumps(got)) == json.loads(GOLDEN.read_text())


def test_the_golden_is_not_vacuous() -> None:
    golden = json.loads(GOLDEN.read_text())
    record = golden["record"]
    emitted = [
        step["appended"] for step in record["window_then_new_row"] if step["appended"]
    ]
    assert len(emitted) == 2, "the window must suppress the middle refusals"
    assert any("suppressed_since_last_row=2" in row for rows in emitted for row in rows)
    secret = [s["appended"] for s in record["secret_guard_surfaces_the_fourth"]]
    assert [bool(rows) for rows in secret] == [True, False, False, True, True, True]
    assert {v[1] for v in golden["lane"].values()} >= {
        "env",
        "claim",
        "worktree",
        "unresolved",
    }
    assert any(
        "What is missing" not in d and "rule=" in d for d in golden["extract_detail"]
    )
