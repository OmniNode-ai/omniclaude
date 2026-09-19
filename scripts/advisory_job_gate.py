#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""No-new-advisory-job gate. OMN-18777, epic OMN-18775.

Two refusals, both about a check that runs and cannot fail:

  1. ADVISORY_UNANNOTATED -- a `continue-on-error: true` that is neither in the
     census baseline nor carries `# advisory-ok: OMN-nnnnn <reason>`.
  2. UNENFORCED_VERIFICATION_JOB -- a verification-shaped job reachable by a
     pull request that appears in neither enforcement surface (the branch's
     `required_status_checks`, or the repo's `EXPECTED_EXTERNAL_CONTEXTS`
     umbrella constant), is not in the baseline, and is not annotated.

WHY. The OMN-18775 inventory counted 64 real `continue-on-error: true` settings
across six repositories, 12 of them making a whole job advisory. Some are
load-bearing: the omnimarket OCC publisher jobs are deliberately non-blocking,
and one omnibase_infra setting carries a comment saying it is "REQUIRED here,
not optional polish". Others are drift. Nothing distinguished them, so the
census could not be acted on and the count only grew. The same inventory found
`fresh-deploy-fitness` running on every pull request, in neither enforcement
surface, 30/30 green -- a number that carries no information.

THE SHAPE IS BORROWED, not invented. `# raw-prod-bypass-ok:` already lets a
deliberate exception through a refusal while leaving a citable artifact, and
CLAUDE.md rule 12 already governs it. Same mechanism, different vocabulary.

WHAT THIS CANNOT DO, stated rather than implied. It cannot tell a good reason
from a bad one written in the annotation, and no file can. What it removes is
the SILENT accumulation: a setting landing with nothing naming it and nobody
reading it. It also does not read branch protection historically -- it reads
the surface live, and a context renamed out from under a job shows up as that
job becoming unenforced, which is the correct reading.

FAIL-CLOSED. An unreadable workflow, an unresolvable enforcement surface, an
unparseable baseline and a malformed annotation are each exit 2 naming
themselves, never a pass. There is no skip input, no force flag and no
report-only mode; `tests/scripts/test_advisory_job_gate.py` reads this file's
own parser option strings, so adding one is a red test rather than a review
catch.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# The annotation. Ticket FIRST, then a reason -- both required. A ticket with
# no reason is a bare citation and says nothing about why; a reason with no
# ticket is the free-text justification CLAUDE.md rule 10 already refuses as a
# bypass ("self-judgement is not evidence").
ANNOTATION = re.compile(
    r"#\s*advisory-ok:\s*(?P<ticket>OMN-\d+)\s+(?P<reason>\S.*?)\s*$",
    re.IGNORECASE,
)

# The same marker WITHOUT the rest of the pattern. Detected separately so the
# failure names itself: an author who wrote an exemption and got a bare
# "unannotated" verdict sees a gate that ignored what they wrote, which is a
# correct verdict for an incomprehensible reason.
ANNOTATION_MARKER = re.compile(r"#\s*advisory-ok:", re.IGNORECASE)

# Verification shape, from the job id and name. Deliberately broad and
# deliberately substring-matched: the ticket's instruction is to accept false
# positives and let the annotation carry the ones that are genuinely
# notification or automation. A narrow matcher is how the next
# fresh-deploy-fitness gets in.
VERIFICATION_WORDS = re.compile(
    r"test|gate|valid|verif|scan|lint|check|audit|guard|complian|policy|"
    r"ratchet|enforce|review|typecheck|mypy|coverage|hygiene|drift|probe",
    re.IGNORECASE,
)

# Verification shape, from what a step actually runs. A job called `ci` whose
# steps run pytest is a test job whatever it is called.
VERIFICATION_COMMANDS = re.compile(
    r"\bpytest\b|\bmypy\b|\bruff\b|\btsc\b|\beslint\b|\bnpm (run )?(test|lint)\b|"
    r"\bpre-commit\b|validate_|check_|_gate\.py|verify_|audit_|assert_",
    re.IGNORECASE,
)

