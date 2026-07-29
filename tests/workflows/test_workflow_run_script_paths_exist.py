# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-15393 (OMN-15231 acceptance 2): workflow `run:` script paths must exist.

The class defect this guards: a workflow is fanned out into a repo WITHOUT the
script it invokes. omniclaude is the third confirmed instance --
`call-occ-autobind.yml` and `call-occ-companion-effect.yml` both ran
`python3 scripts/ci/occ_manual_replay_precheck.py pr_state.json`, and that
script was never fanned out with them (OMN-15231 omnimemory, OMN-15333
onex_change_control, OMN-15393 here). Live proof, omniclaude run 30467245650:

    python3: can't open file '.../scripts/ci/occ_manual_replay_precheck.py':
    [Errno 2] No such file or directory
    ##[error]Process completed with exit code 2

Why nothing caught it: those jobs are `workflow_dispatch`-gated, so they never
run on a normal PR -- the entrypoint is dead for months and every PR is green.
The repo's existing `uses:`-pin checks fail closed on unresolvable cross-repo
pins but are structurally blind to `run:` script paths. That blind spot is
exactly what this module closes, statically, without dispatching anything.

This is the mechanism, not the restatement of a rule
(feedback_a_rule_is_not_a_mechanism). It lives in its own module, separate from
`test_occ_manual_replay_entrypoint.py`, because that module imports the
precheck script at module scope -- a guard living there would die at COLLECTION
in the exact condition it exists to detect, reporting an opaque ImportError
instead of naming the missing file.

SCOPE, stated as what is actually checked rather than as an aspiration:

- Every `*.yml` AND `*.yaml` file in `.github/workflows/`.
- `run:` blocks only. `uses:` pins are a different (already-guarded) surface.
- Steps whose EFFECTIVE working directory is the repo root. Steps that run
  inside another repo's checkout (the OCC publishers sparse-checkout omnimarket
  into `.occ-*-src/`) are excluded by design -- a `scripts/...` path there is
  expected NOT to exist in this tree, and asserting on it would be a false
  positive that pressures someone to weaken the guard.
- Any path containing a `scripts/` segment and ending in `.py` or `.sh`, at any
  depth, in any invocation form. `.py`/`.sh` are the only extensions the
  workflows reference today (verified: an unrestricted scan of repo-root `run:`
  blocks returns `.py` and `.sh` and nothing else).
- Paths rooted in a directory that the workflows themselves declare as an
  `actions/checkout` destination are excluded as foreign checkouts. That set is
  DERIVED, not hardcoded, so a new cross-repo checkout excludes itself.

`test_matcher_has_no_blind_spot_for_in_tree_script_paths` is what keeps that
scope honest: it re-scans with an unrestricted pattern and fails if anything is
neither seen by the production matcher nor attributable to a declared foreign
checkout. Two earlier shapes of this guard both under-matched, and both times
the gap was invisible because the guard was green.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: Any repo-relative path with a ``scripts/`` segment, ending ``.py``/``.sh``,
#: named inside a ``run:`` block, in ANY invocation form.
#:
#: Two earlier shapes of this matcher were both materially too narrow, and both
#: were GREEN while blind:
#:
#: 1. ``(?:^|\s)(?:uv\s+run\s+)?python3?\s+(scripts/[\w/\-.]+\.py)`` -- anchored
#:    on an explicit ``python``/``python3`` token at a word boundary. It saw
#:    ZERO shell entrypoints (``bash scripts/x.sh``, ``./scripts/x.sh``) and
#:    missed Python inside a command substitution (``$(python scripts/x.py``).
#: 2. ``(?<![\w/.\-])(?:\./)?(scripts/[\w/\-.]+\.(?:py|sh))`` -- syntax-agnostic
#:    but anchored on ``scripts/`` as the FIRST segment, so it missed the repo's
#:    two nested script roots: ``bash plugins/onex/scripts/validate-all-agents.sh``
#:    and ``bash plugins/onex/hooks/scripts/grep_guard_no_polymorphic_agent.sh``.
#:
#: Both files exist today, so neither gap was a live break -- but a fan-out that
#: dropped either would have recurred the identical OMN-15393 defect class
#: undetected. EXISTENCE, not invocation syntax and not directory depth, is the
#: property under test.
#:
#: The leading negative lookbehind and the ``[\w\-.]*[\w\-]/`` segment shape
#: (which cannot match a bare ``.``) keep an optional ``./`` prefix out of the
#: captured path, so group 1 is always usable as ``repo_root / group1``.
_RUN_SCRIPT_RE = re.compile(
    r"(?<![\w/.\-])(?:\./)?((?:[\w\-.]*[\w\-]/)*scripts/[\w/\-.]+\.(?:py|sh))"
)

