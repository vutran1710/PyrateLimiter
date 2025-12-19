"""Rate limiter multiprocessing tests"""
import asyncio
import time
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from pathlib import Path
from tempfile import gettempdir
from typing import List
from typing import Optional

import pytest

from pyrate_limiter import AbstractBucket
from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock
from pyrate_limiter.buckets.mp_bucket import MultiprocessBucket
from pyrate_limiter import limiter_factory

import logging

logger = logging.getLogger(__name__)

BUCKET: Optional[AbstractBucket] = None


def my_task():
    assert limiter_factory.LIMITER is not None

    acquired = limiter_factory.LIMITER.try_acquire("my_task")

    result = time.time()
    time.sleep(0.01)

    assert acquired
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
    print(f"{max(ops_last_sec)=},  {requests_per_second=}")
    assert (
        max(ops_last_sec) <= requests_per_second * 1.05
    )  # a small amount of error is observed when multiprocessing


def init_process_sqlite(requests_per_second, db_path):
    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = SQLiteBucket.init_from_file([rate], db_path=db_path, use_file_lock=True)
    bucket._clock = SQLiteClock(bucket)
    limiter_factory.LIMITER = Limiter(
        bucket
    )


def my_task_async(num_requests):
    async def task_async(limiter: Limiter, name="mytask", weight=1):
        await limiter.try_acquire_async(name, weight)
        return time.monotonic()

    async def run_many_async_tasks():

        return await asyncio.gather(
            *(task_async(limiter_factory.LIMITER, str(i), 1) for i in range(num_requests))
        )

    return asyncio.run(run_many_async_tasks())


def test_mp_bucket():
    requests_per_second = 250
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    def prime_bucket():
        # Prime the bucket
        limiter = Limiter(bucket)
        [limiter.try_acquire("mytest") for i in range(requests_per_second)]

    start = time.time()

    with ProcessPoolExecutor(
        initializer=limiter_factory.init_global_limiter,
        initargs=(bucket,)
    ) as executor:
        prime_bucket()
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

    # prime the bucket
    def prime_bucket():
        rate = Rate(requests_per_second, Duration.SECOND)

        with SQLiteBucket.init_from_file(
            [rate], db_path=db_path, use_file_lock=True
        ) as bucket:
            bucket._clock = SQLiteClock(bucket)
            limiter = Limiter(
                bucket,
                
            )
            [limiter.try_acquire("mytest") for i in range(requests_per_second)]

    # Start the ProcessPoolExecutor
    start = time.time()

    with ProcessPoolExecutor(initializer=init_process_sqlite, initargs=(requests_per_second, db_path)) as executor:
        prime_bucket()
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


@pytest.mark.asyncio
async def test_mp_bucket_async():
    requests_per_second = 250
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])
    async def prime_bucket():
        # prime the bucket
        limiter = Limiter(
            bucket,
        )
        for i in range(100):
            await limiter.try_acquire_async("mytest")

    start = time.time()

    with ProcessPoolExecutor(
        initializer=limiter_factory.init_global_limiter,
        initargs=(bucket,)
    ) as executor:
        # make sure requests is divisible by num workers
        num_workers = executor._max_workers
        num_requests = num_workers * (num_requests // num_workers)
        wait([executor.submit(my_task_async, 250)])

        futures = [
            executor.submit(my_task_async, num_requests // num_workers)
            for _ in range(num_workers)
        ]
        wait(futures)

        await asyncio.sleep(2)

        futures = [
            executor.submit(my_task_async, num_requests // num_workers)
            for _ in range(num_workers)
        ]
        wait(futures)

    times = []
    for f in futures:
        try:
            t = f.result()
            times += t
        except Exception as e:
            raise e

    analyze_times(start, requests_per_second, times)


def test_mp_bucket_failures():
    requests_per_second = 1
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    with ProcessPoolExecutor(
        initializer=limiter_factory.init_global_limiter,
        initargs=(bucket,)
    ) as executor:
        futures = [executor.submit(my_task) for _ in range(num_requests)]
        wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            raise e


def test_limiter_delay():
    requests_per_second = 1
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    limiter = Limiter(
        bucket
    )

    for _ in range(1000):
        last_success = limiter.try_acquire("mytest", 1, blocking=False)

    assert not last_success 
    with ProcessPoolExecutor( 
        initializer=limiter_factory.init_global_limiter,
        initargs=(bucket,),
    ) as executor:
        futures = [executor.submit(my_task) for _ in range(num_requests)]
        wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            raise e


def test_bucket_full():
    requests_per_second = 1
    num_seconds = 5
    num_requests = requests_per_second * num_seconds

    rate = Rate(requests_per_second, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])
    limiter = Limiter(
        bucket
)

    for _ in range(1000):
        last_success = limiter.try_acquire("mytest", 1, blocking=False)

    assert not last_success

    with ProcessPoolExecutor(
        initializer=limiter_factory.init_global_limiter, initargs=(bucket,)
    ) as executor:
        futures = [executor.submit(my_task) for _ in range(num_requests)]
        wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            raise e
