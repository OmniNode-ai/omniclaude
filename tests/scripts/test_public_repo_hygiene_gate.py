# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
"""Behaviour tests for ``scripts/public_repo_hygiene_gate.py`` (OMN-18014).

An untested gate rots, and a gate that reports green over an unscanned path
is the failure this whole programme exists about. So every rule below is
pinned by a POSITIVE CONTROL: a fixture repository carrying a known
violation, asserted to be reported — never a fixture asserted merely to be
clean, which is the reading that four consecutive false "zero failures"
sweeps produced during the trusted-CI canary.

Every fixture is a throwaway git repository, because the scanned surface is
the TRACKED set (``git ls-files``), not a directory walk and not the ignore
rules. Root cause 4.9: an ignore file neither untracks an existing path nor
stops a forced add — ``omnicursor/.DS_Store`` is committed *and* ignored.

This file deliberately contains literals that the gate itself detects. They
are the corpus; the repository's own hygiene gates carry the annotations that
say so.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPO_ROOT / "scripts" / "public_repo_hygiene_gate.py"

# Positive-control literals. Each sits alone on its own annotated line so
# `ruff format` cannot reflow it onto a line that has lost its marker.
LAN_LITERAL = "192.168.86.201"  # onex-allow-internal-ip  # public-skill-ok: control
OPERATOR_HOME = (
    "/Users/jonah/Code/omni_home"  # local-path-ok  # public-skill-ok: control
)
INSTANCE_ID = "i-06169517a92b45f86"  # public-skill-ok: control fixture
ROLE_ARN = "arn:aws:iam::123456789012:role/example"  # public-skill-ok: control fixture
PRIVATE_REPO = "omninode_infra"  # public-skill-ok: control fixture
KB_PROSE = "our internal knowledge base"  # public-skill-ok: control fixture
PERSON = "testpersonhandle"  # public-skill-ok: control fixture
TRACKER_URL = "https://linear.app/omninode/issue/OMN-1"  # public-skill-ok: control

# Assembled rather than spelled. These are positive controls for the
# machine-path class, and spelling them would need a `# local-path-ok`
# annotation from the repo's existing local-paths check -- i.e. two more
# self-granted waivers on the pile this lane just filed OMN-18018 about.
MOUNTED_VOLUME_PATH = "/" + "Volumes/EXTERNAL/x"
RFC1918_10 = "10." + "1.2.3"
RFC1918_172 = "172." + "20.0.5"
CGNAT_ADDRESS = "100." + "109.4.5"
TAILNET_FQDN = "host.tail1234" + ".ts" + ".net"
HOST_NICKNAME = "the box." + "201 lane"
LINUX_HOME_PATH = "/" + "home/" + "runner-user/x"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prhg", GATE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["prhg"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VOCAB = r"""
schema_version: 1
private_repo_names_resolved_at: 2999-01-01T00:00:00Z
private_repo_cache_max_age_days: 3650
private_repo_names:
  - "omninode_infra"
internal_kb_prose:
  - "internal\s+knowledge\s+base"
  - "teammates?\s+have\s+access"
host_nicknames:
  - "(?<!\d)\.(?:200|201)\b"
machine_path_patterns:
  - "omni_worktrees/"
person_names:
  - "testpersonhandle"
tracker_url_patterns:
  - "https?://linear\.app/omninode\b"
sensitive_literal_patterns:
  - "AKIA[0-9A-Z]{16}"
sensitive_literal_exempt_globs:
  - "tests/**/fixtures/**"
"""

MINIMAL_CONFIG = """
mode: enforce
allowed_top_level:
  - "src"
  - "tests"
  - "README.md"
  - ".public-repo-hygiene.yaml"
  - ".public-repo-hygiene-suppressions.yaml"