# Only a job a PULL REQUEST can reach can be a required status check, so
# refusing a scheduled or release-only job for being absent from one would be a
# false refusal about a surface it was never eligible for.
PR_TRIGGERS = ("pull_request", "pull_request_target", "merge_group")

CONTEXT_CACHE = "advisory-job-gate-contexts.json"
CACHE_TTL_SECONDS = 24 * 60 * 60


class GateError(RuntimeError):
    """A condition under which the gate refuses to return a verdict."""


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int
    key: str
    detail: str

    def render(self) -> str:
        return f"{self.kind}  {self.path}:{self.line}\n    {self.detail}\n    key: {self.key}"


@dataclass(frozen=True)
class Occurrence:
    """One `continue-on-error: true`, located and identified."""

    path: str
    line: int
    key: str
    where: str


@dataclass(frozen=True)
class Job:
    path: str
    line: int
    key: str
    job_id: str
    name: str | None
    contexts: tuple[str, ...]
    needs: tuple[str, ...]
    verification: bool


def _fail(message: str) -> GateError:
    return GateError(message)


# --------------------------------------------------------------------------
# YAML with line numbers
# --------------------------------------------------------------------------


def _compose(text: str, where: str) -> Any:
    try:
        node = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise _fail(f"{where}: unreadable YAML ({error.__class__.__name__}): {error}")
    if node is None:
        raise _fail(f"{where}: empty document")
    return node


def _mapping(node: Any, where: str) -> list[tuple[Any, Any]]:
    if not isinstance(node, yaml.MappingNode):
        raise _fail(f"{where}: expected a mapping, found {type(node).__name__}")
    return list(node.value)


def _get(node: Any, key: str) -> tuple[Any, Any] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for key_node, value_node in node.value:
        if isinstance(key_node, yaml.ScalarNode) and key_node.value == key:
            return key_node, value_node
    return None


def _scalar(node: Any) -> str | None:
    return node.value if isinstance(node, yaml.ScalarNode) else None


def _is_true(node: Any) -> bool:
    """A literal true. An expression is a shape this gate does not read, and is
    reported as unreadable rather than silently treated as false."""
    value = _scalar(node)
    return value is not None and value.strip().lower() == "true"


def _plain(text: str) -> Any:
    """The same document as plain data, for the parts that need no line."""
    return yaml.safe_load(text)


# --------------------------------------------------------------------------
# Annotation lookup
# --------------------------------------------------------------------------


def _annotation(lines: list[str], line: int) -> tuple[bool, bool]:
    """Return (annotated, marker_without_annotation) for a 1-based line.

    Accepted on the line itself, or on the single comment-only line directly
    above it -- the two spellings a YAML author actually writes. Two lines up is
    NOT accepted: an annotation separated from what it excuses drifts onto the
    wrong key the next time someone edits between them.
    """
    candidates: list[str] = []
    if 1 <= line <= len(lines):
        candidates.append(lines[line - 1])
    if 2 <= line <= len(lines):
        above = lines[line - 2]
        if above.lstrip().startswith("#"):
            candidates.append(above)
    annotated = any(ANNOTATION.search(text) for text in candidates)
    marker = any(ANNOTATION_MARKER.search(text) for text in candidates)
    return annotated, marker and not annotated


# --------------------------------------------------------------------------
# Scanning one workflow
# --------------------------------------------------------------------------


def _triggers(document: Any, where: str) -> set[str]:
    node = _get(document, "on") or _get(document, "true")
    if node is None:
        raise _fail(f"{where}: no `on:` trigger block")
    value = node[1]
    if isinstance(value, yaml.ScalarNode):
        return {value.value}
    if isinstance(value, yaml.SequenceNode):
        return {item.value for item in value.value if isinstance(item, yaml.ScalarNode)}
    if isinstance(value, yaml.MappingNode):
        return {key.value for key, _ in value.value if isinstance(key, yaml.ScalarNode)}
    raise _fail(f"{where}: unreadable `on:` block")


