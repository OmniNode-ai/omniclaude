# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""OMN-18777: a new advisory job is refused unless a ticket annotation names it.

Epic OMN-18775 counted 64 real `continue-on-error: true` settings across six
repositories, 12 of them making a whole job advisory, with nothing
distinguishing the deliberate ones from drift. It also found verification jobs
-- `fresh-deploy-fitness` is the named instance -- that run on every pull
request, appear in neither `required_status_checks` nor the repo's
`EXPECTED_EXTERNAL_CONTEXTS`, and therefore cannot fail anything.

Every test here drives the real parser over a real workflow tree on disk, and
the suite opens with a positive control: a tree that MUST fail. A gate suite
whose fixtures all pass proves only that the gate is silent (rule 16 -- an
empty result is not evidence of absence).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "advisory_job_gate.py"
BASELINE = REPO_ROOT / "config" / "advisory_job_baseline.yaml"
GATE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "advisory-job-gate.yml"
REUSABLE_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "advisory-job-gate-reusable.yml"
)

pytestmark = pytest.mark.unit


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("advisory_job_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["advisory_job_gate"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


@contextmanager
def _env(**values: str | None) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _repo(tmp_path: Path, workflows: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    for name, text in workflows.items():
        (root / ".github" / "workflows" / name).write_text(text, encoding="utf-8")
    return root


def _baseline(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "baseline.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _contexts(tmp_path: Path, contexts: list[str]) -> Path:
    path = tmp_path / "contexts.json"
    path.write_text(json.dumps(contexts), encoding="utf-8")
    return path


def _run(
    root: Path,
    *,
    baseline: Path | None = None,
    contexts: Path | None = None,
    repo: str = "OmniNode-ai/fixture",
    extra: list[str] | None = None,
) -> int:
    argv = ["--repo-root", str(root), "--repo", repo]
    if baseline is not None:
        argv += ["--baseline", str(baseline)]
    if contexts is not None:
        argv += ["--required-contexts-json", str(contexts)]
    argv += extra or []
    with _env(GITHUB_ACTIONS=None):
        return int(gate.main(argv))


EMPTY_BASELINE: dict[str, Any] = {
    "version": 1,
    "repos": {"OmniNode-ai/fixture": {"advisory": [], "verification_jobs": []}},
}

# A workflow whose only job is enforced and carries nothing advisory. Every
# negative control below starts from this text so a failure can only come from
# the line the test added.
CLEAN = """\
name: CI
on:
  pull_request:
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
"""

# The positive control, quoted from the shape epic OMN-18775 found: a job-level
# advisory setting with nothing naming it.
ADVISORY_JOB = """\
name: CI
on:
  pull_request:
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
  fresh-deploy-fitness:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - run: python scripts/check_fitness.py
"""


class TestPositiveControl:
    """The suite's own falsifier: a tree that must fail, and a tree that must not."""

    def test_the_unannotated_advisory_tree_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"ci.yml": ADVISORY_JOB})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
        )
        assert code == 1
        assert "continue-on-error" in capsys.readouterr().out

    def test_the_clean_tree_passes(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"ci.yml": CLEAN})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests"]),
            )
            == 0
        )


class TestAC1UnannotatedAdvisoryFails:
    """AC1 -- falsifier: adding one to a fixture repo produces a green run."""

    def test_names_the_file_and_the_line(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"ci.yml": ADVISORY_JOB})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
        )
        out = capsys.readouterr().out
        assert code == 1
        assert ".github/workflows/ci.yml:11" in out

    def test_a_step_level_setting_is_refused_too(self, tmp_path: Path) -> None:
        text = """\
name: CI
on:
  pull_request:
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
        continue-on-error: true
"""
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests"]),
            )
            == 1
        )

    def test_continue_on_error_false_is_not_a_finding(self, tmp_path: Path) -> None:
        text = CLEAN.replace(
            "      - run: pytest -q\n",
            "      - run: pytest -q\n        continue-on-error: false\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests"]),
            )
            == 0
        )


