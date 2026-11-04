# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""The whole-file hygiene leg and its scrub map (OMN-22273).

Three exit-code cases (detected = 1, clean = 0, configuration error = 2) over
synthetic fixtures and a synthetic vocabulary: no real private name appears here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from omniclaude.nodes.node_validate_skills_compute.enums.enum_scrub_map_key_kind import (
    EnumScrubMapKeyKind,
)
from omniclaude.nodes.node_validate_skills_compute.enums.enum_whole_file_hygiene_outcome import (
    EnumWholeFileHygieneOutcome,
)
from omniclaude.nodes.node_validate_skills_compute.handlers.handler_whole_file_hygiene import (
    SCRUB_MAP_RELATIVE,
    WHOLE_FILE_CLASSES,
    HandlerWholeFileHygiene,
    load_scrub_map,
)
from omniclaude.nodes.node_validate_skills_compute.models.model_whole_file_hygiene import (
    ModelWholeFileHygieneRequest,
    ModelWholeFileHygieneResult,
)
from omniclaude.nodes.node_validate_skills_compute.runtime_whole_file_hygiene import (
    main,
)

pytestmark = pytest.mark.unit


def handle(request: ModelWholeFileHygieneRequest) -> ModelWholeFileHygieneResult:
    return HandlerWholeFileHygiene().handle(request)


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRUB_MAP = REPO_ROOT / SCRUB_MAP_RELATIVE

#: The row ids of the retirement plan's scrub table, spelled in this repository so the
#: test runs everywhere (a cross-repo read of the plan would have to skip).
PLAN_SCRUB_ROWS = (
    "registry_root_variable",
    "private_repository_names",
    "lab_hosts_and_addresses",
    "ledger_path_and_prose",
    "knowledge_base_prose",
    "machine_paths",
    "person_names",
    "private_package_imports",
)

VOCAB = r"""
schema_version: 1
private_repo_names_resolved_at: 2999-01-01T00:00:00Z
private_repo_cache_max_age_days: 3650
private_repo_names:
  - "synthetic_private_repo"
internal_kb_prose:
  - "internal\s+knowledge\s+base"
host_nicknames:
  - "labhost-\d+"
machine_path_patterns:
  - "synthetic_worktrees/"
person_names:
  - "testpersonhandle"
tracker_url_patterns:
  - "https?://tracker\\.invalid/"
sensitive_literal_patterns:
  - "SYNTHETICKEY[0-9A-Z]{8}"
sensitive_literal_exempt_globs:
  - "tests/**/fixtures/**"
"""
LAB_VOCAB = 'schema_version: 1\nlab_lane_ids:\n  - "lane-alpha-lab"\n'
MODEL_VOCAB = 'schema_version: 1\nlab_model_ids:\n  - "synthetic-model-x"\n'
#: Report mode and the added-lines scope: the leg must override both.
REPO_CONFIG = """
mode: report
enforce_scope: added-lines
enforce_classes:
  - "private-repo-name"
allowed_top_level:
  - "plugins"
  - ".public-repo-hygiene.yaml"
  - ".public-repo-hygiene-suppressions.yaml"
"""

#: A lab address and a private repository name, both from the synthetic vocabulary.
DIRTY = "Deploy from synthetic_private_repo to labhost-7 first.\n"
CLEAN = "Read the plugin root from ONEX_REGISTRY_ROOT and the overlay.\n"


def _vocab_dir(tmp_path: Path) -> Path:
    vocab_dir = tmp_path / "vocab"
    vocab_dir.mkdir()
    (vocab_dir / "vocabulary.yaml").write_text(VOCAB, encoding="utf-8")
    (vocab_dir / "public_repo_hygiene_lab_vocabulary.yaml").write_text(
        LAB_VOCAB, encoding="utf-8"
    )
    (vocab_dir / "public_repo_hygiene_model_vocabulary.yaml").write_text(
        MODEL_VOCAB, encoding="utf-8"
    )
    return vocab_dir


