"""
Demonstrates using a SQLite Bucket across multiple processes, using a filelock to enforce synchronization.

This is useful in cases where multiple processes are created, possibly at different times or from different
applications.

The SQLite Bucket uses a .lock file to ensure that only one process is active at a time.

"""
import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import wait
from functools import partial

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket
from pyrate_limiter import SQLiteClock

LIMITER: Limiter | None = None
MAX_DELAY = Duration.DAY
REQUESTS_PER_SECOND = 100
NUM_REQUESTS = REQUESTS_PER_SECOND * 5  # Run for ~5 seconds

logger = logging.getLogger(__name__)


def init_process():
    global LIMITER

    rate = Rate(REQUESTS_PER_SECOND, Duration.SECOND)
    bucket = SQLiteBucket.init_from_file([rate], db_path="pyrate_limiter.sqlite", use_file_lock=True)
    LIMITER = Limiter(bucket, raise_when_fail=False, clock=SQLiteClock(bucket.conn),
                      max_delay=MAX_DELAY)  # retry_until_max_delay=True,


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

    start = time.monotonic()

    with ProcessPoolExecutor(
        initializer=partial(init_process)
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

    print(times)
