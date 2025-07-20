import logging

import time
from multiprocessing.dummy import Pool

from pyrate_limiter import InMemoryBucket, SQLiteBucket, SQLiteClock
from pyrate_limiter import Limiter, Duration, Rate

logging.basicConfig(
    format='%(asctime)s %(name)s %(levelname)-8s %(message)s',
    level=logging.DEBUG,
    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(__name__)


def create_sqlite_limiter(rate: Rate, use_fileLock: bool, max_delay: int):
    bucket = SQLiteBucket.init_from_file([rate], db_path="sqlite_ratelimit.sqlite", use_file_lock=True,)

    return Limiter(bucket, raise_when_fail=False, max_delay=max_delay, clock=SQLiteClock(bucket.conn))

limit_s = 3
max_delay_ms=5 * Duration.SECOND
rate = Rate(limit_s, Duration.SECOND)

rate_limiter = create_sqlite_limiter(rate=rate, use_fileLock=False, max_delay=max_delay_ms)


start = time.time()

def mapping(*args, **kwargs):
    return "check", 1

def check_rate_limiter(i):
    rate_limiter.try_acquire(i, 1)

    print(f"Calling {i} t{round(time.time() - start)}")
    time.sleep(7)
    print(f"Done {i} at t{round(time.time() - start)}")


if __name__ == "__main__":
    x = list(range(10))

    with Pool(processes=10) as p:
        p.map(check_rate_limiter, x) 