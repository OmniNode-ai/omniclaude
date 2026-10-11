# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The deployment-config class reads workflow files in full (OMN-20923).

The class passed omnimarket#3731 and omniclaude#2664 while their Hostile
Reviewer workflows carried the lab's host nicknames, endpoints and model names
in comments and in prose: the value rule never read a comment, and the shapes
it knew (an address, a tailnet name) were not what the workflows named. Every
rule below has a failing fixture. The private vocabularies are synthetic here
(a regex for a made-up host nickname, made-up model ids), so this file names
nothing of ours, and every address is assembled at run time.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from omnibase_core.validators.no_unguarded_git_subprocess import (
    scrub_git_location_env,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "public-repo-hygiene-reusable.yml"

WF = ".github/workflows/review.yml"
LAN_HOST = "192." + "168.7.21"
TEN_HOST = "10." + "3.4.5"
TAILNET = "box.tail0000" + ".ts" + ".net"

# Synthetic private vocabulary: a made-up lab host nickname and made-up model
# ids. The shape is the real files' shape; the values are not ours.
HOST_RE = r"(?<![A-Za-z0-9_-])labbox-\d+(?![A-Za-z0-9_])"
MODEL_IDS = ("example-voter-a", "example-voter-b", "Example-Model-9B")
VOCAB_YAML = (
    "schema_version: 1\n"
    "host_nicknames:\n"
    f'  - "{HOST_RE}"\n'
    "private_repo_names:\n"
    '  - "example-private-repo"\n'
)
MODEL_YAML = "schema_version: 1\n\nlab_model_ids:\n" + "".join(
    f'  - "{m}"\n' for m in MODEL_IDS
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prhg_wf_shapes", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prhg_wf_shapes"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _vocab(tmp_path: Path, *, model: bool = True) -> tuple[Path, Path | None]:
    d = tmp_path / "vocab"
    d.mkdir(exist_ok=True)
    main = d / "public_repo_hygiene_vocabulary.yaml"
    main.write_text(VOCAB_YAML, encoding="utf-8")
    if not model:
        return main, None
    models = d / gate.MODEL_VOCABULARY_BASENAME
    models.write_text(MODEL_YAML, encoding="utf-8")
    return main, models


def _scan(
    rel: str, text: str, tmp_path: Path | None = None, *, with_vocab: bool = False
) -> list[int]:
    vocab = None
    if with_vocab:
        assert tmp_path is not None
        main, models = _vocab(tmp_path)
        vocab = gate.build_deployment_vocabulary(main, models)
    return [
        f.line_no for f in gate.scan_deployment_config(rel, text.splitlines(), vocab)
    ]


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        env=scrub_git_location_env(),
    ).stdout.strip()


def _repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    root = tmp_path / "r"
    root.mkdir()
    _git(root, "init", "-q")
    for rel, text in {"README.md": "a public repository\n", **files}.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root, _git(root, "rev-parse", "HEAD")


def _commit(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "change")


def _cli(root: Path, *extra: str) -> tuple[int, str]:
    env = scrub_git_location_env()
    env.pop("OMNI_HYGIENE_VOCAB_PATH", None)
    proc = subprocess.run(
        [
            sys.executable,
            str(GATE_PATH),
            "--repo-root",
            str(root),
            "--only-classes",
            "deployment-config",
            "--mode",
            "enforce",
            *extra,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------------
# Shape half: a workflow file is read in full, comments included
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        f"# the voter lives at {LAN_HOST}:8000",
        f"    # allow {TEN_HOST}",
        f"  # tailnet mirror {TAILNET}:3141",
        f"        run: curl http://{LAN_HOST}/health",
        "# the endpoint is http://box.lan:8000/v1",
        "# the endpoint is http://box.home.arpa/v1",
        "        run: rsync -a out/ runner@box.lab:/srv",
        "# reached at box.internal:8130",
        "      URL: http://studio.local:8131",
    ],
)
def test_a_workflow_line_naming_a_private_host_is_found_comments_included(
    line: str,
) -> None:
    assert _scan(WF, line + "\n") == [1]


@pytest.mark.parametrize(
    "line",
    [
        "      URL: http://host.docker.internal:8000",
        "      URL: http://db.svc.cluster.local:5432",
        "      URL: http://metadata.google.internal/",
        "      run: cp .env.example .env.local",
        "      run: cat .claude/settings.local.json",
        "# the voter lives in a private overlay, never in this file",
        "      URL: http://studio.lab.example:8131",
        "      URL: http://localhost:8000",
        "# bump to 1.2.3 before release",
    ],
)
def test_generic_names_and_neutral_workflow_lines_are_not_found(line: str) -> None:
    assert _scan(WF, line + "\n") == []


def test_a_comment_in_a_non_workflow_config_file_is_still_not_read() -> None:
    """The comment rule is for workflow files; a config file's comment is not a value."""
    assert _scan("config/x.yaml", f"# lab note: {LAN_HOST}\n") == []


def test_a_workflow_in_a_subdirectory_or_a_non_yaml_file_is_not_a_workflow() -> None:
    comment = f"# lab note: {LAN_HOST}\n"
    assert _scan(".github/workflows/helpers/x.yml", comment) == []
    assert _scan(".github/workflows/README.txt", comment) == []


def test_a_test_or_doc_naming_a_private_zone_is_out_of_scope() -> None:
    assert _scan("tests/ci/test_x.yml", "# http://box.lan:8000\n") == []
    assert _scan("docs/x.yaml", "# http://box.lan:8000\n") == []


# ---------------------------------------------------------------------------
# Vocabulary half: our host nicknames and our model ids
# ---------------------------------------------------------------------------


def test_a_lab_host_nickname_in_a_workflow_comment_is_found(tmp_path: Path) -> None:
    text = "# single-slot endpoint on labbox-7:8001, timing out\n"
    assert _scan(WF, text) == []
    assert _scan(WF, text, tmp_path, with_vocab=True) == [1]


@pytest.mark.parametrize("model", MODEL_IDS)
def test_one_of_our_model_ids_in_a_workflow_is_found(
    tmp_path: Path, model: str
) -> None:
    for text in (
        f"# the roster is {model} plus one more\n",
        f"      --model {model} \\\n",
        f'      REVIEW_MODEL_KEYS: "{model} other"\n',
    ):
        assert _scan(WF, text) == []
        assert _scan(WF, text, tmp_path, with_vocab=True) == [1]


def test_a_model_id_is_a_whole_token_not_a_prefix(tmp_path: Path) -> None:
    text = "# the example-voter-abc and xexample-voter-a names are not ours\n"
    assert _scan(WF, text, tmp_path, with_vocab=True) == []


def test_the_model_rule_is_case_insensitive(tmp_path: Path) -> None:
    assert _scan(WF, "# EXAMPLE-VOTER-A\n", tmp_path, with_vocab=True) == [1]


def test_the_vocabulary_rules_do_not_read_other_files(tmp_path: Path) -> None:
    text = "name: example-voter-a on labbox-3\n"
    assert _scan("config/x.yaml", text, tmp_path, with_vocab=True) == []


def test_a_vocabulary_finding_does_not_quote_its_line(tmp_path: Path) -> None:
    main, models = _vocab(tmp_path)
    vocab = gate.build_deployment_vocabulary(main, models)
    findings = gate.scan_deployment_config(WF, ["# example-voter-a on labbox-3"], vocab)
    assert len(findings) == 1
    assert "example-voter-a" not in findings[0].snippet
    assert "labbox-3" not in findings[0].snippet


# ---------------------------------------------------------------------------
# The private files: fail closed, and a stale visibility cache is not their problem
# ---------------------------------------------------------------------------


def test_a_missing_model_vocabulary_is_a_refusal(tmp_path: Path) -> None:
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        gate.load_model_vocabulary(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ('schema_version: 1\nlab_modle_ids:\n  - "x"\n', "unknown model vocabulary"),
        ("schema_version: 1\n", "missing required key"),
        ("schema_version: 1\nlab_model_ids:\n", "missing required key|is empty"),
    ],
)
def test_a_malformed_model_vocabulary_is_a_refusal(
    tmp_path: Path, body: str, needle: str
) -> None:
    path = tmp_path / "m.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(gate.ConfigError, match=needle):
        gate.load_model_vocabulary(path)


