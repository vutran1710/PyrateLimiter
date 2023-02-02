"""Multithreaded and multiprocess stress tests"""
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from logging import getLogger
from multiprocessing import Process
from os.path import join
from tempfile import gettempdir
from time import perf_counter
from time import sleep

import pytest

from pyrate_limiter import Duration
from pyrate_limiter import FileLockSQLiteBucket
from pyrate_limiter import Limiter
from pyrate_limiter import RequestRate
from pyrate_limiter import SQLiteBucket

N_BUCKETS = 5  # Number of buckets to use
N_REQUESTS = 101  # Total number of requests to make
N_WORKERS = 7  # Number of parallel workers to use
LIMIT_REQUESTS_PER_SECOND = 10  # Rate limit
ATTEMPT_REQUESTS_PER_SECOND = 7  # Attempted request rate per thread/process
TEST_DURATION = 30  # Time in seconds for filelock test to run

logger = getLogger("pyrate_limiter.tests")


# TODO: This test could potentially be run for all bucket classes
# @pytest.mark.parametrize("bucket_class", [SQLiteBucket, MemoryListBucket, MemoryQueueBucket, RedisBucket])
@pytest.mark.parametrize("bucket_class", [SQLiteBucket])
def test_concurrency(bucket_class):
    """Make a fixed number of concurrent requests using a shared Limiter, and check the total time
    they take to run
    """
    logger.info(f"Testing {bucket_class.__name__}")

    # Set up limiter
    bucket_kwargs = {
        "path": join(gettempdir(), "test_concurrency.sqlite"),
    }
    limiter = Limiter(
        RequestRate(LIMIT_REQUESTS_PER_SECOND, Duration.SECOND),
        bucket_class=bucket_class,
        bucket_kwargs=bucket_kwargs,
    )

    # Set up request function
    bucket_ids = [f"bucket_{i}" for i in range(N_BUCKETS)]
    start_time = perf_counter()
    request_func = partial(_send_request, limiter, bucket_ids, start_time)

    # Distribute requests across workers
    with ThreadPoolExecutor(max_workers=N_WORKERS) as executor:
        list(executor.map(request_func, range(N_REQUESTS), timeout=300))

    # Check total time, with debug logging
    elapsed = perf_counter() - start_time
    expected_min_time = (N_REQUESTS - 1) / LIMIT_REQUESTS_PER_SECOND
    logger.info(
        f"Ran {N_REQUESTS} requests with {N_WORKERS} threads in {elapsed:.2f} seconds\n"
        f"With a rate limit of {LIMIT_REQUESTS_PER_SECOND}/second, expected at least "
        f"{expected_min_time} seconds"
    )
    assert elapsed >= expected_min_time


def _send_request(limiter, bucket_ids, start_time, n_request):
    """Rate-limited test function to send a single request, using a shared Limiter.
    Defined in module scope so it can be serialized to multiple processes.
    """
    with limiter.ratelimit(*bucket_ids, delay=True):
        logger.debug(f"t + {(perf_counter() - start_time):.5f}: Request {n_request+1}")
        sleep(1 / ATTEMPT_REQUESTS_PER_SECOND)


def test_filelock_concurrency():
    """Continuously send requests using multiple processes, with a separate Limiter per process, but
    a shared SQLite database. Runs for a fixed length of time, and checks the total number of
    requests made.
    """
    start_time = perf_counter()
    end_time = start_time + TEST_DURATION
    db_path = join(gettempdir(), "test_FileLockSQLiteBucket.sqlite")
    procs = []
    request_counters = [1] * N_WORKERS  # Mutable counters to check results after processes complete

    for i in range(N_WORKERS):
        proc = Process(
            target=_send_requests,
            args=(start_time, end_time, db_path, i, request_counters[i]),
        )
        proc.start()
        procs.append(proc)

    for proc in procs:
        proc.join()

    expected_max_requests = LIMIT_REQUESTS_PER_SECOND * TEST_DURATION
    assert sum(request_counters) <= expected_max_requests


def _send_requests(start_time: float, end_time: float, db_path: str, n_process: int, n_requests: int):
    """Send several rate-limited requests, with a separate Limiter per process."""
    limiter = Limiter(
        RequestRate(LIMIT_REQUESTS_PER_SECOND, Duration.SECOND),
        bucket_class=FileLockSQLiteBucket,
        bucket_kwargs={"path": db_path},
    )
    bucket_ids = [f"bucket_{i}" for i in range(N_BUCKETS)]

    while perf_counter() < end_time:
        with limiter.ratelimit(*bucket_ids, delay=True):
            logger.debug(f"[Process {n_process}] t + {(perf_counter() - start_time):.5f}: Request {n_requests}")
            n_requests += 1
