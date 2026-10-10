# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The PR ownership node reaches the verdicts the standalone guard reached (OMN-20685).

``tests/fixtures/pr_ownership_effect_golden.json`` was captured by running
``record(...)`` below against ``plugins/onex/hooks/lib/pr_ownership_guard.py`` as it
stood at omniclaude 05d66f702, before the guard moved into
``node_pr_ownership_guard_effect``. The node's process entry is driven with the
same cases, argv shape, environment and claims directory, and must return the same
exit codes, JSON verdicts and resulting claim files.

To re-record: check out the pre-move file from that revision into a scratch
directory beside its siblings (``session_id.py``, ``pr_claim_registry.py``,
``onex_state.py``), call ``record(argv_for_old(script), ...)`` and write
``{"recorded_from": ..., "cases": ...}`` over the fixture. Historical objects are
needed only for that one recording, never when these tests run.

Timestamps do not reach a verdict; the temporary directory and the repository root
are normalised out of every recorded value, nothing else is.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from plugins.onex.hooks.lib import pr_claim_registry

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[2]
HOOKS_LIB = ROOT / "plugins" / "onex" / "hooks" / "lib"
GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures/pr_ownership_effect_golden.json"
)
NODE_MODULE = (
    "omniclaude.nodes.node_pr_ownership_guard_effect.handlers.handler_pr_ownership_cli"
)

OWNER = "OmniNode-ai"
REPO = "omniclaude"
LANE = "lane-alpha"
PEER = "lane-beta"
SESSION = "sess-aaaaaaaaaaaaaaaaaaaa"
SESSION_LANE = "session:sess-aaaaaaaaaaa"

#: Env names the guard reads; every case starts without them.
_SCRUBBED = (
    "ONEX_LANE_ID",
    "ONEX_LANE",
    "ONEX_AGENT_NAME",
    "CLAUDE_AGENT_NAME",
    "CLAUDE_SUBAGENT_NAME",
    "OMNI_HOME",
    "ONEX_WORKTREES_ROOT",
    "OMNI_WORKTREES_DIR",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "ONEX_SESSION_ID",
    "SESSION_ID",
    "ONEX_RUN_ID",
    "ONEX_STATE_DIR",
    "PWD",
)


def pr(number: int, repo: str = REPO) -> str:
    return f"{OWNER.lower()}/{repo}#{number}"


def close(number: int, extra: str = "") -> str:
    return f"gh pr close {number} --repo {OWNER}/{REPO}{extra}"


class ModelClaimSpec(BaseModel):
    """One claim file to seed, with the fields a case varies."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    lane: str | None
    run: str | None
    session: str | None
    stale: bool
    raw: str | None
    omit_lane: bool
    extra: dict[str, object]


class ModelCase(BaseModel):
    """One recorded scenario: the commands to run in order and the world around them."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    steps: list[tuple[str, dict[str, str]]]
    env: dict[str, str]
    claims: list[ModelClaimSpec]
    default_repo: str | None
    worktree: str | None


def claim(
    key: str,
    *,
    lane: str | None = LANE,
    run: str | None = "run-1",
    session: str | None = None,
    stale: bool = False,
    raw: str | None = None,
    omit_lane: bool = False,
    extra: dict[str, object] | None = None,
) -> ModelClaimSpec:
    return ModelClaimSpec(
        key=key,
        lane=lane,
        run=run,
        session=session,
        stale=stale,
        raw=raw,
        omit_lane=omit_lane,
        extra=extra or {},
    )


def case(
    command: str | list[tuple[str, dict[str, str]]],
    *,
    env: dict[str, str] | None = None,
    claims: list[ModelClaimSpec] | None = None,
    default_repo: str | None = None,
    worktree: str | None = None,
) -> ModelCase:
    steps = [(command, {})] if isinstance(command, str) else list(command)
    return ModelCase(
        steps=steps,
        env=env or {},
        claims=claims or [],
        default_repo=default_repo,
        worktree=worktree,
    )


_LANE_ENV = {"ONEX_LANE_ID": LANE, "ONEX_RUN_ID": "run-1"}
_SESSION_ENV = {"CLAUDE_CODE_SESSION_ID": SESSION, "ONEX_RUN_ID": "run-s"}
_API_CLOSE = f"gh api -X PATCH repos/{OWNER}/{REPO}/pulls/5 -f state=closed"
_WORKFLOW = f"gh workflow run ci.yml --repo {OWNER}/{REPO} --ref main"
_CANCEL = f"gh run cancel 777 --repo {OWNER}/{REPO}"