"""


@pytest.fixture
def vocab(tmp_path: Path) -> Path:
    path = tmp_path / "vocabulary.yaml"
    path.write_text(VOCAB, encoding="utf-8")
    return path


def _make_repo(root: Path, files: dict[str, str], config: str = MINIMAL_CONFIG) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".public-repo-hygiene.yaml").write_text(config, encoding="utf-8")
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A", "-f"], cwd=root, check=True)
    return root


def _run(root: Path, vocab_path: Path, mode: str = "enforce"):
    return gate.run(root, vocab_path, mode, None)


def _classes(findings) -> set[str]:
    return {f.class_name for f in findings}


# ---------------------------------------------------------------------------
# Layer (a) — the top-level path allowlist
# ---------------------------------------------------------------------------


def test_undeclared_top_level_entry_fails(tmp_path: Path, vocab: Path) -> None:
    """The half that refuses the directory nobody has invented yet."""
    root = _make_repo(tmp_path / "r", {"vendor/thing.txt": "hello\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    assert "top-level-not-allowed" in _classes(blocking)


def test_declared_top_level_entry_passes(tmp_path: Path, vocab: Path) -> None:
    root = _make_repo(tmp_path / "r", {"src/thing.txt": "hello\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


def test_missing_repo_config_is_a_refusal_not_a_pass(
    tmp_path: Path, vocab: Path
) -> None:
    """An absent config is not an empty allowlist. Fail closed."""
    root = tmp_path / "r"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, vocab)


# ---------------------------------------------------------------------------
# Layer (b) — the path denylist is EXTENSION-AGNOSTIC
#
# Root cause 4.2: kb_doc_gate.py:216 is `path.lower().endswith(".md")`, and
# that one line is why every misplaced artifact in the inventory is a YAML,
# JSON, CSV, TSV, TXT, PNG or SVG. These are the positive controls for the
# extensions the doc gate cannot see.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rel_path", "expected"),
    [
        (".onex/aislop-rules.yaml", "agent-state"),
        (".onex_state/evidence/report.json", "agent-state"),
        (".claude_scratch/notes.txt", "agent-state"),
        (".repowise-workspace/contracts.json", "agent-state"),
        ("merge-sweep/run.json", "agent-state"),
        ("docs/evidence/OMN-1.json", "evidence-tree"),
        (".evidence/run.csv", "evidence-tree"),
        ("drift/dod_receipts/OMN-1.yaml", "evidence-tree"),
        ("src/nodes/receipts/out.json", "evidence-tree"),
        ("docs/tracking/status.csv", "misplaced-doc"),
        ("docs/handoffs/2026-01-01-x.tsv", "misplaced-doc"),
        ("docs/2026-01-01-deep-dive.txt", "misplaced-doc"),
        ("docs/assets/brand/logo.svg", "brand-asset"),
        ("docs/assets/brand/logo.png", "brand-asset"),
        (".env.local", "env-file"),
        (".DS_Store", "os-junk"),
        ("src/run.log", "cache-or-log"),
        ("src/__pycache__/x.txt", "cache-or-log"),
    ],
)
def test_path_denylist_is_extension_agnostic(
    tmp_path: Path, vocab: Path, rel_path: str, expected: str
) -> None:
    root = _make_repo(tmp_path / "r", {rel_path: "x\n"})
    _, blocking, _ = _run(root, vocab)
    hits = [f for f in blocking if f.path == rel_path]
    assert expected in {f.class_name for f in hits}, (
        f"{rel_path} should be {expected}; got {[f.class_name for f in hits]}"
    )


def test_env_example_is_not_an_env_file_finding(tmp_path: Path, vocab: Path) -> None:
    """The one env file a public repo is supposed to ship."""
    root = _make_repo(
        tmp_path / "r",
        {"src/.env.example": "TOKEN=replace-me\n"},
    )
    _, blocking, _ = _run(root, vocab)
    assert "env-file" not in _classes(blocking)


# ---------------------------------------------------------------------------
# Content classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (ROLE_ARN, "cloud-identity"),
        (INSTANCE_ID, "cloud-identity"),
        ("123456789012.dkr.ecr.us-east-2.amazonaws.com/x", "cloud-identity"),
        (LAN_LITERAL, "private-network"),
        (RFC1918_10, "private-network"),
        (RFC1918_172, "private-network"),
        (CGNAT_ADDRESS, "private-network"),
        (TAILNET_FQDN, "private-network"),
        ("ssh user@somebox", "private-network"),
        (HOST_NICKNAME, "private-network"),
        (OPERATOR_HOME, "machine-path"),
        (MOUNTED_VOLUME_PATH, "machine-path"),
        (LINUX_HOME_PATH, "machine-path"),
        (f"see {PRIVATE_REPO} for details", "private-repo-name"),
        (KB_PROSE, "internal-kb-prose"),
        ("teammates have access", "internal-kb-prose"),
        (f"contact {PERSON}", "person-name"),
        (TRACKER_URL, "tracker-url"),
        ("AKIA" + "IOSFODNN7EXAMPLE", "secret-shaped"),
    ],
)
def test_content_classes_fire(
    tmp_path: Path, vocab: Path, payload: str, expected: str
) -> None:
    root = _make_repo(tmp_path / "r", {"src/thing.txt": f"value = {payload}\n"})
    _, blocking, _ = _run(root, vocab)
    assert expected in _classes(blocking), [f.class_name for f in blocking]


def test_bare_ticket_id_is_not_a_violation(tmp_path: Path, vocab: Path) -> None:
    """Operator ruling P3, 2026-09-06, firm.

    Internal ticket ids in public source are an accepted convention, not a
    violation — there are 8,826 in one repo and this programme does not
    propose mass-stripping them. The gate has no bare-ticket-id class at all.
    Workspace-scoped tracker URLs are removed either way, which is what the
    ``tracker-url`` class covers.
    """
    root = _make_repo(tmp_path / "r", {"src/thing.txt": "fixed in OMN-12345\n"})
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_rest_url_path_segments_are_not_machine_paths(
    tmp_path: Path, vocab: Path
) -> None:
    """``machine-path`` is NEVER-EXEMPTABLE, so a false positive in it cannot
    be waived — it can only be fixed by rewriting correct product code.

    The macOS home and mounted-volume prefixes are case-SENSITIVE in reality,
    as is the lowercase Linux home prefix. Compiling the whole class with
    IGNORECASE made every lowercase REST path segment bearing those words a
    never-exemptable finding. Measured live 2026-09-07 against the adoption
    branches: 11 such findings across knowledge-base (5), omnidash (4),
    omnibase_spi (1) and RSD (1) — and in RSD that one false positive was
    100% of the repo's residue, i.e. the difference between "can flip to
    enforce" and "can never be green".
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/client.py": (
                'get("/api/v1/users/123")\n'
                'post(f"{prefix}/volumes/create")\n'
                'delete("/HOME/legacy/x")\n'
            )
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert "machine-path" not in _classes(blocking), [
        f"{f.path}:{f.snippet}" for f in blocking if f.class_name == "machine-path"
    ]
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_real_machine_path_prefixes_still_fire_after_the_case_fix(
    tmp_path: Path, vocab: Path
) -> None:
    """Positive control for the test above: narrowing the case sensitivity
    must not disarm the class it narrows. A zero is only evidence when the
    same probe returns rows against input known to carry them.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/a.py": f"p = {OPERATOR_HOME!r}\n",
            "src/b.py": f"p = {MOUNTED_VOLUME_PATH!r}\n",
            "src/c.py": f"p = {LINUX_HOME_PATH!r}\n",
        },
    )
    _, blocking, _ = _run(root, vocab)
    hits = {f.path for f in blocking if f.class_name == "machine-path"}
    assert hits == {"src/a.py", "src/b.py", "src/c.py"}, hits


def test_secret_false_positive_glob_suppresses_only_the_secret_class(
    tmp_path: Path, vocab: Path
) -> None:
    """Three repos ship detector baselines and test corpora; without this the
    gate's first run is ~300 phantom criticals, and a gate whose first run is
    300 false positives is a gate nobody reads. It must not suppress anything
    else at the same path.
    """
    root = _make_repo(
        tmp_path / "r",
        {"tests/x/fixtures/corpus.txt": "AKIA" + f"IOSFODNN7EXAMPLE {LAN_LITERAL}\n"},
    )
    _, blocking, _ = _run(root, vocab)
    assert "secret-shaped" not in _classes(blocking)
    assert "private-network" in _classes(blocking)


# ---------------------------------------------------------------------------
# OMN-18017 — a public README may not name a private repository
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("doc", ["README.md", "CONTRIBUTING.md", "SECURITY.md"])
def test_public_doc_naming_a_private_repo_is_its_own_class(
    tmp_path: Path, vocab: Path, doc: str
) -> None:
    """The rule that did not exist anywhere in the org.

    A README naming a private repository is not the same finding as a script
    importing from one, so it is reported as its own never-exemptable class.
    """
    config = MINIMAL_CONFIG.replace('  - "README.md"', f'  - "README.md"\n  - "{doc}"')
    root = _make_repo(
        tmp_path / "r",
        {doc: f"Prose lives in {PRIVATE_REPO}, and teammates have access.\n"},
        config=config,
    )
    _, blocking, _ = _run(root, vocab)
    assert "public-doc-private-repo" in _classes(blocking)


def test_public_doc_naming_only_public_repos_passes(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {"README.md": "Built on omnibase_core and omnibase_spi.\n"},
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}" for f in blocking]


def test_a_script_naming_a_private_repo_is_not_the_public_doc_class(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(tmp_path / "r", {"src/x.py": f"REPO = '{PRIVATE_REPO}'\n"})
    _, blocking, _ = _run(root, vocab)
    assert "private-repo-name" in _classes(blocking)
    assert "public-doc-private-repo" not in _classes(blocking)


# ---------------------------------------------------------------------------
# Mechanism 3 — suppression is two-party, scoped and expiring
# ---------------------------------------------------------------------------

REGISTRY_VALID = """
entries:
  - path_glob: "src/**"
    class: "person-name"
    reason_code: "fixture-identity"
    ticket: "OMN-1234"
    expires_at: "2999-01-01"
    approved_by: "codeowner"
