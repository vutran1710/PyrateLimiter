"""Rate limiter multiprocessing tests
"""
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from functools import partial
from pathlib import Path
from tempfile import gettempdir
from typing import List
from typing import Optional

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock
from pyrate_limiter import TimeClock
from pyrate_limiter.buckets.mp_bucket import MultiprocessBucket

MAX_DELAY = Duration.DAY

LIMITER: Optional[Limiter] = None


def init_process_mp(bucket: MultiprocessBucket):
    global LIMITER

    LIMITER = Limiter(bucket, raise_when_fail=False, clock=TimeClock(),
                      max_delay=MAX_DELAY, retry_until_max_delay=True)

    LIMITER.lock = bucket.get_combined_lock(LIMITER.lock)  # type: ignore[assignment]


def my_task():
    assert LIMITER is not None

    while not LIMITER.try_acquire("my_task"):
        time.sleep(0.01)

    result = time.time()
    time.sleep(0.01)
    return result


def analyze_times(start: float, requests_per_second: int, times: List[float]):
    elapsed = sorted(t - start for t in times)
    w: deque[float] = deque()
    ops_last_sec: List[int] = []
    for t in elapsed:
        w.append(t)
        while w and w[0] <= t - 1:
            w.popleft()
        ops_last_sec.append(len(w))
    print(f'{max(ops_last_sec)=},  {requests_per_second=}')
    assert max(ops_last_sec) <= requests_per_second * 1.01  # a small amount of error is observed when multiprocessing


def init_process_sqlite(requests_per_second, db_path):
    global LIMITER
    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = SQLiteBucket.init_from_file([rate], db_path=db_path, use_file_lock=True)
    LIMITER = Limiter(bucket,
                      raise_when_fail=False,
                      max_delay=MAX_DELAY,
                      retry_until_max_delay=True,
                      clock=SQLiteClock(bucket))
    LIMITER.lock = bucket.lock


def test_mp_bucket():

    requests_per_second = 250
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    start = time.time()

    with ProcessPoolExecutor(
        initializer=partial(init_process_mp, bucket),
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

    requests_per_second = 250
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    # Initialize the table
    temp_dir = Path(gettempdir())
    db_path = str(temp_dir / f"pyrate_limiter_{time.time()}.sqlite")

    # Start the ProcessPoolExecutor
    start = time.time()

    with ProcessPoolExecutor(
        initializer=partial(init_process_sqlite, requests_per_second=requests_per_second, db_path=db_path)
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
