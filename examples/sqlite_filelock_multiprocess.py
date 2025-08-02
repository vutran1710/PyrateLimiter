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
from typing import Optional

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import limiter_factory

LIMITER: Optional[Limiter] = None
REQUESTS_PER_SECOND = 10
NUM_REQUESTS = REQUESTS_PER_SECOND * 5  # Run for ~5 seconds

logger = logging.getLogger(__name__)


def init_process():
    global LIMITER

    LIMITER = limiter_factory.create_sqlite_limiter(rate_per_duration=REQUESTS_PER_SECOND,
                                                    duration=Duration.SECOND,
                                                    db_path="pyrate_limiter.sqlite",
                                                    use_file_lock=True)


def my_task():
    assert LIMITER is not None
    LIMITER.try_acquire("my_task")
    result = {"time": time.monotonic(), "pid": os.getpid()}
    return result


def test_sqlite_filelock_multiprocess():
    # prime the rates, to show realistic rates
    init_process()
    assert LIMITER is not None
    [LIMITER.try_acquire("test") for _ in range(REQUESTS_PER_SECOND)]

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

    end = time.monotonic()

    print(f"Completed {NUM_REQUESTS=} in {end - start} seconds, at a rate of {REQUESTS_PER_SECOND=}")


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s %(name)s %(levelname)-8s %(message)s",
        level=logging.INFO,
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    test_sqlite_filelock_multiprocess()
