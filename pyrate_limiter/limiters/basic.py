"""Simple rate limiter as example
"""
from typing import Any, List
from pyrate_limiter.core import AbstractBucket
from pyrate_limiter.exceptions import InvalidParams


class BasicLimiter:
    """A Basic Rate-Limiter that supports both LeakyBucket & TokenBucket algorimth
    - Can be initiated with multiple buckets
    eg: primary-rate=60 requests/minute and maximum-rate=1000 requests/day
    """
    def __init__(self, *buckets: List[AbstractBucket]):

        if not buckets:
            raise InvalidParams('At least one Bucket is required')

        self.buckets = buckets

    def allow(self, item: Any) -> None:
        """Determining if an item is allowed to pass through
        - Using lazy-mechanism to calculate the bucket's current volume
        - To prevent race condition, locking/synchronizinging should be considred accordingly
        """
        for bucket in self.buckets:
            with bucket.synchronizing() as single_bucket:
                single_bucket.check_in(item)
