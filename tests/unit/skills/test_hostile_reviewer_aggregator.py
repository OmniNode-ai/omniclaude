# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT
import json
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).parents[3]
    / "plugins/onex/skills/hostile_reviewer/aggregate_reviews.py"
)


@pytest.mark.unit
def test_script_exists() -> None:
    assert SCRIPT.exists(), f"Script not found at {SCRIPT}"


@pytest.mark.unit
def test_merge_findings_dedup() -> None:
    import aggregate_reviews

    findings_a = [
        {
            "description": "SQL injection in query builder",
            "confidence": "high",
            "source": "gemini",
        }
    ]
    findings_b = [
        {
            "description": "SQL injection vulnerability in query builder",
            "confidence": "medium",
            "source": "codex",
        }
    ]
    merged = aggregate_reviews.merge_findings([findings_a, findings_b])
    assert len(merged) == 1, f"Expected 1 merged finding, got {len(merged)}"
    assert set(merged[0]["sources"]) == {"gemini", "codex"}


@pytest.mark.unit
def test_merge_findings_union_distinct() -> None:
    import aggregate_reviews

    findings_a = [
        {
            "description": "Race condition in cache update",
            "confidence": "high",
            "source": "gemini",
        }
    ]
    findings_b = [
        {
            "description": "Missing auth check on admin endpoint",
            "confidence": "high",
            "source": "codex",
        }
    ]
    merged = aggregate_reviews.merge_findings([findings_a, findings_b])
    assert len(merged) == 2, f"Expected 2 distinct findings, got {len(merged)}"


@pytest.mark.unit
def test_merge_findings_stop_word_no_collision() -> None:
    """SQL injection and command injection must NOT merge despite sharing 'injection'."""
    import aggregate_reviews

    findings_a = [
        {
            "description": "SQL injection in query builder allows data exfiltration",
            "confidence": "high",
            "source": "gemini",
        }
    ]
    findings_b = [
        {
            "description": "Command injection in shell executor bypasses sandbox",
            "confidence": "high",
            "source": "codex",
        }
    ]
    merged = aggregate_reviews.merge_findings([findings_a, findings_b])
    assert len(merged) == 2, (
        "Stop-word filter must prevent false merge on shared technical terms"
    )


@pytest.mark.unit
def test_aggregate_verdict_blocking() -> None:
    import aggregate_reviews

    findings = [
        {"description": "x", "confidence": "high", "sources": ["gemini", "codex"]}
    ]
    assert (
        aggregate_reviews.compute_verdict(findings)
        == aggregate_reviews.EnumReviewVerdict.blocking_issue
    )


@pytest.mark.unit
def test_aggregate_verdict_risks_noted() -> None:
    import aggregate_reviews

    findings = [{"description": "x", "confidence": "high", "sources": ["gemini"]}]
    assert (
        aggregate_reviews.compute_verdict(findings)
        == aggregate_reviews.EnumReviewVerdict.risks_noted
    )


@pytest.mark.unit
def test_aggregate_verdict_clean() -> None:
    import aggregate_reviews

    assert (
        aggregate_reviews.compute_verdict([])
        == aggregate_reviews.EnumReviewVerdict.clean
    )


@pytest.mark.unit
def test_gemini_driver_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import aggregate_reviews

    fake_output = json.dumps(
        {
            "findings": [
                {
                    "description": "SQL injection",
                    "confidence": "high",
                    "detection": "query fails",
                }
            ]
        }
    )

    class FakeResult:
        stdout = fake_output
        returncode = 0

    monkeypatch.setattr(
        aggregate_reviews.subprocess, "run", lambda *a, **kw: FakeResult()
    )
    findings = aggregate_reviews.run_gemini("fake diff")
    assert len(findings) == 1
    assert findings[0]["source"] == "gemini"


@pytest.mark.unit
def test_codex_driver_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import aggregate_reviews

    output = "Here is my review:\n" + json.dumps(
        {
            "findings": [
                {
                    "description": "auth bypass",
                    "confidence": "high",
                    "detection": "401 never returned",
                }
            ]
        }
    )

    class FakeResult:
        stdout = output
        returncode = 0

    monkeypatch.setattr(
        aggregate_reviews.subprocess, "run", lambda *a, **kw: FakeResult()
    )
    findings = aggregate_reviews.run_codex("abc123sha")
    assert len(findings) == 1
    assert findings[0]["source"] == "codex"


@pytest.mark.unit
def test_extract_first_json_object_stops_at_first_complete() -> None:
    """Brace-counting extraction must stop at the FIRST complete object, not last '}'."""
    import aggregate_reviews

    # Model emits analysis JSON then a trailing findings JSON — only first should be extracted
    text = '{"analysis": "ok"} some prose {"findings": [{"description": "x"}]}'
    result = aggregate_reviews._extract_first_json_object(text)
    assert result == '{"analysis": "ok"}'