def _step_label(step: Any, index: int) -> str:
    name = _get(step, "name") or _get(step, "uses") or _get(step, "run")
    label = _scalar(name[1]) if name else None
    if label:
        label = label.strip().splitlines()[0][:60]
    return f"step[{index}] {label}" if label else f"step[{index}]"


def _job_contexts(job_id: str, name: str | None, has_uses: bool) -> tuple[str, ...]:
    """Every spelling the check context could take for this job.

    A normal job surfaces as its `name` when it has one and its id otherwise. A
    job whose body is a `uses:` surfaces as `<caller job id> / <called job
    name>`, which this gate cannot know without fetching the called workflow --
    so the caller id followed by a separator is matched as a prefix instead.
    Deliberately forgiving: a false PASS here costs one unenforced job the
    baseline already tolerates, a false FAIL costs every PR in the repo.
    """
    contexts = [job_id]
    if name:
        contexts.append(name)
    if has_uses:
        contexts.append(f"{job_id} / ")
    return tuple(contexts)


def scan_workflow(path: Path, repo_root: Path) -> tuple[list[Occurrence], list[Job]]:
    relative = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    document = _compose(text, relative)
    triggers = _triggers(document, relative)
    pr_reachable = bool(triggers & set(PR_TRIGGERS))

    jobs_node = _get(document, "jobs")
    if jobs_node is None:
        return [], []

    occurrences: list[Occurrence] = []
    jobs: list[Job] = []

    for job_key, job_node in _mapping(jobs_node[1], f"{relative}: jobs"):
        job_id = _scalar(job_key)
        if job_id is None:
            raise _fail(f"{relative}: a job key is not a scalar")
        if not isinstance(job_node, yaml.MappingNode):
            raise _fail(f"{relative}: job `{job_id}` is not a mapping")

        job_level = _get(job_node, "continue-on-error")
        if job_level is not None and _is_true(job_level[1]):
            occurrences.append(
                Occurrence(
                    path=relative,
                    line=job_level[0].start_mark.line + 1,
                    key=f"{relative}::{job_id}::JOB",
                    where=f"job `{job_id}` is advisory in full",
                )
            )

        steps_node = _get(job_node, "steps")
        step_values = (
            steps_node[1].value
            if steps_node is not None and isinstance(steps_node[1], yaml.SequenceNode)
            else []
        )
        run_text: list[str] = []
        for index, step in enumerate(step_values):
            if not isinstance(step, yaml.MappingNode):
                raise _fail(f"{relative}: job `{job_id}` step {index} is not a mapping")
            step_level = _get(step, "continue-on-error")
            if step_level is not None and _is_true(step_level[1]):
                occurrences.append(
                    Occurrence(
                        path=relative,
                        line=step_level[0].start_mark.line + 1,
                        key=f"{relative}::{job_id}::step[{index}]",
                        where=f"job `{job_id}`, {_step_label(step, index)}",
                    )
                )
            for field in ("run", "uses"):
                found = _get(step, field)
                if found is not None:
                    value = _scalar(found[1])
                    if value:
                        run_text.append(value)

        needs_node = _get(job_node, "needs")
        needs: tuple[str, ...] = ()
        if needs_node is not None:
            value = needs_node[1]
            if isinstance(value, yaml.ScalarNode):
                needs = (value.value,)
            elif isinstance(value, yaml.SequenceNode):
                needs = tuple(
                    item.value
                    for item in value.value
                    if isinstance(item, yaml.ScalarNode)
                )
            else:
                raise _fail(f"{relative}: job `{job_id}` has an unreadable `needs:`")

        name_node = _get(job_node, "name")
        name = _scalar(name_node[1]) if name_node is not None else None
        uses_node = _get(job_node, "uses")
        has_uses = uses_node is not None
        if uses_node is not None:
            uses = _scalar(uses_node[1])
            if uses:
                run_text.append(uses)

        verification = bool(
            VERIFICATION_WORDS.search(job_id)
            or (name and VERIFICATION_WORDS.search(name))
            or any(VERIFICATION_COMMANDS.search(item) for item in run_text)
        )
        if pr_reachable:
            jobs.append(
                Job(
                    path=relative,
                    line=job_key.start_mark.line + 1,
                    key=f"{relative}::{job_id}",
                    job_id=job_id,
                    name=name,
                    contexts=_job_contexts(job_id, name, has_uses),
                    needs=needs,
                    verification=verification,
                )
            )

    # Every occurrence needs its annotation read from the raw lines, which the
    # node tree has thrown away.
    return occurrences, jobs


