"""Wrappers over different abstract types"""

from typing import Optional

from .bucket import AsyncAbstractBucket, SyncAbstractBucket
from .rate import RateItem


class BucketAsyncWrapper(AsyncAbstractBucket):
    """BucketAsyncWrapper is a wrapping over any bucket
    that turns a async/synchronous bucket into an async one
    """

    bucket: SyncAbstractBucket

    def __init__(self, bucket: SyncAbstractBucket):
        assert isinstance(bucket, SyncAbstractBucket)
        self.bucket = bucket

    async def put(self, item: RateItem):
        result = self.bucket.put(item)
        return result

    async def count(self):
        result = self.bucket.count()

        return result

    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        result = self.bucket.leak(current_timestamp)

        assert isinstance(result, int)
        return result

    async def flush(self) -> None:
        self.bucket.flush()

    async def peek(self, index: int) -> Optional[RateItem]:
        item = self.bucket.peek(index)

        return item

    async def waiting(self, item: RateItem) -> int:
        wait = self.bucket.waiting(item)

        assert isinstance(wait, int)
        return wait

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates
