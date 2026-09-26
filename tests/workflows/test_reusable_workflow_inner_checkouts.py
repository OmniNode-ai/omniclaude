# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-16723: a reusable workflow's INNER checkout must be pinned, and a sparse
checkout must be asserted.

Two defects, one detection surface. Both were live and unlinted fleet-wide.

DEFECT 1 -- the floating inner ref.
A caller-side ``uses: OWNER/REPO/.github/workflows/x.yml@<sha>`` pin governs
exactly one thing: which workflow FILE loads. It cannot reach a SECOND,
independently-pinned ``actions/checkout`` inside that file. So an inner checkout
written ``ref: main`` resolves to whatever ``main`` holds at run time, and the
workflow source and the script source drift apart silently.

``github.sha`` is worse, not better: inside a reusable workflow the ``github``
context is the CALLER's, so ``github.sha`` is a commit in the caller repo
(omnibase_core, omnimarket, ...) that does not exist in the callee repo at all.

``github.job_workflow_sha`` does not exist. It evaluates to an empty string, and
``actions/checkout`` silently falls back to the checked-out repository's default
branch when ``ref:`` is empty. The documented source is ``job.workflow_sha``.
It must be read and validated by an earlier step, exposed through
``$GITHUB_OUTPUT``, used by the checkout, and verified against the checkout's
actual ``HEAD`` by a later step. This keeps the workflow and the code it invokes
on one immutable commit behind a SINGLE caller-side pin.

DEFECT 2 -- the silent sparse-checkout miss.
``actions/checkout`` with ``sparse-checkout:`` naming a path that does not exist
at the requested ref SUCCEEDS. It leaves an empty directory and a zero exit. The
miss surfaces only downstream, as::

    python3: can't open file '.../scripts/kb_doc_gate.py': [Errno 2] ...
    ##[error]Process completed with exit code 2

