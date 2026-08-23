"""GCRA / TokenBucket: constant-state rate limiting."""

import asyncio
import importlib.util
from time import monotonic, sleep

import pytest

from pyrate_limiter import (
    GCRA,
    Duration,
    InMemoryStateStore,
    Limiter,
    MultiprocessStateStore,
    Rate,
    RateItem,
    StateBucket,
    TokenBucket,
    id_generator,
)
from pyrate_limiter.abstracts.algorithm import ADMITTED, LogAlgorithm, StateAlgorithm
from pyrate_limiter.clocks import AbstractClock, WallClock


class FrozenClock(AbstractClock):
    """Time only moves when a test says so."""

    def __init__(self, start: int = 1_700_000_000_000):
        self.t = start

    def now(self) -> int:
        return self.t

    def advance(self, ms: int) -> int:
        self.t += ms
        return self.t


# ------------------------------------------------------------------ Rate.burst

def test_burst_defaults_to_limit():
    assert Rate(5, 1000).burst == 5
    assert Rate(5, 1000, burst=10).burst == 10


def test_burst_must_be_positive():
    with pytest.raises(AssertionError):
        Rate(5, 1000, burst=0)


def test_burst_shows_in_repr_only_when_it_differs():
    assert "burst" not in str(Rate(5, 1000))
    assert "burst=10" in str(Rate(5, 1000, burst=10))


# ------------------------------------------------------------------ the policy

def test_gcra_is_a_state_algorithm_not_a_log_one():
    assert isinstance(GCRA(), StateAlgorithm)
    assert not isinstance(GCRA(), LogAlgorithm)


def test_token_bucket_is_gcra():
    # Same policy, familiar name - not a second implementation to keep in sync.
    assert isinstance(TokenBucket(), GCRA)


def test_max_weight_is_the_burst_not_the_limit():
    assert GCRA().max_weight(Rate(5, 1000, burst=10)) == 10
    assert GCRA().max_weight(Rate(5, 1000)) == 5


def test_step_spends_one_emission_interval_per_unit():
    algo, rates = GCRA(), [Rate(4, 1000)]
    state = algo.initial(rates)

    state, decision = algo.step(rates, state, now=1000, weight=1)
    assert decision is ADMITTED
    assert state == (1250.0,)  # 1000ms / 4 = 250ms per unit

    state, decision = algo.step(rates, state, now=1000, weight=2)
    assert decision.allowed
    assert state == (1750.0,)


def test_step_denies_and_reports_the_exact_wait():
    algo, rates = GCRA(), [Rate(4, 1000)]
    state = algo.initial(rates)

    for _ in range(4):
        state, decision = algo.step(rates, state, now=1000, weight=1)
        assert decision.allowed

    state, decision = algo.step(rates, state, now=1000, weight=1)
    assert not decision.allowed
    assert decision.failing_rate is rates[0]
    assert decision.retry_after_ms == 250


def test_denial_spends_nothing():
    algo, rates = GCRA(), [Rate(2, 1000)]
    state = algo.initial(rates)

    for _ in range(2):
        state, _ = algo.step(rates, state, now=1000, weight=1)

    full = state
    for _ in range(5):
        state, decision = algo.step(rates, state, now=1000, weight=1)
        assert not decision.allowed

    # Repeated rejections must not push the TAT further out, or a client that
    # keeps retrying would starve itself.
    assert state == full


def test_multi_rate_commit_is_all_or_nothing():
    """A rate failing second must not leave the first one already debited."""
    algo = GCRA()
    rates = [Rate(10, 1000), Rate(12, 10_000)]
    state = algo.initial(rates)

    for _ in range(10):
        state, decision = algo.step(rates, state, now=1000, weight=1)
        assert decision.allowed

    # The wide rate still has room; the tight one does not.
    before = state
    state, decision = algo.step(rates, state, now=1000, weight=1)
    assert not decision.allowed
    assert decision.failing_rate is rates[0]
    assert state == before


