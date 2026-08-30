"""GCRA / TokenBucket: constant-state rate limiting."""

import asyncio
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep

import pytest

from pyrate_limiter import (
    GCRA,
    Duration,
    InMemoryBucket,
    InMemoryStateStore,
    Limiter,
    MultiprocessStateStore,
    Rate,
    RateItem,
    StateBucket,
    TokenBucket,
    id_generator,
    limiter_factory,
)
from pyrate_limiter.abstracts.algorithm import ADMITTED, Decision, LogAlgorithm, StateAlgorithm
from pyrate_limiter.abstracts.store import StateStore
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

    # State is microseconds: 1000ms / 4 = 250ms = 250_000us per unit.
    state, decision = algo.step(rates, state, now=1000, weight=1)
    assert decision is ADMITTED
    assert state == (1_250_000,)

    state, decision = algo.step(rates, state, now=1000, weight=2)
    assert decision.allowed
    assert state == (1_750_000,)


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


@pytest.mark.parametrize("now", [0, 12_345, 1_000_000, 1_000_000_000, 1_700_000_000_000, 1_787_486_223_173])
@pytest.mark.parametrize("limit", [1, 2, 3, 7, 97, 1000, 3000])
def test_a_full_burst_always_admits_exactly_burst(now, limit):
    """Regression: the TAT must not drift with the timestamp's magnitude.

    Accumulating a fractional emission interval onto an absolute TAT (~1.7e12
    for epoch ms) loses the low bits, so the accumulated sum of `burst`
    emissions stops equalling `burst * emission` and the last unit gets
    rejected by a rounding error. Integer microseconds make it exact - but only
    a sweep like this catches it, since any single pair of values may round
    favourably.
    """
    algo, rates = GCRA(), [Rate(limit, 1000)]
    state = algo.initial(rates)

    admitted = 0
    for _ in range(limit + 2):
        state, decision = algo.step(rates, state, now=now, weight=1)
        if decision.allowed:
            admitted += 1

    assert admitted == limit


def test_state_is_integer_microseconds():
    # Not fractional milliseconds: see the regression test above.
    algo, rates = GCRA(), [Rate(3, 1000)]
    state, _ = algo.step(rates, algo.initial(rates), now=1_700_000_000_000, weight=1)
    assert all(isinstance(value, int) for value in state)
    assert state == (1_700_000_000_000 * 1000 + 333334,)  # emission rounded up


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
    # 1001, not 1000: 1000ms/3 does not divide evenly and the emission interval
    # rounds up, so the bucket errs strict rather than admitting marginally fast.
    assert bucket.waiting(RateItem("a", clock.now(), weight=3)) == 1001
    assert bucket.waiting(light) == 334


def test_a_lighter_request_need_not_wait_at_all():
    """A standing denial for a heavy item must not make a light one wait."""
    clock = FrozenClock()
    bucket = StateBucket([Rate(4, 1000)], clock=clock)

    assert bucket.put(RateItem("a", clock.now(), weight=3)) is True

    heavy = RateItem("a", clock.now(), weight=3)
    assert bucket.put(heavy) is False
    assert bucket.waiting(heavy) > 0

    # One unit still fits right now, so the re-derivation reports no wait.
    assert bucket.waiting(RateItem("a", clock.now(), weight=1)) == 0
    assert bucket.put(RateItem("a", clock.now(), weight=1)) is True


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


@pytest.mark.asyncio
@pytest.mark.asyncredis
async def test_async_redis_count_and_re_derived_wait():
    """The async read paths: count(), and waiting() for a mismatched weight."""
    pytest.importorskip("redis")
    from redis.asyncio import Redis as AsyncRedis

    from pyrate_limiter import RedisStateStore

    client = AsyncRedis.from_url("redis://localhost:6379")
    key = f"gcra-async-read/{id_generator()}"
    await client.delete(key)

    clock = FrozenClock()
    bucket = StateBucket([Rate(4, 1000)], store=RedisStateStore(client, key), clock=clock)

    for _ in range(4):
        assert await bucket.put(RateItem("x", clock.now())) is True

    assert await bucket.count() == 4

    light = RateItem("x", clock.now())
    assert await bucket.put(light) is False
    assert bucket.waiting(light) == 250  # recorded, no await needed

    # A different weight has to go back to the store, which returns a coroutine.
    assert await bucket.waiting(RateItem("x", clock.now(), weight=2)) == 500

    clock.advance(500)
    assert await bucket.count() == 2

    await bucket.flush()
    assert await bucket.count() == 0

    await client.delete(key)
    await client.aclose()


@pytest.mark.redis
def test_explicit_ttl_overrides_the_derived_one():
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    client = Redis.from_url("redis://localhost:6379")
    key = f"gcra-ttl/{id_generator()}"
    client.delete(key)

    bucket = StateBucket([Rate(3, 1000)], store=RedisStateStore(client, key, ttl_ms=60_000), clock=FrozenClock())
    assert bucket.put(RateItem("x", 1_700_000_000_000)) is True

    ttl = client.pttl(key)
    assert 55_000 < ttl <= 60_000, ttl  # not the ~2s the rate would imply
    client.delete(key)


