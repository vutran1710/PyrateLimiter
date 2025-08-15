# ruff: noqa: T201
"""
Demonstrates using a MultiprocessBucket using a ProcessPoolExecutor, running a simple task.

A MultiprocessBucket is useful when the rate is to be shared among a multiprocessing pool or ProcessPoolExecutor.

The mp_bucket stores its items in a multiprocessing ListProxy, and a multiprocessing lock is shared
across Limiter instances.

"""

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor, wait
from functools import partial
from typing import Optional

from pyrate_limiter import Duration, Limiter, MonotonicClock, MultiprocessBucket, Rate

LIMITER: Optional[Limiter] = None
MAX_DELAY = Duration.DAY
REQUESTS_PER_SECOND = 100
NUM_REQUESTS = REQUESTS_PER_SECOND * 5  # Run for ~5 seconds

logger = logging.getLogger(__name__)


def init_process(bucket: MultiprocessBucket):
    global LIMITER

    LIMITER = Limiter(bucket, raise_when_fail=False, clock=MonotonicClock(), max_delay=MAX_DELAY, retry_until_max_delay=True)


def my_task():
    assert LIMITER is not None
    LIMITER.try_acquire("my_task")
    result = {"time": time.monotonic(), "pid": os.getpid()}
    return result


def test_in_memory_multiprocess():
    rate = Rate(REQUESTS_PER_SECOND, Duration.SECOND)

    bucket = MultiprocessBucket.init([rate])

    # create a limiter and feed it 100 requests to prime it
    # Otherwise, the test appears to run too fast
    init_process(bucket)
    assert LIMITER is not None
    [LIMITER.try_acquire("test") for _ in range(REQUESTS_PER_SECOND)]

    start = time.monotonic()

    with ProcessPoolExecutor(initializer=partial(init_process, bucket)) as executor:
        futures = [executor.submit(my_task) for _ in range(NUM_REQUESTS)]
        wait(futures)

    times = []
    for f in futures:
        try:
            t = f.result()
            times.append(t)
        except Exception as e:
            print(f"Task raised: {e}")

    end = time.monotonic()

    print(f"Completed {NUM_REQUESTS=} in {end - start} seconds, at a rate of {REQUESTS_PER_SECOND=}")


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    test_in_memory_multiprocess()
