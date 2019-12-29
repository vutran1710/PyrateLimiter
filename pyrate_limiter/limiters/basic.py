from typing import Any
from time import time
from pyrate_limiter.core import (
    AbstractBucket,
    HitRate,
    LoggedItem,
)


class BasicLimiter:
    """A Basic Rate-Limiter that supports both LeakyBucket & TokenBucket algorimth
    - This Limiter implements Sliding-Window log algorithm
    - This Limiter can be initialized with maximum 3 HitRate instances
    - Each HitRate instance must be on larger-scale than the previous one
    eg: primary-rate=60 requests/minute and maximum-rate=1000 requests/day
    """
    bucket: AbstractBucket = None

    def __init__(
        self,
        bucket: AbstractBucket,
        average: HitRate,
    ):

        self.bucket = bucket
        self.average = average

    def allow(self, item: Any) -> bool:
        """Determining if an item is allowed to pass through
        - Using lazy-mechanism to calculate the bucket's current volume
        - To prevent race condition, locking/synchronizinging should be considred accordingly
        """
        now = int(time())
        bucket: AbstractBucket = self.bucket

        with bucket.synchronizing() as Bucket:
            bucket_capacity = self.average.hit
            volume = len(Bucket)

            if not volume or volume < bucket_capacity:
                logged_item = LoggedItem(item=item, timestamp=now, nth=1)
                bucket.append(logged_item)
                return True

            after_leak_volume = volume

            for idx in range(volume):
                item: LoggedItem = Bucket[0]
                timestamp = item.timestamp
                if (now - timestamp) > self.average.time:
                    after_leak_volume = Bucket.discard(number=1)
                else:
                    break

            if after_leak_volume < bucket_capacity:
                logged_item = LoggedItem(
                    item=item,
                    timestamp=now,
                    nth=volume + 1,
                )
                bucket.append(logged_item)
                return True

            return False