def workflow_paths(repo_root: Path) -> list[Path]:
    directory = repo_root / ".github" / "workflows"
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.suffix in (".yml", ".yaml") and path.is_file()
    )


# --------------------------------------------------------------------------
# Enforcement surfaces
# --------------------------------------------------------------------------


def expected_external_contexts(repo_root: Path) -> tuple[list[str], str]:
    """The CI-summary umbrella constant, parsed statically.

    On omnibase_infra and omnimarket the umbrella IS the enforcement surface --
    a context missing from that tuple is silently unenforced with no
    branch-protection signal that it is missing (CLAUDE.md, deploy-gate table).
    """
    path = repo_root / "scripts" / "ci" / "ci_summary_gate.py"
    if not path.is_file():
        return [], f"no {path.relative_to(repo_root).as_posix()} in this repo"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as error:
        raise _fail(f"{path}: unparseable ({error})")
    for node in ast.walk(tree):
        # BOTH assignment shapes. omnibase_infra spells it
        # `EXPECTED_EXTERNAL_CONTEXTS: tuple[str, ...] = (...)`, an AnnAssign,
        # and an Assign-only walk read it as absent -- a silent zero that put
        # every one of that repo's externally-asserted contexts into the
        # unenforced column. Caught by a positive control on the constant
        # itself, not by the verdict, which looked entirely plausible.
        value_node: ast.expr | None
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value_node = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value_node = node.value
        else:
            continue
        if "EXPECTED_EXTERNAL_CONTEXTS" not in names or value_node is None:
            continue
        try:
            value = ast.literal_eval(value_node)
        except ValueError as error:
            raise _fail(
                f"{path}: EXPECTED_EXTERNAL_CONTEXTS is not a literal ({error})"
            )
        contexts = [str(item) for item in value]
        return contexts, f"{len(contexts)} from EXPECTED_EXTERNAL_CONTEXTS"
    return [], "EXPECTED_EXTERNAL_CONTEXTS absent from ci_summary_gate.py"


def _gh(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=60, check=False
    )
    if result.returncode != 0:
        raise _fail(
            f"`gh {' '.join(args)}` exited {result.returncode}: "
            f"{result.stderr.strip() or '(no stderr)'}"
        )
    return result.stdout


