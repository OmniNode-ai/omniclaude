# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Guards on the Hostile Reviewer's runner placement and its stderr (OMN-18415).

TWO PROPERTIES, BOTH OF WHICH FAILED SILENTLY BEFORE THIS FILE EXISTED.

1. PLACEMENT. The reviewer calls DeepSeek-R1 on the lab host over the LAN,
   reading ``LLM_DEEPSEEK_R1_URL`` and two trust-boundary variables from the
   runner's own environment. Only the self-hosted ``omnibase-ci`` fleet carries
   any of them. omniclaude is a PUBLIC repository whose
   ``OMNI_TRUSTED_CI_RUNS_ON_JSON`` seam is deliberately ``["ubuntu-latest"]``
   at org and repo scope, and the job's selector *also* sent every same-repo
   pull request based on ``dev`` down the fork-isolation branch. So the job
   landed hosted on every real PR, could not reach the model, and reported
   ``infra_error`` on a REQUIRED check -- measured on omniclaude#2181 run
   35043714512 attempt 4, which executed on a hosted ubuntu-24.04 image.

   The routing node ``node_ci_runner_route_compute`` cannot fix this: it treats
   the caller's seam as a CEILING it may only DOWNGRADE from, so for a public
   repository it returns ``seam_ceiling_hosted`` every time. A lab-touching job
   in a public repository has to sit AHEAD of the seam, which is what the
   narrower ``OMNI_HOSTILE_REVIEW_RUNS_ON_JSON`` variable is for -- the same
   carve-out shape the OCC publishers use for the tailnet-only broker
   (OMN-16691), pinned by ``test_occ_publisher_runner_carveout.py`` beside this.

2. STDERR. ``2>/dev/null`` stood on the ``cli_review`` invocation. Three
   independent fail-closed causes on this one gate -- an absent signing key, an
   absent endpoint CIDR boundary, and a hosted runner with no route at all --
   each had to be reproduced by hand on a laptop to be named, because CI showed
   a bare ``infra_error`` and nothing else. Each was one line of the stderr that
   was being discarded.

The functional tests below execute the workflow's own review script against a
stubbed ``uv`` rather than asserting on its text, so a rewrite that keeps the
words and loses the behaviour fails here.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "hostile-reviewer.yml"

CARVEOUT_VAR = "OMNI_HOSTILE_REVIEW_RUNS_ON_JSON"
SHARED_SEAM_VAR = "OMNI_TRUSTED_CI_RUNS_ON_JSON"
PUBLIC_VAR = "OMNI_PUBLIC_PR_RUNS_ON_JSON"
FLEET_LITERAL = '\'["self-hosted","omnibase-ci"]\''

REVIEW_JOB = "hostile-review"
REVIEW_STEP = "Run adversarial review"
FORK_GUARD_STEP = "Refuse fork-origin pull requests (fail closed, named)"
UPLOAD_STEP = "Upload the verdict artifact"

# The environment variable whose absence produced the first of the three
# fail-closed causes. Named here so the redaction test can assert on it.
SIGNING_KEY_VAR = "LOCAL_LLM_SHARED_SECRET"


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "hostile-reviewer.yml must parse as a mapping"
    return cast("dict[str, Any]", loaded)


def _job(job_id: str) -> dict[str, Any]:
    jobs = _workflow()["jobs"]
    assert job_id in jobs, f"hostile-reviewer.yml must define job `{job_id}`"
    return cast("dict[str, Any]", jobs[job_id])


def _step(job_id: str, step_name: str) -> dict[str, Any]:
    for step in _job(job_id)["steps"]:
        if step.get("name") == step_name:
            return cast("dict[str, Any]", step)
    raise AssertionError(f"`{job_id}` must define a step named `{step_name}`")


# -- placement ------------------------------------------------------------


def test_reviewer_selects_its_runner_from_the_dedicated_carveout_variable() -> None:
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert CARVEOUT_VAR in runs_on, (
        f"`{REVIEW_JOB}` reaches a LAN-only inference endpoint on the lab host "
        f"and must select its runner from the dedicated `{CARVEOUT_VAR}` "
        "variable (OMN-18415)"
    )


def test_reviewer_is_not_governed_by_the_shared_seam() -> None:
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert SHARED_SEAM_VAR not in runs_on, (
        f"`{REVIEW_JOB}` must NOT read `{SHARED_SEAM_VAR}`. That seam is "
        'deliberately ["ubuntu-latest"] for this PUBLIC repository under the '
        "2026-09-14 ruling that public hermetic CI stays hosted. This job is not "
        "hermetic -- it calls a LAN-only model -- so binding it to the seam puts "
        "a required adversarial gate on a runner that cannot reach its own "
        "reviewer, which is the omniclaude#2181 failure this pin exists to stop."
    )