"""

REGISTRY_EXPIRED = REGISTRY_VALID.replace("2999-01-01", "2020-01-01")


def test_annotation_without_a_registry_entry_is_a_failure(
    tmp_path: Path, vocab: Path
) -> None:
    """Root cause 4.3, mechanically closed.

    A self-written annotation is not an approval. It must be LOUDER than
    silence, not quieter — the finding it tried to hide is reported too.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n"
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    assert "unresolved-suppression" in _classes(blocking)
    assert "person-name" in _classes(blocking)


def test_annotation_with_a_matching_registry_entry_suppresses(
    tmp_path: Path, vocab: Path
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n",
            ".public-repo-hygiene-suppressions.yaml": REGISTRY_VALID,
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 0, [f"{f.path}:{f.class_name}:{f.snippet}" for f in blocking]


def test_expired_registry_entry_stops_suppressing(tmp_path: Path, vocab: Path) -> None:
    """An allowlist granted under one policy must not silently outlive its
    premise — which is exactly what happened to omniintelligence's internal-IP
    waivers when that repository became public.
    """
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"NAME = '{PERSON}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n",
            ".public-repo-hygiene-suppressions.yaml": REGISTRY_EXPIRED,
        },
    )
    code, blocking, _ = _run(root, vocab)
    assert code == 1
    problems = [f.snippet for f in blocking if f.class_name == "unresolved-suppression"]
    assert any("expired" in p for p in problems), problems