def resolve_required_contexts(slug: str, repo_root: Path) -> tuple[list[str], str]:
    """Live `required_status_checks` for the repository's default branch.

    Read live, never from a list that goes stale -- the same posture the
    public-repo hygiene gate takes on visibility. A 24h cache under `.git/`
    keeps a local pre-commit run cheap; a cache older than that is not used,
    and when neither the live read nor a fresh cache answers, the gate refuses.
    """
    # In a WORKTREE `.git` is a file, not a directory (CLAUDE.md rule 17), so
    # there is nowhere to cache. Best-effort by design: a missing cache costs a
    # live read, never a verdict.
    git_dir = repo_root / ".git"
    cache = (git_dir / CONTEXT_CACHE) if git_dir.is_dir() else None
    try:
        branch = json.loads(
            _gh(["api", f"repos/{slug}", "--jq", "{b:.default_branch}"])
        )["b"]
        payload = _gh(
            [
                "api",
                f"repos/{slug}/branches/{branch}/protection/required_status_checks",
                "--jq",
                ".contexts",
            ]
        )
        contexts = [str(item) for item in json.loads(payload)]
    except (
        GateError,
        json.JSONDecodeError,
        KeyError,
        OSError,
        subprocess.SubprocessError,
    ) as error:
        if cache is not None and cache.is_file():
            try:
                cached = json.loads(cache.read_text(encoding="utf-8"))
                age = time.time() - float(cached["fetched_at"])
                if age < CACHE_TTL_SECONDS and cached["repo"] == slug:
                    return (
                        [str(item) for item in cached["contexts"]],
                        f"{len(cached['contexts'])} from the {int(age)}s-old .git cache "
                        f"(live read failed: {error})",
                    )
            except (ValueError, KeyError, OSError):
                pass
        raise _fail(
            f"could not resolve required_status_checks for {slug} and no fresh "
            f"cache exists: {error}"
        )
    try:
        if cache is None:
            raise OSError("no .git directory to cache in")
        cache.write_text(
            json.dumps({"repo": slug, "fetched_at": time.time(), "contexts": contexts}),
            encoding="utf-8",
        )
    except OSError:
        pass
    return contexts, f"{len(contexts)} live from {slug}@{branch} branch protection"


def enforced(contexts: list[str], candidates: tuple[str, ...]) -> bool:
    for candidate in candidates:
        if candidate.endswith(" / "):
            if any(context.startswith(candidate) for context in contexts):
                return True
        elif candidate in contexts:
            return True
    return False