def test_empty_or_absent_host_nicknames_are_a_refusal(tmp_path: Path) -> None:
    path = tmp_path / "v.yaml"
    path.write_text("schema_version: 1\n", encoding="utf-8")
    with pytest.raises(gate.ConfigError, match="host_nicknames"):
        gate.load_host_nicknames(path)
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        gate.load_host_nicknames(tmp_path / "absent.yaml")


def test_a_stale_visibility_cache_does_not_stop_the_deployment_rules(
    tmp_path: Path,
) -> None:
    """The full run refuses a visibility cache past its max age; this class reads
    only host_nicknames, so a stale cache cannot turn a required job red."""
    path = tmp_path / "v.yaml"
    path.write_text(
        VOCAB_YAML
        + "private_repo_names_resolved_at: 2020-01-01T00:00:00Z\n"
        + "private_repo_cache_max_age_days: 30\n",
        encoding="utf-8",
    )
    assert gate.load_host_nicknames(path) == [HOST_RE]


# ---------------------------------------------------------------------------
# The command line
# ---------------------------------------------------------------------------


def _added_args(base: str) -> tuple[str, ...]:
    return ("--enforce-scope", "added-lines", "--diff-base", base)


def test_a_pull_request_adding_a_lab_comment_is_refused_with_the_vocabulary(
    tmp_path: Path,
) -> None:
    main, models = _vocab(tmp_path)
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    _commit(root, {WF: "name: review\n# calls example-voter-a on labbox-4\n"})
    code, out = _cli(
        root,
        "--vocabulary",
        str(main),
        "--model-vocabulary",
        str(models),
        *_added_args(base),
    )
    assert code == 1, out
    assert f"REFUSED {WF}:2" in out
    assert "example-voter-a" not in out.split("REFUSED", 1)[1]


