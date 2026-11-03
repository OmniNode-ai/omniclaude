# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Run the Hostile Reviewer workflow's own steps, with a fake reviewer and a fake node.

The workflow's ``run:`` text for the review step, the gate-accept step and the
enforcement step is executed as written, in the order the job runs it, with the
``${{ }}`` expressions substituted and each step's ``if:`` evaluated over the earlier
steps' outputs. Only the world is faked: ``uv`` prints a recorded reviewer document
(exiting with the recorded cli_review code) and, for the gate-accept node's ``python -m``
entry, stands in for the node: it checks that the step runs it from the trusted
omnimarket clone's source with the input the step names, and answers a chosen decision.
The gate job's script then runs with the job's conclusion. The result is the conclusion
of every required context.

Steps outside review, accept and enforce (checkout, overlay, install, the clone of the
trusted revision, the PR comment) are not run here: they do not decide the verdict. The
clone step has its own tests (``test_hostile_review_accept_base_commit``).

This is a copy by pattern of the helper the omnimarket workflow tests use (OMN-22176),
adapted to this workflow, where the review step writes the reviewer's document to
``$RUNNER_TEMP/hostile-review-result.json`` and the enforcement step is the one that
fails the job on an unresolved verdict.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"
REQUIRED_CHECKS_PATH = REPO_ROOT / ".github" / "required-checks.yaml"

REVIEW_JOB = "hostile-review"
GATE_JOB = "hostile-review-gate"
REPOSITORY = "example-org/example-repo"
PULL_REQUEST = 41
HEAD_SHA = "a" * 40
OTHER_HEAD_SHA = "c" * 40
RESULT_FILE_NAME = "hostile-review-result.json"
NODE_DIR = "omnimarket/nodes/node_agent_review_gate_accept_effect"

_PASSED_DOCUMENT: dict[str, Any] = {
    "models_attempted": ["voter-1", "voter-2"],
    "models_succeeded": ["voter-1", "voter-2"],
    "models_failed": [],
    "results": [
        {"model": "voter-1", "success": True, "error": None, "findings": []},
        {"model": "voter-2", "success": True, "error": None, "findings": []},
    ],
    "total_findings": 0,
    "quorum": {"verdict": "passed", "blocking_count": 0, "warning_count": 0},
}
_LOST_DOCUMENT: dict[str, Any] = {
    "models_attempted": ["voter-1", "voter-2"],
    "models_succeeded": [],
    "models_failed": ["voter-1", "voter-2"],
    "results": [
        {"model": "voter-1", "success": False, "error": "boom", "findings": []},
        {"model": "voter-2", "success": False, "error": "boom", "findings": []},
    ],
    "total_findings": 0,
    "quorum": {"verdict": "degraded_quorum", "blocking_count": 0, "warning_count": 0},
}
_PARTIAL_DOCUMENT: dict[str, Any] = {
    "models_attempted": ["voter-1", "voter-2"],
    "models_succeeded": ["voter-1"],
    "models_failed": ["voter-2"],
    "results": [
        {"model": "voter-1", "success": True, "error": None, "findings": []},
        {"model": "voter-2", "success": False, "error": "boom", "findings": []},
    ],
    "total_findings": 0,
    "quorum": {"verdict": "degraded_quorum", "blocking_count": 0, "warning_count": 0},
}
_BLOCKED_DOCUMENT: dict[str, Any] = {
    "models_attempted": ["voter-1", "voter-2"],
    "models_succeeded": ["voter-1", "voter-2"],
    "models_failed": [],
    "results": [
        {"model": "voter-1", "success": True, "error": None, "findings": []},
        {"model": "voter-2", "success": True, "error": None, "findings": []},
    ],
    "total_findings": 2,
    "quorum": {"verdict": "blocked", "blocking_count": 1, "warning_count": 0},
}

