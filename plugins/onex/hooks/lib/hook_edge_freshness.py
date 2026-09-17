#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2025 OmniNode.ai Inc.
# SPDX-License-Identifier: MIT

"""Freshness measured on RECORD CONTENT, not on offsets (OMN-18120 AC1).

The condition this exists to catch
----------------------------------
Between 2026-09-06 and 2026-09-10 the hook wire on the lab compose dev
lane looked healthy by every surface anyone checks, and carried no new fact
at all:

* consumer-group offsets advanced;
* every group was ``Stable`` with ``TOTAL-LAG 0``;
* ``CURRENT-OFFSET`` equalled ``LOG-END-OFFSET`` on all four hook topics;
* the projection wrote continuously -- ``n_tup_upd`` reached 94,811;
* autoanalyze fired that same morning.

And ``omninode_internal.work_events`` had not taken a single INSERT since
2026-09-06T20:44:25Z, because the newest records on the topic were *replays*
of pre-09-06 events. A replayed record carries the ``emitted_at`` it was born
with, so it advances every offset a liveness probe reads while adding no
information. The three newest ``session-started`` records at the time had
broker timestamps of 05:02Z, 05:05Z and 05:07Z on 2026-09-10 and
``emitted_at`` values from 2026-09-06 -- and the last two were the same event
delivered twice, identical ``session_id``, ``correlation_id``, ``entity_id``
and ``emitted_at``.

So an offset-based check, a lag-based check, and an "is anything attached"
check all report green on a dead stream. The only thing that distinguishes a
live stream from a replaying one is the age of the record CONTENT, and that is
what this module compares.

What it does NOT do
-------------------
It does not read Kafka. It is a pure verdict over two samples someone else
collected, for three reasons: the collection needs a broker credential this
hook path deliberately does not hold; the defect is in the *reasoning* about
liveness rather than in any one probe; and a pure function makes the failing
condition a value a test can construct instead of a broker state a test would
have to reproduce.

Fail-closed
-----------
A topic whose newest record content cannot be determined is reported STALE,
never fresh. "I could not tell" is the same answer as "I do not know it is
alive", and the whole subject of this ticket is surfaces that reported health
they had not established.

Related: ``hook_emit_health.py`` answers the adjacent question on the PRODUCER
side of the same chain -- whether the local journal is draining at all. This
module answers the CONSUMER side: whether what arrives is new.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

# A hook stream on an active workstation produces continuously. An hour of no
# NEW content, while offsets move, is not a quiet period -- it is a replay.
DEFAULT_MAX_CONTENT_AGE_SECONDS = 3600.0


class EnumFreshness:
    """Verdict vocabulary. Four outcomes, and they are not interchangeable."""

    FRESH = "fresh"

    # The defeating condition: offsets moving, content ageing. This is the
    # verdict every other liveness surface is incapable of producing.
    STALE_CONTENT_LIVE_OFFSETS = "stale_content_live_offsets"

    # Content ageing and offsets flat. Also broken, but a different defect --
    # nothing is arriving, rather than the wrong thing arriving.
    STALE_CONTENT_IDLE = "stale_content_idle"

    # Newest content unknown. Fails closed.
    CONTENT_UNKNOWN = "content_unknown"


@dataclass(frozen=True)
class ModelTopicSample:
    """One observation of a topic: where the offsets are, and how old the head is.

    ``newest_record_emitted_at`` is the ``emitted_at`` carried INSIDE the
    newest record, never the broker's append timestamp. The broker timestamp
    of a replayed record is now; its ``emitted_at`` is when the event actually
    happened, and only the second one can tell them apart.
    """

    topic: str
    observed_at: datetime
    consumer_offset: int
    log_end_offset: int
    newest_record_emitted_at: datetime | None


@dataclass(frozen=True)
class ModelFreshnessVerdict:
    """What two samples of one topic prove about it."""

    topic: str
    verdict: str
    stale: bool
    content_age_seconds: float | None
    consumer_offset_delta: int
    log_end_offset_delta: int
    detail: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "verdict": self.verdict,
                "stale": self.stale,
                "content_age_seconds": self.content_age_seconds,
                "consumer_offset_delta": self.consumer_offset_delta,
                "log_end_offset_delta": self.log_end_offset_delta,
                "detail": self.detail,
            },
            sort_keys=True,
        )


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are read as UTC; every surface here emits UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def evaluate(
    before: ModelTopicSample,
    after: ModelTopicSample,
    *,
    max_content_age_seconds: float = DEFAULT_MAX_CONTENT_AGE_SECONDS,
) -> ModelFreshnessVerdict:
    """Verdict over two samples of the same topic.

    ``before`` and ``after`` must name the same topic; comparing two topics
    would produce a confident verdict about nothing.
    """
    if before.topic != after.topic:
        raise ValueError(
            f"samples name different topics ({before.topic!r} then "
            f"{after.topic!r}); a freshness verdict over two topics is not a "
            f"verdict"
        )

    consumer_delta = after.consumer_offset - before.consumer_offset
    log_end_delta = after.log_end_offset - before.log_end_offset
    offsets_moved = consumer_delta > 0 or log_end_delta > 0

    if after.newest_record_emitted_at is None:
        return ModelFreshnessVerdict(
            topic=after.topic,
            verdict=EnumFreshness.CONTENT_UNKNOWN,
            stale=True,
            content_age_seconds=None,
            consumer_offset_delta=consumer_delta,
            log_end_offset_delta=log_end_delta,
            detail=(
                "the newest record's own emitted_at could not be read, so "
                "freshness is UNESTABLISHED; reported stale because an "
                "unverified stream is not a live one"
            ),
        )

    age = (
        _as_utc(after.observed_at) - _as_utc(after.newest_record_emitted_at)
    ).total_seconds()

    if age <= max_content_age_seconds:
        return ModelFreshnessVerdict(
            topic=after.topic,
            verdict=EnumFreshness.FRESH,
            stale=False,
            content_age_seconds=age,
            consumer_offset_delta=consumer_delta,
            log_end_offset_delta=log_end_delta,
            detail=f"newest record content is {age:.0f}s old",
        )

    if offsets_moved:
        return ModelFreshnessVerdict(
            topic=after.topic,
            verdict=EnumFreshness.STALE_CONTENT_LIVE_OFFSETS,
            stale=True,
            content_age_seconds=age,
            consumer_offset_delta=consumer_delta,
            log_end_offset_delta=log_end_delta,
            detail=(
                f"offsets advanced (consumer +{consumer_delta}, log end "
                f"+{log_end_delta}) while the newest record content aged to "
                f"{age:.0f}s (bound {max_content_age_seconds:.0f}s) -- records "
                f"are arriving and none of them is new. Every offset-based and "
                f"lag-based liveness check reads GREEN in this state"
            ),
        )

    return ModelFreshnessVerdict(
        topic=after.topic,
        verdict=EnumFreshness.STALE_CONTENT_IDLE,
        stale=True,
        content_age_seconds=age,
        consumer_offset_delta=consumer_delta,
        log_end_offset_delta=log_end_delta,
        detail=(
            f"newest record content aged to {age:.0f}s (bound "
            f"{max_content_age_seconds:.0f}s) and no offset moved -- nothing "
            f"is arriving at all"
        ),
    )


def evaluate_all(
    pairs: list[tuple[ModelTopicSample, ModelTopicSample]],
    *,
    max_content_age_seconds: float = DEFAULT_MAX_CONTENT_AGE_SECONDS,
) -> list[ModelFreshnessVerdict]:
    return [
        evaluate(before, after, max_content_age_seconds=max_content_age_seconds)
        for before, after in pairs
    ]


def _sample_from_mapping(raw: dict[str, object]) -> ModelTopicSample:
    newest = raw.get("newest_record_emitted_at")
    return ModelTopicSample(
        topic=str(raw["topic"]),
        observed_at=datetime.fromisoformat(str(raw["observed_at"])),
        consumer_offset=int(raw["consumer_offset"]),  # type: ignore[arg-type]
        log_end_offset=int(raw["log_end_offset"]),  # type: ignore[arg-type]
        newest_record_emitted_at=(
            None if newest is None else datetime.fromisoformat(str(newest))
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Read `{"pairs": [[before, after], ...]}` on stdin; exit 1 if any is stale.

    The collector is whatever holds the broker credential -- this reads its
    output rather than taking one itself, which is what keeps the verdict
    testable without a broker.
    """
    parser = argparse.ArgumentParser(description="Record-content freshness verdict.")
    parser.add_argument(
        "--max-content-age-seconds",
        type=float,
        default=DEFAULT_MAX_CONTENT_AGE_SECONDS,
    )
    args = parser.parse_args(argv)

    raw = json.loads(sys.stdin.read())
    pairs = [
        (_sample_from_mapping(before), _sample_from_mapping(after))
        for before, after in raw["pairs"]
    ]
    verdicts = evaluate_all(pairs, max_content_age_seconds=args.max_content_age_seconds)
    for verdict in verdicts:
        print(verdict.to_json())
    return 1 if any(v.stale for v in verdicts) else 0


if __name__ == "__main__":
    sys.exit(main())
