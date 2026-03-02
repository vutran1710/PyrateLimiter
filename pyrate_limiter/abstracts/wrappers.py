"""Wrappers over different abstract types"""

from inspect import isawaitable
from typing import Any, Optional

from .bucket import AbstractBucket, _AsyncMode
from .rate import RateItem


class BucketAsyncWrapper(AbstractBucket[_AsyncMode]):
    """BucketAsyncWrapper is a wrapping over any bucket
    that turns a async/synchronous bucket into an async one
    """

    def __init__(self, bucket: AbstractBucket[Any]):
        assert isinstance(bucket, AbstractBucket)
        self.bucket = bucket

    async def put(self, item: RateItem) -> bool:
        result = self.bucket.put(item)

        while isawaitable(result):
            result = await result

        return result

    async def count(self) -> int:
        result = self.bucket.count()

        while isawaitable(result):
            result = await result

        return result

    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        result = self.bucket.leak(current_timestamp)

        while isawaitable(result):
            result = await result

        assert isinstance(result, int)
        return result

    async def flush(self) -> None:
        result = self.bucket.flush()

        while isawaitable(result):
            # TODO: AbstractBucket.flush() may not have correct type annotation?
            result = await result  # type: ignore

        return None

    async def peek(self, index: int) -> Optional[RateItem]:
        item = self.bucket.peek(index)

        while isawaitable(item):
            item = await item

        assert item is None or isinstance(item, RateItem)
        return item

    async def waiting(self, item: RateItem) -> int:
        wait_or_awaitable = super().waiting(item)

        if isawaitable(wait_or_awaitable):
            wait = await wait_or_awaitable
        else:
            wait = wait_or_awaitable

        assert isinstance(wait, int)
        return wait

    def now(self) -> int:
        return self.bucket.now()

    @property
    def failing_rate(self):
        return self.bucket.failing_rate

    @property
    def rates(self):
        return self.bucket.rates