#: One recorded cli_review outcome per case: (document, exit code of cli_review).
#: The review step turns each into the verdict named after it, except ``lost_all``.
REVIEWER_CASES: dict[str, tuple[dict[str, Any] | None, int]] = {
    # exit 0, quorum passed -> verdict=passed
    "passed": (_PASSED_DOCUMENT, 0),
    # exit 0, quorum blocked -> verdict=blocked (the review step fails the job)
    "blocked": (_BLOCKED_DOCUMENT, 0),
    # exit 2 after both attempts -> verdict=degraded_quorum, deferred to enforcement
    "degraded_quorum": (_LOST_DOCUMENT, 2),
    # exit 1 after both attempts -> verdict=infra_error, deferred to enforcement
    "infra_error": (_LOST_DOCUMENT, 1),
    # exit 0, one voter lost, quorum degraded -> verdict=degraded_quorum from the parser
    "partial": (_PARTIAL_DOCUMENT, 0),
    # exit 0, every voter lost -> verdict=degraded, informational in the pilot
    "lost_all": (_LOST_DOCUMENT, 0),
}
#: The cases the gate holds red when the voters are lost (the ones an agent receipt may lift).
DEGRADED_CASES = ("degraded_quorum", "infra_error", "partial")

_UV = """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

argv = sys.argv[1:]
joined = " ".join(argv)
NODE = "omnimarket.nodes.node_agent_review_gate_accept_effect.runtime_gate_accept"
if "cli_review" in joined:
    document = os.environ.get("FAKE_REVIEWER_DOCUMENT", "")
    if document:
        sys.stdout.write(Path(document).read_text())
    sys.exit(int(os.environ.get("FAKE_REVIEWER_EXIT", "0")))
if NODE in argv:
    with open(os.environ["FAKE_NODE_LOG"], "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"argv": argv, "pythonpath": os.environ.get("PYTHONPATH")}) + "\\n")
    if os.environ.get("PYTHONPATH") != os.environ["FAKE_TRUSTED_SRC"]:
        sys.exit("fake node: not run from the trusted omnimarket clone: " + repr(os.environ.get("PYTHONPATH")))
    if argv[:2] != ["run", "--no-sync"]:
        sys.exit("fake node: unexpected uv arguments " + repr(argv))
    if argv[argv.index("--project") + 1] != os.environ["FAKE_PROJECT"]:
        sys.exit("fake node: not run in the reviewer project " + repr(argv))
    flags = argv[argv.index(NODE) + 1:]
    payload = {flags[i][2:].replace("-", "_"): flags[i + 1] for i in range(0, len(flags), 2)}
    payload["pull_request"] = int(payload["pull_request"])
    expected = json.loads(os.environ["FAKE_NODE_EXPECT"])
    if payload != expected:
        sys.exit("fake node: input " + repr(payload) + " is not " + repr(expected))
    if not os.path.exists(payload["voter_result_path"]):
        sys.exit("fake node: the voter result file the step named does not exist")
    if os.environ.get("FAKE_NODE_EXIT", "0") != "0":
        sys.exit(int(os.environ["FAKE_NODE_EXIT"]))
    decision = os.environ["FAKE_DECISION"]
    # A receipt is accepted only for the exact head the step names.
    if decision == "pass_agent" and os.environ["FAKE_RECEIPT_HEAD"] != payload["head_sha"]:
        decision = "refuse"
    with open(payload["step_output_path"], "a", encoding="utf-8") as handle:
        handle.write("decision=" + decision + "\\n")
        handle.write("reason=fake\\nreceipt_id=\\n")
sys.exit(0)
"""
_SLEEP = "#!/usr/bin/env bash\nexit 0\n"


def load_workflow() -> dict[str, Any]:
    return cast("dict[str, Any]", yaml.safe_load(WORKFLOW_PATH.read_text()))


def job(name: str) -> dict[str, Any]:
    return cast("dict[str, Any]", load_workflow()["jobs"][name])