def test_registry_entry_on_a_never_exemptable_class_is_refused(
    tmp_path: Path, vocab: Path
) -> None:
    """There is no legitimate fixture need for a real cloud identifier that a
    stable synthetic value cannot serve. The registry refuses to hold one.
    """
    registry = REGISTRY_VALID.replace('"person-name"', '"cloud-identity"')
    root = _make_repo(
        tmp_path / "r",
        {"src/x.py": "x = 1\n", ".public-repo-hygiene-suppressions.yaml": registry},
    )
    with pytest.raises(gate.ConfigError, match="NEVER-EXEMPTABLE"):
        _run(root, vocab)


@pytest.mark.parametrize(
    "payload", [ROLE_ARN, LAN_LITERAL, OPERATOR_HOME, PRIVATE_REPO, KB_PROSE]
)
def test_never_exemptable_classes_ignore_the_annotation(
    tmp_path: Path, vocab: Path, payload: str
) -> None:
    root = _make_repo(
        tmp_path / "r",
        {
            "src/x.py": f"V = '{payload}'  # {gate.INLINE_MARKER}: fixture-identity OMN-1234\n"
        },
    )
    code, _, _ = _run(root, vocab)
    assert code == 1


@pytest.mark.parametrize(
    "missing", ["ticket", "expires_at", "approved_by", "reason_code"]
)
def test_registry_entry_missing_a_required_field_is_a_config_error(
    tmp_path: Path, vocab: Path, missing: str
) -> None:
    registry = "\n".join(
        line for line in REGISTRY_VALID.splitlines() if f"{missing}:" not in line
    )
    root = _make_repo(
        tmp_path / "r",
        {"src/x.py": "x = 1\n", ".public-repo-hygiene-suppressions.yaml": registry},
    )
    with pytest.raises(gate.ConfigError, match="missing required"):
        _run(root, vocab)