#: Unrestricted companion pattern for the blind-spot test: NO lookbehind, and a
#: greedy left prefix so a ``$VAR/``-prefixed or otherwise unusual reference is
#: still surfaced for classification instead of silently vanishing.
_ANY_SCRIPT_RE = re.compile(r"([\w\-./]*)(scripts/[\w/\-.]+\.(?:py|sh))")

#: `working-directory` values that still resolve to the repo root. Any other
#: value means the step runs inside a checkout of ANOTHER repo, where a
#: `scripts/...` path is expected NOT to exist in this tree.
_REPO_ROOT_WORKING_DIRS = frozenset({"", ".", "${{ github.workspace }}"})


def _iter_workflow_files(workflows_dir: Path) -> list[Path]:
    """Both GitHub-accepted workflow extensions.

    ``.yaml`` is matched even though this repo has zero today: a ``.yaml``
    workflow silently escaping the guard is the same blind spot in a new coat,
    and `.github/workflows/*.yaml` is as valid to GitHub as `*.yml`.
    """
    return sorted(
        [*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")],
        key=lambda p: p.name,
    )


def _declared_foreign_checkout_roots(
    workflows_dir: Path = WORKFLOWS_DIR,
) -> frozenset[str]:
    """First path segment of every ``actions/checkout`` ``path:`` declaration.

    The workflows themselves declare where foreign repos land (`.ci/`,
    `_omnibase_infra/`, `onex_change_control/`, `.occ-*-src/`, ...), so this set
    is DERIVED rather than a hardcoded denylist someone must remember to update:
    adding a new cross-repo checkout automatically excludes its own tree.
    """
    roots: set[str] = set()
    for workflow_path in _iter_workflow_files(workflows_dir):
        loaded = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        jobs = loaded.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job in jobs.values():
            if not isinstance(job, dict):
                continue
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                if "actions/checkout" not in str(step.get("uses", "") or ""):
                    continue
                with_block = step.get("with")
                if not isinstance(with_block, dict):
                    continue
                declared = str(with_block.get("path", "") or "")
                if declared:
                    roots.add(declared.strip("/").split("/", 1)[0])
    return frozenset(roots)


def _iter_repo_root_run_steps(
    workflows_dir: Path = WORKFLOWS_DIR,
) -> list[tuple[str, str, str]]:
    """Return ``(workflow, job_id, run_body)`` for every ``run:`` step whose
    effective working directory is the repo root."""
    steps_out: list[tuple[str, str, str]] = []
    for workflow_path in _iter_workflow_files(workflows_dir):
        loaded = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        jobs = loaded.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            defaults = job.get("defaults")
            job_dir = ""
            if isinstance(defaults, dict) and isinstance(defaults.get("run"), dict):
                job_dir = str(defaults["run"].get("working-directory", "") or "")
            steps = job.get("steps")
            if not isinstance(steps, list):
                continue
            for step in steps:
                if not isinstance(step, dict):
                    continue
                working_dir = str(step.get("working-directory", "") or "") or job_dir
                if working_dir not in _REPO_ROOT_WORKING_DIRS:
                    continue
                run_body = str(step.get("run", "") or "")
                if run_body:
                    steps_out.append((workflow_path.name, str(job_id), run_body))
    return steps_out


def _iter_repo_root_run_script_refs(
    workflows_dir: Path = WORKFLOWS_DIR,
) -> list[tuple[str, str, str]]:
    """Return ``(workflow, job_id, script_path)`` for every repo-root-relative
    ``run:`` reference to a ``scripts/**`` Python or shell file.

    ``workflows_dir`` is a parameter so the guard can be driven against a
    synthetic tree and PROVEN to go red (``test_guard_detects_a_missing_script``).
    A guard that has never been observed failing is an assertion, not evidence.
    """
    foreign_roots = _declared_foreign_checkout_roots(workflows_dir)
    refs: list[tuple[str, str, str]] = []
    for workflow, job_id, run_body in _iter_repo_root_run_steps(workflows_dir):
        for match in _RUN_SCRIPT_RE.finditer(run_body):
            script = match.group(1)
            if script.split("/", 1)[0] in foreign_roots:
                continue
            refs.append((workflow, job_id, script))
    return refs


def _missing_refs(
    workflows_dir: Path = WORKFLOWS_DIR, repo_root: Path = REPO_ROOT
) -> list[str]:
    """Every matched reference whose target file is absent from ``repo_root``."""
    return [
        f"{workflow}:{job_id} -> {script} (expected at {repo_root / script})"
        for workflow, job_id, script in _iter_repo_root_run_script_refs(workflows_dir)
        if not (repo_root / script).is_file()
    ]


def test_matcher_is_not_vacuous() -> None:
    """Guard the guard: if the matcher stops finding ANY reference, the
    existence assertion below passes vacuously and this whole module becomes
    a green no-op (reference_detection_shelf_structurally_blind).

    Deliberately a FLOOR, never an exact count. #1962's body shipped two exact
    counts (59, then 55) that were both stale within the hour because the
    matcher changed and the probe was never re-run; an exact assertion here
    would turn every unrelated workflow edit into a red test and train people
    to bump the number without reading it.
    """
    refs = _iter_repo_root_run_script_refs()
    assert len(refs) >= 60, (
        f"expected the matcher to find many repo-root `run:` script "
        f"references across {WORKFLOWS_DIR}, found {len(refs)} -- the matcher "
        f"is broken (or workflows moved), not the repo suddenly clean; a "
        f"silently-empty matcher makes the existence check below vacuous"
    )


def test_matcher_sees_shell_entrypoints_not_just_python() -> None:
    """Shape 1 of this matcher was interpreter-anchored on ``python``/``python3``
    and saw ZERO of the repo's shell entrypoints, so a fan-out dropping a ``.sh``
    file recurred the defect class undetected. Pin the broadened reach so it
    cannot silently regress to Python-only."""
    shell_refs = {
        script
        for _wf, _job, script in _iter_repo_root_run_script_refs()
        if script.endswith(".sh")
    }
    assert len(shell_refs) >= 5, (
        f"expected the matcher to see the repo's shell entrypoints "
        f"(bash scripts/x.sh, ./scripts/x.sh); found {sorted(shell_refs)} -- "
        f"an interpreter-anchored matcher is blind to every one of them"
    )


def test_matcher_sees_nested_script_roots_not_just_repo_root_scripts() -> None:
    """Shape 2 was anchored on ``scripts/`` as the FIRST path segment, so it was
    blind to this repo's nested script roots under ``plugins/``. Pin that reach
    as a PROPERTY (at least one reference is not ``scripts/``-rooted) rather
    than as an inventory of today's files, which would rot on any rename."""
    nested = {
        script
        for _wf, _job, script in _iter_repo_root_run_script_refs()
        if not script.startswith("scripts/")
    }
    assert nested, (
        "expected at least one workflow-referenced script under a NESTED root "
        "(e.g. plugins/onex/scripts/, plugins/onex/hooks/scripts/); found none, "
        "which is the signature of a matcher anchored on `scripts/` as the "
        "first path segment"
    )


def test_matcher_has_no_blind_spot_for_in_tree_script_paths() -> None:
    """Anti-blind-spot mechanism -- the reason this module can claim its scope.

    Re-scan every repo-root ``run:`` block with an UNRESTRICTED pattern (no
    lookbehind, greedy left prefix) and require every hit to be explained by
    either (a) a reference the production matcher saw, or (b) a path rooted in a
    directory the workflows declare as an ``actions/checkout`` destination.

    Anything else is a matcher blind spot. This is exactly how the two
    ``plugins/**/scripts/*.sh`` entrypoints escaped shape 2 of this guard: the
    guard was green, the assertion was live, and the references were simply
    never handed to it.
    """
    foreign_roots = _declared_foreign_checkout_roots()
    seen = {script for _wf, _job, script in _iter_repo_root_run_script_refs()}

    blind: list[str] = []
    for workflow, job_id, run_body in _iter_repo_root_run_steps():
        for match in _ANY_SCRIPT_RE.finditer(run_body):
            prefix, tail = match.group(1), match.group(2)
            candidate = f"{prefix}{tail}".lstrip("/")
            if candidate.startswith("./"):
                candidate = candidate[2:]
            if candidate in seen:
                continue
            segments = set(candidate.split("/"))
            if segments & foreign_roots:
                continue
            blind.append(f"{workflow}:{job_id} -> {candidate}")

    assert not blind, (
        "unrestricted scan found `scripts/**` references in repo-root `run:` "
        "blocks that the production matcher did NOT see and that are not rooted "
        "in a declared foreign checkout. Each is a silent blind spot: the guard "
        "would stay green if the file were deleted. Widen _RUN_SCRIPT_RE (or, "
        "if these really do live in another checkout, add that checkout's "
        "`path:` declaration so the exclusion is derived, not assumed):\n  "
        + "\n  ".join(sorted(blind))
    )


def test_declared_foreign_roots_do_not_shadow_in_tree_script_roots() -> None:
    """The foreign-checkout exclusion is derived from workflow ``path:`` values.
    If one of those ever collided with a real in-tree directory that holds
    scripts, the exclusion would silently blind the guard for that whole
    subtree. Assert the two sets are disjoint."""
    foreign_roots = _declared_foreign_checkout_roots()
    in_tree_roots = {
        script.split("/", 1)[0]
        for _wf, _job, script in _iter_repo_root_run_script_refs()
    }
    overlap = foreign_roots & in_tree_roots
    assert not overlap, (
        f"declared foreign checkout root(s) {sorted(overlap)} collide with "
        f"in-tree script root(s); every reference under them is being excluded "
        f"from the existence assertion"
    )


def test_guard_detects_a_missing_script() -> None:
    """RED proof (feedback_prove_red_against_exists_but_wrong).

    A guard that has only ever been observed passing is an assertion, not a
    mechanism. Drive it against a synthetic tree reproducing the exact
    OMN-15393 shape -- a workflow invoking a script that was never fanned out
    with it -- and require it to name the missing file. Cover all three
    invocation shapes that earlier matchers missed, then assert the
    present-file case goes green so the guard is discriminating rather than
    simply always-red.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "call-occ-companion-effect.yml").write_text(
            "on: workflow_dispatch\n"
            "jobs:\n"
            "  replay:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: python3 scripts/ci/occ_manual_replay_precheck.py pr_state.json\n"
            "      - run: bash scripts/never_fanned_out.sh\n"
            "      - run: bash plugins/onex/scripts/nested_never_fanned_out.sh\n"
            '      - run: echo "$(python scripts/ci/in_substitution.py)"\n',
            encoding="utf-8",
        )
        # `.yaml`, not `.yml` -- the extension shape 2's glob ignored entirely.
        (workflows / "future.yaml").write_text(
            "on: pull_request\n"
            "jobs:\n"
            "  probe:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: ./scripts/yaml_extension_never_fanned_out.sh\n",
            encoding="utf-8",
        )

        missing = _missing_refs(workflows, root)
        expected = {
            "scripts/ci/occ_manual_replay_precheck.py",
            "scripts/never_fanned_out.sh",
            "plugins/onex/scripts/nested_never_fanned_out.sh",
            "scripts/ci/in_substitution.py",
            "scripts/yaml_extension_never_fanned_out.sh",
        }
        for script in expected:
            assert any(script in m for m in missing), (
                f"{script} must be flagged -- it is one of the invocation or "
                f"extension shapes an earlier matcher was blind to: {missing}"
            )
        assert len(missing) == len(expected), (
            f"expected exactly {len(expected)} flagged refs, got {missing}"
        )

        # Discrimination: create the files and the guard must go green.
        for script in expected:
            target = root / script
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")
        assert _missing_refs(workflows, root) == [], (
            "guard must go green once the referenced files exist -- otherwise "
            "it is always-red and proves nothing"
        )


def test_guard_ignores_scripts_in_another_repos_checkout() -> None:
    """The OCC publishers sparse-checkout omnimarket into ``.occ-*-src/`` and
    invoke ``scripts/publish_occ_*.py`` THERE. Those paths are correctly absent
    from this tree; asserting on them would be a false positive that pressures
    someone to weaken the guard.

    Both exclusion routes are covered: ``working-directory`` on the step, and a
    path prefix matching a declared ``actions/checkout`` destination.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "call-occ-autobind.yml").write_text(
            "on: pull_request\n"
            "jobs:\n"
            "  publish:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v7\n"
            "        with:\n"
            "          repository: OmniNode-ai/omnimarket\n"
            "          path: .occ-autobind-src\n"
            "      - working-directory: .occ-autobind-src\n"
            "        run: python scripts/publish_occ_autobind_command.py --lane dev\n"
            "      - run: python .occ-autobind-src/scripts/publish_occ_other.py\n",
            encoding="utf-8",
        )
        assert _missing_refs(workflows, root) == [], (
            "steps running inside, or referencing paths under, another repo's "
            "declared checkout must be excluded"
        )