# ------------------------------------------------------- the extension point

class HalfRate(StateAlgorithm):
    """A minimal third-party policy, to prove the seam is usable.

    Deliberately implements only the two abstract methods, so the base
    defaults for decode/consumed/redis_script are the ones under test.
    """

    def initial(self, rates):
        return tuple(0.0 for _ in rates)

    def step(self, rates, state, now, weight):
        used = state[0] + weight
        if used > rates[0].limit / 2:
            return state, Decision(failing_rate=rates[0], retry_after_ms=42)
        return (used,), ADMITTED


def test_a_custom_state_algorithm_works_end_to_end():
    rates = [Rate(10, 1000)]
    bucket = StateBucket(rates, algorithm=HalfRate(), clock=FrozenClock())

    admitted = sum(1 for _ in range(10) if bucket.put(RateItem("a", 1_700_000_000_000)))
    assert admitted == 5  # half of 10

    item = RateItem("a", 1_700_000_000_000)
    assert bucket.put(item) is False
    assert bucket.waiting(item) == 42


def test_state_algorithm_defaults():
    algo, rates = HalfRate(), [Rate(10, 1000)]

    # consumed() has no meaningful answer for a policy that does not define one.
    assert algo.consumed(rates, algo.initial(rates), now=0) == 0
    # No Lua means the store must refuse rather than guess.
    assert algo.redis_script() is None
    # The default decode parses floats, which suits a policy that stores them.
    assert algo.decode(["1.5", "2"]) == (1.5, 2.0)


def test_bucket_count_falls_back_to_zero_without_a_consumed_impl():
    bucket = StateBucket([Rate(10, 1000)], algorithm=HalfRate(), clock=FrozenClock())
    bucket.put(RateItem("a", 1_700_000_000_000))
    assert bucket.count() == 0


class NoWaitPolicy(HalfRate):
    """Denies without ever reporting a wait."""

    def step(self, rates, state, now, weight):
        return state, Decision(failing_rate=rates[0])


def test_replay_reports_zero_when_the_policy_gives_no_wait():
    rates = [Rate(10, 1000)]
    bucket = StateBucket(rates, algorithm=NoWaitPolicy(), clock=FrozenClock())

    denied = RateItem("a", 1_700_000_000_000, weight=1)
    assert bucket.put(denied) is False

    # A different weight forces the re-derivation path, which has no wait to
    # return either - 0 means "retry now", not "never".
    assert bucket.waiting(RateItem("a", 1_700_000_000_000, weight=2)) == 0


# --------------------------------------------------------------- odds and ends

def test_wall_clock_is_epoch_milliseconds():
    from time import time

    now = WallClock().now()
    assert isinstance(now, int)
    assert abs(now - int(time() * 1000)) < 5_000


def test_factory_builds_a_token_bucket_limiter():
    limiter = limiter_factory.create_token_bucket_limiter(rate_per_duration=3, duration=Duration.SECOND, burst=5)

    assert [limiter.try_acquire("k", blocking=False) for _ in range(7)] == [True] * 5 + [False, False]
    limiter.close()


def test_factory_burst_defaults_to_the_rate():
    limiter = limiter_factory.create_token_bucket_limiter(rate_per_duration=2, duration=Duration.SECOND)

    assert [limiter.try_acquire("k", blocking=False) for _ in range(4)] == [True, True, False, False]
    limiter.close()


@pytest.mark.mpbucket
def test_multiprocess_bucket_carries_its_algorithm():
    from pyrate_limiter import FixedWindow, MultiprocessBucket

    bucket = MultiprocessBucket.init([Rate(3, 1000)], algorithm=FixedWindow())
    assert isinstance(bucket._algorithm, FixedWindow)

    for ts in (1000, 1400, 1900):
        assert bucket.put(RateItem("a", ts)) is True

    assert bucket.put(RateItem("a", 1950)) is False
    assert bucket.put(RateItem("a", 2000)) is True  # window reset, not expiry


def test_async_wrapper_delegates_the_algorithm():
    from pyrate_limiter import BucketAsyncWrapper, FixedWindow

    bucket = InMemoryBucket([Rate(3, 1000)], algorithm=FixedWindow())
    wrapped = BucketAsyncWrapper(bucket)

    # The inherited waiting() reads _algorithm off self; it must see the
    # wrapped bucket's, not the class default.
    assert wrapped._algorithm is bucket._algorithm
    assert isinstance(wrapped._algorithm, FixedWindow)


class ScriptedNoArgs(HalfRate):
    """Has a Lua script but supplies no per-rate arguments.

    The point of the test: this must not blow up on a helper the interface
    never promised. Its script ignores the tail entirely.
    """

    def redis_script(self):
        return """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        redis.call('SET', key, now)
        return {-1, 0}
        """