@pytest.mark.unit
def test_extract_first_json_object_with_trailing_prose() -> None:
    """JSON followed by prose does not corrupt extraction."""
    import aggregate_reviews

    text = 'Here is my review: {"findings": [{"description": "SQL injection"}]} Feel free to ask.'
    result = aggregate_reviews._extract_first_json_object(text)
    assert result is not None
    data = json.loads(result)
    assert "findings" in data


@pytest.mark.unit
def test_http_driver_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    import aggregate_reviews

    response_body = json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "findings": [
                                    {
                                        "description": "TOCTOU race",
                                        "confidence": "medium",
                                        "detection": "stress test",
                                    }
                                ]
                            }
                        )
                    }
                }
            ]
        }
    ).encode()

    class FakeResp:
        def read(self) -> bytes:
            return response_body

        def __enter__(self) -> "FakeResp":
            return self

        def __exit__(self, *a: object) -> None:
            pass

    monkeypatch.setattr(
        aggregate_reviews.urllib.request, "urlopen", lambda *a, **kw: FakeResp()
    )
    findings = aggregate_reviews.run_http_model(
        "qwen3-coder", "http://localhost:8000", "Qwen3-Coder-30B", "fake diff"
    )
    assert len(findings) == 1
    assert findings[0]["source"] == "qwen3-coder"


@pytest.mark.unit
def test_run_all_models_handles_coordinator_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TimeoutError from as_completed() must not crash run_all_models().

    When the 210s coordinator cap expires, as_completed() raises TimeoutError.
    The function must catch it, collect completed futures, add remaining to
    models_failed, and return a valid ModelAggregateResult (not crash).

    Strategy: patch `as_completed` on the aggregate_reviews module (where it was
    imported by name) to raise immediately. Also patch `subprocess.run` to return
    a valid diff so run_all_models reaches the ThreadPoolExecutor call.
    """
    import aggregate_reviews

    def fake_as_completed(fs: object, timeout: float) -> object:
        raise TimeoutError("simulated coordinator cap")

    monkeypatch.setattr(aggregate_reviews, "as_completed", fake_as_completed)

    class FakeDiff:
        stdout = "+def foo(): pass\n"
        returncode = 0
        stderr = ""

    class FakeSha:
        stdout = "abc123\n"
        returncode = 0

    call_count = [0]

    def fake_run(*args: object, **kwargs: object) -> object:
        call_count[0] += 1
        return FakeDiff() if call_count[0] == 1 else FakeSha()

    monkeypatch.setattr(aggregate_reviews.subprocess, "run", fake_run)
    monkeypatch.delenv("LLM_CODER_URL", raising=False)
    monkeypatch.delenv("LLM_DEEPSEEK_R1_URL", raising=False)

    result = aggregate_reviews.run_all_models("99", "org/repo")
    # Must return a valid ModelAggregateResult (no raise), with models_failed populated
    assert isinstance(result, aggregate_reviews.ModelAggregateResult)
    assert len(result.models_failed) > 0, (
        "Timed-out models must appear in models_failed"
    )
    assert result.verdict in aggregate_reviews.EnumReviewVerdict.__members__.values()


@pytest.mark.unit
def test_emit_result_non_fatal_on_connection_refused() -> None:
    """ConnectionRefusedError (daemon down) must not raise."""
    import aggregate_reviews

    def fake_emit(event_type: str, payload: dict) -> bool:
        raise ConnectionRefusedError("daemon not running")

    result = aggregate_reviews.ModelAggregateResult(
        success=True,
        findings=[],
        models_run=["gemini"],
        models_failed=[],
        verdict="clean",
    )
    # Must not raise; emit_fn is injected (no sys.path mutation needed)
    aggregate_reviews.emit_result(result, "1", "org/repo", emit_fn=fake_emit)


@pytest.mark.unit
def test_emit_result_calls_emit_fn_with_correct_event_type() -> None:
    """Successful result emits 'hostile.reviewer.completed'."""
    import aggregate_reviews

    captured: list[tuple[str, dict]] = []

    def fake_emit(event_type: str, payload: dict) -> bool:
        captured.append((event_type, payload))
        return True

    result = aggregate_reviews.ModelAggregateResult(
        success=True,
        findings=[],
        models_run=["gemini"],
        models_failed=[],
        verdict="clean",
    )
    aggregate_reviews.emit_result(result, "42", "org/repo", emit_fn=fake_emit)
    assert len(captured) == 1
    assert captured[0][0] == "hostile.reviewer.completed"
    assert captured[0][1]["pr_number"] == "42"
    assert captured[0][1]["verdict"] == "clean"