def step_named(job_id: str, prefix: str) -> dict[str, Any]:
    found = [
        s for s in job(job_id)["steps"] if str(s.get("name", "")).startswith(prefix)
    ]
    assert len(found) == 1, f"expected one step named {prefix!r}, found {len(found)}"
    return cast("dict[str, Any]", found[0])


def required_context_names() -> list[str]:
    """The required contexts this repository lists for the Hostile Reviewer workflow."""
    document = cast("dict[str, Any]", yaml.safe_load(REQUIRED_CHECKS_PATH.read_text()))
    return [
        str(entry["name"])
        for entry in document["gates"]
        if entry.get("workflow") == "hostile-reviewer.yml"
    ]


@dataclass
class Run:
    """The outcome of one simulated job: each step's exit and every context's result."""

    exits: dict[str, int]
    skipped: list[str]
    outputs: dict[str, dict[str, str]]
    node_calls: list[dict[str, Any]]
    contexts: dict[str, bool]

    def green(self, context: str) -> bool:
        return self.contexts[context]


def _evaluate(
    expression: str, outputs: dict[str, dict[str, str]], ctx: dict[str, str]
) -> str:
    for term in (t.strip() for t in expression.split("||")):
        match = re.fullmatch(r"steps\.([\w-]+)\.outputs\.([\w-]+)", term)
        if match:
            value = outputs.get(match.group(1), {}).get(match.group(2), "")
        elif term in ctx:
            value = ctx[term]
        else:
            raise AssertionError(f"unsupported expression term {term!r}")
        if value:
            return value
    return ""


def render(text: str, outputs: dict[str, dict[str, str]], ctx: dict[str, str]) -> str:
    rendered = re.sub(
        r"\$\{\{\s*(.+?)\s*\}\}",
        lambda m: _evaluate(m.group(1), outputs, ctx),
        text,
    )
    assert "${{" not in rendered, f"unsubstituted expression in:\n{rendered}"
    return rendered


def _holds(condition: Any, outputs: dict[str, dict[str, str]]) -> bool:
    """Evaluate an ``if:`` made of ``always()`` and output comparisons joined by ``&&``."""
    if condition is None:
        return True
    for clause in (c.strip() for c in str(condition).split("&&")):
        if clause == "always()":
            continue
        match = re.fullmatch(
            r"steps\.([\w-]+)\.outputs\.([\w-]+) (==|!=) '([^']*)'", clause
        )
        if not match:
            raise AssertionError(f"unsupported if: clause {clause!r}")
        value = outputs.get(match.group(1), {}).get(match.group(2), "")
        if (value == match.group(4)) != (match.group(3) == "=="):
            return False
    return True


