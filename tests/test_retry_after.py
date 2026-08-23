"""Retry-after carried on `Decision`: recorded by put(), read by waiting()."""
from typing import List, Optional

import pytest

from pyrate_limiter import Decision, FixedWindow, InMemoryBucket, Rate, RateItem
from pyrate_limiter.abstracts.algorithm import ADMITTED, SlidingWindowLog


def legacy_waiting(bucket, item: RateItem) -> int:
    """The pre-4.5 derivation, kept as the reference to cross-check against."""
    rate = bucket.failing_rate

    if rate is None:
        return 0

    if item.weight > rate.limit:
        return -1

    bound_item = bucket.peek(rate.limit - item.weight)

    if bound_item is None:
        return 0

    return bound_item.timestamp - (item.timestamp - rate.interval) + 1


# --------------------------------------------------------------- Decision

def test_decision_defaults():
    assert Decision().retry_after_ms is None
    assert Decision().allowed is True
    assert ADMITTED.allowed is True
    assert ADMITTED.retry_after_ms is None


def test_decision_carries_retry_after():
    rate = Rate(3, 1000)
    denied = Decision(failing_rate=rate, retry_after_ms=250)
    assert denied.allowed is False
    assert denied.failing_rate is rate
    assert denied.retry_after_ms == 250


# ------------------------------------------------------- LogAlgorithm.decide

def test_blocking_offset_and_retry_after():
    algo = SlidingWindowLog()
    rate = Rate(5, 1000)
    assert algo.blocking_offset(rate, 1) == 4
    assert algo.blocking_offset(rate, 5) == 0
    # +1 clears the inclusive lower bound.
    assert algo.retry_after(rate, blocking_timestamp=500, now=1200) == 301


def test_decide_skips_lookup_when_admitted():
    algo = SlidingWindowLog()
    rates = [Rate(3, 1000)]

    def boom(_offset):
        raise AssertionError("decide() must not look up storage when admitting")

    decision = algo.decide(rates, [0], weight=1, now=1000, peek_timestamp=boom)
    assert decision.allowed
    assert decision.retry_after_ms is None


def test_decide_skips_lookup_when_weight_can_never_fit():
    algo = SlidingWindowLog()
    rates = [Rate(3, 1000)]

    def boom(_offset):
        raise AssertionError("decide() must not look up storage for an impossible weight")

    decision = algo.decide(rates, [0], weight=4, now=1000, peek_timestamp=boom)
    assert not decision.allowed
    # None, not 0: waiting() reports -1 for a weight over the limit.
    assert decision.retry_after_ms is None


def test_decide_resolves_retry_after_on_denial():
    algo = SlidingWindowLog()
    rates = [Rate(3, 1000)]
    seen: List[int] = []

    def peek(offset: int) -> Optional[int]:
        seen.append(offset)
        return 700

    decision = algo.decide(rates, [3], weight=1, now=1200, peek_timestamp=peek)
    assert seen == [2]  # limit 3 - weight 1
    assert decision.failing_rate is rates[0]
    assert decision.retry_after_ms == 700 + 1000 - 1200 + 1


def test_decide_reports_zero_when_nothing_left_to_expire():
    algo = SlidingWindowLog()
    decision = algo.decide([Rate(3, 1000)], [3], weight=1, now=1200, peek_timestamp=lambda _o: None)
    assert not decision.allowed
    assert decision.retry_after_ms == 0


# --------------------------------------------------- recorded wait on buckets

@pytest.mark.parametrize(
    "rates",
    [
        [Rate(1, 100)],
        [Rate(3, 1000)],
        [Rate(3, 1000), Rate(5, 5000)],
        [Rate(10, 1000), Rate(20, 10000)],
    ],
    ids=["tiny", "single", "two-rates", "wide"],
)
@pytest.mark.parametrize("weight", [1, 2, 3])
def test_recorded_wait_matches_legacy_derivation(rates, weight):
    """What put() records must equal what waiting() used to derive."""
    bucket = InMemoryBucket(rates)
    denials = 0

    for step in range(40):
        item = RateItem("x", 100_000 + step * 37, weight=weight)

        if bucket.put(item):
            continue

        denials += 1
        assert bucket.waiting(item) == legacy_waiting(bucket, item)

    assert denials > 0, "scenario never exercised the denial path"


