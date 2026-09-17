# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""OMN-18120 AC1: fail on stale record CONTENT while offsets keep advancing.

The AC asks for a test that is RED against the state measured on the lab
compose dev lane between 2026-09-06 and 2026-09-10 -- offsets advancing,
consumer groups Stable at TOTAL-LAG 0, the projection writing 94,811 UPDATEs,
and the newest record content four days old because the stream was replaying
pre-09-06 events.

:func:`test_the_measured_2026_09_10_state_is_reported_stale` is that test.
It uses the ticket's own figures: `onex.evt.omniclaude.session-started.v1`
at log-end 1,251,873 with the three newest records carrying `emitted_at`
values from 2026-09-06, observed on 2026-09-10.

Its partner, :func:`test_a_live_stream_is_reported_fresh`, is the positive
control. Without it a checker that returned STALE unconditionally would pass
the AC.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    REPO_ROOT / "plugins" / "onex" / "hooks" / "lib" / "hook_edge_freshness.py"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("hook_edge_freshness", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hook_edge_freshness"] = module
    spec.loader.exec_module(module)
    return module


fresh = _load_module()

TOPIC = "onex.evt.omniclaude.session-started.v1"


def _sample(
    *,
    observed_at: datetime,
    consumer_offset: int,
    log_end_offset: int,
    newest: datetime | None,
    topic: str = TOPIC,
) -> Any:
    return fresh.ModelTopicSample(
        topic=topic,
        observed_at=observed_at,
        consumer_offset=consumer_offset,
        log_end_offset=log_end_offset,
        newest_record_emitted_at=newest,
    )


@pytest.mark.unit
class TestTheDefeatingCondition:
    """Offsets advancing, content ageing. The verdict nothing else can produce."""

    def test_the_measured_2026_09_10_state_is_reported_stale(self) -> None:
        """RED-first, against the figures recorded on OMN-18120.

        Consumer offsets advance by 4,895 over the window and the newest
        record content is from 2026-09-06T20:44:12Z -- the replay loop
        re-delivering already-projected events. `work_events` took zero
        INSERTs across the same period while taking 94,811 UPDATEs.
        """
        t0 = datetime(2026, 9, 10, 5, 2, 1, tzinfo=UTC)
        t1 = datetime(2026, 9, 10, 5, 7, 34, tzinfo=UTC)
        newest_content = datetime(2026, 9, 6, 20, 44, 12, tzinfo=UTC)

        verdict = fresh.evaluate(
            _sample(
                observed_at=t0,
                consumer_offset=1_246_978,
                log_end_offset=1_246_978,
                newest=newest_content,
            ),
            _sample(
                observed_at=t1,
                consumer_offset=1_251_873,
                log_end_offset=1_251_873,
                newest=newest_content,
            ),
        )

        assert verdict.stale is True
        assert verdict.verdict == fresh.EnumFreshness.STALE_CONTENT_LIVE_OFFSETS
        assert verdict.consumer_offset_delta == 4_895
        # Four days of ageing, not four minutes of quiet.
        assert verdict.content_age_seconds > 3 * 24 * 3600
        assert "none of them is new" in verdict.detail

    def test_zero_lag_and_a_stable_group_do_not_make_it_fresh(self) -> None:
        """The surfaces that read green in the measured state are not inputs.

        ``CURRENT-OFFSET == LOG-END-OFFSET`` on every partition was TRUE
        throughout the outage. A checker that took lag as evidence would have
        agreed with every other surface that the stream was healthy.
        """
        now = datetime(2026, 9, 10, 5, 7, 34, tzinfo=UTC)
        verdict = fresh.evaluate(
            _sample(
                observed_at=now - timedelta(minutes=5),
                consumer_offset=599_687,
                log_end_offset=599_687,  # lag 0
                newest=now - timedelta(days=4),
            ),
            _sample(
                observed_at=now,
                consumer_offset=599_711,
                log_end_offset=599_711,  # still lag 0
                newest=now - timedelta(days=4),
            ),
        )
        assert verdict.stale is True
        assert verdict.verdict == fresh.EnumFreshness.STALE_CONTENT_LIVE_OFFSETS


@pytest.mark.unit
class TestTheOtherVerdicts:
    def test_a_live_stream_is_reported_fresh(self) -> None:
        """POSITIVE CONTROL: without it, always-STALE would satisfy the AC."""
        now = datetime(2026, 9, 16, 22, 40, tzinfo=UTC)
        verdict = fresh.evaluate(
            _sample(
                observed_at=now - timedelta(minutes=2),
                consumer_offset=664_671,
                log_end_offset=664_671,
                newest=now - timedelta(seconds=90),
            ),
            _sample(
                observed_at=now,
                consumer_offset=664_710,
                log_end_offset=664_710,
                newest=now - timedelta(seconds=5),
            ),
        )
        assert verdict.stale is False
        assert verdict.verdict == fresh.EnumFreshness.FRESH

    def test_stale_content_with_flat_offsets_is_a_different_verdict(self) -> None:
        """Nothing arriving is a different defect from the wrong thing arriving.

        Collapsing the two would lose the distinction that took three lanes to
        establish on this ticket: a replaying stream and a dead one need
        different repairs.
        """
        now = datetime(2026, 9, 10, 5, 7, tzinfo=UTC)
        verdict = fresh.evaluate(
            _sample(
                observed_at=now - timedelta(minutes=5),
                consumer_offset=8_660,
                log_end_offset=8_660,
                newest=now - timedelta(days=4),
            ),
            _sample(
                observed_at=now,
                consumer_offset=8_660,
                log_end_offset=8_660,
                newest=now - timedelta(days=4),
            ),
        )
        assert verdict.stale is True
        assert verdict.verdict == fresh.EnumFreshness.STALE_CONTENT_IDLE

    def test_unknown_content_fails_closed(self) -> None:
        """An unestablished stream is never reported live."""
        now = datetime(2026, 9, 16, 22, 40, tzinfo=UTC)
        verdict = fresh.evaluate(
            _sample(
                observed_at=now - timedelta(minutes=1),
                consumer_offset=1,
                log_end_offset=1,
                newest=None,
            ),
            _sample(observed_at=now, consumer_offset=9, log_end_offset=9, newest=None),
        )
        assert verdict.stale is True
        assert verdict.verdict == fresh.EnumFreshness.CONTENT_UNKNOWN
        assert verdict.content_age_seconds is None

    def test_naive_timestamps_are_read_as_utc(self) -> None:
        """Every surface in this chain emits UTC; a naive value is not a puzzle."""
        verdict = fresh.evaluate(
            _sample(
                observed_at=datetime(2026, 9, 16, 22, 0),
                consumer_offset=1,
                log_end_offset=1,
                newest=datetime(2026, 9, 16, 21, 59),
            ),
            _sample(
                observed_at=datetime(2026, 9, 16, 22, 1),
                consumer_offset=2,
                log_end_offset=2,
                newest=datetime(2026, 9, 16, 22, 0, 30),
            ),
        )
        assert verdict.stale is False

    def test_two_different_topics_is_refused_not_answered(self) -> None:
        now = datetime(2026, 9, 16, 22, 40, tzinfo=UTC)
        with pytest.raises(ValueError, match="different topics"):
            fresh.evaluate(
                _sample(
                    observed_at=now,
                    consumer_offset=1,
                    log_end_offset=1,
                    newest=now,
                    topic="onex.evt.omniclaude.session-started.v1",
                ),
                _sample(
                    observed_at=now,
                    consumer_offset=2,
                    log_end_offset=2,
                    newest=now,
                    topic="onex.evt.omniclaude.tool-executed.v1",
                ),
            )


@pytest.mark.unit
class TestCli:
    def test_exit_1_when_any_topic_is_stale(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "pairs": [
                [
                    {
                        "topic": TOPIC,
                        "observed_at": "2026-09-10T05:02:01+00:00",
                        "consumer_offset": 1_246_978,
                        "log_end_offset": 1_246_978,
                        "newest_record_emitted_at": "2026-09-06T20:44:12+00:00",
                    },
                    {
                        "topic": TOPIC,
                        "observed_at": "2026-09-10T05:07:34+00:00",
                        "consumer_offset": 1_251_873,
                        "log_end_offset": 1_251_873,
                        "newest_record_emitted_at": "2026-09-06T20:44:12+00:00",
                    },
                ]
            ]
        }
        monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload)))
        assert fresh.main([]) == 1
        line = json.loads(capsys.readouterr().out.strip())
        assert line["verdict"] == fresh.EnumFreshness.STALE_CONTENT_LIVE_OFFSETS

    def test_exit_0_when_every_topic_is_fresh(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = {
            "pairs": [
                [
                    {
                        "topic": TOPIC,
                        "observed_at": "2026-09-16T22:38:00+00:00",
                        "consumer_offset": 10,
                        "log_end_offset": 10,
                        "newest_record_emitted_at": "2026-09-16T22:37:30+00:00",
                    },
                    {
                        "topic": TOPIC,
                        "observed_at": "2026-09-16T22:40:00+00:00",
                        "consumer_offset": 12,
                        "log_end_offset": 12,
                        "newest_record_emitted_at": "2026-09-16T22:39:55+00:00",
                    },
                ]
            ]
        }
        monkeypatch.setattr("sys.stdin", _Stdin(json.dumps(payload)))
        assert fresh.main([]) == 0
        assert json.loads(capsys.readouterr().out.strip())["stale"] is False


class _Stdin:
    """Minimal stdin stand-in; the CLI only ever calls ``read()``."""

    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text