def _parse_outputs(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                values[key] = value
    return values


def _bash(
    script: str, env: dict[str, str], cwd: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=cwd,
    )


def simulate(
    work: Path,
    *,
    case: str,
    decision: str,
    receipt_head: str = HEAD_SHA,
    review_step_prefix: str = "Run adversarial review",
    enforce_prefix: str | None = "Enforce hostile-review verdict",
    trusted_has_node: bool = True,
    workspace_has_node: bool = False,
    node_exit: int = 0,
) -> Run:
    """Run the job's review, accept and enforcement steps, then the gate job."""
    bin_dir = work / "bin"
    bin_dir.mkdir()
    for name, text in (("uv", _UV), ("sleep", _SLEEP)):
        path = bin_dir / name
        path.write_text(text)
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    runner_temp = work / "runner-temp"
    runner_temp.mkdir()
    workspace = work / "workspace"
    workspace.mkdir()
    reviewer_project = work / "omniintelligence"
    reviewer_project.mkdir()
    trusted_src = work / "omnimarket" / "src"
    if trusted_has_node:
        (trusted_src / NODE_DIR).mkdir(parents=True)
    else:
        trusted_src.mkdir(parents=True)
    if workspace_has_node:
        (workspace / "src" / NODE_DIR).mkdir(parents=True)
    document, review_exit = REVIEWER_CASES[case]
    document_path = work / "reviewer-document.json"
    document_path.write_text(json.dumps(document) if document is not None else "")
    node_log = work / "node.log"
    base_env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(work),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_WORKSPACE": str(workspace),
        "FAKE_REVIEWER_DOCUMENT": str(document_path),
        "FAKE_REVIEWER_EXIT": str(review_exit),
        "FAKE_DECISION": decision,
        "FAKE_RECEIPT_HEAD": receipt_head,
        "FAKE_NODE_LOG": str(node_log),
        "FAKE_NODE_EXIT": str(node_exit),
        "FAKE_TRUSTED_SRC": f"{workspace}/../omnimarket/src",
        "FAKE_PROJECT": f"{workspace}/../omniintelligence",
        "REVIEW_VOTERS_OVERLAY": str(work / "overlay.yaml"),
        "LOCAL_LLM_SHARED_SECRET": "unused",
        "VERDICT_ARTIFACT": str(work / "verdict-artifact.json"),
    }
    ctx = {
        "github.repository": REPOSITORY,
        "github.event.pull_request.number": str(PULL_REQUEST),
        "github.event.pull_request.head.sha": HEAD_SHA,
        "github.workspace": str(workspace),
        "runner.temp": str(runner_temp),
        "secrets.GITHUB_TOKEN": "unused",
        "secrets.LOCAL_LLM_SHARED_SECRET": "unused",
    }
    plan: list[tuple[str, dict[str, Any]]] = [
        ("review", step_named(REVIEW_JOB, review_step_prefix)),
    ]
    accept = [s for s in job(REVIEW_JOB)["steps"] if s.get("id") == "accept"]
    if accept:
        plan.append(("accept", accept[0]))
    if enforce_prefix is not None:
        plan.append(("enforce", step_named(REVIEW_JOB, enforce_prefix)))
    outputs: dict[str, dict[str, str]] = {}
    exits: dict[str, int] = {}
    skipped: list[str] = []
    failed = False
    for key, step in plan:
        condition = step.get("if")
        runs = _holds(condition, outputs) if condition is not None else not failed
        if not runs:
            skipped.append(key)
            continue
        out_path = work / f"{key}.output"
        summary_path = work / f"{key}.summary"
        env = dict(base_env) | {
            "GITHUB_OUTPUT": str(out_path),
            "GITHUB_STEP_SUMMARY": str(summary_path),
            "FAKE_NODE_EXPECT": json.dumps(
                {
                    "repository": REPOSITORY,
                    "pull_request": PULL_REQUEST,
                    "head_sha": HEAD_SHA,
                    "voter_result_path": str(runner_temp / RESULT_FILE_NAME),
                    "step_output_path": str(out_path),
                    "step_summary_path": str(summary_path),
                }
            ),
        }
        for name, value in (step.get("env") or {}).items():
            env[str(name)] = render(str(value), outputs, ctx)
        script = render(str(step["run"]), outputs, ctx)
        completed = _bash(script, env, reviewer_project)
        exits[key] = completed.returncode
        outputs[str(step.get("id", key))] = _parse_outputs(out_path)
        if completed.returncode != 0:
            failed = True
    result = "failure" if failed else "success"
    gate_script = render(
        next(str(s["run"]) for s in job(GATE_JOB)["steps"] if "run" in s),
        {},
        {f"needs.{REVIEW_JOB}.result": result},
    )
    node_calls = (
        [json.loads(line) for line in node_log.read_text().splitlines()]
        if node_log.exists()
        else []
    )
    gate = _bash(
        gate_script, base_env | {"GITHUB_STEP_SUMMARY": str(work / "g.sum")}, work
    )
    contexts = {
        str(job(REVIEW_JOB)["name"]): not failed,
        str(job(GATE_JOB)["name"]): gate.returncode == 0,
    }
    return Run(exits, skipped, outputs, node_calls, contexts)
