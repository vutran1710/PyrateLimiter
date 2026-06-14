"""Unit tests for the Algorithm seam (R2): SlidingWindowLog + Decision."""
from pyrate_limiter import InMemoryBucket, Rate
from pyrate_limiter.abstracts.algorithm import Algorithm, Decision, SlidingWindowLog

RATES = [Rate(3, 1000), Rate(5, 5000)]


def test_decision_allowed_flag():
    assert Decision().allowed is True
    assert Decision().failing_rate is None
    denied = Decision(failing_rate=RATES[0])
    assert denied.allowed is False
    assert denied.failing_rate is RATES[0]


def test_sliding_window_log_is_algorithm():
    assert isinstance(SlidingWindowLog(), Algorithm)


def test_admit_allows_when_all_rates_fit():
    algo = SlidingWindowLog()
    # counts well under both limits
    assert algo.admit(RATES, [0, 0], weight=1).allowed
    assert algo.admit(RATES, [2, 4], weight=1).allowed  # exactly fills, still fits


def test_admit_returns_first_violated_rate():
    algo = SlidingWindowLog()
    # first rate full (limit 3, count 3) -> can't fit 1 more
    d = algo.admit(RATES, [3, 0], weight=1)
    assert not d.allowed and d.failing_rate is RATES[0]
    # first rate fits, second full
    d = algo.admit(RATES, [0, 5], weight=1)
    assert not d.allowed and d.failing_rate is RATES[1]


def test_admit_respects_weight():
    algo = SlidingWindowLog()
    # limit 3, count 2 -> weight 1 fits, weight 2 does not
    assert algo.admit(RATES, [2, 0], weight=1).allowed
    assert not algo.admit(RATES, [2, 0], weight=2).allowed


def test_leak_bound_is_widest_window():
    algo = SlidingWindowLog()
    # rates sorted ascending by interval -> widest is 5000
    assert algo.leak_bound(RATES, now=10_000) == 10_000 - 5000


def test_buckets_default_to_sliding_window_log():
    assert isinstance(InMemoryBucket(RATES)._algorithm, SlidingWindowLog)