@pytest.mark.redis
def test_store_only_uses_the_declared_redis_interface():
    """A third-party policy needs redis_script() and nothing private."""
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    client = Redis.from_url("redis://localhost:6379")
    key = f"gcra-iface/{id_generator()}"
    client.delete(key)

    rates = [Rate(3, 1000)]
    store = RedisStateStore(client, key)

    # No AttributeError for a policy that never defines GCRA's private helpers.
    assert store.check(ScriptedNoArgs(), rates, now=1_700_000_000_000, weight=1).allowed
    client.delete(key)


def test_redis_args_default_is_empty():
    assert HalfRate().redis_args([Rate(3, 1000)]) == []


def test_gcra_redis_args_pair_emission_with_burst():
    rates = [Rate(4, 1000), Rate(5, 5000, burst=9)]
    # 1000ms/4 = 250_000us, 5000ms/5 = 1_000_000us
    assert GCRA().redis_args(rates) == [250_000, 4, 1_000_000, 9]


@pytest.mark.redis
def test_reset_returns_none_not_the_delete_count():
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    client = Redis.from_url("redis://localhost:6379")
    key = f"gcra-reset/{id_generator()}"
    client.delete(key)

    store = RedisStateStore(client, key)
    bucket = StateBucket([Rate(2, 1000)], store=store, clock=FrozenClock())
    assert bucket.put(RateItem("a", 1_700_000_000_000)) is True

    # StateStore.reset() and AbstractBucket.flush() are both contracted to None.
    assert store.reset() is None
    assert bucket.flush() is None
    client.delete(key)


@pytest.mark.asyncio
@pytest.mark.asyncredis
async def test_async_reset_resolves_to_none():
    pytest.importorskip("redis")
    from redis.asyncio import Redis as AsyncRedis

    from pyrate_limiter import RedisStateStore

    client = AsyncRedis.from_url("redis://localhost:6379")
    key = f"gcra-areset/{id_generator()}"
    await client.delete(key)

    clock = FrozenClock()
    bucket = StateBucket([Rate(2, 1000)], store=RedisStateStore(client, key), clock=clock)
    assert await bucket.put(RateItem("a", clock.now())) is True

    assert await bucket.flush() is None
    assert await bucket.put(RateItem("a", clock.now())) is True  # state really gone

    await client.delete(key)
    await client.aclose()


# ---------------------------------------------------------------- contention

class _RacyStore(StateStore):
    """A deliberately non-atomic store, used only to prove the assertions below
    can actually fail. Without it, a passing contention test proves nothing."""

    is_async = False

    def __init__(self):
        self._state = None

    def check(self, algorithm, rates, now, weight):
        state = self._state if self._state is not None else algorithm.initial(rates)
        sleep(0.0005)  # the read-modify-write gap a real store must not have
        new_state, decision = algorithm.step(rates, state, now, weight)
        self._state = new_state
        return decision

    def read(self, algorithm, rates):
        return self._state if self._state is not None else algorithm.initial(rates)

    def reset(self):
        self._state = None


def _hammer(bucket, threads: int = 120, at: int = 1_700_000_000_000) -> int:
    """Admissions when `threads` callers race at one frozen instant."""
    with ThreadPoolExecutor(max_workers=24) as pool:
        return sum(1 for ok in pool.map(lambda _: bucket.put(RateItem("k", at)), range(threads)) if ok)


def test_the_contention_assertion_can_fail():
    """Guard for the two tests below: a racy store must breach the limit."""
    admitted = _hammer(StateBucket([Rate(20, 1000)], store=_RacyStore(), clock=FrozenClock()))
    assert admitted > 20, "the contention tests below would pass vacuously"


def test_in_memory_store_holds_the_limit_under_threads():
    # The clock is frozen, so no drain can occur: at most `burst` may ever pass.
    bucket = StateBucket([Rate(20, 1000)], store=InMemoryStateStore(), clock=FrozenClock())
    assert _hammer(bucket) == 20


@pytest.mark.redis
def test_redis_store_holds_the_limit_across_separate_clients():
    """The reason the transition is a Lua script rather than a Python step()."""
    pytest.importorskip("redis")
    from redis import Redis

    from pyrate_limiter import RedisStateStore

    key = f"gcra-race/{id_generator()}"
    Redis.from_url("redis://localhost:6379").delete(key)

    # Separate clients, i.e. separate connections - the distributed shape, not
    # one client whose GIL would hide a non-atomic read-modify-write.
    buckets = [
        StateBucket(
            [Rate(20, 1000)],
            store=RedisStateStore(Redis.from_url("redis://localhost:6379"), key),
            clock=FrozenClock(),
        )
        for _ in range(8)
    ]

    at = 1_700_000_000_000
    with ThreadPoolExecutor(max_workers=24) as pool:
        admitted = sum(1 for ok in pool.map(lambda i: buckets[i % len(buckets)].put(RateItem("k", at)), range(120)) if ok)

    assert admitted == 20
    Redis.from_url("redis://localhost:6379").delete(key)