def test_waiting_does_not_touch_storage_when_put_recorded_a_wait():
    bucket = InMemoryBucket([Rate(2, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1100)) is True

    item = RateItem("a", 1200)
    assert bucket.put(item) is False

    def boom(_index):
        raise AssertionError("waiting() must not peek when put() recorded a wait")

    bucket.peek = boom  # type: ignore[method-assign]
    # Blocking item is 1 place from the newest -> ts 1000.
    assert bucket.waiting(item) == 1000 + 1000 - 1200 + 1


def test_recorded_wait_is_not_reused_for_a_different_weight():
    bucket = InMemoryBucket([Rate(3, 1000)])

    for ts in (1000, 1100, 1200):
        assert bucket.put(RateItem("a", ts)) is True

    light = RateItem("a", 1300, weight=1)
    assert bucket.put(light) is False
    assert bucket.waiting(light) == 1000 + 1000 - 1300 + 1  # 701

    # A heavier item waits on a different stored item.
    heavy = RateItem("a", 1300, weight=2)
    assert bucket.waiting(heavy) == 1100 + 1000 - 1300 + 1  # 801
    assert bucket.waiting(heavy) == legacy_waiting(bucket, heavy)


def test_recorded_wait_survives_a_later_query_timestamp():
    """Recorded as an absolute instant, so a later query shrinks the wait."""
    bucket = InMemoryBucket([Rate(1, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True

    item = RateItem("a", 1000)
    assert bucket.put(item) is False
    assert bucket.waiting(item) == 1001

    assert bucket.waiting(RateItem("a", 1500)) == 501
    # Past the point where it fits, the wait floors at 0 rather than going negative.
    assert bucket.waiting(RateItem("a", 9000)) == 0


def test_successful_put_clears_the_recorded_wait():
    bucket = InMemoryBucket([Rate(1, 100)])
    assert bucket.put(RateItem("a", 1000)) is True

    denied = RateItem("a", 1000)
    assert bucket.put(denied) is False
    assert bucket.failing_rate is not None
    assert bucket._last_wait is not None

    assert bucket.put(RateItem("a", 2000)) is True
    assert bucket.failing_rate is None
    assert bucket._last_wait is None
    assert bucket.waiting(denied) == 0


# ------------------------------------------------------------- put_decision

def test_put_decision_on_success():
    bucket = InMemoryBucket([Rate(2, 1000)])
    decision = bucket.put_decision(RateItem("a", 1000))
    assert isinstance(decision, Decision)
    assert decision.allowed
    assert decision.failing_rate is None


def test_put_decision_on_denial_carries_the_wait():
    rates = [Rate(1, 1000)]
    bucket = InMemoryBucket(rates)
    assert bucket.put(RateItem("a", 1000)) is True

    decision = bucket.put_decision(RateItem("a", 1200))
    assert isinstance(decision, Decision)
    assert not decision.allowed
    assert decision.failing_rate is rates[0]
    assert decision.retry_after_ms == 1000 + 1000 - 1200 + 1


def test_put_decision_for_a_weightless_item():
    bucket = InMemoryBucket([Rate(1, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1000)) is False

    decision = bucket.put_decision(RateItem("a", 1000, weight=0))
    assert isinstance(decision, Decision)
    assert decision.allowed


def test_weightless_put_clears_a_standing_denial():
    """A trivial admit still records: the previous denial must not survive it."""
    bucket = InMemoryBucket([Rate(1, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1000)) is False
    assert bucket.failing_rate is not None
    assert bucket._last_wait is not None

    assert bucket.put(RateItem("a", 1000, weight=0)) is True
    assert bucket.failing_rate is None
    assert bucket._last_wait is None


def test_put_decision_reports_no_wait_for_an_impossible_weight():
    rates = [Rate(2, 1000)]
    bucket = InMemoryBucket(rates)

    decision = bucket.put_decision(RateItem("a", 1000, weight=5))
    assert isinstance(decision, Decision)
    assert not decision.allowed
    assert decision.failing_rate is rates[0]
    assert decision.retry_after_ms is None
    assert bucket.waiting(RateItem("a", 1000, weight=5)) == -1


# ------------------------------------------------- fallback for custom buckets

class LegacyBucket(InMemoryBucket):
    """Pre-4.5 contract: sets `failing_rate`, records no retry-after."""

    def put(self, item: RateItem) -> bool:
        admitted = super().put(item)
        self._last_wait = None
        return admitted


def test_waiting_falls_back_to_storage_when_nothing_was_recorded():
    bucket = LegacyBucket([Rate(2, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True
    assert bucket.put(RateItem("a", 1100)) is True

    item = RateItem("a", 1200)
    assert bucket.put(item) is False
    assert bucket._last_wait is None

    assert bucket.waiting(item) == legacy_waiting(bucket, item)
    assert bucket.waiting(item) == 1000 + 1000 - 1200 + 1


def test_put_decision_reports_unknown_wait_for_a_legacy_bucket():
    bucket = LegacyBucket([Rate(1, 1000)])
    assert bucket.put(RateItem("a", 1000)) is True

    decision = bucket.put_decision(RateItem("a", 1200))
    assert isinstance(decision, Decision)
    assert not decision.allowed
    assert decision.retry_after_ms is None  # "ask waiting()", not "no wait"
    assert bucket.waiting(RateItem("a", 1200)) == 801


# ------------------------------------------------------- redis lua sentinels

class StubRedis:
    """Returns a canned `evalsha` reply, to pin the sentinel mapping."""

    def __init__(self, reply):
        self.reply = reply

    def evalsha(self, *_args, **_kwargs):
        return self.reply


def _redis_bucket(reply, rates):
    from pyrate_limiter import RedisBucket

    return RedisBucket(rates, StubRedis(reply), "stub-key", "stub-hash")


def test_redis_sentinel_never_fits():
    rates = [Rate(3, 1000)]
    bucket = _redis_bucket([0, -1], rates)

    item = RateItem("a", 1000, weight=9)
    assert bucket.put(item) is False
    assert bucket.failing_rate is rates[0]
    assert bucket._last_wait is None
    assert bucket.waiting(item) == -1


def test_redis_sentinel_no_blocking_item():
    """-2 must not read as "never fits": it means already ready, wait 0."""
    rates = [Rate(3, 1000)]
    bucket = _redis_bucket([0, -2], rates)

    item = RateItem("a", 1000, weight=1)
    assert bucket.put(item) is False
    assert bucket.failing_rate is rates[0]
    assert bucket.waiting(item) == 0

    decision = bucket.put_decision(RateItem("a", 1000, weight=1))
    assert isinstance(decision, Decision)
    assert decision.retry_after_ms == 0


def test_redis_blocking_timestamp_becomes_a_wait():
    rates = [Rate(3, 1000)]
    bucket = _redis_bucket([0, 700], rates)

    item = RateItem("a", 1200, weight=1)
    assert bucket.put(item) is False
    assert bucket.waiting(item) == 700 + 1000 - 1200 + 1


# ------------------------------------------------- fallback paths in waiting()

class AsyncLegacyBucket(InMemoryBucket):
    """Pre-4.5 contract *and* async: records nothing, awaitable peek()."""

    is_async = True

    def put(self, item: RateItem):
        admitted = super().put(item)
        self._last_wait = None

        async def _put():
            return admitted

        return _put()

    # Deliberately widens InMemoryBucket's narrowed peek() back to the
    # abstract contract, which allows an awaitable.
    async def peek(self, index: int):  # type: ignore[override]
        return super().peek(index)


@pytest.mark.asyncio
async def test_waiting_awaits_an_async_peek_in_the_fallback():
    """The fallback has to resolve an awaitable peek() before it can measure."""
    bucket = AsyncLegacyBucket([Rate(2, 1000)])
    assert await bucket.put(RateItem("a", 1000)) is True
    assert await bucket.put(RateItem("a", 1100)) is True

    item = RateItem("a", 1200)
    assert await bucket.put(item) is False
    assert bucket._last_wait is None

    assert await bucket.waiting(item) == 1000 + 1000 - 1200 + 1


@pytest.mark.asyncio
async def test_async_fallback_handles_an_empty_bucket():
    bucket = AsyncLegacyBucket([Rate(1, 1000)])
    bucket.failing_rate = bucket.rates[0]  # denial with nothing stored
    assert await bucket.waiting(RateItem("a", 1000)) == 0


def test_fallback_skips_the_lookup_when_the_policy_wants_no_entry():
    """FixedWindow waits to a boundary, so the fallback must not peek at all."""
    bucket = LegacyBucket([Rate(2, 1000)], algorithm=FixedWindow())

    for ts in (1000, 1100):
        assert bucket.put(RateItem("a", ts)) is True

    item = RateItem("a", 1200)
    assert bucket.put(item) is False
    assert bucket._last_wait is None

    def boom(_index):
        raise AssertionError("FixedWindow's wait does not depend on a stored entry")

    bucket.peek = boom  # type: ignore[method-assign]
    assert bucket.waiting(item) == 800  # to the 2000 boundary


def test_waiting_asks_the_algorithm_for_the_maximum_weight():
    """The ceiling is the policy's, not blindly rate.limit."""
    rates = [Rate(3, 1000)]
    bucket = InMemoryBucket(rates)
    bucket.failing_rate = rates[0]

    assert bucket.waiting(RateItem("a", 1000, weight=3)) != -1
    assert bucket.waiting(RateItem("a", 1000, weight=4)) == -1
