"""
A collection of common use cases and patterns for pyrate_limiter
"""
import logging
from typing import List
from typing import Optional

from pyrate_limiter import AbstractBucket
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import Duration
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import Rate
from pyrate_limiter import SQLiteBucket

logger = logging.getLogger(__name__)


def create_sqlite_bucket(
    rates: List[Rate],
    db_path: Optional[str],
    table_name: str = "pyrate_limiter",
    use_file_lock: bool = False,
):
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
    duration: Duration = Duration.SECOND,
    db_path: Optional[str] = None,
    table_name: str = "rate_bucket",
    max_delay: Duration = Duration.DAY,
    use_file_lock: bool = False,
    async_wrapper: bool = False,
) -> Limiter:
    """
    use_file_lock: Used for ensuring rate limiting across multiple processes.
    async_wrapper: Used for asyncio contexts
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
        bucket, raise_when_fail=False, max_delay=max_delay, retry_until_max_delay=True
    )

    return limiter


def create_inmemory_limiter(
    rate_per_duration: int = 3,
    duration: Duration = Duration.SECOND,
    max_delay: Duration = Duration.DAY,
    async_wrapper: bool = False,
) -> Limiter:
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]
    bucket: AbstractBucket = InMemoryBucket(rate_limits)

    if async_wrapper:
        bucket = BucketAsyncWrapper(InMemoryBucket(rate_limits))

    limiter = Limiter(
        bucket, raise_when_fail=False, max_delay=max_delay, retry_until_max_delay=True
    )

    return limiter