def test_undeclared_foreign_path_is_not_silently_excluded() -> None:
    """Fail-closed direction of the exclusion: a nested path that is NOT backed
    by a declared checkout must still be asserted. Otherwise 'looks like
    another repo' would become a free bypass."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        workflows = root / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "sneaky.yml").write_text(
            "on: pull_request\n"
            "jobs:\n"
            "  probe:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - run: python _undeclared_tree/scripts/thing.py\n",
            encoding="utf-8",
        )
        missing = _missing_refs(workflows, root)
        assert any("_undeclared_tree/scripts/thing.py" in m for m in missing), (
            f"an undeclared nested path must still be asserted; got {missing}"
        )


def test_precheck_script_reference_is_covered() -> None:
    """Pin the specific reference OMN-15393 is about, so a future refactor
    cannot drop it from the matcher's reach and call this guard green."""
    refs = _iter_repo_root_run_script_refs()
    covered = {
        (workflow, script)
        for workflow, _job_id, script in refs
        if script.endswith("occ_manual_replay_precheck.py")
    }
    assert covered == {
        ("call-occ-autobind.yml", "scripts/ci/occ_manual_replay_precheck.py"),
        ("call-occ-companion-effect.yml", "scripts/ci/occ_manual_replay_precheck.py"),
    }, (
        f"both OCC born-path callers must invoke the manual-replay precheck "
        f"from the repo root and be seen by this matcher; found: {sorted(covered)}"
    )


def test_every_repo_root_run_script_reference_exists() -> None:
    """Fail closed when a workflow `run:` step invokes a repo-root
    `scripts/**` file that is not in this tree."""
    missing = _missing_refs()
    assert not missing, (
        "workflow `run:` steps reference repo-root script paths that are not "
        "in this tree; each would die with `[Errno 2] No such file or "
        "directory` the moment that job runs (OMN-15393 / OMN-15231 defect "
        "class):\n  " + "\n  ".join(missing)
    )
