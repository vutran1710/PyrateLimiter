from .data_structures import (
    AbstractBucket,
    HitRate,
    LoggedItem,
)


class SlidingWindowLog:
    bucket: AbstractBucket = None
    rate: HitRate = None

    def __init__(self, bucket: AbstractBucket, rate: HitRate):
        """SlidingWindowLog algorithm
        """
        self.bucket = bucket
        self.rate = rate
