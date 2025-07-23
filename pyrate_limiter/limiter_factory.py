"""
A collection of common use cases and patterns for pyrate_limiter
"""
from pyrate_limiter import BucketAsyncWrapper
from pyrate_limiter import Duration
from pyrate_limiter import InMemoryBucket
from pyrate_limiter import Limiter
from pyrate_limiter import Rate


def get_inmemory_limiter(rate_per_duration: int = 3,
                         duration: Duration = Duration.SECOND,
                         max_delay: Duration = Duration.DAY) -> Limiter:
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]
    bucket = InMemoryBucket(rate_limits)
    limiter = Limiter(bucket,
                      raise_when_fail=False,
                      max_delay=max_delay,
                      retry_until_max_delay=True)

    return limiter


def get_async_limiter(rate_per_duration: int = 3,
                      duration: Duration = Duration.SECOND,
                      max_delay: Duration = Duration.DAY) -> Limiter:
    rate = Rate(rate_per_duration, duration)
    rate_limits = [rate]
    bucket = BucketAsyncWrapper(InMemoryBucket(rate_limits))
    limiter = Limiter(bucket,
                      raise_when_fail=False,
                      max_delay=max_delay,
                      retry_until_max_delay=True)

    return limiter