def test_legacy_self_granted_annotations_are_counted_never_blocking(
    tmp_path: Path, vocab: Path
) -> None:
    """OMN-18018 is the migration. This gate reports the count and does not
    perform it: a lane that builds the registry and fills it in the same
    change has self-granted every entry a second time.
    """
    marker = "# onex-" + "allow-internal-ip"
    root = _make_repo(tmp_path / "r", {"src/x.py": f"HOST = 'placeholder'  {marker}\n"})
    code, blocking, info = _run(root, vocab)
    assert code == 0, [f.class_name for f in blocking]
    assert [f.class_name for f in info] == ["self-granted-annotation"]


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_missing_vocabulary_is_a_refusal_not_a_pass(tmp_path: Path) -> None:
    """A gate that cannot read its own denylist has not passed; it has not run.

    This is the failure mode that produced four consecutive confident false
    "zero failures" readings during the trusted-CI canary: a sweep that
    errored and returned no rows reads exactly like a clean bill of health.
    """
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, tmp_path / "nope.yaml")


def test_unparseable_vocabulary_is_a_refusal(tmp_path: Path) -> None:
    bad = tmp_path / "v.yaml"
    bad.write_text("this line is not the supported subset\n", encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError):
        _run(root, bad)


def test_stale_visibility_cache_is_a_refusal(tmp_path: Path) -> None:
    """A stale private-repo list is the hardcoded-list failure the class
    exists to avoid, and a stale list that still reports green is worse than
    no list at all.
    """
    stale = tmp_path / "v.yaml"
    stale.write_text(
        VOCAB.replace("2999-01-01T00:00:00Z", "2020-01-01T00:00:00Z").replace(
            "private_repo_cache_max_age_days: 3650",
            "private_repo_cache_max_age_days: 30",
        ),
        encoding="utf-8",
    )
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="THE GATE DID NOT RUN"):
        _run(root, stale)


def test_undated_visibility_cache_is_a_refusal(tmp_path: Path) -> None:
    undated = tmp_path / "v.yaml"
    undated.write_text(
        "\n".join(
            line
            for line in VOCAB.splitlines()
            if "private_repo_names_resolved_at" not in line
        ),
        encoding="utf-8",
    )
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="live repository visibility"):
        _run(root, undated)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------


def test_report_mode_records_findings_and_exits_zero(
    tmp_path: Path, vocab: Path
) -> None:
    config = MINIMAL_CONFIG.replace("mode: enforce", "mode: report")
    root = _make_repo(tmp_path / "r", {"src/x.py": f"H = '{LAN_LITERAL}'\n"}, config)
    code, blocking, _ = _run(root, vocab, mode="enforce")
    assert code == 0
    assert "private-network" in _classes(blocking)