def test_fleet_literal_is_the_operating_value() -> None:
    """The dedicated variable is deliberately UNSET, so the literal places the job.

    Setting the variable is an operator kill switch that must cite a
    reachability proof for whatever runner class it names; it is never a side
    effect of a seam migration. Until then the fallback below is what actually
    selects the runner, so it must name the fleet.
    """
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert FLEET_LITERAL in runs_on, (
        f"`{REVIEW_JOB}` must carry the literal {FLEET_LITERAL} fallback -- with "
        "the dedicated variable unset it is the value that selects the runner"
    )


def test_the_fleet_literal_is_a_fallback_and_not_a_bare_label() -> None:
    """A hardcoded runner label answers to no routing variable at all.

    The hourly runner-routing audit reads Actions variables, so a label written
    straight into a workflow file is invisible to it -- the blind spot rule 14
    names. Pinning this job with a bare ``fromJSON('["self-hosted",...]')``
    places it correctly and leaves nobody able to move it without a code change,
    and no surface able to see that it was moved.
    """
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert f"vars.{CARVEOUT_VAR} || {FLEET_LITERAL}" in runs_on, (
        "the fleet labels must be the FALLBACK of the dedicated variable, not a "
        "bare literal -- one explicit knob is what keeps this placement visible "
        "to the routing audit and killable without a code change"
    )


def test_fork_isolation_branch_is_retained_and_comes_first() -> None:
    """OMN-16683/16684: untrusted fork code never reaches the LAN-attached fleet.

    The fork test must also be the FIRST term, ahead of the carve-out, so no
    capacity or classification argument can be applied before it.
    """
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert PUBLIC_VAR in runs_on, (
        f"`{REVIEW_JOB}` must retain the fork-PR branch through `{PUBLIC_VAR}`"
    )
    assert "head.repo.full_name != github.repository" in runs_on, (
        f"`{REVIEW_JOB}` must retain the fork/non-fork test"
    )
    assert runs_on.index(PUBLIC_VAR) < runs_on.index(CARVEOUT_VAR), (
        "the fork-isolation branch must be evaluated BEFORE the fleet carve-out"
    )


def test_base_branch_is_not_treated_as_untrusted() -> None:
    """The selector must not route same-repo `dev` PRs down the fork branch.

    That extra ``base.ref == 'dev'`` term is what actually sent every real pull
    request in this repository to a hosted runner, which no amount of
    fleet-side provisioning could have fixed. Fork origin is the trust
    question; the base branch is not.
    """
    runs_on = _job(REVIEW_JOB)["runs-on"]
    assert "base.ref" not in runs_on, (
        f"`{REVIEW_JOB}` must decide trust on fork origin alone -- a same-repo "
        "pull request targeting `dev` is not untrusted, and treating it as such "
        "placed the reviewer where its model is unreachable"
    )


def test_fork_origin_pull_requests_fail_closed_with_a_named_reason() -> None:
    """A fork PR cannot produce a verdict, and the absence of one is not a pass.

    A `skip` is not an option either: the gate treats `skipped` as the absence
    of a verdict and fails closed on it, so skipping would produce a red check
    with no reason attached. This is a red check WITH one.
    """
    step = _step(REVIEW_JOB, FORK_GUARD_STEP)
    assert step["if"] == "env.RUNNER_IS_TRUSTED != 'true'", (
        "the fork refusal must be conditioned on the same trust test as `runs-on`"
    )
    script = step["run"]
    assert "exit 1" in script, "the fork path must fail, never pass silently"
    assert "unavailable_fork_isolation" in script, (
        "the refusal must carry a NAMED verdict, not a bare failure"
    )
    assert "::error" in script, "the named reason must reach the job log"

    env = _job(REVIEW_JOB)["env"]
    assert "RUNNER_IS_TRUSTED" in env, (
        "the job must thread the fork/non-fork test into its steps"
    )


# -- stderr (AC3) ---------------------------------------------------------


def test_reviewer_stderr_is_never_discarded_anywhere_in_the_workflow() -> None:
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "2>/dev/null" not in raw, (
        "discarding the reviewer's stderr is the defect OMN-18415 AC3 closes -- "
        "it is where every fail-closed cause this gate has ever had was written"
    )


