# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Unit tests for the hardcoded LLM reference detector (OMN-11944)."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validation" / "validate_no_hardcoded_llm_refs.py"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "validation"))
from validate_no_hardcoded_llm_refs import (  # noqa: E402
    _DIRECT_PROVIDER_RE,
    _check_timeout_in_llm_context,
    _is_skip_path,
    _load_allowlist,
    _scan_file,
)

# ---------------------------------------------------------------------------
# Model ID detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestModelIdDetection:
    def test_claude_sonnet_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('model = "claude-sonnet-4-6"\n')
        allowlist: set[str] = set()
        inventory: list[dict] = []
        violations = _scan_file(f, allowlist, inventory)
        assert violations, "Expected model ID violation"
        assert any("hardcoded_model_id" in v for v in violations)

    def test_claude_opus_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('default_model = "claude-opus-4-6"\n')
        violations = _scan_file(f, set(), [])
        assert violations

    def test_qwen_coder_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('name = "qwen3-coder-30b"\n')
        violations = _scan_file(f, set(), [])
        assert violations

    def test_deepseek_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('model_id = "deepseek-r1-14b"\n')
        violations = _scan_file(f, set(), [])
        assert violations

    def test_gemini_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('provider_model = "gemini-2.5-flash"\n')
        violations = _scan_file(f, set(), [])
        assert violations

    def test_suppression_marker_clears_violation(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('model = "claude-sonnet-4-6"  # llm-hardcode-ok: test fixture\n')
        violations = _scan_file(f, set(), [])
        assert violations == [], "Suppression marker should clear the violation"

    def test_allowlist_entry_clears_violation(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('model = "claude-sonnet-4-6"\n')
        rel = str(f)
        allowlist = {f"{rel}:1"}
        violations = _scan_file(f, allowlist, [])
        assert violations == [], "Allowlist entry should clear the violation"

    def test_clean_file_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "router.py"
        f.write_text('model_key = get_model_from_registry("code_generation")\n')
        violations = _scan_file(f, set(), [])
        assert violations == []


# ---------------------------------------------------------------------------
# Endpoint URL detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEndpointUrlDetection:
    def test_vllm_endpoint_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "client.py"
        f.write_text('base_url = "http://192.168.86.201:8000/v1"\n')
        violations = _scan_file(f, set(), [])
        assert violations
        assert any("llm_endpoint_url" in v for v in violations)

    def test_embedding_endpoint_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "client.py"
        f.write_text('EMBED_URL = "http://192.168.86.200:8100/v1/embeddings"\n')
        violations = _scan_file(f, set(), [])
        assert violations

    def test_non_llm_ip_not_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "client.py"
        # Non-LLM port — should not match
        f.write_text('postgres_url = "192.168.86.201:5432"\n')
        violations = _scan_file(f, set(), [])
        # Port 5432 is not an LLM port — should not flag
        llm_violations = [v for v in violations if "llm_endpoint_url" in v]
        assert llm_violations == []

    def test_suppressed_endpoint_passes(self, tmp_path: Path) -> None:
        f = tmp_path / "client.py"
        f.write_text(
            'url = "http://192.168.86.201:8000/v1"  # llm-hardcode-ok: local dev only\n'
        )
        violations = _scan_file(f, set(), [])
        assert violations == []


# ---------------------------------------------------------------------------
# Direct provider construction detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDirectProviderConstruction:
    def test_openai_sync_flagged(self) -> None:
        assert _DIRECT_PROVIDER_RE.search("client = openai.OpenAI(base_url=...)")

    def test_openai_async_flagged(self) -> None:
        assert _DIRECT_PROVIDER_RE.search("client = openai.AsyncOpenAI()")

    def test_anthropic_sync_flagged(self) -> None:
        assert _DIRECT_PROVIDER_RE.search("client = anthropic.Anthropic(api_key=k)")

    def test_anthropic_async_flagged(self) -> None:
        assert _DIRECT_PROVIDER_RE.search("client = anthropic.AsyncAnthropic()")

    def test_non_provider_call_not_flagged(self) -> None:
        assert not _DIRECT_PROVIDER_RE.search('result = some_client.create(model="x")')


# ---------------------------------------------------------------------------
# Timeout literal in LLM context detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLlmTimeoutDetection:
    def test_timeout_in_openai_context_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "caller.py"
        f.write_text(
            textwrap.dedent("""\
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    timeout=30,
                )
                result = await openai_client.chat.completions.create(messages=msgs)
        """)
        )
        violations = _check_timeout_in_llm_context(f)
        assert violations, "Expected timeout violation in LLM context"

    def test_timeout_outside_llm_context_not_flagged(self, tmp_path: Path) -> None:
        f = tmp_path / "db_client.py"
        # Pure HTTP client with no LLM signal in surrounding context
        f.write_text(
            textwrap.dedent("""\
            import httpx

            async def fetch_metrics(url: str) -> dict:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, timeout=5)
                return response.json()
        """)
        )
        violations = _check_timeout_in_llm_context(f)
        assert violations == [], "Timeout outside LLM context should not flag"


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAllowlistLoading:
    def test_empty_allowlist_returns_empty_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nonexistent = tmp_path / "no_such_file.json"
        import validate_no_hardcoded_llm_refs as mod

        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", nonexistent)
        result = _load_allowlist()
        assert result == set()

    def test_valid_allowlist_parsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowlist_file = tmp_path / "allowlist.json"
        allowlist_file.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "path": "src/foo.py",
                            "lineno": 42,
                            "reason": "test",
                            "ticket": "OMN-1",
                            "owner": "x",
                        },
                        {
                            "path": "src/bar.py",
                            "lineno": 7,
                            "reason": "test",
                            "ticket": "OMN-2",
                            "owner": "y",
                        },
                    ]
                }
            )
        )
        import validate_no_hardcoded_llm_refs as mod

        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", allowlist_file)
        result = _load_allowlist()
        assert "src/foo.py:42" in result
        assert "src/bar.py:7" in result

    def test_malformed_allowlist_returns_empty_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")
        import validate_no_hardcoded_llm_refs as mod

        monkeypatch.setattr(mod, "_ALLOWLIST_PATH", bad_file)
        result = _load_allowlist()
        assert result == set()


# ---------------------------------------------------------------------------
# Skip path filter — test/fixture/doc files excluded
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSkipPathFilter:
    def test_test_file_skipped(self, tmp_path: Path) -> None:
        test_dir = tmp_path / "tests"
        test_dir.mkdir()
        f = test_dir / "test_router.py"
        f.write_text('model = "claude-sonnet-4-6"\n')

        assert _is_skip_path(f), "File under tests/ should be skipped"

    def test_fixture_file_skipped(self, tmp_path: Path) -> None:
        fixture_dir = tmp_path / "fixtures"
        fixture_dir.mkdir()
        f = fixture_dir / "response.py"
        f.write_text('model = "deepseek-r1"\n')

        assert _is_skip_path(f), "File under fixtures/ should be skipped"

    def test_runtime_src_file_violations_detected(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        f = src_dir / "router.py"
        f.write_text('model = "claude-sonnet-4-6"\n')

        # src/router.py is not in a skip segment
        assert not _is_skip_path(f), "File under src/ should not be skipped"
        # And _scan_file should flag it
        violations = _scan_file(f, set(), [])
        assert violations, "Expected model ID violation in src/ file"
