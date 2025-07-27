"""
A collection of common use cases and patterns for pyrate_limiter
"""
import logging
from typing import List
from typing import Optional
from typing import Union

from pyrate_limiter import AbstractBucket
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import Duration
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket

logger = logging.getLogger(__name__)


# Global for convenience in multiprocessing, populated by init_mp_limiter.
# Intended to be called by a ProcessPoolExecutor's initializer
LIMITER: Optional[Limiter] = None


def create_sqlite_bucket(
    rates: List[Rate],
    db_path: Optional[str],
    table_name: str = "pyrate_limiter",
    use_file_lock: bool = False,
):
    """
    Create and initialize a SQLite bucket for rate limiting.

    Args:
        rates: List of rate limit configurations.
        db_path: Path to the SQLite database file (or in-memory if None).
        table_name: Name of the table to store rate bucket data.
        use_file_lock: Enable file locking for multi-process synchronization.

    Returns:
        SQLiteBucket: Initialized SQLite-backed bucket.
    """
    logger.info(f"{table_name=}")
    bucket = SQLiteBucket.init_from_file(
        rates,
        db_path=str(db_path),
        table=table_name,
        create_new_table=True,
        use_file_lock=use_file_lock,
    )

    return bucket


def create_sqlite_limiter(
    rate_per_duration: int = 3,
    duration: Union[int, Duration] = Duration.SECOND,
    db_path: Optional[str] = None,
    table_name: str = "rate_bucket",
    max_delay: Union[int, Duration] = Duration.DAY,
    buffer_ms: int = 50,
    use_file_lock: bool = False,
    async_wrapper: bool = False,
) -> Limiter:
    """
    Create a SQLite-backed rate limiter with configurable rate, persistence, and optional async support.

    Args:
        rate_per_duration: Number of allowed requests per duration.
        duration: Time window for the rate limit.
        db_path: Path to the SQLite database file (or in-memory if None).
        table_name: Name of the table used for rate buckets.
        max_delay: Maximum delay before failing requests.
        buffer_ms: Extra wait time in milliseconds to account for clock drift.
        use_file_lock: Enable file locking for multi-process synchronization.
        async_wrapper: Whether to wrap the bucket for async usage.

    Returns:
        Limiter: Configured SQLite-backed limiter instance.
    """
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]

    bucket: AbstractBucket = SQLiteBucket.init_from_file(
        rate_limits,
        db_path=str(db_path),
        table=table_name,
        create_new_table=True,
        use_file_lock=use_file_lock,
    )

    if async_wrapper:
        bucket = BucketAsyncWrapper(bucket)

    limiter = Limiter(
        bucket, raise_when_fail=False, max_delay=max_delay, retry_until_max_delay=True, buffer_ms=buffer_ms
    )

    return limiter


def create_inmemory_limiter(
    rate_per_duration: int = 3,
    duration: Union[int, Duration] = Duration.SECOND,
    max_delay: Union[int, Duration] = Duration.DAY,
    buffer_ms: int = 50,
    async_wrapper: bool = False,
) -> Limiter:
    """
    Create an in-memory rate limiter with configurable rate, duration, delay, and optional async support.

    Args:
        rate_per_duration: Number of allowed requests per duration.
        duration: Time window for the rate limit.
        max_delay: Maximum delay before failing requests.
        buffer_ms: Extra wait time in milliseconds to account for clock drift.
        async_wrapper: Whether to wrap the bucket for async usage.

    Returns:
        Limiter: Configured in-memory limiter instance.
    """
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]
    bucket: AbstractBucket = InMemoryBucket(rate_limits)

    if async_wrapper:
        bucket = BucketAsyncWrapper(InMemoryBucket(rate_limits))

    limiter = Limiter(
        bucket, raise_when_fail=False, max_delay=max_delay, retry_until_max_delay=True, buffer_ms=buffer_ms
    )

    return limiter


def init_global_limiter(bucket: AbstractBucket,
                        max_delay: Union[int, Duration] = Duration.HOUR,
                        raise_when_fail: bool = False,
                        retry_until_max_delay: bool = True,
                        buffer_ms: int = 50):
    """
    Initialize a global Limiter instance using the provided bucket.

    Intended for use as an initializer for ProcessPoolExecutor.

    Args:
        bucket: The rate-limiting bucket to be used.
        max_delay: Maximum delay before failing requests.
        raise_when_fail: Whether to raise an exception when a request fails.
        retry_until_max_delay: Retry until the maximum delay is reached.
        buffer_ms: Additional buffer time in milliseconds for retries.
    """

    global LIMITER
    LIMITER = Limiter(bucket, raise_when_fail=raise_when_fail,
                      max_delay=max_delay, retry_until_max_delay=retry_until_max_delay, buffer_ms=buffer_ms)