def test_weight_over_burst_never_fits():
    algo, rates = GCRA(), [Rate(5, 1000, burst=5)]
    state, decision = algo.step(rates, algo.initial(rates), now=1000, weight=6)
    assert not decision.allowed
    assert decision.retry_after_ms is None  # not "wait 0"; it never fits


def test_burst_allows_a_bigger_lump_than_limit():
    algo, rates = GCRA(), [Rate(5, 1000, burst=20)]
    state = algo.initial(rates)

    state, decision = algo.step(rates, state, now=1000, weight=20)
    assert decision.allowed
    # ...and the next unit has to wait a full emission interval.
    _, decision = algo.step(rates, state, now=1000, weight=1)
    assert decision.retry_after_ms == 200


# ---------------------------------------------------------------- StateBucket

def test_bucket_admits_a_burst_then_drips():
    clock = FrozenClock()
    bucket = StateBucket([Rate(4, 1000)], clock=clock)

    for _ in range(4):
        assert bucket.put(RateItem("a", clock.now())) is True

    denied = RateItem("a", clock.now())
    assert bucket.put(denied) is False
    assert bucket.waiting(denied) == 250

    clock.advance(250)
    assert bucket.put(RateItem("a", clock.now())) is True


def test_bucket_waiting_re_derives_for_a_different_weight():
    clock = FrozenClock()
    bucket = StateBucket([Rate(3, 1000)], clock=clock)

    for _ in range(3):
        assert bucket.put(RateItem("a", clock.now())) is True

    light = RateItem("a", clock.now())
    assert bucket.put(light) is False
    assert bucket.waiting(light) == 334

    # A heavier query has a different answer, and asking must not spend anything.
    assert bucket.waiting(RateItem("a", clock.now(), weight=2)) == 667
    assert bucket.waiting(RateItem("a", clock.now(), weight=3)) == 1000
    assert bucket.waiting(light) == 334


def test_bucket_reports_minus_one_for_an_impossible_weight():
    rates = [Rate(3, 1000)]
    bucket = StateBucket(rates, clock=FrozenClock())

    item = RateItem("a", 1_700_000_000_000, weight=9)
    assert bucket.put(item) is False
    assert bucket.failing_rate is rates[0]
    assert bucket.waiting(item) == -1


def test_bucket_has_no_log_to_inspect():
    clock = FrozenClock()
    bucket = StateBucket([Rate(3, 1000)], clock=clock)
    assert bucket.put(RateItem("a", clock.now())) is True

    # The log contract genuinely does not apply here; both are documented no-ops.
    assert bucket.peek(0) is None
    assert bucket.leak(clock.now()) == 0


def test_count_is_units_owed_and_drains_with_time():
    clock = FrozenClock()
    bucket = StateBucket([Rate(4, 1000)], clock=clock)
    assert bucket.count() == 0

    for _ in range(4):
        bucket.put(RateItem("a", clock.now()))

    assert bucket.count() == 4
    clock.advance(500)
    assert bucket.count() == 2
    clock.advance(500)
    assert bucket.count() == 0


def test_flush_forgets_everything():
    clock = FrozenClock()
    bucket = StateBucket([Rate(2, 1000)], clock=clock)

    for _ in range(2):
        bucket.put(RateItem("a", clock.now()))

    assert bucket.put(RateItem("a", clock.now())) is False
    bucket.flush()

    assert bucket.failing_rate is None
    assert bucket.count() == 0
    assert bucket.put(RateItem("a", clock.now())) is True


def test_weightless_put_clears_a_standing_denial():
    clock = FrozenClock()
    bucket = StateBucket([Rate(1, 1000)], clock=clock)

    assert bucket.put(RateItem("a", clock.now())) is True
    assert bucket.put(RateItem("a", clock.now())) is False
    assert bucket.failing_rate is not None

    assert bucket.put(RateItem("a", clock.now(), weight=0)) is True
    assert bucket.failing_rate is None


