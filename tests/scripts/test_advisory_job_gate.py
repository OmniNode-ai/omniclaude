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
from datetime import UTC, datetime
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

    BRANCH_PROTECTION_AUDIT = """\
name: Branch Protection Audit
on:
  pull_request:
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - name: Mint onexbot App token
        run: echo mint
      - name: Checkout code
        run: echo checkout
      - name: Orphaned required-context audit
        run: echo audit
      - name: Fail if the audit reported violations
        run: echo fail
      - name: Required-context parity report (REPORT-ONLY, non-blocking)
        continue-on-error: true
        run: echo parity
"""

    def test_the_infra_branch_protection_audit_parity_step_is_keyed_at_its_current_position(
        self, tmp_path: Path
    ) -> None:
        """OMN-20955: omnibase_infra dropped the change-control fetch and the
        shared-audit step from branch-protection-audit.yml, which moved its
        report-only parity step from step 6 to step 4. The baseline keys that
        step by position, so the old key left the step unnamed and the gate red
        on omnibase_infra. The committed baseline must name the step where it
        now sits, and must not keep the old key as a second entry."""
        root = _repo(
            tmp_path, {"branch-protection-audit.yml": self.BRANCH_PROTECTION_AUDIT}
        )
        occurrences, _ = gate.scan_workflow(
            root / ".github" / "workflows" / "branch-protection-audit.yml", root
        )
        assert [o.key for o in occurrences] == [
            ".github/workflows/branch-protection-audit.yml::audit::step[4]"
        ]
        payload = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
        keys = {
            entry["key"]
            for entry in payload["repos"]["OmniNode-ai/omnibase_infra"]["advisory"]
            if entry["path"] == ".github/workflows/branch-protection-audit.yml"
        }
        assert keys == {occurrences[0].key}


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
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def unavailable(_args: list[str]) -> str:
            raise gate.GateError("authoritative live read refused")

        monkeypatch.setattr(gate, "_gh", unavailable)
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


class TestLandingControllerContextCache:
    """OMN-21006: a fresh controller read remains usable after a quota refusal."""

    @pytest.fixture
    def cached_contexts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Path, Path, int]:
        root = _repo(tmp_path, {"ci.yml": CLEAN})
        (root / ".git").write_text("gitdir: /fixture/worktrees/lane\n")
        home = tmp_path / "home"
        cache = home / ".local/state/omni/landing/required-contexts.json"
        cache.parent.mkdir(parents=True)
        now = 1791756000
        cache.write_text(
            json.dumps(
                {
                    "fixture:dev": {
                        "read_at": datetime.fromtimestamp(now - 60, UTC).strftime(
                            "%Y-%m-%dT%H:%M:%SZ"
                        ),
                        "contexts": ["unit-tests"],
                    }
                }
            )
        )
        monkeypatch.setattr(gate.Path, "home", lambda: home)
        monkeypatch.setattr(gate.time, "time", lambda: now)

        def unavailable(_args: list[str]) -> str:
            raise gate.GateError("authoritative live read refused")

        def default_branch(args: list[str], **_kwargs: Any) -> Any:
            assert args == [
                "git",
                "-C",
                str(root),
                "symbolic-ref",
                "--short",
                "refs/remotes/origin/HEAD",
            ]
            return gate.subprocess.CompletedProcess(args, 0, "origin/dev\n", "")

        monkeypatch.setattr(gate, "_gh", unavailable)
        monkeypatch.setattr(gate.subprocess, "run", default_branch)
        return root, cache, now

    def test_fresh_exact_repo_and_branch_cache_runs_the_gate(
        self, cached_contexts: tuple[Path, Path, int], tmp_path: Path
    ) -> None:
        root, _, _ = cached_contexts
        contexts, source = gate.resolve_required_contexts("OmniNode-ai/fixture", root)
        assert contexts == ["unit-tests"]
        assert "controller" in source
        assert "60s-old" in source
        assert (
            _run(
                root,
                repo="OmniNode-ai/fixture",
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
            )
            == 0
        )

    def test_cached_contexts_still_refuse_an_unenforced_job(
        self, cached_contexts: tuple[Path, Path, int], tmp_path: Path
    ) -> None:
        root, _, _ = cached_contexts
        (root / ".github/workflows/extra.yml").write_text(
            CLEAN.replace("unit-tests:", "unenforced-tests:")
        )
        assert (
            _run(
                root,
                repo="OmniNode-ai/fixture",
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
            )
            == 1
        )

    @pytest.mark.parametrize(
        "defect", ["stale", "future", "branch", "missing", "shape"]
    )
    def test_unusable_controller_cache_remains_a_refusal(
        self, cached_contexts: tuple[Path, Path, int], defect: str
    ) -> None:
        root, cache, now = cached_contexts
        data = json.loads(cache.read_text())
        row = data["fixture:dev"]
        if defect in {"stale", "future"}:
            stamp = now - 6 * 3600 - 1 if defect == "stale" else now + 1
            row["read_at"] = datetime.fromtimestamp(stamp, UTC).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        elif defect == "branch":
            data["fixture:main"] = data.pop("fixture:dev")
        elif defect == "missing":
            del row["read_at"]
        else:
            row["contexts"] = "unit-tests"
        cache.write_text(json.dumps(data))
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("OmniNode-ai/fixture", root)

    def test_other_organization_cannot_use_this_controller_cache(
        self, cached_contexts: tuple[Path, Path, int]
    ) -> None:
        root, _, _ = cached_contexts
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("AnotherOrg/fixture", root)