def _checkout(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / ".public-repo-hygiene.yaml").write_text(REPO_CONFIG, encoding="utf-8")
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


def _request(
    root: Path, vocab_dir: Path | None, **overrides: object
) -> ModelWholeFileHygieneRequest:
    fields: dict[str, object] = {
        "repo_root": root,
        "scrub_map": SCRUB_MAP,
        "gate_script": REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py",
    }
    if vocab_dir is not None:
        fields["vocabulary"] = vocab_dir / "vocabulary.yaml"
    fields.update(overrides)
    return ModelWholeFileHygieneRequest.model_validate(fields)


def test_whole_file_leg_detects_a_lab_address_and_a_private_repo_name(
    tmp_path: Path,
) -> None:
    root = _checkout(
        tmp_path,
        {"plugins/omni/skills/x/SKILL.md": DIRTY, "plugins/omni/README.md": CLEAN},
    )
    result = handle(_request(root, _vocab_dir(tmp_path)))

    assert result.outcome is EnumWholeFileHygieneOutcome.DETECTED
    assert result.exit_code == 1
    assert result.files_scanned == 2
    found = {(f.path, f.class_name) for f in result.findings}
    assert ("plugins/omni/skills/x/SKILL.md", "private-repo-name") in found
    assert ("plugins/omni/skills/x/SKILL.md", "private-network") in found
    assert all(f.path != "plugins/omni/README.md" for f in result.findings)
    by_class = {f.class_name: f.becomes for f in result.findings}
    assert by_class["private-repo-name"] == (
        "ONEX_REGISTRY_ROOT",
        "repos.plugin_source",
        "repos.private_data",
        "repos.deploy",
        "repos.knowledge_base",
    )
    assert by_class["private-network"] == ("lab_hosts",)


def test_whole_file_leg_detects_in_a_file_the_change_did_not_add(
    tmp_path: Path,
) -> None:
    # The repo config says report mode + added-lines; the leg still fails the file.
    root = _checkout(tmp_path, {"plugins/omni/a.md": DIRTY})
    assert handle(_request(root, _vocab_dir(tmp_path))).exit_code == 1


def test_whole_file_leg_detects_deployment_config_in_a_yaml(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path, {"plugins/omni/overlays/hosts.yaml": "target: 10.20." + "30.40\n"}
    )
    result = handle(_request(root, _vocab_dir(tmp_path)))
    assert result.exit_code == 1
    assert "deployment-config" in {f.class_name for f in result.findings}


def test_whole_file_leg_clean_exits_zero(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path,
        {"plugins/omni/skills/x/SKILL.md": CLEAN, "plugins/omni/b.md": CLEAN},
    )
    result = handle(_request(root, _vocab_dir(tmp_path)))
    assert result.outcome is EnumWholeFileHygieneOutcome.CLEAN
    assert result.exit_code == 0
    assert result.files_scanned == 2
    assert result.findings == ()


def test_whole_file_leg_clean_ignores_files_outside_the_scope(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path, {"plugins/omni/b.md": CLEAN, "plugins/other/c.md": DIRTY}
    )
    assert handle(_request(root, _vocab_dir(tmp_path))).exit_code == 0


