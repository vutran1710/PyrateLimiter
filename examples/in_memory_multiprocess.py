"""
Demonstrates using a MultiprocessBucket using a ProcessPoolExecutor, running a simple task.

A MultiprocessBucket is useful when the rate is to be shared among a multiprocessing pool or ProcessPoolExecutor.

The mp_bucket stores its items in a multiprocessing ListProxy, and a multiprocessing lock is shared
across Limiter instances.

"""
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from functools import partial
from multiprocessing import Lock

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import MonotonicClock
from pyrate_limiter import MultiprocessBucket
from pyrate_limiter import Rate

LIMITER: Limiter | None = None
MAX_DELAY = Duration.DAY
REQUESTS_PER_SECOND = 100
NUM_REQUESTS = REQUESTS_PER_SECOND * 5  # Run for ~5 seconds

logger = logging.getLogger(__name__)


def init_process(bucket: MultiprocessBucket):
    global LIMITER

    LIMITER = Limiter(bucket, raise_when_fail=False, clock=MonotonicClock(),
                      max_delay=MAX_DELAY)  # retry_until_max_delay=True,

    LIMITER.lock = bucket.mp_lock  # type: ignore[assignment]


def my_task():
    assert LIMITER is not None
    LIMITER.try_acquire("my_task")
    result = {"time": time.monotonic(), "pid": os.getpid()}
    return result


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    rate = Rate(REQUESTS_PER_SECOND, Duration.SECOND)

    bucket = MultiprocessBucket.init([rate])
    mp_lock = Lock()

    start = time.monotonic()

    with ProcessPoolExecutor(
        initializer=partial(init_process, bucket)
    ) as executor:
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