def test_default_clock_follows_the_store():
    # A monotonic clock is meaningless across machines, so a shared store
    # must not inherit one by default.
    assert isinstance(StateBucket([Rate(1, 1000)])._clock, type(InMemoryStateStore.default_clock))

    redis = pytest.importorskip("redis")
    from pyrate_limiter import RedisStateStore

    store = RedisStateStore(redis.Redis.from_url("redis://localhost:6379"), "unused")
    assert isinstance(StateBucket([Rate(1, 1000)], store=store)._clock, WallClock)


# ------------------------------------------------------------- sustained rate

def test_sustained_throughput_matches_the_rate():
    """Over real time, admissions must converge on limit/interval."""
    clock = FrozenClock()
    bucket = StateBucket([Rate(10, 1000)], clock=clock)

    admitted = 0
    for _ in range(5000):  # 5 simulated seconds, 1ms per tick
        if bucket.put(RateItem("a", clock.now())):
            admitted += 1
        clock.advance(1)

    # 10 burst up front, then 10/s for 5s.
    assert 55 <= admitted <= 61, admitted


def test_smooth_burst_of_one_never_bunches():
    clock = FrozenClock()
    bucket = StateBucket([Rate(10, 1000, burst=1)], clock=clock)

    assert bucket.put(RateItem("a", clock.now())) is True
    # burst=1 means no reserve at all: the very next unit waits a full interval.
    assert bucket.put(RateItem("a", clock.now())) is False
    clock.advance(100)
    assert bucket.put(RateItem("a", clock.now())) is True


# --------------------------------------------------------------- via Limiter

def test_limiter_non_blocking():
    limiter = Limiter(StateBucket([Rate(3, Duration.SECOND)]))

    assert [limiter.try_acquire("k", blocking=False) for _ in range(5)] == [True, True, True, False, False]


def test_limiter_blocks_for_the_computed_wait():
    limiter = Limiter(StateBucket([Rate(5, Duration.SECOND)]), buffer_ms=10)

    for _ in range(5):
        assert limiter.try_acquire("k", blocking=False) is True

    started = monotonic()
    assert limiter.try_acquire("k", blocking=True, timeout=2) is True
    waited = monotonic() - started
    # One emission interval is 200ms; allow generous slack for CI.
    assert 0.1 <= waited < 1.0, waited


@pytest.mark.asyncio
async def test_limiter_async():
    limiter = Limiter(StateBucket([Rate(3, Duration.SECOND)]), buffer_ms=10)

    for _ in range(3):
        assert await limiter.try_acquire_async("k", blocking=False) is True

    assert await limiter.try_acquire_async("k", blocking=False) is False
    assert await limiter.try_acquire_async("k", blocking=True, timeout=2) is True


# ---------------------------------------------------------- store equivalence

def _stores():
    # Markers, not just import guards: CI installs every driver everywhere but
    # only runs the servers on Linux, so non-Linux jobs deselect by marker.
    # multiprocess needs mpbucket too - the general session runs under xdist
    # with -m "not mpbucket", and Manager processes belong in the serial one.
    stores = [
        pytest.param(lambda: InMemoryStateStore(), id="inmemory", marks=pytest.mark.inmemory),
        pytest.param(lambda: MultiprocessStateStore.init(), id="multiprocess", marks=pytest.mark.mpbucket),
    ]

    if importlib.util.find_spec("redis") is not None:
        from redis import Redis

        from pyrate_limiter import RedisStateStore

        def make_redis():
            client = Redis.from_url("redis://localhost:6379")
            key = f"gcra-test/{id_generator()}"
            client.delete(key)
            return RedisStateStore(client, key)

        stores.append(pytest.param(make_redis, id="redis", marks=pytest.mark.redis))

    return stores


@pytest.mark.parametrize("make_store", _stores())
def test_stores_agree_on_the_same_sequence(make_store):
    """Every store must produce the reference in-memory verdicts exactly."""
    rates = [Rate(3, 1000), Rate(5, 5000)]
    clock, reference_clock = FrozenClock(), FrozenClock()

    bucket = StateBucket(rates, store=make_store(), clock=clock)
    reference = StateBucket(rates, store=InMemoryStateStore(), clock=reference_clock)

    for step in range(12):
        weight = 1 + step % 3

        for _ in range(2):
            item = RateItem("x", clock.now(), weight=weight)
            expected_item = RateItem("x", reference_clock.now(), weight=weight)

            assert bucket.put(item) == reference.put(expected_item), f"verdict diverged at step {step}"
            assert bucket.waiting(item) == reference.waiting(expected_item), f"wait diverged at step {step}"

        clock.advance(200)
        reference_clock.advance(200)

    assert bucket.count() == reference.count()
    bucket.close()