CASES: dict[str, ModelCase] = {
    # ---- commands the guard does not govern
    "pr_view_is_not_a_mutation": case(f"gh pr view 5 --repo {OWNER}/{REPO}"),
    "api_get_is_not_a_mutation": case(f"gh api repos/{OWNER}/{REPO}/pulls/5"),
    "api_patch_title_is_not_a_close": case(
        f"gh api -X PATCH repos/{OWNER}/{REPO}/pulls/5 -f title=x", env=_LANE_ENV
    ),
    "quoted_verb_is_not_a_command": case(
        f"printf 'gh pr close 5 --repo {OWNER}/{REPO}'"
    ),
    "quoted_head_is_not_gh": case(f"'gh' pr close 5 --repo {OWNER}/{REPO}"),
    "commit_message_naming_a_close": case(
        f"git commit -m 'run gh pr close 5 --repo {OWNER}/{REPO}'"
    ),
    "empty_command": case(""),
    "too_few_words": case("gh pr"),
    # ---- ownership class, claim states
    "close_unclaimed": case(close(5), env=_LANE_ENV),
    "close_owned_by_self": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), lane=LANE, run="run-1")]
    ),
    "close_owned_by_peer": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), lane=PEER)]
    ),
    "close_expired_claim": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), stale=True)]
    ),
    "close_claim_json_garbage": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), raw="{not json")]
    ),
    "close_claim_json_list": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), raw="[1, 2]")]
    ),
    "close_claim_without_lane": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), omit_lane=True)]
    ),
    "close_claim_null_lane": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), lane=None)]
    ),
    "close_claim_blank_lane": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), lane="   ")]
    ),
    "close_claim_run_not_a_string": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), extra={"claimed_by_run": 7})]
    ),
    "close_claim_blank_session": case(
        close(5),
        env=_LANE_ENV,
        claims=[claim(pr(5), extra={"claimed_by_session": " "})],
    ),
    "close_claim_bad_timestamp": case(
        close(5),
        env=_LANE_ENV,
        claims=[claim(pr(5), extra={"claimed_at": "yesterday-ish"})],
    ),
    "close_same_lane_other_run": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), run="run-other")]
    ),
    "close_claim_session_not_ours": case(
        close(5),
        env=_LANE_ENV,
        claims=[claim(pr(5), session="sess-claim-holder")],
    ),
    "close_expired_peer_claim_does_not_block_owner_rule": case(
        close(5), env=_LANE_ENV, claims=[claim(pr(5), lane=PEER, stale=True)]
    ),
    # ---- lane and run identity
    "no_identity_at_all": case(close(5), claims=[claim(pr(5))]),
    "lane_from_onex_lane": case(
        close(5),
        env={"ONEX_LANE": LANE, "ONEX_RUN_ID": "run-1"},
        claims=[claim(pr(5))],
    ),
    "lane_from_agent_name_is_sanitised": case(
        close(5),
        env={"CLAUDE_AGENT_NAME": "lane alpha!", "ONEX_RUN_ID": "run-1"},
        claims=[claim(pr(5), lane="lane-alpha-")],
    ),
    "lane_env_precedence": case(
        close(5),
        env={"ONEX_LANE_ID": LANE, "ONEX_LANE": PEER, "ONEX_RUN_ID": "run-1"},
        claims=[claim(pr(5))],
    ),
    "session_fallback_owns_its_claim": case(
        close(5),
        env=_SESSION_ENV,
        claims=[claim(pr(5), lane=SESSION_LANE, run="run-s", session=SESSION)],
    ),
    "session_fallback_wrong_run": case(
        close(5),
        env=_SESSION_ENV,
        claims=[claim(pr(5), lane=SESSION_LANE, run="run-t", session=SESSION)],
    ),
    "session_fallback_shared_prefix_other_session": case(
        close(5),
        env=_SESSION_ENV,
        claims=[
            claim(pr(5), lane=SESSION_LANE, run="run-s", session=SESSION + "-other")
        ],
    ),
    "session_fallback_claim_without_session": case(
        close(5),
        env=_SESSION_ENV,
        claims=[claim(pr(5), lane=SESSION_LANE, run="run-s")],
    ),
    "session_fallback_resolves_a_named_claim": case(
        close(5),
        env=_SESSION_ENV,
        claims=[claim(pr(5), lane=PEER, run="run-s", session=SESSION)],
    ),
    "run_falls_back_to_session": case(
        close(5),
        env={"ONEX_LANE_ID": LANE, "CLAUDE_CODE_SESSION_ID": "run-1"},
        claims=[claim(pr(5), run="run-1", session="run-1")],
    ),
    "worktree_lane_owned": case(
        close(5),
        worktree="OMN-9/repo",
        env={"OMNI_HOME": "{registry_root}"},
        claims=[claim(pr(5), lane="wt:OMN-9/repo", run="wt:OMN-9/repo")],
    ),
    "worktree_lane_other_run": case(
        close(5),
        worktree="OMN-9/repo",
        env={"OMNI_HOME": "{registry_root}"},
        claims=[claim(pr(5), lane="wt:OMN-9/repo", run="run-1")],
    ),
    "worktree_root_override_single_part": case(
        close(5),
        worktree="OMN-9",
        env={"ONEX_WORKTREES_ROOT": "{registry_root}/omni_worktrees"},
        claims=[claim(pr(5), lane="wt:OMN-9", run="wt:OMN-9")],
    ),
    "worktree_dir_override": case(
        close(5),
        worktree="OMN-9/repo/sub",
        env={"OMNI_WORKTREES_DIR": "{registry_root}/omni_worktrees"},
        claims=[claim(pr(5), lane="wt:OMN-9/repo", run="wt:OMN-9/repo")],
    ),
    "worktree_outside_roots": case(
        close(5), worktree=None, env={"OMNI_HOME": "{registry_root}"}
    ),
    # ---- target parsing
    "close_by_url": case(
        f"gh pr close https://github.com/{OWNER}/{REPO}/pull/5",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "close_short_flag_and_trailing_slash": case(
        f"gh pr close -R {OWNER}/{REPO} https://github.com/{OWNER}/{REPO}/pull/5/",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "close_flag_value_is_not_the_number": case(
        f"gh pr close --comment 99 --repo {OWNER}/{REPO} 5",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "close_without_number": case(f"gh pr close --repo {OWNER}/{REPO}", env=_LANE_ENV),
    "close_without_repo": case("gh pr close 5", env=_LANE_ENV),
    "close_default_repo_from_url": case(
        "gh pr close 5",
        env=_LANE_ENV,
        default_repo=f"https://github.com/{OWNER}/{REPO}.git",
        claims=[claim(pr(5))],
    ),
    "close_default_repo_unparseable": case(
        "gh pr close 5", env=_LANE_ENV, default_repo="git@github.com:o/r.git"
    ),
    "reopen_is_governed": case(f"gh pr reopen 5 --repo {OWNER}/{REPO}", env=_LANE_ENV),
    "api_close_owned": case(_API_CLOSE, env=_LANE_ENV, claims=[claim(pr(5))]),
    "api_close_unclaimed": case(_API_CLOSE, env=_LANE_ENV),
    "api_close_method_equals_form": case(
        f"gh api --method=PATCH repos/{OWNER}/{REPO}/pulls/5 -f state='closed'",
        env=_LANE_ENV,
    ),
    "api_close_with_variable_repo_and_default": case(
        "gh api -X PATCH repos/$ORG/$REPO/pulls/5 -f state=closed",
        env=_LANE_ENV,
        default_repo=f"{OWNER}/{REPO}",
        claims=[claim(pr(5))],
    ),
    "api_close_with_variable_repo_no_default": case(
        "gh api -X PATCH repos/$ORG/$REPO/pulls/5 -f state=closed", env=_LANE_ENV
    ),
    "api_post_without_pulls_path": case(
        f"gh api -X POST repos/{OWNER}/{REPO}/issues -f state=closed", env=_LANE_ENV
    ),
    # ---- compound and prefixed commands
    "env_prefix": case(
        f"env FOO=1 gh pr close 5 --repo {OWNER}/{REPO}",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "assignment_and_nohup_prefix": case(
        f"FOO=1 nohup time gh pr close 5 --repo {OWNER}/{REPO}",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "compound_one_owned_one_not": case(
        f"cd /tmp && {close(5)} ; {close(6)}",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "compound_all_owned": case(
        f"{close(5)} && {close(6)} || {close(7)}",
        env=_LANE_ENV,
        claims=[claim(pr(5)), claim(pr(6)), claim(pr(7))],
    ),
    "newline_separated": case(
        f"echo go\n{close(5)}\n{close(6)}",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "pipe_separated": case(
        f"{close(5)} | tee out.log", env=_LANE_ENV, claims=[claim(pr(5))]
    ),
    "quoted_separator_stays_in_the_word": case(
        f"gh pr close 5 --repo {OWNER}/{REPO} --comment 'done && gh pr close 9'",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "double_quoted_escape": case(
        f'gh pr close 5 --repo {OWNER}/{REPO} --comment "say \\"hi\\""',
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "backslash_newline_continuation": case(
        f"gh pr close 5 \\\n  --repo {OWNER}/{REPO}",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    "unterminated_quote": case(
        f"gh pr close 5 --repo {OWNER}/{REPO} --comment 'oops",
        env=_LANE_ENV,
        claims=[claim(pr(5))],
    ),
    # ---- exclusivity class
    "workflow_first_writer_records_a_claim": case(_WORKFLOW, env=_LANE_ENV),
    "workflow_second_lane_is_refused": case(
        [(_WORKFLOW, {}), (_WORKFLOW, {"ONEX_LANE_ID": PEER})], env=_LANE_ENV
    ),
    "workflow_same_lane_again_is_allowed": case(
        [(_WORKFLOW, {}), (_WORKFLOW, {})], env=_LANE_ENV
    ),
    "workflow_other_ref_is_another_key": case(
        [(_WORKFLOW, {}), (_WORKFLOW + "x", {"ONEX_LANE_ID": PEER})], env=_LANE_ENV
    ),
    "workflow_without_ref_uses_default": case(
        f"gh workflow run ci.yml --repo {OWNER}/{REPO}", env=_LANE_ENV
    ),
    "workflow_ref_short_flag": case(
        f"gh workflow run ci.yml -R {OWNER}/{REPO} -r dev", env=_LANE_ENV
    ),
    "workflow_expired_peer_claim_is_reaped": case(
        _WORKFLOW,
        env=_LANE_ENV,
        claims=[
            claim(
                f"dispatch:{OWNER.lower()}/{REPO}#ci.yml@main",
                lane=PEER,
                stale=True,
            )
        ],
    ),
    "workflow_without_name": case(
        f"gh workflow run --repo {OWNER}/{REPO}", env=_LANE_ENV
    ),
    "workflow_without_repo": case("gh workflow run ci.yml", env=_LANE_ENV),
    "workflow_default_repo": case(
        "gh workflow run ci.yml", env=_LANE_ENV, default_repo=f"{OWNER}/{REPO}"
    ),
    "workflow_no_identity": case(_WORKFLOW),
    "run_cancel_first_writer": case(_CANCEL, env=_LANE_ENV),
    "run_cancel_peer_holds": case(
        _CANCEL,
        env=_LANE_ENV,
        claims=[claim(f"run:{OWNER.lower()}/{REPO}#777", lane=PEER)],
    ),
    "run_cancel_without_id": case(
        f"gh run cancel --repo {OWNER}/{REPO}", env=_LANE_ENV
    ),
    "run_cancel_unclaimed_by_session_identity": case(_CANCEL, env=_SESSION_ENV),
    "blocked_command_records_no_claims": case(
        f"{_WORKFLOW} && {close(5)}", env=_LANE_ENV
    ),
    "allowed_compound_records_the_exclusive_claim": case(
        f"{_WORKFLOW} && {close(5)}", env=_LANE_ENV, claims=[claim(pr(5))]
    ),
}


def _stamp(*, stale: bool) -> str:
    moment = datetime.now(UTC) - (timedelta(hours=3) if stale else timedelta())
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_claims(claims_dir: Path, claims: list[ModelClaimSpec]) -> None:
    claims_dir.mkdir(parents=True, exist_ok=True)
    for spec in claims:
        path = claims_dir / f"{pr_claim_registry.filesystem_key(spec.key)}.json"
        if spec.raw is not None:
            path.write_text(spec.raw)
            continue
        stamp = _stamp(stale=spec.stale)
        data: dict[str, object] = {
            "pr_key": spec.key,
            "claimed_at": stamp,
            "last_heartbeat_at": stamp,
            "claimed_by_host": "host-1",
            "claimed_by_instance_id": "inst-1",
            "action": "close",
        }
        if not spec.omit_lane:
            data["lane_id"] = spec.lane
        if spec.run is not None:
            data["claimed_by_run"] = spec.run
        if spec.session is not None:
            data["claimed_by_session"] = spec.session
        data.update(spec.extra)
        path.write_text(json.dumps(data))


_TS = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b")


def _norm(text: str, tmp: Path) -> str:
    return _TS.sub("<ts>", text.replace(str(tmp), "<tmp>").replace(str(ROOT), "<repo>"))


def _claim_files(claims_dir: Path, tmp: Path) -> dict[str, object]:
    found: dict[str, object] = {}
    if not claims_dir.is_dir():
        return found
    for path in sorted(claims_dir.iterdir()):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            found[path.name] = {"raw": _norm(path.read_text(), tmp)}
            continue
        if isinstance(data, dict):
            found[path.name] = {
                name: data.get(name)
                for name in (
                    "lane_id",
                    "claimed_by_run",
                    "claimed_by_session",
                    "action",
                    "pr_key",
                )
            }
        else:
            found[path.name] = {"raw": data}
    return found


def argv_for_old(script: Path) -> list[str]:
    return [sys.executable, str(script)]


def argv_for_node() -> list[str]:
    return [sys.executable, "-P", "-m", NODE_MODULE, "--hooks-lib", str(HOOKS_LIB)]


def record(argv: list[str], spec: ModelCase, tmp: Path) -> dict[str, object]:
    """Run one case's steps through ``argv`` and return everything observable."""
    registry_root = tmp / "registry_root"
    state = tmp / "state"
    cwd = tmp / "plain"
    cwd.mkdir()
    if spec.worktree:
        cwd = registry_root / "omni_worktrees" / spec.worktree
        cwd.mkdir(parents=True)
    else:
        registry_root.mkdir()
    claims_dir = state / "pr-queue" / "claims"
    _write_claims(claims_dir, spec.claims)

    steps: list[dict[str, object]] = []
    for index, (command, step_env) in enumerate(spec.steps):
        env = {
            name: value
            for name, value in os.environ.items()
            if name not in _SCRUBBED and not name.startswith(("ONEX_", "CLAUDE_"))
        }
        env["ONEX_STATE_DIR"] = str(state)
        env["PWD"] = str(cwd)
        for name, value in {**spec.env, **step_env}.items():
            env[name] = value.replace("{registry_root}", str(registry_root))
        command_file = tmp / f"command-{index}.txt"
        command_file.write_text(command)
        call = [*argv, "--command-file", str(command_file), "--cwd", str(cwd)]
        if spec.default_repo:
            call += ["--default-repo", spec.default_repo]
        done = subprocess.run(
            call, env=env, cwd=cwd, capture_output=True, text=True, check=False
        )
        stdout = _norm(done.stdout, tmp)
        try:
            parsed: object = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = stdout
        steps.append(
            {
                "rc": done.returncode,
                "stdout": parsed,
                "stderr": _norm(done.stderr, tmp),
            }
        )
    return {"steps": steps, "claims": _claim_files(claims_dir, tmp)}


def test_golden_covers_every_case() -> None:
    golden = json.loads(GOLDEN.read_text())["cases"]
    assert set(golden) == set(CASES)


def test_golden_pins_each_verdict_class() -> None:
    """The recording is not a table of allows: every reason code is in it."""
    golden = json.loads(GOLDEN.read_text())["cases"]
    seen = {
        decision["reason_code"]
        for observed in golden.values()
        for step in observed["steps"]
        if isinstance(step["stdout"], dict)
        for decision in step["stdout"]["decisions"]
    }
    assert seen >= {
        "OWNED_BY_SELF",
        "CROSS_LANE",
        "CROSS_RUN",
        "UNCLAIMED",
        "FIRST_WRITER",
        "INDETERMINATE_LANE",
        "INDETERMINATE_TARGET",
        "INDETERMINATE_CLAIM",
    }
    codes = {step["rc"] for observed in golden.values() for step in observed["steps"]}
    assert codes == {0, 3}


@pytest.mark.parametrize("name", sorted(CASES))
def test_node_entry_matches_the_recorded_guard(name: str, tmp_path: Path) -> None:
    golden = json.loads(GOLDEN.read_text())["cases"][name]
    assert record(argv_for_node(), CASES[name], tmp_path) == golden


def _broken_registry_lib(tmp: Path) -> Path:
    lib = tmp / "lib"
    lib.mkdir()
    for sibling in HOOKS_LIB.glob("*.py"):
        (lib / sibling.name).write_bytes(sibling.read_bytes())
    (lib / "pr_claim_registry.py").write_text(
        'raise RuntimeError("registry deliberately broken")\n'
    )
    return lib


def _entry(lib: Path, command: str, tmp: Path) -> subprocess.CompletedProcess[str]:
    command_file = tmp / "command.txt"
    command_file.write_text(command)
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ONEX_", "CLAUDE_"))
    }
    env.update(ONEX_STATE_DIR=str(tmp / "state"), ONEX_LANE_ID=LANE)
    return subprocess.run(
        [
            sys.executable,
            "-P",
            "-m",
            NODE_MODULE,
            "--hooks-lib",
            str(lib),
            "--command-file",
            str(command_file),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "command",
    [
        f"gh api repos/{OWNER}/{REPO}",
        f"printf 'gh pr close 5 --repo {OWNER}/{REPO}'",
        f"gh pr view 5 --repo {OWNER}/{REPO}",
    ],
)
def test_a_command_with_no_guarded_mutation_never_reaches_the_registry(
    command: str, tmp_path: Path
) -> None:
    """The registry is imported only after a mutation parsed (OMN-16983)."""
    done = _entry(_broken_registry_lib(tmp_path), command, tmp_path)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == {"blocked": False, "decisions": [], "reason": ""}


@pytest.mark.parametrize("command", [close(5), _WORKFLOW])
def test_a_guarded_mutation_fails_closed_when_the_registry_is_unusable(
    command: str, tmp_path: Path
) -> None:
    """Control for the test above: the same broken library refuses a real mutation."""
    done = _entry(_broken_registry_lib(tmp_path), command, tmp_path)
    assert done.returncode == 1
    assert json.loads(done.stderr.splitlines()[-1])["blocked"] is True


def test_the_claim_cli_lane_resolver_needs_only_the_standard_library() -> None:
    """The CLI every refusal names runs under any python3, so it cannot import omniclaude."""
    lane_file = (
        ROOT
        / "src/omniclaude/nodes/node_pr_ownership_guard_effect/handlers"
        / "handler_pr_ownership_lane.py"
    )
    probe = (
        "import importlib.util, sys;"
        "spec = importlib.util.spec_from_file_location('lane', sys.argv[1]);"
        "module = importlib.util.module_from_spec(spec);"
        "spec.loader.exec_module(module);"
        "print(module.resolve_lane_id(env={'ONEX_LANE_ID': 'x y'}));"
        "print(any(name.split('.')[0] == 'omniclaude' for name in sys.modules))"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-S", "-c", probe, str(lane_file)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.split() == ["x-y", "False"]


@pytest.mark.parametrize(
    ("command", "imports_pydantic"),
    [
        (f"gh api repos/{OWNER}/{REPO}", False),
        (close(5), True),
    ],
)
def test_only_a_guarded_mutation_pays_for_the_models(
    command: str, imports_pydantic: bool, tmp_path: Path
) -> None:
    """Read-only ``gh api`` traffic is the common case; it must stay cheap (OMN-20685)."""
    command_file = tmp_path / "command.txt"
    command_file.write_text(command)
    probe = (
        "import sys;"
        f"from {NODE_MODULE} import main;"
        f"main(['--hooks-lib', {str(HOOKS_LIB)!r}, '--command-file', {str(command_file)!r}]);"
        "sys.stderr.write(str('pydantic' in sys.modules))"
    )
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("ONEX_", "CLAUDE_"))
    }
    env.update(ONEX_STATE_DIR=str(tmp_path / "state"), ONEX_LANE_ID=LANE)
    done = subprocess.run(
        [sys.executable, "-P", "-c", probe],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stderr.endswith(str(imports_pydantic)), done.stderr
