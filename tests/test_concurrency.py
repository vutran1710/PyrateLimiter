"""Multithreaded and multiprocess stress tests"""
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from logging import getLogger
from os.path import join
from tempfile import gettempdir
from time import perf_counter
from time import sleep

import pytest

from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import RequestRate
from pyrate_limiter import SQLiteBucket

N_BUCKETS = 5  # Number of buckets to use
N_REQUESTS = 101  # Total number of requests to make
N_WORKERS = 7  # Number of parallel workers to use
LIMIT_REQUESTS_PER_SECOND = 10  # Rate limit
THREAD_REQUESTS_PER_SECOND = 7  # Attempted request rate per thread/process

logger = getLogger("pyrate_limiter.tests")


# TODO: These tests could potentially be run for all bucket classes
# @pytest.mark.parametrize("bucket_class", [SQLiteBucket, MemoryListBucket, MemoryQueueBucket, RedisBucket])
@pytest.mark.parametrize("bucket_class", [SQLiteBucket])
@pytest.mark.parametrize("executor_class", [ThreadPoolExecutor, ProcessPoolExecutor])
def test_concurrency(executor_class, bucket_class):
    """Make a fixed number of concurrent requests and check the total time they take to run"""
    logger.info(f"Testing {bucket_class.__name__} with {executor_class.__name__}")

    # Set up limiter and request function
    path = join(gettempdir(), f"test_{executor_class.__name__}.sqlite")
    rate = RequestRate(LIMIT_REQUESTS_PER_SECOND, Duration.SECOND)
    limiter = Limiter(rate, bucket_class=bucket_class, bucket_kwargs={"path": path})
    bucket_ids = [f"{executor_class}_bucket_{i}" for i in range(N_BUCKETS)]
    start_time = perf_counter()
    request_func = partial(_send_request, limiter, bucket_ids, start_time)

    # Distribute requests across workers
    with executor_class(max_workers=N_WORKERS) as executor:
        list(executor.map(request_func, range(N_REQUESTS), timeout=300))

    # Check total time, with debug logging
    elapsed = perf_counter() - start_time
    expected_min_time = (N_REQUESTS - 1) / LIMIT_REQUESTS_PER_SECOND
    worker_type = "threads" if executor_class is ThreadPoolExecutor else "processes"
    logger.info(
        f"Ran {N_REQUESTS} requests with {N_WORKERS} {worker_type} in {elapsed:.2f} seconds\n"
        f"With a rate limit of {LIMIT_REQUESTS_PER_SECOND}/second, expected at least "
        f"{expected_min_time} seconds"
    )
    assert elapsed >= expected_min_time


def _send_request(limiter, bucket_ids, start_time, n_request):
    """Rate-limited test function. Defined in module scope so it can be serialized to multiple
    processes.
    """
    with limiter.ratelimit(*bucket_ids, delay=True):
        logger.info(f"t + {(perf_counter() - start_time):.5f}: Request {n_request+1}")
        sleep(1 / THREAD_REQUESTS_PER_SECOND)