def test_the_same_pull_request_passes_shape_only_and_says_what_was_not_evaluated(
    tmp_path: Path,
) -> None:
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    _commit(root, {WF: "name: review\n# calls example-voter-a on labbox-4\n"})
    code, out = _cli(root, *_added_args(base))
    assert code == 0, out
    assert "NOT EVALUATED: lab host nicknames in workflow files" in out
    assert "NOT EVALUATED: our model ids in workflow files" in out


def test_a_pull_request_adding_a_private_address_comment_is_refused_shape_only(
    tmp_path: Path,
) -> None:
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    _commit(root, {WF: f"name: review\n# runs on {LAN_HOST}\n"})
    code, out = _cli(root, *_added_args(base))
    assert code == 1, out
    assert f"REFUSED {WF}:2" in out


def test_the_model_vocabulary_beside_the_vocabulary_is_found(tmp_path: Path) -> None:
    main, _ = _vocab(tmp_path)
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    _commit(root, {WF: "name: review\n# example-voter-b\n"})
    code, out = _cli(root, "--vocabulary", str(main), *_added_args(base))
    assert code == 1, out
    assert "NOT EVALUATED: our model ids" not in out


def test_without_a_model_vocabulary_beside_it_the_model_rule_is_not_evaluated(
    tmp_path: Path,
) -> None:
    main, _ = _vocab(tmp_path, model=False)
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    _commit(root, {WF: "name: review\n# example-voter-b\n"})
    code, out = _cli(root, "--vocabulary", str(main), *_added_args(base))
    assert code == 0, out
    assert "NOT EVALUATED: our model ids in workflow files" in out


def test_a_given_model_vocabulary_that_is_absent_is_exit_2(tmp_path: Path) -> None:
    main, _ = _vocab(tmp_path, model=False)
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    code, out = _cli(
        root,
        "--vocabulary",
        str(main),
        "--model-vocabulary",
        str(tmp_path / "absent.yaml"),
        *_added_args(base),
    )
    assert code == 2, out
    assert "THE GATE DID NOT RUN" in out


def test_a_given_vocabulary_that_is_absent_is_exit_2(tmp_path: Path) -> None:
    root, base = _repo(tmp_path, {WF: "name: review\n"})
    code, out = _cli(
        root, "--vocabulary", str(tmp_path / "absent.yaml"), *_added_args(base)
    )
    assert code == 2, out


def test_residue_the_change_does_not_add_is_reported_not_failed(
    tmp_path: Path,
) -> None:
    main, models = _vocab(tmp_path)
    root, base = _repo(tmp_path, {WF: "name: review\n# calls example-voter-a\n"})
    _commit(root, {"src/app.py": "print('unrelated')\n"})
    code, out = _cli(
        root,
        "--vocabulary",
        str(main),
        "--model-vocabulary",
        str(models),
        *_added_args(base),
    )
    assert code == 0, out
    assert "0 finding(s) fail the run" in out


# ---------------------------------------------------------------------------
# Wiring: the token-holding job runs the vocabulary half, fail closed
# ---------------------------------------------------------------------------


def test_the_token_job_runs_the_vocabulary_half_and_refuses_when_a_file_is_absent() -> (
    None
):
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("- name: Deployment configuration in workflow files")
    block = text[start : text.index("\n  # OMN-20923: the deployment-config class,")]
    assert "--only-classes deployment-config" in block
    assert "--mode enforce" in block
    assert '--vocabulary "${VOCAB_PATH}"' in block
    assert '--model-vocabulary "${MODEL_VOCAB_PATH}"' in block
    assert "--enforce-scope added-lines" in block
    assert '--diff-base "${DIFF_BASE}"' in block
    assert "THE GATE DID NOT RUN" in block
    assert "exit 1" in block


def test_the_model_vocabulary_is_fetched_with_the_lab_vocabulary() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "vocabularies/public_repo_hygiene_model_vocabulary.yaml" in text
    start = text.index("- name: Deployment configuration in workflow files")
    block = text[start : text.index("\n  # OMN-20923: the deployment-config class,")]
    assert "|| true" not in block
    assert "2>/dev/null" not in block


def test_the_secretless_job_does_not_read_the_private_vocabularies() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    block = text[text.index("\n  deployment-config:\n") :]
    assert "secrets." not in block
    assert "--vocabulary" not in block
    assert "--model-vocabulary" not in block