which reads like a gate VERDICT rather than a plumbing failure. That pair is why
the KB doc gate had never once executed successfully from any caller repo (5
runs, 5 failures on omnimarket; exit 2 on omnibase_core#1599 job 98344865386)
while both pilots looked correctly wired to everyone reading the YAML.

Reference implementation for both fixes:
``.github/workflows/kb-doc-gate-reusable.yml`` -- a step that validates
``job.workflow_sha`` as a full lowercase commit SHA, emits it through
``$GITHUB_OUTPUT``, a checkout using that output, and later assertions that the
checkout is at the pin and that each sparse path exists.

SCOPE, stated as what is actually checked rather than as an aspiration:

- Every ``*.yml`` AND ``*.yaml`` in ``.github/workflows/`` whose ``on:`` block
  declares ``workflow_call``. A workflow that is not reusable has no
  ``workflow_sha`` to pin to and is out of scope by construction.
- Within those, only ``actions/checkout`` steps that set ``repository:``. A bare
  checkout of the caller's own tree is the normal case and is not touched.
- SELF-checkout (``repository:`` naming the repo that hosts this workflow) must
  pin to a literal lowercase 40-character SHA, or to an earlier step's output.
  That step must read ``job.workflow_sha``, validate it as a lowercase 40-hex
  SHA, and write the referenced output to ``$GITHUB_OUTPUT``. A later step must
  verify that the side checkout's ``HEAD`` equals that same output.
- THIRD-REPO checkout (``repository:`` naming some other repo) cannot use
  ``job.workflow_sha`` -- that commit does not exist over there. It must instead be
  caller-controlled: an input expression or a 40-character SHA. A bare branch
  name is still refused, because it is an unpinned dependency on another repo's
  moving branch.
- Any step declaring ``sparse-checkout:`` must be followed, in the same job, by
  a step that tests each fetched path exists.

ESCAPE HATCH: an annotation, never a silent allowlist. A pre-existing instance
carries a comment line in the workflow file::

    # reusable-checkout-ref-ok: <job_id> <OMN-ticket> <reason>
    # reusable-checkout-sparse-ok: <job_id> <OMN-ticket> <reason>

Annotations are greppable, so the debt list is always one ``grep`` away and
cannot rot into an invisible allowlist file. Every annotation must cite a
ticket -- an annotation without one is itself a failure.

``test_scanner_sees_the_known_inner_checkouts`` is the positive control. A
parser regression that silently matches nothing would otherwise report green
forever, which is the exact failure mode this module exists to detect
(an empty result is not evidence of absence).
"""

from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path
from typing import Any, NamedTuple

import pytest
import yaml
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

#: A literal git object name. Anything shorter is ambiguous and anything longer
#: is not a SHA.
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: This spelling does not exist in the ``github`` context. It evaluates empty,
#: which makes actions/checkout fall back to the repository's default branch.
INVALID_GITHUB_JOB_WORKFLOW_SHA = "github.job_workflow_sha"

#: A self-checkout may consume only a single, exact earlier-step output.
STEP_OUTPUT_RE = re.compile(
    r"^\$\{\{\s*steps\.(?P<step>[A-Za-z0-9_-]+)\.outputs\."
    r"(?P<output>[A-Za-z0-9_-]+)\s*\}\}$"
)

#: The documented context property must appear as a GitHub expression in the
#: pin step's environment or script, never with the nonexistent ``github.``
#: prefix.
JOB_WORKFLOW_SHA_EXPR_RE = re.compile(r"\$\{\{\s*job\.workflow_sha\s*\}\}")

#: The shell must reject everything except a full lowercase git object name.
FULL_SHA_VALIDATION_RE = re.compile(r"\^\[0-9a-f\]\{40\}\$")

#: A ``${{ inputs.* }}`` reference. For a third-repo checkout this is the best
#: available pin, because the caller chooses the value.
INPUT_EXPR_RE = re.compile(r"\$\{\{[^}]*\binputs\b[^}]*\}\}")

#: Shell existence tests. ``[ -f x ]``, ``[ ! -f x ]``, ``test -e x``, and the
#: ``[[ ]]`` forms all reduce to one of these tokens.
EXISTENCE_TEST_RE = re.compile(
    r"(?:\[\[?\s*!?\s*-[efdsr]\s)|(?:\btest\s+!?\s*-[efdsr]\s)"
)

#: ``# reusable-checkout-ref-ok: <job_id> <OMN-ticket> <reason>``
REF_ANNOTATION_RE = re.compile(
    r"#\s*reusable-checkout-ref-ok:\s*(?P<job>[\w.-]+)\s+(?P<ticket>OMN-\d+)\b"
)
#: ``# reusable-checkout-sparse-ok: <job_id> <OMN-ticket> <reason>``
SPARSE_ANNOTATION_RE = re.compile(
    r"#\s*reusable-checkout-sparse-ok:\s*(?P<job>[\w.-]+)\s+(?P<ticket>OMN-\d+)\b"
)

#: An annotation that names a job but cites no ticket. Refused: an untracked
#: annotation is an allowlist wearing a comment's clothes.
UNTICKETED_ANNOTATION_RE = re.compile(
    r"#\s*reusable-checkout-(?:ref|sparse)-ok:(?P<rest>.*)$"
)


class InnerCheckout(NamedTuple):
    """One cross-repo ``actions/checkout`` step inside a reusable workflow."""

    workflow: str
    job: str
    step_index: int
    repository: str
    ref: str | None
    path: str | None
    sparse_paths: tuple[str, ...]
    earlier_steps: tuple[dict[str, Any], ...]
    later_steps: tuple[dict[str, Any], ...]
    later_steps_text: str

    @property
    def location(self) -> str:
        return f"{self.workflow} :: job '{self.job}' :: step {self.step_index}"


def _self_repository() -> str:
    """``OWNER/REPO`` for the repo this test lives in.

    Read from the git remote so the value is not a hardcoded constant that goes
    stale on a rename; falls back to the checkout directory name, which is what
    a tarball export or a detached CI checkout without a remote will have.
    """
    try:
        url = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
            env=scrub_git_location_env(os.environ),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - defensive
        url = ""
    match = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", url)
    if match:
        return match.group(1)
    return f"OmniNode-ai/{REPO_ROOT.name}"


def _is_reusable(document: dict[str, Any]) -> bool:
    """True when the workflow declares ``workflow_call``.

    ``on:`` is the YAML 1.1 boolean ``True`` after parsing, which is the single
    most common way a workflow scanner silently matches nothing.
    """
    on_block = document.get(True, document.get("on"))
    if isinstance(on_block, dict):
        return "workflow_call" in on_block
    if isinstance(on_block, list):
        return "workflow_call" in on_block
    return on_block == "workflow_call"


def _sparse_paths(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(line.strip() for line in value.splitlines() if line.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def _collect(workflows_dir: Path) -> list[InnerCheckout]:
    """Every cross-repo checkout step inside every reusable workflow."""
    found: list[InnerCheckout] = []
    for path in sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]):
        try:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            # Workflow YAML validity is a different guard's job; do not turn a
            # syntax error into a misleading failure from this module.
            continue
        if not isinstance(document, dict) or not _is_reusable(document):
            continue

        for job_id, job in (document.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            steps = [s for s in (job.get("steps") or []) if isinstance(s, dict)]
            for index, step in enumerate(steps):
                if not str(step.get("uses", "")).startswith("actions/checkout"):
                    continue
                with_block = step.get("with") or {}
                if not isinstance(with_block, dict) or "repository" not in with_block:
                    continue
                ref = with_block.get("ref")
                found.append(
                    InnerCheckout(
                        workflow=path.name,
                        job=str(job_id),
                        step_index=index,
                        repository=str(with_block["repository"]),
                        ref=None if ref is None else str(ref),
                        path=(
                            None
                            if with_block.get("path") is None
                            else str(with_block["path"])
                        ),
                        sparse_paths=_sparse_paths(with_block.get("sparse-checkout")),
                        earlier_steps=tuple(steps[:index]),
                        later_steps=tuple(steps[index + 1 :]),
                        later_steps_text=yaml.safe_dump(
                            steps[index + 1 :], default_flow_style=False
                        ),
                    )
                )
    return found


def _annotated_jobs(
    workflows_dir: Path, pattern: re.Pattern[str]
) -> set[tuple[str, str]]:
    """``(workflow filename, job id)`` pairs carrying an annotation."""
    annotated: set[tuple[str, str]] = set()
    for path in sorted([*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            annotated.add((path.name, match.group("job")))
    return annotated


def _ref_verdict(checkout: InnerCheckout, self_repository: str) -> str | None:
    """``None`` when the ref is acceptably pinned, else why it is not."""
    ref = checkout.ref
    is_self = checkout.repository.strip().endswith(
        self_repository.rsplit("/", maxsplit=1)[-1]
    )

    if ref is None:
        return (
            "no 'ref:' at all, so the checkout takes the other repo's DEFAULT "
            "branch — an unpinned dependency on a moving branch"
        )
    ref = ref.strip()
    if INVALID_GITHUB_JOB_WORKFLOW_SHA in ref:
        return (
            "'github.job_workflow_sha' does not exist in the github context, "
            "evaluates to an empty string, and makes actions/checkout fall "
            "back to the repository's default branch. Use the validated "
            "'job.workflow_sha' pin step and its output instead"
        )
    if FULL_SHA_RE.match(ref):
        return None
    if "github.sha" in ref:
        return (
            "'github.sha' inside a reusable workflow is the CALLER's commit, "
            "which does not exist in the checked-out repo at all"
        )
    if is_self:
        if INPUT_EXPR_RE.search(ref):
            return (
                f"self-checkout pinned to {ref!r}. An inputs.* expression is "
                "not the reusable workflow's validated commit pin"
            )
        output_match = STEP_OUTPUT_RE.fullmatch(ref)
        if output_match is None:
            if "job.workflow_sha" in ref:
                return (
                    "bare 'job.workflow_sha' in ref is unvalidated; if it is "
                    "empty, actions/checkout falls back to the default branch. "
                    "Use an earlier validated pin step's output"
                )
            return (
                f"self-checkout pinned to {ref!r}. It must use a literal "
                "lowercase 40-hex SHA or an exact "
                "'${{ steps.<id>.outputs.<name> }}' from an earlier validated "
                "job.workflow_sha pin step"
            )

        step_id = output_match.group("step")
        output_name = output_match.group("output")
        pin_step = next(
            (
                step
                for step in checkout.earlier_steps
                if str(step.get("id", "")) == step_id
            ),
            None,
        )
        if pin_step is None:
            return (
                f"self-checkout reads {ref!r}, but step {step_id!r} does not "
                "exist earlier in the same job"
            )

        pin_source = yaml.safe_dump(
            {"env": pin_step.get("env"), "run": pin_step.get("run")},
            default_flow_style=False,
        )
        pin_run = str(pin_step.get("run", ""))
        if INVALID_GITHUB_JOB_WORKFLOW_SHA in pin_source:
            return (
                f"pin step {step_id!r} reads 'github.job_workflow_sha', which "
                "does not exist in the github context and evaluates empty. It "
                "must read the documented 'job.workflow_sha' property"
            )
        if JOB_WORKFLOW_SHA_EXPR_RE.search(pin_source) is None:
            return (
                f"pin step {step_id!r} does not read "
                "'${{ job.workflow_sha }}' in its env or run"
            )
        if FULL_SHA_VALIDATION_RE.search(pin_run) is None:
            return (
                f"pin step {step_id!r} does not validate job.workflow_sha "
                "against the anchored lowercase 40-hex pattern "
                "'^[0-9a-f]{40}$'"
            )
        writes_output = any(
            f"{output_name}=" in line
            and re.search(r"\$(?:\{)?GITHUB_OUTPUT(?:\})?", line)
            for line in pin_run.splitlines()
        )
        if not writes_output:
            return (
                f"pin step {step_id!r} does not write output {output_name!r} "
                "to $GITHUB_OUTPUT"
            )

        if checkout.path is None:
            return (
                "self-checkout uses a validated step output but has no 'path:', "
                "so a later step cannot prove that checkout's HEAD is the pin"
            )
        head_check = next(
            (
                step
                for step in checkout.later_steps
                if re.search(
                    rf"\bgit\s+-C\s+['\"]?{re.escape(checkout.path)}['\"]?"
                    r"\s+rev-parse\s+HEAD\b",
                    str(step.get("run", "")),
                )
                and ref
                in yaml.safe_dump(
                    {"env": step.get("env"), "run": step.get("run")},
                    default_flow_style=False,
                )
            ),
            None,
        )
        if head_check is None:
            return (
                f"self-checkout at path {checkout.path!r} uses {ref!r}, but no "
                "later step runs 'rev-parse HEAD' against that path and "
                "references the same pin output"
            )
        return None
    if INPUT_EXPR_RE.search(ref):
        return None
    return (
        f"third-repo checkout pinned to {ref!r}, a moving branch. "
        "the job.workflow_sha commit does not exist in another repo, so the "
        "pin must be caller-controlled: take a ref input, or hardcode a "
        "40-char SHA"
    )


def _sparse_verdict(checkout: InnerCheckout) -> str | None:
    """``None`` when every sparse path is asserted downstream, else why not."""
    if not checkout.sparse_paths:
        return None
    following = checkout.later_steps_text
    if not EXISTENCE_TEST_RE.search(following):
        return (
            "declares sparse-checkout but no later step in this job tests that "
            "the fetched path exists. A sparse checkout of a MISSING path "
            "succeeds and leaves an empty directory, so the miss surfaces "
            "downstream as an exit-2 that reads like a gate verdict"
        )
    unasserted = [
        path
        for path in checkout.sparse_paths
        if Path(path).name not in following and path not in following
    ]
    if unasserted:
        return (
            "sparse-checkout path(s) "
            f"{', '.join(sorted(unasserted))} are never named in a later step, "
            "so nothing proves they were actually fetched"
        )
    return None


def _format(location: str, problem: str, annotation: str, job: str) -> str:
    return textwrap.dedent(
        f"""
        {location}
            {problem}
            If this is knowingly-carried debt, annotate it in the workflow file:
                # {annotation}: {job} OMN-XXXX <one-line reason>
        """
    ).rstrip()


# --------------------------------------------------------------------------
# Production assertions (run against this repo's real workflows)
# --------------------------------------------------------------------------


def test_inner_checkout_refs_are_pinned() -> None:
    """No reusable workflow fetches code from a moving branch."""
    self_repository = _self_repository()
    annotated = _annotated_jobs(WORKFLOWS_DIR, REF_ANNOTATION_RE)

    failures = [
        _format(c.location, verdict, "reusable-checkout-ref-ok", c.job)
        for c in _collect(WORKFLOWS_DIR)
        if (verdict := _ref_verdict(c, self_repository)) is not None
        and (
            (c.ref is not None and INVALID_GITHUB_JOB_WORKFLOW_SHA in c.ref)
            or (c.workflow, c.job) not in annotated
        )
    ]
    assert not failures, (
        "Unpinned inner checkout in a reusable workflow "
        f"({len(failures)}):\n" + "\n".join(failures)
    )


def test_sparse_checkouts_assert_the_paths_they_fetch() -> None:
    """No reusable workflow trusts a sparse checkout it never verified."""
    annotated = _annotated_jobs(WORKFLOWS_DIR, SPARSE_ANNOTATION_RE)

    failures = [
        _format(c.location, verdict, "reusable-checkout-sparse-ok", c.job)
        for c in _collect(WORKFLOWS_DIR)
        if (verdict := _sparse_verdict(c)) is not None
        and (c.workflow, c.job) not in annotated
    ]
    assert not failures, (
        "Unasserted sparse checkout in a reusable workflow "
        f"({len(failures)}):\n" + "\n".join(failures)
    )


def test_every_annotation_cites_a_ticket() -> None:
    """An annotation without a ticket is an untracked allowlist."""
    offenders: list[str] = []
    for path in sorted([*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")]):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = UNTICKETED_ANNOTATION_RE.search(line)
            if match and not re.search(r"\bOMN-\d+\b", match.group("rest")):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, (
        "Bypass annotation with no OMN ticket — the debt would be untracked:\n"
        + "\n".join(offenders)
    )


def test_scanner_sees_the_known_inner_checkouts() -> None:
    """Positive control: a parser that matches nothing must not read as green.

    Every assertion above is vacuously true if ``_collect`` returns an empty
    list — which is exactly what a YAML-shape regression (the ``on:`` -> ``True``
    key being the classic one) produces. This pins the scanner against reality.
    """
    found = _collect(WORKFLOWS_DIR)
    assert found, (
        "Scanner found ZERO cross-repo checkouts in reusable workflows. This "
        "repo demonstrably has several, so the scanner is broken, not the "
        "workflows. Check the `on:` -> YAML-`True` key handling in _is_reusable."
    )
    reusable_files = {c.workflow for c in found}
    assert len(reusable_files) >= 3, (
        "Scanner matched only "
        f"{sorted(reusable_files)}; it previously saw several reusable "
        "workflows with cross-repo checkouts. Under-matching is invisible."
    )


# --------------------------------------------------------------------------
# Matcher unit tests (fixtures, not this repo's workflows)
# --------------------------------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    """Write one fixture workflow. ``body`` is already flush-left YAML."""
    directory = tmp_path / "workflows"
    directory.mkdir(exist_ok=True)
    (directory / "sample.yml").write_text(body, encoding="utf-8")
    return directory


REUSABLE_HEADER = (
    "name: sample\n"
    "on:\n"
    "  workflow_call:\n"
    "    inputs:\n"
    "      validator_ref:\n"
    "        type: string\n"
    "        required: false\n"
    "jobs:\n"
    "  gate:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
)


def _checkout_step(ref_line: str, sparse: bool = False, assertion: bool = False) -> str:
    sparse_block = (
        "          sparse-checkout: |\n            scripts/validator.py\n"
        if sparse
        else ""
    )
    assert_block = (
        "      - name: Assert fetched paths exist\n"
        "        run: test -f side/scripts/validator.py"
        ' || { echo "::error::validator missing"; exit 1; }\n'
        if assertion
        else ""
    )
    return (
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          repository: OmniNode-ai/omniclaude\n"
        f"{ref_line}"
        "          path: side\n"
        f"{sparse_block}"
        f"{assert_block}"
    )


@pytest.mark.parametrize(
    "ref_line",
    [
        "          ref: main\n",
        "          ref: dev\n",
        "          ref: ${{ github.sha }}\n",
        "",
    ],
)
def test_self_checkout_moving_or_missing_refs_are_refused(
    tmp_path: Path, ref_line: str
) -> None:
    directory = _write(tmp_path, REUSABLE_HEADER + _checkout_step(ref_line))
    checkouts = _collect(directory)
    assert len(checkouts) == 1
    verdict = _ref_verdict(checkouts[0], "OmniNode-ai/omniclaude")
    assert verdict is not None


@pytest.mark.parametrize(
    ("repository", "ref"),
    [
        ("OmniNode-ai/omniclaude", "${{ github.job_workflow_sha }}"),
        (
            "OmniNode-ai/omniclaude",
            "${{ inputs.validator_ref || github.job_workflow_sha }}",
        ),
        ("OmniNode-ai/omnimarket", "${{ github.job_workflow_sha }}"),
        (
            "OmniNode-ai/omnimarket",
            "${{ inputs.validator_ref || github.job_workflow_sha }}",
        ),
    ],
)
def test_legacy_github_job_workflow_sha_is_refused_everywhere(
    tmp_path: Path, repository: str, ref: str
) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step(f"          ref: {ref}\n").replace(
            "repository: OmniNode-ai/omniclaude", f"repository: {repository}"
        ),
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None
    assert "does not exist in the github context" in verdict
    assert "evaluates to an empty string" in verdict
    assert "default branch" in verdict
    assert "validated 'job.workflow_sha' pin step" in verdict


@pytest.mark.parametrize(
    "ref",
    [
        "${{ job.workflow_sha }}",
        "${{ inputs.validator_ref }}",
        "${{ inputs.validator_ref || job.workflow_sha }}",
    ],
)
def test_unvalidated_self_checkout_expressions_are_refused(
    tmp_path: Path, ref: str
) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER + _checkout_step(f"          ref: {ref}\n"),
    )
    assert _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude") is not None


PIN_STEP = """\
      - name: Resolve the gate pin
        id: pin
        env:
          WORKFLOW_SHA: ${{ job.workflow_sha }}
        run: |
          set -euo pipefail
          if [[ ! "$WORKFLOW_SHA" =~ ^[0-9a-f]{40}$ ]]; then
            exit 1
          fi
          echo "sha=$WORKFLOW_SHA" >> "$GITHUB_OUTPUT"
"""

HEAD_CHECK_STEP = """\
      - name: Assert the gate checkout is at the pin
        env:
          GATE_PIN: ${{ steps.pin.outputs.sha }}
        run: |
          set -euo pipefail
          checked_out_sha="$(git -C side rev-parse HEAD)"
          test "$checked_out_sha" = "$GATE_PIN"
"""


def test_valid_pin_step_and_head_check_are_accepted(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + PIN_STEP
        + _checkout_step("          ref: ${{ steps.pin.outputs.sha }}\n")
        + HEAD_CHECK_STEP,
    )
    assert _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude") is None


def test_pin_step_without_40_hex_validation_is_refused(tmp_path: Path) -> None:
    pin_step = PIN_STEP.replace(
        '          if [[ ! "$WORKFLOW_SHA" =~ ^[0-9a-f]{40}$ ]]; then\n',
        '          if [ -z "$WORKFLOW_SHA" ]; then\n',
    )
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + pin_step
        + _checkout_step("          ref: ${{ steps.pin.outputs.sha }}\n")
        + HEAD_CHECK_STEP,
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "^[0-9a-f]{40}$" in verdict


def test_pin_step_reading_legacy_property_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + PIN_STEP.replace("job.workflow_sha", "github.job_workflow_sha")
        + _checkout_step("          ref: ${{ steps.pin.outputs.sha }}\n")
        + HEAD_CHECK_STEP,
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "does not exist in the github context" in verdict


def test_step_output_from_nonexistent_step_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step("          ref: ${{ steps.missing.outputs.sha }}\n"),
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "does not exist earlier" in verdict


def test_step_output_from_step_after_checkout_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step("          ref: ${{ steps.pin.outputs.sha }}\n")
        + PIN_STEP,
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "does not exist earlier" in verdict


def test_output_name_not_written_by_pin_step_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + PIN_STEP
        + _checkout_step("          ref: ${{ steps.pin.outputs.commit }}\n")
        + HEAD_CHECK_STEP.replace("outputs.sha", "outputs.commit"),
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "does not write output 'commit'" in verdict


def test_valid_pin_without_head_check_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + PIN_STEP
        + _checkout_step("          ref: ${{ steps.pin.outputs.sha }}\n"),
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "no later step runs 'rev-parse HEAD'" in verdict


def test_literal_40_hex_self_checkout_ref_is_accepted(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step("          ref: 0123456789abcdef0123456789abcdef01234567\n"),
    )
    assert _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude") is None


@pytest.mark.parametrize(
    "ref",
    [
        "${{ inputs.omnimarket-ref }}",
        "0123456789abcdef0123456789abcdef01234567",
    ],
)
def test_third_repo_pinned_ref_is_accepted(tmp_path: Path, ref: str) -> None:
    """Another repo takes a caller-controlled input or a literal commit pin."""
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          repository: OmniNode-ai/omnimarket\n"
            f"          ref: {ref}\n"
        ),
    )
    assert _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude") is None


def test_third_repo_branch_ref_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + (
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          repository: OmniNode-ai/omnimarket\n"
            "          ref: dev\n"
        ),
    )
    verdict = _ref_verdict(_collect(directory)[0], "OmniNode-ai/omniclaude")
    assert verdict is not None and "moving branch" in verdict


def test_sparse_without_assertion_is_refused(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step(
            "          ref: 0123456789abcdef0123456789abcdef01234567\n",
            sparse=True,
        ),
    )
    verdict = _sparse_verdict(_collect(directory)[0])
    assert verdict is not None and "empty directory" in verdict


def test_sparse_with_assertion_passes(tmp_path: Path) -> None:
    directory = _write(
        tmp_path,
        REUSABLE_HEADER
        + _checkout_step(
            "          ref: 0123456789abcdef0123456789abcdef01234567\n",
            sparse=True,
            assertion=True,
        ),
    )
    assert _sparse_verdict(_collect(directory)[0]) is None


def test_non_reusable_workflow_is_out_of_scope(tmp_path: Path) -> None:
    """A plain PR workflow has no workflow_sha to pin to."""
    directory = _write(
        tmp_path,
        textwrap.dedent(
            """\
            name: sample
            on:
              pull_request:
            jobs:
              gate:
                runs-on: ubuntu-latest
                steps:
                  - uses: actions/checkout@v4
                    with:
                      repository: OmniNode-ai/omniclaude
                      ref: main
            """
        ),
    )
    assert _collect(directory) == []


def test_bare_self_checkout_is_out_of_scope(tmp_path: Path) -> None:
    """No ``repository:`` means the caller's own tree — the normal case."""
    directory = _write(
        tmp_path,
        REUSABLE_HEADER + "      - uses: actions/checkout@v4\n",
    )
    assert _collect(directory) == []