def test_verdict_artifact_is_uploaded_even_when_the_job_fails() -> None:
    step = _step(REVIEW_JOB, UPLOAD_STEP)
    assert step["if"] == "always()", (
        "the run that most needs its stderr read is the one that failed"
    )
    assert step["uses"].startswith("actions/upload-artifact@"), (
        "the verdict must leave the runner as an artifact"
    )


# -- functional: the script itself, against a stubbed reviewer ------------


def _review_script() -> str:
    script = _step(REVIEW_JOB, REVIEW_STEP)["run"]
    assert "${{" not in script, (
        "the review script must take every value from `env:`, not from inline "
        "expression interpolation -- Actions substitutes those as raw text "
        "before the shell parses them"
    )
    return cast("str", script)


def _run_review_script(
    tmp_path: Path, *, stub: str, extra_env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, dict[str, str]]:
    """Execute the workflow's own review script with `uv` stubbed out."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text(stub, encoding="utf-8")
    uv.chmod(0o755)

    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    github_output = tmp_path / "github-output"
    github_output.write_text("", encoding="utf-8")
    artifact = tmp_path / "hostile-review-verdict.json"

    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "RUNNER_TEMP": str(runner_temp),
        "GITHUB_OUTPUT": str(github_output),
        "VERDICT_ARTIFACT": str(artifact),
        "PR_NUMBER": "2181",
        "REPO": "OmniNode-ai/omniclaude",
    }
    env.update(extra_env or {})

    script = tmp_path / "review.sh"
    script.write_text(_review_script(), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        timeout=180,
        check=False,
    )
    outputs: dict[str, str] = {}
    for line in github_output.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        outputs[key] = value
    return result, artifact, outputs


# A placeholder standing in for a real signing value, so the redaction path can
# be exercised without any real value existing in this repository.
FAKE_SIGNING_VALUE = "placeholder-not-a-real-value-0123456789"

FAILING_STUB = f"""#!/usr/bin/env bash
echo "Review failed for model 'qwen3-review': [ONEX_CORE_041_INVALID_CONFIGURATION] Environment variable {SIGNING_KEY_VAR} is not set." >&2
echo "{FAKE_SIGNING_VALUE}" >&2
echo "ERROR: All models failed. Review could not be performed." >&2
exit 1
"""

PARTIAL_SECRET_STUB = f"""#!/usr/bin/env bash
echo "\\"{FAKE_SIGNING_VALUE}\\"" >&2
echo "unrelated-prefix-{FAKE_SIGNING_VALUE}-suffix" >&2
echo "ERROR: All models failed. Review could not be performed." >&2
exit 1
"""

# A placeholder chosen so each ENCODING of it differs from the raw spelling --
# it carries a quote, a slash and a plus, and no whitespace (a real signing
# value has none, and line-scoped redaction cannot match across a space). A
# value made only of unreserved characters would pass an encoding test that
# tested nothing.
ENCODED_VALUE = 'pl@ceholder/"not+real"0123456789'

# The same value after each transformation it can plausibly survive on its way
# to stderr: a JSON body, a query string, an encoded header.
ENCODED_STUB = """#!/usr/bin/env bash
echo 'json: {json}' >&2
echo 'query: {query}' >&2
echo 'b64: {b64}' >&2
exit 1
""".format(
    json=json.dumps(ENCODED_VALUE)[1:-1],
    query=urllib.parse.quote(ENCODED_VALUE, safe=""),
    b64=base64.b64encode(ENCODED_VALUE.encode()).decode(),
)

# OMN-18479: the reviewer resolves cross-model agreement itself and ships it
# in `quorum`. Every stub below therefore emits the two-model shape the gate
# now reads: a payload with no quorum block, or with fewer succeeded models
# than agreement requires, is DEGRADED QUORUM -- no verdict at all -- and the
# gate fails closed on it (see DEGRADED_QUORUM_STUB).
PASSING_STUB = """#!/usr/bin/env bash
echo "Model 'qwen3-review' succeeded in 233.5s (0 finding(s))." >&2
echo "Model 'gpt-oss-review' succeeded in 41.2s (0 finding(s))." >&2
cat <<'JSON'
{"models_succeeded": ["qwen3-review", "gpt-oss-review"], "total_findings": 0, "results": [{"success": true, "findings": []}], "quorum": {"verdict": "passed", "quorum_threshold": 2, "blocking_count": 0, "warning_count": 0, "blocking_findings": [], "warning_findings": []}}
JSON
exit 0
"""


# The shape `cli_review` actually emits: `ModelReviewFindingObserved` in
# omniintelligence.review_pairing.models, whose fields are `rule_id`,
# `file_path`, `line_start` and `normalized_message`. The first revision of the
# renderer guessed title/message/file and produced a row of three empty cells on
# the live run, which reads as a reviewer with nothing to say.
# Both models raise the same finding, so it reaches quorum and blocks
# (OMN-18479). One model raising it alone is a warning and does not.
BLOCKING_STUB = """#!/usr/bin/env bash
echo "Model 'qwen3-review' succeeded in 6.2s (1 finding(s))." >&2
echo "Model 'gpt-oss-review' succeeded in 8.1s (1 finding(s))." >&2
cat <<'JSON'
{"models_succeeded": ["qwen3-review", "gpt-oss-review"], "total_findings": 2, "results": [{"success": true, "model": "qwen3-review", "findings": [{"severity": "error", "rule_id": "unbounded-retry", "normalized_message": "the loop has no ceiling", "raw_message": "the loop has no ceiling", "file_path": "a/b.py", "line_start": 12, "line_end": 12}]}, {"success": true, "model": "qwen3-review-b", "findings": [{"severity": "error", "rule_id": "unbounded-retry", "normalized_message": "the loop has no ceiling", "raw_message": "the loop has no ceiling", "file_path": "a/b.py", "line_start": 12, "line_end": 12}]}], "quorum": {"verdict": "blocked", "quorum_threshold": 2, "blocking_count": 1, "warning_count": 0, "blocking_findings": [{"agreement_count": 2, "file_path": "a/b.py", "line_start": 12}], "warning_findings": []}}
JSON
exit 0
"""

# A finding whose every mapped key is absent. The renderer must still say
# something, because an empty row is indistinguishable from no finding.
UNMAPPABLE_STUB = """#!/usr/bin/env bash
echo "Model 'qwen3-review' succeeded in 1.0s (1 finding(s))." >&2
echo "Model 'gpt-oss-review' succeeded in 1.4s (1 finding(s))." >&2
cat <<'JSON'
{"models_succeeded": ["qwen3-review", "gpt-oss-review"], "total_findings": 2, "results": [{"success": true, "model": "qwen3-review", "findings": [{"severity": "critical", "some_future_field": "renamed upstream"}]}, {"success": true, "model": "qwen3-review-b", "findings": [{"severity": "critical", "some_future_field": "renamed upstream"}]}], "quorum": {"verdict": "blocked", "quorum_threshold": 2, "blocking_count": 1, "warning_count": 0, "blocking_findings": [{"agreement_count": 2}], "warning_findings": []}}
JSON
exit 0
"""

# One model returned; agreement cannot be established, so there is no verdict
# and the gate fails closed (OMN-18479). Before that ticket this exact payload
# produced a blocking verdict from a single opinion.
DEGRADED_QUORUM_STUB = """#!/usr/bin/env bash
echo "Model 'qwen3-review' succeeded in 6.2s (1 finding(s))." >&2
echo "Model 'gpt-oss-review' FAILED in 0.4s (0 finding(s))." >&2
echo "ERROR: DEGRADED QUORUM \u2014 1 model(s) succeeded, 2 required for agreement." >&2
cat <<'JSON'
{"models_succeeded": ["qwen3-review"], "total_findings": 1, "results": [{"success": true, "model": "qwen3-review", "findings": [{"severity": "error", "rule_id": "unbounded-retry", "normalized_message": "the loop has no ceiling", "raw_message": "the loop has no ceiling", "file_path": "a/b.py", "line_start": 12}]}], "quorum": {"verdict": "degraded_quorum", "quorum_threshold": 2, "blocking_count": 0, "warning_count": 1, "blocking_findings": [], "warning_findings": [{"agreement_count": 1}]}}
JSON
exit 2
"""


def test_a_blocking_verdict_names_the_finding_that_blocked_it(
    tmp_path: Path,
) -> None:
    """`blocked` is the only verdict that stops a merge, so it must be readable.

    The first live run of this gate on a real diff blocked with a finding COUNT
    of 1 and nothing anywhere naming the finding: the reviewer's JSON went to a
    shell variable, was parsed for counts, and was then discarded. A required
    gate whose refusal cannot be read is not reviewable, only obstructive.
    """
    result, artifact, outputs = _run_review_script(tmp_path, stub=BLOCKING_STUB)

    assert result.returncode == 1, "a blocking finding must fail the job"
    assert outputs["verdict"] == "blocked"
    assert outputs["blocking_count"] == "1"

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["findings"], "the verdict artifact must carry the findings"
    finding = payload["findings"][0]
    assert finding["severity"] == "error"
    assert finding["rule"] == "unbounded-retry"
    assert finding["message"] == "the loop has no ceiling"
    assert finding["file"] == "a/b.py"
    assert finding["line"] == 12
    assert finding["raw"]["line_end"] == 12, (
        "the finding must also be kept verbatim, so an upstream field rename "
        "costs a worse-looking row rather than a lost finding"
    )

    assert "unbounded-retry" in result.stdout, (
        "the finding must be readable in the job log without downloading the "
        "artifact -- a count alone tells a reader nothing to act on"
    )
    assert "a/b.py:12" in result.stdout
    assert "the loop has no ceiling" in result.stdout


def test_an_unmappable_finding_is_printed_verbatim(tmp_path: Path) -> None:
    """A renamed upstream field must not render as an empty finding."""
    result, artifact, _ = _run_review_script(tmp_path, stub=UNMAPPABLE_STUB)

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["findings"][0]["raw"]["some_future_field"] == "renamed upstream"
    assert "some_future_field" in result.stdout, (
        "with nothing mapped the job log must fall back to the verbatim "
        "finding; an empty row reads as a reviewer with nothing to say"
    )


def test_the_comment_reads_findings_from_the_artifact_not_a_step_output() -> None:
    """A finding is multi-line free text written by a model.

    Threading that through ``GITHUB_OUTPUT`` means choosing a delimiter the
    model could itself emit. Reading the file the review step already wrote has
    no such failure mode.
    """
    for step in _job(REVIEW_JOB)["steps"]:
        if step.get("name", "").startswith("Post review summary"):
            script = step["with"]["script"]
            break
    else:
        raise AssertionError("the PR-comment step must exist")

    assert "hostile-review-verdict.json" in script, (
        "the comment must read the findings out of the verdict artifact"
    )
    assert "findings" in script


def test_a_broken_model_config_names_its_cause_in_the_job_log(tmp_path: Path) -> None:
    """AC3's falsifier, executed rather than asserted about.

    Against the pre-OMN-18415 script this produces an `infra_error` with the
    cause nowhere in the log, which is exactly the state that forced three
    separate hand reproductions.
    """
    result, artifact, outputs = _run_review_script(tmp_path, stub=FAILING_STUB)

    assert result.returncode == 1, "an unusable reviewer must fail the job"
    assert "ONEX_CORE_041_INVALID_CONFIGURATION" in result.stdout, (
        "the named cause must be readable in the job log; it was the one line "
        "that `2>/dev/null` was throwing away"
    )
    assert f"{SIGNING_KEY_VAR} is not set" in result.stdout

    assert outputs["verdict"] == "infra_error"
    assert "ONEX_CORE_041_INVALID_CONFIGURATION" in outputs["named_cause"], (
        "the named cause must also reach the PR comment via the step output"
    )

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["verdict"] == "infra_error"
    assert payload["review_exit"] == 1
    assert "ONEX_CORE_041_INVALID_CONFIGURATION" in payload["stderr"], (
        "the verdict artifact must carry the captured stderr"
    )


def test_the_signing_value_is_redacted_before_it_is_logged(tmp_path: Path) -> None:
    """Capturing stderr must not turn a fail-closed message into a disclosure.

    GitHub masks registered Actions secrets, not runner environment variables,
    and the fleet declares this one in the runner's ambient environment -- so
    the redaction is ours to do.
    """
    result, artifact, _ = _run_review_script(
        tmp_path,
        stub=FAILING_STUB,
        extra_env={SIGNING_KEY_VAR: FAKE_SIGNING_VALUE},
    )
    assert FAKE_SIGNING_VALUE not in result.stdout, (
        "a signing value must never reach the job log"
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert FAKE_SIGNING_VALUE not in payload["stderr"], (
        "a signing value must never reach the uploaded artifact"
    )
    assert f"{SIGNING_KEY_VAR}-redacted" in payload["stderr"], (
        "the redaction must leave a marker, so a reader can tell a redacted "
        "line from a line that never existed"
    )


def test_secret_redaction_replaces_lines_with_partial_token_matches(
    tmp_path: Path,
) -> None:
    """A redaction must replace the containing line, not splice it."""
    result, artifact, _ = _run_review_script(
        tmp_path,
        stub=PARTIAL_SECRET_STUB,
        extra_env={SIGNING_KEY_VAR: FAKE_SIGNING_VALUE},
    )

    assert FAKE_SIGNING_VALUE not in result.stdout
    assert f"prefix-***{SIGNING_KEY_VAR}-redacted***-suffix" not in result.stdout
    assert result.stdout.count(f"***{SIGNING_KEY_VAR}-redacted***") >= 2
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert FAKE_SIGNING_VALUE not in payload["stderr"]
    assert f"prefix-***{SIGNING_KEY_VAR}-redacted***-suffix" not in payload["stderr"]
    assert payload["stderr"].count(f"***{SIGNING_KEY_VAR}-redacted***") >= 2


def test_encoded_spellings_of_the_signing_value_are_redacted_too(
    tmp_path: Path,
) -> None:
    """A plain substring replace only catches the value spelled verbatim.

    Anything that passes through a JSON body, a query string or an encoded
    header reaches stderr in a form that does not match the raw value, and the
    first revision of the redaction printed those in full. Raised by this gate's
    own adversarial reviewer on the pull request that introduced it.
    """
    result, artifact, _ = _run_review_script(
        tmp_path,
        stub=ENCODED_STUB,
        extra_env={SIGNING_KEY_VAR: ENCODED_VALUE},
    )
    payload = json.loads(artifact.read_text(encoding="utf-8"))

    for label, spelling in (
        ("raw", ENCODED_VALUE),
        ("json-escaped", json.dumps(ENCODED_VALUE)[1:-1]),
        ("percent-encoded", urllib.parse.quote(ENCODED_VALUE, safe="")),
        ("base64", base64.b64encode(ENCODED_VALUE.encode()).decode()),
    ):
        assert spelling not in result.stdout, (
            f"the {label} spelling of the signing value reached the job log"
        )
        assert spelling not in payload["stderr"], (
            f"the {label} spelling of the signing value reached the artifact"
        )

    assert payload["stderr"].count(f"***{SIGNING_KEY_VAR}-redacted***") >= 3, (
        "each encoded spelling line must keep a marker, so a reader can tell "
        "redacted lines from lines that never existed"
    )


def test_a_successful_review_still_carries_its_stderr(tmp_path: Path) -> None:
    """The success path writes the artifact too.

    A non-blocking run writes the artifact too, so the cause of a degradation
    that did not stop the merge is still readable after the run -- which is how
    this gate spent an unknown number of PRs reviewing nothing.
    """
    result, artifact, outputs = _run_review_script(tmp_path, stub=PASSING_STUB)

    assert result.returncode == 0
    assert outputs["verdict"] == "passed"
    assert outputs["models_succeeded"] == "qwen3-review,gpt-oss-review"
    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["verdict"] == "passed"
    assert payload["models_succeeded"] == ["qwen3-review", "gpt-oss-review"]
    assert "Model 'qwen3-review' succeeded" in payload["stderr"]
    assert "Model 'qwen3-review' succeeded" in result.stdout


def test_both_attempts_are_logged_separately(tmp_path: Path) -> None:
    """The retry is not a reason to lose the first attempt's diagnostic."""
    result, _, _ = _run_review_script(tmp_path, stub=FAILING_STUB)
    groups = re.findall(r"::group::cli_review stderr \(attempt (\d)/2", result.stdout)
    assert groups == ["1", "2"], (
        f"each attempt's stderr must be its own log group; saw {groups}"
    )


def test_a_degraded_quorum_fails_the_gate_closed(tmp_path: Path) -> None:
    """OMN-18479: one model of two is not a verdict.

    This payload -- a single succeeded model carrying one error finding --
    produced ``verdict=blocked`` before OMN-18479, which is how one model's
    rotating finding blocked 24 of 40 runs on this repository. It must now
    resolve to ``degraded_quorum`` and fail the step closed under that name,
    without inventing a blocking count from the one opinion it has.
    """
    result, artifact, outputs = _run_review_script(tmp_path, stub=DEGRADED_QUORUM_STUB)

    assert result.returncode == 1, "no verdict is not a passing verdict"
    assert outputs["verdict"] == "degraded_quorum"
    assert outputs["blocking_count"] == "0"

    payload = json.loads(artifact.read_text(encoding="utf-8"))
    assert payload["verdict"] == "degraded_quorum"
    assert payload["blocking_count"] == 0
    assert "DEGRADED QUORUM" in payload["stderr"], (
        "the reason must survive into the artifact, not only the job log"
    )
