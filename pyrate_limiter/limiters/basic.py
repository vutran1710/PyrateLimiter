from typing import Any
from time import time
from pyrate_limiter.core.data_structures import (
    AbstractBucket,
    SpamBlocker,
    HitRate,
)


class BasicLimiter:
    """A Basic Rate-Limiter that supports both LeakyBucket & TokenBucket algorimth
    - This Limiter implements Sliding-Window log algorithm
    - This Limiter can be initialized with maximum 3 HitRate instances
    - Each HitRate instance must be on larger-scale than the previous one
    eg: primary-rate=60 requests/minute and maximum-rate=1000 requests/day
    """
    bucket: AbstractBucket = None
    blocker: SpamBlocker = None

    def __init__(
        self,
        bucket: AbstractBucket,
        average: HitRate,
        maximum: HitRate = None,
        blocker: SpamBlocker = None,
    ):

        self.bucket = bucket
        self.average = average

        if maximum and maximum.time <= average.time:
            msg = "Maximum's time must be larger than Average's time"
            raise Exception(msg)

        if maximum and maximum.hit <= average.hit:
            msg = "Maximum's hit must be larger than Average's hit"
            raise Exception(msg)

        if maximum:
            self.maximum = maximum

        if blocker:
            self.blocker = blocker

    def leak(self, elapsed) -> bool:
        """To ensure the stability & consistency of Average HitRate Limit
        - when override, should consider window-overlapping that results in
        actual hit-rate being greater than average hit-rate
        """
        return elapsed > self.average.time

    def allow(self, item: Any) -> bool:
        """Determining if an item is allowed to pass through
        - Using lazy-mechanism to calculate the bucket's current volume
        - To prevent race condition, locking/synchronizinging should be considred accordingly
        - Separate algorithms for this method
        """
        now = int(time())

        for bucket in self.buckets:
            with bucket.synchronizing() as Bucket:
                Bucket.append(item, now)