class TestAC2AnnotationPasses:
    """AC2 -- falsifier: an annotated line still fails."""

    def test_same_line_annotation_passes(self, tmp_path: Path) -> None:
        text = ADVISORY_JOB.replace(
            "    continue-on-error: true\n",
            "    continue-on-error: true  # advisory-ok: OMN-18777 publisher is "
            "deliberately non-blocking\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
            )
            == 0
        )

    def test_preceding_comment_line_annotation_passes(self, tmp_path: Path) -> None:
        text = ADVISORY_JOB.replace(
            "    continue-on-error: true\n",
            "    # advisory-ok: OMN-18777 publisher is deliberately non-blocking\n"
            "    continue-on-error: true\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
            )
            == 0
        )

    def test_an_annotation_two_lines_above_does_not_reach(self, tmp_path: Path) -> None:
        text = ADVISORY_JOB.replace(
            "    continue-on-error: true\n",
            "    # advisory-ok: OMN-18777 deliberate\n"
            "    # (a second comment line pushes the annotation out of reach)\n"
            "    continue-on-error: true\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
            )
            == 1
        )


class TestAC3AnnotationNeedsARealTicket:
    """AC3 -- falsifier: `# advisory-ok: because it is fine` is accepted."""

    @pytest.mark.parametrize(
        "annotation",
        [
            "# advisory-ok: because it is fine",
            "# advisory-ok: OMN- missing digits",
            "# advisory-ok:",
            "# advisory-ok: OMN-18777",
        ],
        ids=["free-text", "no-digits", "empty", "ticket-with-no-reason"],
    )
    def test_rejected(self, tmp_path: Path, annotation: str) -> None:
        text = ADVISORY_JOB.replace(
            "    continue-on-error: true\n",
            f"    continue-on-error: true  {annotation}\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
            )
            == 1
        )

    def test_a_bare_marker_names_itself(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A marker split across lines reads as absent; say so rather than
        report a bare advisory setting for an incomprehensible reason."""
        text = ADVISORY_JOB.replace(
            "    continue-on-error: true\n",
            "    continue-on-error: true  # advisory-ok:\n",
        )
        root = _repo(tmp_path, {"ci.yml": text})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
        )
        assert code == 1
        assert "MALFORMED_ANNOTATION" in capsys.readouterr().out


class TestAC4BaselineNamesEveryLine:
    """AC4 -- falsifier: a baseline that names no individual line."""

    def test_a_baselined_occurrence_passes(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"ci.yml": ADVISORY_JOB})
        baseline = _baseline(
            tmp_path,
            {
                "version": 1,
                "repos": {
                    "OmniNode-ai/fixture": {
                        "advisory": [
                            {
                                "path": ".github/workflows/ci.yml",
                                "line": 11,
                                "key": ".github/workflows/ci.yml::fresh-deploy-fitness::JOB",
                                "note": "pre-existing at the OMN-18777 census",
                            }
                        ],
                        "verification_jobs": [],
                    }
                },
            },
        )
        assert (
            _run(
                root,
                baseline=baseline,
                contexts=_contexts(tmp_path, ["unit-tests", "fresh-deploy-fitness"]),
            )
            == 0
        )

    def test_a_second_occurrence_in_a_baselined_file_still_fails(
        self, tmp_path: Path
    ) -> None:
        """The grandfather is per line, not per file -- a date cutoff or a file
        allowlist would wave the new one through."""
        text = (
            ADVISORY_JOB
            + """\
  extra-advisory:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - run: echo hi
"""
        )
        root = _repo(tmp_path, {"ci.yml": text})
        baseline = _baseline(
            tmp_path,
            {
                "version": 1,
                "repos": {
                    "OmniNode-ai/fixture": {
                        "advisory": [
                            {
                                "path": ".github/workflows/ci.yml",
                                "line": 11,
                                "key": ".github/workflows/ci.yml::fresh-deploy-fitness::JOB",
                            }
                        ],
                        "verification_jobs": [],
                    }
                },
            },
        )
        assert (
            _run(
                root,
                baseline=baseline,
                contexts=_contexts(
                    tmp_path,
                    ["unit-tests", "fresh-deploy-fitness", "extra-advisory"],
                ),
            )
            == 1
        )

    def test_the_committed_baseline_names_a_path_and_an_integer_line_for_every_entry(
        self,
    ) -> None:
        payload = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
        entries = [
            entry
            for repo in payload["repos"].values()
            for entry in repo.get("advisory", [])
        ]
        assert entries, "a baseline with no entries grandfathers nothing"
        for entry in entries:
            assert isinstance(entry["line"], int)
            assert entry["path"].startswith(".github/workflows/")
            assert entry["key"].startswith(entry["path"] + "::")

    def test_the_committed_baseline_covers_the_six_census_repos(self) -> None:
        payload = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
        assert {slug.split("/")[-1] for slug in payload["repos"]} == {
            "omnibase_core",
            "omnibase_infra",
            "omnimarket",
            "omniclaude",
            "omninode_infra",
            "onex_change_control",
        }

    def test_the_committed_baseline_carries_the_sixty_four_census_settings(
        self,
    ) -> None:
        """The census in OMN-18775 counted 64. A baseline that silently carried
        fewer would leave the remainder failing every caller's CI, and one that
        carried more would be grandfathering something nobody counted."""
        payload = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
        per_repo = {
            slug.split("/")[-1]: len(repo.get("advisory", []))
            for slug, repo in payload["repos"].items()
        }
        assert per_repo == {
            "omnibase_core": 5,
            "omnibase_infra": 28,
            "omnimarket": 9,
            "omniclaude": 4,
            "omninode_infra": 11,
            "onex_change_control": 7,
        }
        assert sum(per_repo.values()) == 64


class TestAC5UnenforcedVerificationJobFails:
    """AC5 -- falsifier: adding one reproducing the fresh-deploy-fitness shape
    produces a green run."""

    FITNESS = """\
name: Fresh Deploy Fitness
on:
  pull_request:
jobs:
  fresh-deploy-fitness:
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/validate_fresh_deploy_fitness.py
"""

    def test_a_verification_job_in_neither_surface_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"fresh-deploy-fitness.yml": self.FITNESS})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, ["unit-tests"]),
        )
        assert code == 1
        assert "UNENFORCED_VERIFICATION_JOB" in capsys.readouterr().out

    def test_the_same_job_in_required_status_checks_passes(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path, {"fresh-deploy-fitness.yml": self.FITNESS})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["fresh-deploy-fitness"]),
            )
            == 0
        )

    def test_the_same_job_in_expected_external_contexts_passes(
        self, tmp_path: Path
    ) -> None:
        """The umbrella surface: on omnibase_infra and omnimarket a context is
        enforced by the CI-summary constant, with no branch-protection signal."""
        root = _repo(tmp_path, {"fresh-deploy-fitness.yml": self.FITNESS})
        (root / "scripts" / "ci").mkdir(parents=True)
        (root / "scripts" / "ci" / "ci_summary_gate.py").write_text(
            'EXPECTED_EXTERNAL_CONTEXTS = ("fresh-deploy-fitness", "deploy-gate / deploy-gate")\n',
            encoding="utf-8",
        )
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, []),
            )
            == 0
        )

    def test_an_annotated_verification_job_passes(self, tmp_path: Path) -> None:
        text = self.FITNESS.replace(
            "  fresh-deploy-fitness:\n",
            "  # advisory-ok: OMN-18777 notification only, never a verdict\n"
            "  fresh-deploy-fitness:\n",
        )
        root = _repo(tmp_path, {"fresh-deploy-fitness.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, []),
            )
            == 0
        )

    def test_a_job_that_no_pull_request_can_reach_is_out_of_scope(
        self, tmp_path: Path
    ) -> None:
        """A scheduled or release-only job can never be a required context, so
        refusing it for being absent from one would be a false refusal."""
        text = self.FITNESS.replace(
            "on:\n  pull_request:\n", "on:\n  schedule:\n    - cron: '0 6 * * *'\n"
        )
        root = _repo(tmp_path, {"nightly.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, []),
            )
            == 0
        )

    def test_a_non_verification_job_is_out_of_scope(self, tmp_path: Path) -> None:
        text = """\
name: Notify
on:
  pull_request:
jobs:
  post-slack-message:
    runs-on: ubuntu-latest
    steps:
      - run: curl -X POST "$SLACK_WEBHOOK"
"""
        root = _repo(tmp_path, {"notify.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, []),
            )
            == 0
        )

    def test_a_baselined_verification_job_passes(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"fresh-deploy-fitness.yml": self.FITNESS})
        baseline = _baseline(
            tmp_path,
            {
                "version": 1,
                "repos": {
                    "OmniNode-ai/fixture": {
                        "advisory": [],
                        "verification_jobs": [
                            {
                                "path": ".github/workflows/fresh-deploy-fitness.yml",
                                "line": 5,
                                "key": ".github/workflows/fresh-deploy-fitness.yml::fresh-deploy-fitness",
                            }
                        ],
                    }
                },
            },
        )
        assert _run(root, baseline=baseline, contexts=_contexts(tmp_path, [])) == 0


class TestEnforcementSurfaceResolution:
    """A recorded context that is not live is a fiction; a live context that is
    not recorded is more enforcement than we wrote down, which is safe."""

    def test_a_reusable_caller_job_matches_its_two_segment_context(
        self, tmp_path: Path
    ) -> None:
        text = """\
name: Deploy Gate
on:
  pull_request:
jobs:
  deploy-gate:
    uses: OmniNode-ai/omniclaude/.github/workflows/deploy-gate-reusable.yml@abc
"""
        root = _repo(tmp_path, {"deploy-gate.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["deploy-gate / deploy-gate"]),
            )
            == 0
        )

    def test_a_job_name_that_differs_from_its_id_matches_on_the_name(
        self, tmp_path: Path
    ) -> None:
        text = """\
name: CI
on:
  pull_request:
jobs:
  run-the-validator:
    name: Contract Validation
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/validate_contracts.py
"""
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["Contract Validation"]),
            )
            == 0
        )

    def test_a_missing_required_contexts_file_is_a_refusal_not_a_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"ci.yml": CLEAN})
        code = _run(root, baseline=_baseline(tmp_path, EMPTY_BASELINE))
        assert code == 2
        assert "THE GATE DID NOT RUN" in capsys.readouterr().err

    def test_an_unreadable_workflow_is_a_refusal_not_a_pass(
        self, tmp_path: Path
    ) -> None:
        root = _repo(tmp_path, {"broken.yml": "jobs: [this: is: not: a: map\n"})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, []),
        )
        assert code == 2


class TestAC6TheGateIsItselfRequired:
    """AC6 -- falsifier: the gate's own workflow carries `continue-on-error`,
    which would be self-refuting."""

    def test_neither_gate_workflow_is_advisory(self) -> None:
        for path in (GATE_WORKFLOW, REUSABLE_WORKFLOW):
            text = path.read_text(encoding="utf-8")
            assert "continue-on-error" not in text, path.name

    def test_the_gate_scans_its_own_repository_clean(self, tmp_path: Path) -> None:
        """omniclaude runs the gate over itself. If this repository's own tree
        does not pass, the gate is being landed in a state it refuses."""
        contexts = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))["repos"][
            "OmniNode-ai/omniclaude"
        ].get("recorded_contexts", [])
        path = tmp_path / "contexts.json"
        path.write_text(json.dumps(contexts), encoding="utf-8")
        with _env(GITHUB_ACTIONS=None):
            code = gate.main(
                [
                    "--repo-root",
                    str(REPO_ROOT),
                    "--repo",
                    "OmniNode-ai/omniclaude",
                    "--baseline",
                    str(BASELINE),
                    "--required-contexts-json",
                    str(path),
                ]
            )
        assert code == 0


class TestAC7NoSkipNoForceNoOverride:
    """AC7 -- falsifier: the argument parser or workflow declares any such
    option."""

    FORBIDDEN = (
        "skip",
        "force",
        "ignore",
        "bypass",
        "disable",
        "no-fail",
        "report-only",
        "warn-only",
        "soft",
        "advisory",
        "dry-run",
    )

    def test_the_parser_declares_no_escape_option(self) -> None:
        """Read the parser's own option strings rather than matching prose, so
        adding one is a red test and not a review catch."""
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        options: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    options.append(arg.value)
        assert options, "no parser options found -- the probe itself is broken"
        for option in options:
            for word in self.FORBIDDEN:
                assert word not in option.lower(), option

    def test_neither_gate_workflow_declares_an_input_or_a_conditional_gate_step(
        self,
    ) -> None:
        for path in (GATE_WORKFLOW, REUSABLE_WORKFLOW):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            triggers = document[True] if True in document else document["on"]
            for trigger in ("workflow_dispatch", "workflow_call"):
                declared = (triggers or {}).get(trigger) or {}
                assert not (declared or {}).get("inputs"), (
                    f"{path.name}: {trigger} declares inputs"
                )
            for job in document["jobs"].values():
                assert "if" not in job, f"{path.name}: a gate job carries `if:`"
                for step in job.get("steps", []) or []:
                    if "advisory_job_gate.py" in str(step.get("run", "")):
                        assert "if" not in step, (
                            f"{path.name}: the gate step carries `if:`"
                        )

    def test_the_gate_step_passes_no_fixture_flag(self) -> None:
        for path in (GATE_WORKFLOW, REUSABLE_WORKFLOW):
            text = path.read_text(encoding="utf-8")
            assert "--baseline " not in text
            assert "--write-baseline" not in text


class TestFixtureFlagsAreRefusedInsideActions:
    """The fixture flags substitute a file for the tree the gate is supposed to
    govern. A claim in a docstring is not a control."""

    def test_baseline_override_is_refused_inside_actions(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"ci.yml": CLEAN})
        with _env(GITHUB_ACTIONS="true"):
            code = gate.main(
                [
                    "--repo-root",
                    str(root),
                    "--repo",
                    "OmniNode-ai/fixture",
                    "--baseline",
                    str(_baseline(tmp_path, EMPTY_BASELINE)),
                    "--required-contexts-json",
                    str(_contexts(tmp_path, [])),
                ]
            )
        assert code == 2
        assert "THE GATE DID NOT RUN" in capsys.readouterr().err

    def test_write_baseline_is_refused_inside_actions(self, tmp_path: Path) -> None:
        root = _repo(tmp_path, {"ci.yml": ADVISORY_JOB})
        with _env(GITHUB_ACTIONS="true"):
            code = gate.main(
                [
                    "--repo-root",
                    str(root),
                    "--repo",
                    "OmniNode-ai/fixture",
                    "--write-baseline",
                    str(tmp_path / "out.yaml"),
                ]
            )
        assert code == 2


class TestWiring:
    """Rule 5: a detection tool that is not a pre-merge gate is advisory and
    gets ignored. Both surfaces run the same module."""

    def test_the_hook_is_exported_and_runs_the_same_script(self) -> None:
        hooks = yaml.safe_load(
            (REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
        )
        hook = next(h for h in hooks if h["id"] == "advisory-job-gate")
        assert "scripts/advisory_job_gate.py" in hook["entry"]
        # Whole-tree scope, workflow-file trigger, and NOT always_run --
        # pre-commit ignores `files:` when always_run is set.
        assert hook["pass_filenames"] is False
        assert hook.get("always_run") is not True
        assert ".github/workflows" in hook["files"]

    def test_the_hook_is_installed_locally(self) -> None:
        config = yaml.safe_load(
            (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        )
        ids = [hook["id"] for repo in config["repos"] for hook in repo.get("hooks", [])]
        assert "advisory-job-gate" in ids

    def test_the_local_hook_and_the_workflow_run_the_same_entrypoint(self) -> None:
        config = yaml.safe_load(
            (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        )
        hook = next(
            hook
            for repo in config["repos"]
            for hook in repo.get("hooks", [])
            if hook["id"] == "advisory-job-gate"
        )
        assert "advisory_job_gate.py" in (hook.get("entry") or "")
        assert "advisory_job_gate.py" in REUSABLE_WORKFLOW.read_text(encoding="utf-8")