class TestDeclaredManifestFallback:
    """OMN-17427: a host with no controller cache and no GitHub read still gets a verdict.

    Lane hosts other than the landing controller's have no `required-contexts.json`
    and a GitHub read budget of 0, so the hook refused every commit there. The clone
    carries `.github/required-checks.yaml`, whose REQUIRED rows the manifest reconcile
    job holds equal to live branch protection, and that is the last source tried.
    """

    MANIFEST = {
        "schema_version": 3,
        "repo": "fixture",
        "gates": [
            {"name": "unit-tests", "mode": "REQUIRED"},
            {"name": "lint", "mode": "REQUIRED"},
            {"name": "advisory-only", "mode": "ADVISORY"},
            {"name": "gone", "mode": "RETIRED"},
        ],
    }

    @pytest.fixture
    def offline_host(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """No controller cache under HOME, and every GitHub read refused."""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(gate.Path, "home", lambda: home)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)

        def refused(_args: list[str]) -> str:
            raise gate.GateError("raw GitHub read budget=0")

        monkeypatch.setattr(gate, "_gh", refused)
        return _repo(tmp_path, {"ci.yml": CLEAN})

    @staticmethod
    def _declare(root: Path, manifest: Any) -> None:
        (root / ".github" / "required-checks.yaml").write_text(
            yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
        )

    def test_positive_control_without_a_manifest_the_host_is_still_refused(
        self, offline_host: Path
    ) -> None:
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("OmniNode-ai/fixture", offline_host)

    def test_required_rows_of_the_declared_manifest_answer(
        self, offline_host: Path
    ) -> None:
        self._declare(offline_host, self.MANIFEST)
        contexts, source = gate.resolve_required_contexts(
            "OmniNode-ai/fixture", offline_host
        )
        assert contexts == ["unit-tests", "lint"]
        assert "required-checks.yaml" in source

    def test_the_hook_passes_and_still_refuses_an_unenforced_job(
        self, offline_host: Path, tmp_path: Path
    ) -> None:
        self._declare(offline_host, self.MANIFEST)
        baseline = _baseline(tmp_path, EMPTY_BASELINE)
        assert _run(offline_host, repo="OmniNode-ai/fixture", baseline=baseline) == 0
        (offline_host / ".github/workflows/extra.yml").write_text(
            CLEAN.replace("unit-tests:", "unenforced-tests:")
        )
        assert _run(offline_host, repo="OmniNode-ai/fixture", baseline=baseline) == 1

    def test_live_read_wins_over_the_manifest(
        self, offline_host: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._declare(offline_host, self.MANIFEST)
        answers = iter(['{"b":"dev"}', '["live-only"]'])
        monkeypatch.setattr(gate, "_gh", lambda _args: next(answers))
        contexts, source = gate.resolve_required_contexts(
            "OmniNode-ai/fixture", offline_host
        )
        assert contexts == ["live-only"]
        assert "live" in source

    @pytest.mark.parametrize(
        "manifest",
        [
            {**MANIFEST, "schema_version": 2},
            {**MANIFEST, "repo": "another-repo"},
            {"schema_version": 3, "repo": "fixture", "gates": []},
            {
                "schema_version": 3,
                "repo": "fixture",
                "gates": [{"name": "x", "mode": "ADVISORY"}],
            },
            {"schema_version": 3, "repo": "fixture", "gates": [{"mode": "REQUIRED"}]},
            {"schema_version": 3, "repo": "fixture", "gates": "unit-tests"},
            ["not", "a", "mapping"],
        ],
        ids=[
            "old-schema",
            "other-repo",
            "no-gates",
            "no-required-row",
            "nameless-row",
            "gates-not-a-list",
            "not-a-mapping",
        ],
    )
    def test_an_unusable_manifest_remains_a_refusal(
        self, offline_host: Path, manifest: Any
    ) -> None:
        self._declare(offline_host, manifest)
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("OmniNode-ai/fixture", offline_host)

    def test_an_unparseable_manifest_remains_a_refusal(
        self, offline_host: Path
    ) -> None:
        (offline_host / ".github" / "required-checks.yaml").write_text(
            "gates: [this: is: not: a: map\n", encoding="utf-8"
        )
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("OmniNode-ai/fixture", offline_host)

    def test_github_actions_never_falls_back_to_the_manifest(
        self, offline_host: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._declare(offline_host, self.MANIFEST)
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        with pytest.raises(gate.GateError, match="no fresh cache"):
            gate.resolve_required_contexts("OmniNode-ai/fixture", offline_host)

    def test_this_repositorys_own_manifest_is_usable(self) -> None:
        """Control on the real file: the fallback must read what this repo ships."""
        declared = gate.declared_manifest_contexts("OmniNode-ai/omniclaude", REPO_ROOT)
        assert declared is not None
        assert "advisory-job-gate / advisory-job-gate" in declared[0]


class TestAdvisoryJobGateRoutingOn:
    """OMN-20043 AC3: with the gh read router on, the gate's branch-protection read yields
    one JSON document. The App token is refused with a 403 body on stdout; the gate still
    parses the operator's answer."""

    APP_TOKEN = "ghs_" + "A" * 36

    def _install(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        route = REPO_ROOT / "scripts" / "user-bin" / "gh_route.py"
        calls = tmp_path / "calls.log"
        real_dir = tmp_path / "realbin"
        shim_dir = tmp_path / "shimbin"
        real_dir.mkdir()
        shim_dir.mkdir()
        fake = real_dir / "gh"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import os, sys\n"
            f"with open({str(calls)!r}, 'a') as fh:\n"
            "    fh.write(os.environ.get('GH_TOKEN', '') + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n"
            f"if os.environ.get('GH_TOKEN') == {self.APP_TOKEN!r}:\n"
            '    sys.stdout.write(\'{"message":"Resource not accessible by integration"}\')\n'
            "    sys.stderr.write('Resource not accessible by integration\\n')\n"
            "    sys.exit(1)\n"
            "if 'protection' in ' '.join(sys.argv):\n"
            "    sys.stdout.write('[\"unit-tests\"]')\n"
            "else:\n"
            '    sys.stdout.write(\'{"b":"dev"}\')\n'
        )
        fake.chmod(0o755)
        mint = real_dir / "mint"
        mint.write_text(f"#!/bin/sh\necho {self.APP_TOKEN}\n")
        mint.chmod(0o755)
        shim = shim_dir / "gh"
        shim.write_text(
            f'#!/bin/sh\n# ONEX_GH_USER_SHIM test double\nexec {sys.executable} {route} exec -- "$@"\n'
        )
        shim.chmod(0o755)
        monkeypatch.setenv(
            "PATH", os.pathsep.join([str(shim_dir), str(real_dir), "/usr/bin", "/bin"])
        )
        monkeypatch.setenv("ONEX_GH_READ_ROUTING", "1")
        monkeypatch.setenv("GH_READ_TOKEN_CMD", str(mint))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("GH_TOKEN", "operator-token")
        monkeypatch.setattr(gate, "landing_controller_contexts", lambda *_a: None)
        return calls

    def test_advisory_job_gate_routing_on_parses_the_protection_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._install(tmp_path, monkeypatch)
        root = tmp_path / "repo"
        root.mkdir()
        contexts, source = gate.resolve_required_contexts("OmniNode-ai/fixture", root)
        assert contexts == ["unit-tests"]
        assert "live" in source
        assert calls.read_text()

    def test_advisory_job_gate_routing_on_never_asks_the_app_for_the_protection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The branch-protection read is admin-only: it is served by the operator at once,
        not tried on the App first."""
        calls = self._install(tmp_path, monkeypatch)
        root = tmp_path / "repo"
        root.mkdir()
        gate.resolve_required_contexts("OmniNode-ai/fixture", root)
        protection = [
            line for line in calls.read_text().splitlines() if "protection" in line
        ]
        assert protection and all(
            line.startswith("operator-token ") for line in protection
        )


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


class TestAutomationDeclarationIsChecked:
    """OMN-20074, RULING 2026-10-10T15:10:25Z: the auto-merge and propagate jobs
    are declared automation in a form the gate reads, and the gate CHECKS the
    declaration -- no failing automation step may block a merge -- instead of
    treating it as an exemption the way the advisory-ok annotation is treated.

    The fixture is the omniclaude/omnibase_core auto-merge shape: its hold-check
    step runs `check_auto_merge_hold.py`, which the verification matcher reads
    as verification, and no job in the file is a required context once the OCC
    preflight caller is gone.
    """

    AUTOMATION = """\
name: Auto-Merge
on:
  pull_request:
jobs:
  # advisory-automation: OMN-20074 arms auto-merge on a ready pull request
  auto-merge:
    name: Enable Auto-Merge
    runs-on: ubuntu-latest
    steps:
      - run: python3 scripts/ci/check_auto_merge_hold.py hold
      - run: gh pr merge "$PR" --auto --squash
"""

    SUMMARY = """\
  ci-summary:
    name: CI Summary
    needs: [auto-merge]
    runs-on: ubuntu-latest
    steps:
      - run: echo done
"""

    def _gate(self, tmp_path: Path, text: str, contexts: list[str]) -> int:
        tmp_path.mkdir(parents=True, exist_ok=True)
        root = _repo(tmp_path, {"auto-merge.yml": text})
        return _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, contexts),
        )

    def test_a_correctly_declared_automation_job_passes(self, tmp_path: Path) -> None:
        assert self._gate(tmp_path, self.AUTOMATION, ["CI Summary"]) == 0

    def test_the_same_job_undeclared_is_still_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = self.AUTOMATION.replace(
            "  # advisory-automation: OMN-20074 arms auto-merge on a ready pull request\n",
            "",
        )
        assert self._gate(tmp_path, text, ["CI Summary"]) == 1
        out = capsys.readouterr().out
        assert "UNENFORCED_VERIFICATION_JOB" in out
        assert "auto-merge.yml::auto-merge" in out

    def test_declared_but_a_needs_of_the_ci_summary_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The file holds a required job, so the per-file coverage reads every
        job in it as enforced. The declaration is checked anyway: a failing
        automation job under a required summary's `needs:` blocks the merge."""
        assert self._gate(tmp_path, self.AUTOMATION + self.SUMMARY, ["CI Summary"]) == 1
        out = capsys.readouterr().out
        assert "AUTOMATION_DECLARATION_VIOLATED" in out
        assert "`auto-merge`" in out
        assert "not-needed-by-a-required-job" in out
        assert "ci-summary" in out

    def test_declared_but_reached_transitively_from_the_summary_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        middle = """\
  aggregate:
    needs: auto-merge
    runs-on: ubuntu-latest
    steps:
      - run: echo aggregate
"""
        summary = self.SUMMARY.replace("needs: [auto-merge]", "needs: [aggregate]")
        assert (
            self._gate(tmp_path, self.AUTOMATION + middle + summary, ["CI Summary"])
            == 1
        )
        assert "not-needed-by-a-required-job" in capsys.readouterr().out

    def test_declared_but_itself_a_required_context_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert self._gate(tmp_path, self.AUTOMATION, ["Enable Auto-Merge"]) == 1
        out = capsys.readouterr().out
        assert "AUTOMATION_DECLARATION_VIOLATED" in out
        assert "not-a-required-context" in out

    def test_declared_but_runs_a_pytest_step_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = self.AUTOMATION + "      - run: uv run pytest tests/ -q\n"
        assert self._gate(tmp_path, text, ["CI Summary"]) == 1
        out = capsys.readouterr().out
        assert "AUTOMATION_DECLARATION_VIOLATED" in out
        assert "runs-no-verification" in out
        assert "pytest" in out

    @pytest.mark.parametrize(
        "step",
        [
            "uv run ruff check src/",
            "pre-commit run --all-files",
            "python scripts/ci/dod_receipt_gate.py",
            "python scripts/write_evidence.py",
        ],
    )
    def test_declared_but_runs_a_lint_receipt_or_evidence_step_fails(
        self, tmp_path: Path, step: str
    ) -> None:
        text = self.AUTOMATION + f"      - run: {step}\n"
        assert self._gate(tmp_path, text, ["CI Summary"]) == 1

    def test_a_comment_inside_a_run_block_is_not_a_step(self, tmp_path: Path) -> None:
        """A comment naming a linter or citing a test file executes nothing;
        omniclaude's own arming step carries such comments."""
        text = self.AUTOMATION.replace(
            '      - run: gh pr merge "$PR" --auto --squash\n',
            "      - run: |\n"
            "          # ruff and pytest run in ci.yml, not in this job\n"
            "          # tests/ci/test_auto_merge_hold_omn18179.py pins this query\n"
            '          gh pr merge "$PR" --auto --squash\n',
        )
        assert "pytest" in text
        assert self._gate(tmp_path, text, ["CI Summary"]) == 0

    def test_declared_but_calls_a_verification_reusable_fails(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = """\
name: Auto-Merge
on:
  pull_request:
jobs:
  # advisory-automation: OMN-20074 resolves eligibility before arming
  preflight:
    uses: OmniNode-ai/omnibase_core/.github/workflows/occ-preflight.yml@abc
"""
        assert self._gate(tmp_path, text, []) == 1
        assert "runs-no-verification" in capsys.readouterr().out

    def test_a_declaration_with_no_reason_is_malformed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = self.AUTOMATION.replace(
            "OMN-20074 arms auto-merge on a ready pull request", "OMN-20074"
        )
        assert self._gate(tmp_path, text, []) == 1
        out = capsys.readouterr().out
        assert "MALFORMED_ANNOTATION" in out
        assert "advisory-automation" in out

    def test_a_declaration_attached_to_no_job_is_a_finding(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = self.AUTOMATION.replace(
            "      - run: gh pr merge",
            "      # advisory-automation: OMN-20074 stray marker on a step\n"
            "      - run: gh pr merge",
        )
        assert self._gate(tmp_path, text, []) == 1
        assert "ORPHANED_DECLARATION" in capsys.readouterr().out

    def test_an_advisory_ok_annotation_is_still_an_exemption(
        self, tmp_path: Path
    ) -> None:
        """Unchanged behaviour for the existing annotation: only the new
        declaration is checked."""
        text = (self.AUTOMATION + self.SUMMARY).replace(
            "advisory-automation: OMN-20074 arms auto-merge on a ready pull request",
            "advisory-ok: OMN-20074 automation, not a verdict",
        )
        assert self._gate(tmp_path, text, ["CI Summary"]) == 0

    def test_omniclaude_auto_merge_job_is_declared_and_passes_without_occ(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """This repository's own auto-merge.yml, scanned with no required
        context in the file (the state once the OCC preflight caller goes),
        passes because of the declaration, and fails without it."""
        text = (REPO_ROOT / ".github" / "workflows" / "auto-merge.yml").read_text(
            encoding="utf-8"
        )
        assert "# advisory-automation: OMN-20074" in text
        assert self._gate(tmp_path / "declared", text, []) == 0
        stripped = "\n".join(
            line for line in text.splitlines() if "# advisory-automation:" not in line
        )
        assert self._gate(tmp_path / "stripped", stripped + "\n", []) == 1
        assert "UNENFORCED_VERIFICATION_JOB" in capsys.readouterr().out


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


class TestP2CensusScopesCoverageToTheJob:
    """OMN-18796 / P2: one required job must not mark its whole workflow file
    enforced. 56 of 90 files share a boilerplate eligibility job that is a
    required context, and read file-wide it blinded the census to every other
    job beside it."""

    ELIGIBILITY_BESIDE_ADVISORY = """\
name: Fitness
on:
  pull_request:
jobs:
  eligibility:
    runs-on: ubuntu-latest
    steps:
      - run: echo eligible
  fresh-deploy-fitness:
    runs-on: ubuntu-latest
    steps:
      - run: python scripts/validate_fresh_deploy_fitness.py
"""

    def test_a_file_with_one_required_job_and_one_advisory_job_reports_the_advisory_job(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _repo(tmp_path, {"fitness.yml": self.ELIGIBILITY_BESIDE_ADVISORY})
        code = _run(
            root,
            baseline=_baseline(tmp_path, EMPTY_BASELINE),
            contexts=_contexts(tmp_path, ["eligibility"]),
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "UNENFORCED_VERIFICATION_JOB" in out
        assert "fitness.yml::fresh-deploy-fitness" in out

    def test_a_job_the_required_job_needs_is_still_enforced(
        self, tmp_path: Path
    ) -> None:
        text = """\
name: CI
on:
  pull_request:
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
  gate:
    needs: [unit-tests]
    runs-on: ubuntu-latest
    steps:
      - run: echo ok
"""
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["gate"]),
            )
            == 0
        )

    def test_a_needsless_summary_still_covers_its_own_file(
        self, tmp_path: Path
    ) -> None:
        """omnibase_infra's `CI Summary` carries no `needs:` on purpose and polls
        the run's job conclusions, so it owns every job in its file."""
        text = """\
name: CI
on:
  pull_request:
jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest -q
  ci-summary:
    name: CI Summary
    runs-on: ubuntu-latest
    steps:
      - run: echo poll
"""
        root = _repo(tmp_path, {"ci.yml": text})
        assert (
            _run(
                root,
                baseline=_baseline(tmp_path, EMPTY_BASELINE),
                contexts=_contexts(tmp_path, ["CI Summary"]),
            )
            == 0
        )


def test_runtime_profiles_is_required_not_grandfathered() -> None:
    payload = yaml.safe_load(BASELINE.read_text())
    entries = payload["repos"]["OmniNode-ai/omniclaude"]
    for entry in entries["advisory"] + entries["verification_jobs"]:
        assert "runtime-profiles" not in entry["key"]
    from scripts.ci.ci_summary_gate import GATE_JOBS, STRICT_SUCCESS_JOBS

    assert "Runtime Profiles" in GATE_JOBS
    assert "Runtime Profiles" in STRICT_SUCCESS_JOBS