@pytest.mark.parametrize("make_store", _stores())
def test_stores_survive_a_flush(make_store):
    clock = FrozenClock()
    bucket = StateBucket([Rate(2, 1000)], store=make_store(), clock=clock)

    for _ in range(2):
        assert bucket.put(RateItem("a", clock.now())) is True

    assert bucket.put(RateItem("a", clock.now())) is False
    bucket.flush()
    assert bucket.put(RateItem("a", clock.now())) is True
    bucket.close()


# ------------------------------------------------------------------ redis lua

@pytest.mark.redis
def test_redis_keeps_state_constant_and_expiring():
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    client = Redis.from_url("redis://localhost:6379")
    key = f"gcra-size/{id_generator()}"
    client.delete(key)

    rates = [Rate(1000, 60_000)]
    bucket = StateBucket(rates, store=RedisStateStore(client, key), clock=FrozenClock())

    for _ in range(500):
        bucket.put(RateItem("x", 1_700_000_000_000))

    assert client.hlen(key) == 1  # one field, no matter the traffic
    assert 0 < client.pttl(key) <= 2 * 60_000  # idle keys expire on their own
    client.delete(key)


@pytest.mark.asyncio
@pytest.mark.asyncredis
async def test_async_redis_client():
    pytest.importorskip("redis")
    from redis.asyncio import Redis as AsyncRedis

    from pyrate_limiter import RedisStateStore

    client = AsyncRedis.from_url("redis://localhost:6379")
    key = f"gcra-async/{id_generator()}"
    await client.delete(key)

    clock = FrozenClock()
    bucket = StateBucket([Rate(3, 1000)], store=RedisStateStore(client, key), clock=clock)

    verdicts = [await bucket.put(RateItem("x", clock.now())) for _ in range(5)]
    assert verdicts == [True, True, True, False, False]

    wait = bucket.waiting(RateItem("x", clock.now()))
    assert (await wait if asyncio.iscoroutine(wait) else wait) == 334

    await client.delete(key)
    await client.aclose()


def test_algorithm_without_a_redis_script_is_rejected():
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    class ScriptlessPolicy(GCRA):
        def redis_script(self):
            return None

    store = RedisStateStore(Redis.from_url("redis://localhost:6379"), f"no-script/{id_generator()}")
    rates = [Rate(3, 1000)]

    with pytest.raises(TypeError, match="no Redis implementation"):
        store.check(ScriptlessPolicy(), rates, now=1000, weight=1)


def test_slow_clock_never_rewinds_the_bucket():
    """A timestamp behind the stored TAT must not hand back free capacity."""
    clock = FrozenClock()
    bucket = StateBucket([Rate(2, 1000)], clock=clock)

    for _ in range(2):
        assert bucket.put(RateItem("a", clock.now())) is True

    stale = RateItem("a", clock.now() - 5000)
    assert bucket.put(stale) is False


def test_bucket_is_picklable():
    import pickle

    bucket = StateBucket([Rate(3, 1000)], store=InMemoryStateStore())
    bucket.put(RateItem("a", bucket.now()))

    revived = pickle.loads(pickle.dumps(bucket))  # noqa: S301 - our own object, not untrusted input
    assert revived.rates[0].limit == 3
    assert revived.put(RateItem("a", revived.now())) is True


def test_leaker_accepts_a_state_bucket():
    """The Leaker must tolerate a bucket whose leak() is a no-op."""
    limiter = Limiter(StateBucket([Rate(3, Duration.SECOND)]))
    assert limiter.try_acquire("k") is True
    sleep(0.05)
    assert limiter.buckets()
    limiter.close()
