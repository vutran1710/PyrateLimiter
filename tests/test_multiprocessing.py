"""Complete Limiter test suite
"""
import multiprocessing
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from functools import partial
from typing import List
from typing import Optional

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import MonotonicClock
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock
from pyrate_limiter.buckets.mp_bucket import MultiprocessBucket

MAX_DELAY = Duration.DAY

LIMITER: Optional[Limiter] = None


def init_process_mp(bucket: MultiprocessBucket):
    global LIMITER

    LIMITER = Limiter(bucket, raise_when_fail=False, clock=MonotonicClock(),
                      max_delay=MAX_DELAY)

    LIMITER.lock = bucket.mp_lock  # type: ignore[assignment]


def my_task():
    assert LIMITER is not None

    while not LIMITER.try_acquire("my_task"):
        # Keep trying
        pass

    result = time.monotonic()
    return result


def analyze_times(start: float, requests_per_second: int, times: List[float]):
    elapsed = sorted(t - start for t in times)
    w, ops_last_sec = deque(), []  # type: ignore[var-annotated]
    for t in elapsed:
        w.append(t)
        while w and w[0] < t - 1:
            w.popleft()
        ops_last_sec.append(len(w))
    print(f'{max(ops_last_sec)=},  {requests_per_second=}')
    assert max(ops_last_sec) == requests_per_second


def init_process_sqlite(rate):
    global LIMITER

    bucket = SQLiteBucket.init_from_file([rate], db_path="pyrate_limiter.sqlite", use_file_lock=True)

    LIMITER = Limiter(bucket, raise_when_fail=False, max_delay=MAX_DELAY, clock=SQLiteClock(bucket.conn))


def test_mp_bucket():

    requests_per_second = 100
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    start = time.monotonic()
    # future proofing for 3.14
    is_fork_default = multiprocessing.get_start_method(allow_none=True) == 'fork'

    with ProcessPoolExecutor(
        initializer=partial(init_process_mp, bucket),
        mp_context=multiprocessing.get_context("forkserver") if is_fork_default else None
    ) as executor:
        futures = [executor.submit(my_task) for _ in range(num_requests)]
        wait(futures)

    times = []
    for f in futures:
        try:
            t = f.result()
            times.append(t)
        except Exception as e:
            raise e

    analyze_times(start, requests_per_second, times)


def test_sqlite_filelock_bucket():

    requests_per_second = 10
    num_seconds = 5
    num_requests = requests_per_second * num_seconds
    rate = Rate(requests_per_second, Duration.SECOND)

    start = time.monotonic()

    with ProcessPoolExecutor(
        initializer=partial(init_process_sqlite, rate)
    ) as executor:
        futures = [executor.submit(my_task) for _ in range(num_requests)]
        wait(futures)

    times = []
    for f in futures:
        try:
            t = f.result()
            times.append(t)
        except Exception as e:
            raise e

    analyze_times(start, requests_per_second, times)
