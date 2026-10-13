# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-21006: caller-owned allowlist, core ratchet, and historical guard parity.

The historical reusable checked out origin/main for its validator and allowlists.
The entries and finding digest were read at a89a6f30fabf74189195f57b57fcc5d4751f4c48.
An isolated validator environment installs the caller's exact core workflow pin.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
CALLER = ROOT / ".github/workflows/imperative-contract-guard.yml"
ALLOWLIST_PATH = ".github/imperative-contract-allowlist.yaml"
ALLOWLIST = ROOT / ALLOWLIST_PATH
CORE_SHA = "70f7ceda44af968ccf26264ecd429cfd27503971"
CORE_USES = "OmniNode-ai/omnibase_core/.github/workflows/imperative-contract-guard.yml"
RECORDED_HANDLER_PATHS = [
    "omniclaude/nodes/node_delegation_orchestrator/handlers/handler_cross_cli_invoker.py",
    "omniclaude/nodes/node_git_effect/handlers/handler_git_subprocess.py",
    "omniclaude/nodes/node_github_pr_watcher_effect/handlers/watch_registry.py",
]
RECORDED_FREESTANDING_ENTRIES = [
    ("src/omniclaude/hooks/lib/compliance_result_subscriber.py", "raw_kafka"),
    ("src/omniclaude/hooks/lib/decision_record_subscriber.py", "raw_kafka"),
    ("src/omniclaude/hooks/topics.py", "hardcoded_topic"),
    (
        "src/omniclaude/nodes/node_local_llm_inference_effect/backends/backend_vllm.py",
        "raw_http_inference",
    ),
    (
        "src/omniclaude/nodes/node_personality_logging_effect/sinks/sink_slack.py",
        "raw_http_inference",
    ),
]
LIVE_HANDLER = (
    "src/omniclaude/nodes/node_git_effect/handlers/handler_git_admission_transport.py"
)
FINDING_KEYS = (
    "new_violations",
    "non_live_violations",
    "freestanding_violations",
    "non_live_freestanding_violations",
)
# All finding fields, including details, line numbers, reachability and allowlisting.
RECORDED_OCC_FINDING_DIGEST = (
    "dc967304fad97a8fbd0a5b4c19be43713fc2f1f4f2a70d7a1a8427813d5ab2ec"
)


def _mapping(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _core(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--with",
            f"omnibase-core @ git+https://github.com/OmniNode-ai/omnibase_core.git@{CORE_SHA}",
            *args,
        ],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        timeout=90,
        cwd=ROOT,
    )


def _guard_job() -> dict:
    job = _mapping(CALLER)["jobs"]["imperative-contract-guard"]
    assert job["uses"] == f"{CORE_USES}@{CORE_SHA}"
    assert job["with"] == {"allowlist-path": ALLOWLIST_PATH}
    return job


def test_caller_pins_core_and_keeps_the_job_and_context() -> None:
    workflow = _mapping(CALLER)
    assert workflow["name"] == "Imperative Contract Guard"
    assert "imperative-contract-guard" in workflow["jobs"]
    _guard_job()
    assert re.fullmatch(r"[0-9a-f]{40}", CORE_SHA)
    assert workflow["permissions"] == {"contents": "read"}
    for path in (ROOT / ".github/workflows").iterdir():
        if path.suffix in {".yml", ".yaml"}:
            assert not re.search(
                r"onex_change_control/\.github/workflows/imperative-contract-guard\.yml",
                path.read_text(encoding="utf-8"),
            ), path


def test_own_allowlist_preserves_all_historical_entries_and_metadata() -> None:
    assert _mapping(ALLOWLIST) == {
        "allowlisted_handlers": [
            {
                "path": path,
                "violations": ["missing_handler_routing"],
                "ticket": "OMN-11880",
            }
            for path in RECORDED_HANDLER_PATHS
        ]
        + [
            {"path": path, "violations": [violation], "ticket": "OMN-12564"}
            for path, violation in RECORDED_FREESTANDING_ENTRIES
        ]
    }


