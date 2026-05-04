"""
A collection of common use cases and patterns for pyrate_limiter
"""

import logging
from typing import List, Optional, Union

from pyrate_limiter import AbstractBucket, Duration, InMemoryBucket, Limiter, Rate, SQLiteBucket

logger = logging.getLogger(__name__)


# Global for convenience in multiprocessing, populated by init_mp_limiter.
# Intended to be called by a ProcessPoolExecutor's initializer
LIMITER: Optional[Limiter] = None


def create_sqlite_bucket(
    rates: List[Rate],
    db_path: Optional[str],
    table_name: str = "pyrate_limiter",
    use_file_lock: bool = False,
) -> SQLiteBucket:
    """
    Create and initialize a SQLite bucket for rate limiting.

    Args:
        rates: List of rate limit configurations.
        db_path: Path to the SQLite database file. If None, a temporary on-disk SQLite database is created.
        table_name: Name of the table to store rate bucket data.
        use_file_lock: Enable file locking for multi-process synchronization.

    Returns:
        SQLiteBucket: Initialized SQLite-backed bucket.
    """
    logger.info("Table name is %s", table_name)
    bucket = SQLiteBucket.init_from_file(
        rates,
        db_path=db_path,
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
    buffer_ms: int = 50,
    use_file_lock: bool = False,
) -> Limiter:
    """
    Create a SQLite-backed rate limiter with configurable rate, persistence, and file locking.

    Args:
        rate_per_duration: Number of allowed requests per duration.
        duration: Time window for the rate limit.
        db_path: Path to the SQLite database file. If None, a temporary on-disk SQLite database is created.
        table_name: Name of the table used for rate buckets.
        buffer_ms: Extra wait time in milliseconds to account for clock drift.
        use_file_lock: Enable file locking for multi-process synchronization.

    Returns:
        Limiter: Configured SQLite-backed limiter instance.
    """
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]

    bucket: AbstractBucket = SQLiteBucket.init_from_file(
        rate_limits,
        db_path=db_path,
        table=table_name,
        create_new_table=True,
        use_file_lock=use_file_lock,
    )

    limiter = Limiter(bucket, buffer_ms=buffer_ms)

    return limiter


def create_inmemory_limiter(
    rate_per_duration: int = 3,
    duration: Union[int, Duration] = Duration.SECOND,
    buffer_ms: int = 50,
) -> Limiter:
    """
    Create an in-memory rate limiter with configurable rate and clock-drift buffer.

    Args:
        rate_per_duration: Number of allowed requests per duration.
        duration: Time window for the rate limit.
        buffer_ms: Extra wait time in milliseconds to account for clock drift.

    Returns:
        Limiter: Configured in-memory limiter instance.
    """
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]
    bucket: AbstractBucket = InMemoryBucket(rate_limits)

    limiter = Limiter(bucket, buffer_ms=buffer_ms)

    return limiter


def init_global_limiter(
    bucket: AbstractBucket,
    buffer_ms: int = 50,
) -> None:
    """
    Initialize a global Limiter instance using the provided bucket.

    Intended for use as an initializer for ProcessPoolExecutor.

    Args:
        bucket: The rate-limiting bucket to be used.
        buffer_ms: Additional buffer time in milliseconds for retries.
    """

    global LIMITER
    LIMITER = Limiter(bucket, buffer_ms=buffer_ms)