def enforced_jobs(jobs: list[Job], contexts: list[str]) -> set[str]:
    """Job ids in ONE workflow that a required context can fail on.

    Directly, by being a required context themselves -- and TRANSITIVELY, by
    being `needs:` of one that is. This half is not a nicety: the whole
    CI-summary pattern is one required umbrella job that `needs:` every other
    job in the file, and without the closure every job under an umbrella reads
    as unenforced. That mis-reading is not conservative, it is the opposite:
    it would have put roughly four hundred correctly-enforced jobs into the
    grandfather list, and a baseline that large is where a real finding hides.
    """
    direct = {job.job_id for job in jobs if enforced(contexts, job.contexts)}
    if not direct:
        return set()

    # THE UMBRELLA IS PER FILE, not per edge. omnibase_infra's `CI Summary`
    # carries NO `needs:` ON PURPOSE (ci.yml, the OMN-14127 comment): a
    # needs-gated summary gets no check-run until its needs terminalize, so
    # under fleet saturation the required context was ABSENT forever and the PR
    # wedged BLOCKED with zero failing and zero pending checks. It polls the
    # run's job conclusions instead, default-deny. A graph closure sees no edge
    # there and would report every job in that file unenforced -- 111 of them,
    # which is not a conservative reading but a useless one.
    #
    # So a required context ANYWHERE in a workflow file covers that file. The
    # concession this makes is real and is stated: a job added to a
    # needs-gated summary's file but NOT added to its `needs:` list reads as
    # enforced here and is not. That residual belongs to the summary's own
    # default-deny sweep, which is the surface that owns it; what this gate is
    # for is the job in a file NOTHING required ever reads -- the
    # fresh-deploy-fitness shape.
    reached = {job.job_id for job in jobs}
    return reached


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def load_baseline(path: Path, slug: str) -> tuple[set[str], set[str]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise _fail(f"{path}: unreadable baseline ({error})")
    if not isinstance(payload, dict) or "repos" not in payload:
        raise _fail(f"{path}: baseline has no `repos:` block")
    repo = payload["repos"].get(slug)
    if repo is None:
        return set(), set()
    advisory: set[str] = set()
    jobs: set[str] = set()
    for field, sink in (("advisory", advisory), ("verification_jobs", jobs)):
        for entry in repo.get(field) or []:
            for required in ("path", "line", "key"):
                if required not in entry:
                    raise _fail(
                        f"{path}: a `{field}` entry for {slug} has no `{required}`. "
                        "Every grandfathered line is named individually; a blanket "
                        "cutoff is not a baseline."
                    )
            if not isinstance(entry["line"], int):
                raise _fail(f"{path}: `{entry['key']}` has a non-integer line")
            sink.add(str(entry["key"]))
    return advisory, jobs


# --------------------------------------------------------------------------
# The verdict
# --------------------------------------------------------------------------


def scan(
    repo_root: Path,
    baseline_advisory: set[str],
    baseline_jobs: set[str],
    contexts: list[str],
) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    stale: list[str] = []
    seen_advisory: set[str] = set()
    seen_jobs: set[str] = set()

    for path in workflow_paths(repo_root):
        occurrences, jobs = scan_workflow(path, repo_root)
        lines = path.read_text(encoding="utf-8").splitlines()

        for occurrence in occurrences:
            seen_advisory.add(occurrence.key)
            if occurrence.key in baseline_advisory:
                continue
            annotated, malformed = _annotation(lines, occurrence.line)
            if annotated:
                continue
            findings.append(
                Finding(
                    kind="MALFORMED_ANNOTATION"
                    if malformed
                    else "ADVISORY_UNANNOTATED",
                    path=occurrence.path,
                    line=occurrence.line,
                    key=occurrence.key,
                    detail=(
                        "an `# advisory-ok:` marker is present but is not one line "
                        "carrying a ticket AND a reason"
                        if malformed
                        else f"{occurrence.where}: a new `continue-on-error: true` "
                        "with nothing naming it. Add "
                        "`# advisory-ok: OMN-nnnnn <reason>` on this line or the "
                        "line above, or remove the setting."
                    ),
                )
            )

        covered = enforced_jobs(jobs, contexts)
        for job in jobs:
            if not job.verification:
                continue
            seen_jobs.add(job.key)
            if job.key in baseline_jobs or job.job_id in covered:
                continue
            annotated, malformed = _annotation(lines, job.line)
            if annotated:
                continue
            findings.append(
                Finding(
                    kind="MALFORMED_ANNOTATION"
                    if malformed
                    else "UNENFORCED_VERIFICATION_JOB",
                    path=job.path,
                    line=job.line,
                    key=job.key,
                    detail=(
                        "an `# advisory-ok:` marker is present but is not one line "
                        "carrying a ticket AND a reason"
                        if malformed
                        else f"job `{job.job_id}` runs on every pull request, looks "
                        "like verification, and is in neither "
                        "`required_status_checks` nor `EXPECTED_EXTERNAL_CONTEXTS`. "
                        "It cannot fail anything. Enforce it, or annotate it "
                        "`# advisory-ok: OMN-nnnnn <reason>` if it is notification "
                        "or automation."
                    ),
                )
            )

    for key in sorted(baseline_advisory - seen_advisory):
        stale.append(f"advisory baseline entry no longer present: {key}")
    for key in sorted(baseline_jobs - seen_jobs):
        stale.append(f"verification-job baseline entry no longer present: {key}")
    return findings, stale


def write_baseline(
    repo_root: Path, slug: str, contexts: list[str], destination: Path
) -> int:
    advisory: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for path in workflow_paths(repo_root):
        occurrences, found = scan_workflow(path, repo_root)
        for occurrence in occurrences:
            advisory.append(
                {
                    "path": occurrence.path,
                    "line": occurrence.line,
                    "key": occurrence.key,
                }
            )
        covered = enforced_jobs(found, contexts)
        for job in found:
            if job.verification and job.job_id not in covered:
                jobs.append({"path": job.path, "line": job.line, "key": job.key})
    payload = {
        "version": 1,
        "repos": {
            slug: {
                "advisory": advisory,
                "verification_jobs": jobs,
                "recorded_contexts": sorted(contexts),
            }
        },
    }
    destination.write_text(
        yaml.safe_dump(payload, sort_keys=False, width=100), encoding="utf-8"
    )
    print(
        f"wrote {destination}: {len(advisory)} advisory, "
        f"{len(jobs)} unenforced verification jobs"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", type=Path)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY"),
        help="owner/name of the repository under test; defaults to $GITHUB_REPOSITORY",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help=(
            "path to the census baseline. FIXTURE FLAG: substitutes a file for "
            "the committed baseline and is refused inside GitHub Actions."
        ),
    )
    parser.add_argument(
        "--required-contexts-json",
        type=Path,
        help=(
            "path to a JSON array of required status check contexts, used "
            "INSTEAD of the live read. FIXTURE FLAG: refused inside GitHub "
            "Actions, because a fixture cannot go stale the way the live "
            "surface can."
        ),
    )
    parser.add_argument(
        "--write-baseline",
        type=Path,
        help=(
            "regenerate the baseline for this repository and write it here, "
            "then exit. FIXTURE FLAG: refused inside GitHub Actions -- a run "
            "that rewrites its own baseline has no verdict to give."
        ),
    )
    args = parser.parse_args(argv)

    fixtures = [
        name
        for name, value in (
            ("--baseline", args.baseline),
            ("--required-contexts-json", args.required_contexts_json),
            ("--write-baseline", args.write_baseline),
        )
        if value
    ]
    if fixtures and os.environ.get("GITHUB_ACTIONS") == "true":
        print(
            f"::error::{', '.join(fixtures)} substitutes a file for what the "
            "gate is supposed to read and is for tests and local runs only. "
            "THE GATE DID NOT RUN.",
            file=sys.stderr,
        )
        return 2

    if not args.repo:
        print(
            "::error::--repo (or $GITHUB_REPOSITORY) is required: the "
            "enforcement surface is resolved live per repository, never "
            "guessed. THE GATE DID NOT RUN.",
            file=sys.stderr,
        )
        return 2

    repo_root: Path = args.repo_root.resolve()
    baseline_path: Path = args.baseline or (
        Path(__file__).resolve().parent.parent / "config" / "advisory_job_baseline.yaml"
    )

    try:
        if args.required_contexts_json is not None:
            required = [
                str(item)
                for item in json.loads(
                    args.required_contexts_json.read_text(encoding="utf-8")
                )
            ]
            required_source = f"{len(required)} from {args.required_contexts_json}"
        else:
            required, required_source = resolve_required_contexts(args.repo, repo_root)
        umbrella, umbrella_source = expected_external_contexts(repo_root)
        contexts = sorted({*required, *umbrella})

        if args.write_baseline is not None:
            return write_baseline(repo_root, args.repo, contexts, args.write_baseline)

        baseline_advisory, baseline_jobs = load_baseline(baseline_path, args.repo)
        findings, stale = scan(repo_root, baseline_advisory, baseline_jobs, contexts)
    except GateError as error:
        print(f"::error::{error} THE GATE DID NOT RUN.", file=sys.stderr)
        return 2

    print(f"advisory-job-gate: {args.repo} at {repo_root}")
    print(f"  required status checks: {required_source}")
    print(f"  umbrella constant:      {umbrella_source}")
    print(
        f"  baseline:               {len(baseline_advisory)} advisory, "
        f"{len(baseline_jobs)} verification jobs grandfathered "
        f"({baseline_path.name})"
    )
    for note in stale:
        # A baseline entry that has gone is the DESIRED direction, so it is a
        # reconcile note and not a failure. Refusing the removal of an advisory
        # setting would make the gate punish the only fix it wants.
        print(f"  reconcile: {note}")

    if not findings:
        print(
            "PASS: no unannotated advisory setting and no unenforced verification job."
        )
        return 0

    print("")
    for finding in sorted(findings, key=lambda f: (f.path, f.line)):
        print(finding.render())
    print("")
    print(
        f"FAIL: {len(findings)} finding(s). A check that runs and cannot fail is a "
        "line in a CI listing that reads as coverage (OMN-18775). Either make it "
        "able to fail, or name it: `# advisory-ok: OMN-nnnnn <reason>`."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