def test_repo_config_mode_wins_over_the_cli_default(
    tmp_path: Path, vocab: Path
) -> None:
    """Both surfaces are set on purpose so they cannot silently disagree about
    which one is authoritative.
    """
    root = _make_repo(tmp_path / "r", {"src/x.py": f"H = '{LAN_LITERAL}'\n"})
    code, _, _ = _run(root, vocab, mode="report")
    assert code == 1


# ---------------------------------------------------------------------------
# The gate is stdlib-only, by contract
# ---------------------------------------------------------------------------


def test_gate_imports_no_third_party_module() -> None:
    """The structural precedent is RSD's validate_public_release.py: a gate
    that needs a dependency install to run is a gate that does not run in the
    window where it matters. Pinned as a test so the constraint survives the
    next convenience import.
    """
    import ast

    tree = ast.parse(GATE_PATH.read_text(encoding="utf-8"))
    stdlib = set(sys.stdlib_module_names)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= stdlib, sorted(imported - stdlib)


def test_the_repo_declares_its_own_top_level_allowlist() -> None:
    """This repo runs the gate it ships. A config that drifted from the tree
    would make omniclaude the one repo the gate cannot govern.
    """
    config = gate.load_repo_config(REPO_ROOT / gate.CONFIG_BASENAME)
    assert config.mode in gate.MODES
    assert len(config.allowed_top_level) > 10


def test_misspelled_vocabulary_key_is_a_refusal(tmp_path: Path) -> None:
    """A fail-open hole this lane hit for real, now closed.

    The loader used to look up the key it expected, find nothing, and build a
    pattern that matches nothing — so renaming a class in the vocabulary
    without renaming it in the loader turned that class OFF and every test
    stayed green, because the fixtures carry their own vocabulary. The
    production run's own finding count was the only thing that caught it.
    """
    bad = tmp_path / "v.yaml"
    bad.write_text(VOCAB.replace("person_names:", "persn_names:"), encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="unknown vocabulary key"):
        _run(root, bad)


def test_vocabulary_missing_a_required_class_is_a_refusal(tmp_path: Path) -> None:
    lines = VOCAB.splitlines()
    idx = lines.index("person_names:")
    trimmed = "\n".join(lines[:idx] + lines[idx + 2 :])
    bad = tmp_path / "v.yaml"
    bad.write_text(trimmed, encoding="utf-8")
    root = _make_repo(tmp_path / "r", {"src/x.py": "x = 1\n"})
    with pytest.raises(gate.ConfigError, match="missing required vocabulary"):
        _run(root, bad)


@pytest.mark.unit
def test_a_yaml_document_start_marker_is_not_a_parse_error() -> None:
    """`---` and `...` are document markers, not content. OMN-18016.

    Several repositories run a `yamlfmt` pre-commit hook that PREPENDS `---`
    to every YAML file it touches. The adoption script writes a config without
    one; the hook adds it on the very first commit; the gate then died with
    `unrecognized top-level line: '---'` and exit 2 -- which surfaces as a red
    check that reads like a verdict and is actually "the gate did not run".

    Measured on omnimemory, omniintelligence, omnibase_compat and omnidash: in
    each the adoption commit was rewritten by that hook and every one of those
    four gate runs failed this way, while omnibase_spi (no such hook) passed.

    A gate that cannot be adopted in a repo that formats its YAML is not a
    gate. Both markers are skipped, exactly like a blank line or a comment --
    and nothing else about the fail-closed posture changes: an unparseable
    line is still exit 2.
    """
    parsed = gate.parse_restricted_yaml(
        '---\nmode: report\nallowed_top_level:\n  - "README.md"\n...\n',
        "fixture.yaml",
    )

    assert parsed["mode"] == "report"
    assert parsed["allowed_top_level"] == ["README.md"]


@pytest.mark.unit
def test_a_genuinely_unparseable_line_is_still_a_hard_error() -> None:
    """Positive control for the skip above.

    Skipping `---` must not become skipping anything the parser dislikes. If
    this assertion ever stops holding, the fail-closed parser has become a
    fail-open one and the previous test is what let it happen.
    """
    with pytest.raises(gate.ConfigError):
        gate.parse_restricted_yaml("mode: report\n@ not yaml at all\n", "fixture.yaml")