@pytest.mark.parametrize("missing", ["vocabulary", "lab", "model"])
def test_whole_file_leg_config_error_is_exit_two_not_a_detection(
    tmp_path: Path, missing: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OMNI_HYGIENE_VOCAB_PATH", raising=False)
    root = _checkout(tmp_path, {"plugins/omni/a.md": DIRTY})
    vocab_dir = _vocab_dir(tmp_path)
    if missing == "vocabulary":
        request = _request(root, None)
    else:
        name = {
            "lab": "public_repo_hygiene_lab_vocabulary.yaml",
            "model": "public_repo_hygiene_model_vocabulary.yaml",
        }[missing]
        (vocab_dir / name).unlink()
        request = _request(root, vocab_dir)

    result = handle(request)

    assert result.outcome is EnumWholeFileHygieneOutcome.CONFIG_ERROR
    assert result.exit_code == 2
    assert result.exit_code != EnumWholeFileHygieneOutcome.DETECTED.exit_code
    assert result.error
    assert result.findings == ()


def test_whole_file_leg_config_error_on_a_missing_or_empty_scope(
    tmp_path: Path,
) -> None:
    vocab_dir = _vocab_dir(tmp_path)
    root = _checkout(tmp_path, {})
    assert handle(_request(root, vocab_dir)).exit_code == 2
    (root / "plugins" / "omni").mkdir(parents=True)
    assert handle(_request(root, vocab_dir)).exit_code == 2


def test_whole_file_leg_config_error_on_a_broken_scrub_map(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {"plugins/omni/a.md": CLEAN})
    bad = tmp_path / "bad_map.yaml"
    bad.write_text("version: 1\nrows: [not a row]\n", encoding="utf-8")
    result = handle(_request(root, _vocab_dir(tmp_path), scrub_map=bad))
    assert result.exit_code == 2


def test_whole_file_leg_cli_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vocab_dir = _vocab_dir(tmp_path)
    root = _checkout(tmp_path, {"plugins/omni/a.md": DIRTY})
    argv = [
        "--repo-root",
        str(root),
        "--vocabulary",
        str(vocab_dir / "vocabulary.yaml"),
        "--scrub-map",
        str(SCRUB_MAP),
        "--gate-script",
        str(REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py"),
    ]
    assert main(argv) == 1
    out = capsys.readouterr().out
    assert "DETECTED plugins/omni/a.md" in out
    assert "synthetic_private_repo" not in out  # the line's text is never printed
    (root / "plugins/omni/a.md").write_text(CLEAN, encoding="utf-8")
    assert main(argv) == 0
    (vocab_dir / "vocabulary.yaml").unlink()
    assert main(argv) == 2


def test_scrub_map_has_a_row_for_every_class_of_the_plan_table() -> None:
    scrub_map = load_scrub_map(SCRUB_MAP)
    assert tuple(r.row_id for r in scrub_map.rows) == PLAN_SCRUB_ROWS
    for row in scrub_map.rows:
        if row.kind is EnumScrubMapKeyKind.NOT_REWRITTEN:
            assert row.keys == ()
        else:
            assert row.keys, f"{row.row_id} names no destination key"


def test_scrub_map_names_the_overlay_keys_of_the_plan_table() -> None:
    scrub_map = load_scrub_map(SCRUB_MAP)
    rows = {r.row_id: r for r in scrub_map.rows}
    assert set(rows["private_repository_names"].keys) == {
        "repos.plugin_source",
        "repos.private_data",
        "repos.deploy",
        "repos.knowledge_base",
    }
    assert rows["lab_hosts_and_addresses"].keys == ("lab_hosts",)
    assert rows["person_names"].keys == ("people",)
    assert rows["ledger_path_and_prose"].keys == ("ONEX_LEDGER_PATH",)
    assert "ONEX_REGISTRY_ROOT" in rows["registry_root_variable"].keys


def test_scrub_map_every_detectable_class_with_a_rewrite_resolves_to_keys() -> None:
    scrub_map = load_scrub_map(SCRUB_MAP)
    rewritten = {
        "private-repo-name",
        "internal-kb-prose",
        "lab-config",
        "person-name",
        "private-network",
        "machine-path",
    }
    assert rewritten <= WHOLE_FILE_CLASSES
    for class_name in sorted(rewritten):
        assert scrub_map.keys_for_class(class_name), class_name


def test_scrub_map_a_class_with_no_row_is_a_config_error(tmp_path: Path) -> None:
    data = yaml.safe_load(SCRUB_MAP.read_text(encoding="utf-8"))
    data["rows"][0]["finding_classes"] = ["no-such-class"]
    path = tmp_path / "map.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    root = _checkout(tmp_path, {"plugins/omni/a.md": CLEAN})
    result = handle(_request(root, _vocab_dir(tmp_path), scrub_map=path))
    assert result.exit_code == 2
    assert result.error is not None
    assert "no-such-class" in result.error