def test_canonical_shape_pin_and_caller_test_have_hook_and_ci_twins() -> None:
    repos = _mapping(ROOT / ".pre-commit-config.yaml")["repos"]
    (shape_repo,) = [
        repo
        for repo in repos
        if any(hook["id"] == "canonical-file-shape" for hook in repo["hooks"])
    ]
    assert shape_repo["repo"] == "https://github.com/OmniNode-ai/omnibase_core"
    assert shape_repo["rev"] == CORE_SHA
    command = "pytest tests/ci/test_imperative_contract_guard_caller_omn21006.py -q"
    (hook,) = [
        hook
        for repo in repos
        for hook in repo["hooks"]
        if hook["id"] == "imperative-contract-guard-caller"
    ]
    assert hook["entry"] == f"bash scripts/uv-run-worktree-safe.sh {command}"
    assert hook["pass_filenames"] is False
    jobs = _mapping(ROOT / ".github/workflows/ci.yml")["jobs"]
    assert jobs["canonical-file-shape"]["env"]["CANONICAL_FILE_SHAPE_CORE"].endswith(
        f"@{CORE_SHA}"
    )
    assert any(
        step.get("run") == f"uv run {command}"
        for job in jobs.values()
        for step in job.get("steps", [])
    )


def test_core_ratchet_accepts_unchanged_and_shrinking_but_refuses_growth() -> None:
    _guard_job()
    text = ALLOWLIST.read_text(encoding="utf-8")
    entries = _mapping(ALLOWLIST)["allowlisted_handlers"]
    extra = "omniclaude/nodes/node_planted_effect/handlers/handler_planted.py"
    request = {
        "base": text,
        "shrunk": yaml.safe_dump({"allowlisted_handlers": entries[:-1]}),
        "grown": yaml.safe_dump({"allowlisted_handlers": [*entries, {"path": extra}]}),
    }
    result = _core(
        "python",
        "-c",
        "import json, sys; "
        "from omnibase_core.handlers.handler_imperative_allowlist_ratchet import "
        "HandlerImperativeAllowlistRatchet; "
        "from omnibase_core.models.nodes.imperative_contract_guard."
        "model_allowlist_ratchet_input import ModelAllowlistRatchetInput; "
        "p=json.load(sys.stdin); h=HandlerImperativeAllowlistRatchet(); "
        "reports=[h.handle(ModelAllowlistRatchetInput(base_text=p['base'], "
        "head_text=p[k])) for k in ('base', 'shrunk', 'grown')]; "
        "print(json.dumps([dict(r.model_dump(), admitted=r.admitted) for r in reports]))",
        stdin=json.dumps(request),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    unchanged, shrunk, grown = json.loads(result.stdout)
    assert unchanged == {
        "added": [],
        "removed": [],
        "bootstrap": False,
        "admitted": True,
    }
    assert shrunk["admitted"] is True
    assert shrunk["removed"] == [RECORDED_FREESTANDING_ENTRIES[-1][0]]
    assert grown["admitted"] is False
    assert grown["bootstrap"] is False
    assert grown["added"] == [extra]


def test_core_matches_historical_findings_and_adds_only_the_live_plant(
    tmp_path: Path,
) -> None:
    _guard_job()  # Every AC's falsifier must also fail on the merge-base caller.
    root = tmp_path / "omniclaude"
    shutil.copytree(
        ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copyfile(ROOT / "pyproject.toml", root / "pyproject.toml")
    (root / ".github").mkdir()
    shutil.copyfile(ALLOWLIST, root / ALLOWLIST_PATH)
    # These are the historical reusable's scan arguments, with caller-owned input.
    args = (
        "check-imperative-contracts",
        "--repo-root",
        str(root),
        "--allowlist-path",
        ALLOWLIST_PATH,
        "--scan-freestanding",
        "--json",
    )
    clean = _core(*args)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    clean_report = json.loads(clean.stdout)[0]
    clean_findings = {key: clean_report[key] for key in FINDING_KEYS}
    digest = hashlib.sha256(
        json.dumps(clean_findings, sort_keys=True).encode()
    ).hexdigest()
    assert digest == RECORDED_OCC_FINDING_DIGEST
    assert clean_report["new_violation_count"] == 0

    handler = root / LIVE_HANDLER
    original = handler.read_text(encoding="utf-8")
    # The scanner reads this source. The planted request is never executed.
    planted_url = "http://" + ".".join(("10", "0", "0", "5")) + ":8080/planted"
    handler.write_text(
        original + f'\nimport httpx\nhttpx.get("{planted_url}")\n', encoding="utf-8"
    )
    planted = _core(*args)
    assert planted.returncode == 1, planted.stdout + planted.stderr
    planted_report = json.loads(planted.stdout)[0]
    assert planted_report["new_violation_count"] == 1
    (violation,) = planted_report["new_violations"]
    assert violation["handler_path"] == LIVE_HANDLER.removeprefix("src/")
    assert violation["reachability"] == "live"
    assert violation["undeclared_transports"] == ["HTTP"]
    assert violation["violations"] == ["undeclared_transport"]
    assert {
        key: planted_report[key] for key in FINDING_KEYS if key != "new_violations"
    } == {key: clean_findings[key] for key in FINDING_KEYS if key != "new_violations"}
