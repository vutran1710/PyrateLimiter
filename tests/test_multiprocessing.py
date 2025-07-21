"""Complete Limiter test suite
"""
import multiprocessing
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from functools import partial
from multiprocessing.synchronize import Lock as LockType
from typing import Dict
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


def init_process_mp(bucket, mp_lock: LockType):
    global LIMITER

    LIMITER = Limiter(bucket, raise_when_fail=False, clock=MonotonicClock(),
                      max_delay=MAX_DELAY)

    LIMITER.lock = mp_lock  # type: ignore[assignment]


def my_task():
    assert LIMITER is not None
    LIMITER.try_acquire("my_task")
    result = {"time": time.monotonic(), "pid": os.getpid()}
    return result


def analyze_times(start: float, requests_per_second: int, time: List[Dict]):
    import pandas as pd

    df = pd.DataFrame(time)

    df = df.sort_values(by="time")
    df["time"] = df["time"] - start
    df['ops_last_sec'] = df['time'].apply(lambda t: ((df['time'] > t - 1) & (df['time'] <= t)).sum())

    print(df)

    print(f'{df["ops_last_sec"].max()=},  {requests_per_second=}')


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
    mp_lock = multiprocessing.Lock()

    start = time.monotonic()

    with ProcessPoolExecutor(
        initializer=partial(init_process_mp, bucket, mp_lock)
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
