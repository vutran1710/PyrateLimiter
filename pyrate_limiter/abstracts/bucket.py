""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from inspect import iscoroutine
from typing import Coroutine
from typing import List
from typing import Optional
from typing import Union

from .clock import Clock
from .rate import Rate
from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket interface
    Assumption: len(rates) always > 0
    TODO: allow empty rates
    """

    rates: List[Rate]
    failing_rate: Optional[Rate] = None

    @abstractmethod
    def put(self, item: RateItem) -> Union[bool, Coroutine[None, None, bool]]:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    def leak(self, current_timestamp: Optional[int] = None) -> Union[int, Coroutine[None, None, int]]:
        """Schedule a leak and run in a task"""

    @abstractmethod
    def flush(self) -> Union[None, Coroutine[None, None, None]]:
        """Flush the whole bucket"""

    @abstractmethod
    def count(self) -> Union[int, Coroutine[None, None, int]]:
        """Count number of items in the bucket"""

    @abstractmethod
    def peek(self, index: int) -> Union[Optional[RateItem], Coroutine[None, None, Optional[RateItem]]]:
        """Peek at the rate-item at a specific index"""


class AbstractClockingBucket(AbstractBucket):
    """AbstractBucket with dedicated clock"""

    clock: Clock

    def availability(self, weight: int) -> Union[int, Coroutine[None, None, int]]:
        """Use dedicated clock to calculate bucket's availability"""
        if weight == 0:
            return 0

        if self.failing_rate is None:
            if weight > self.rates[-1].limit:
                return -1

            return 0

        now = self.clock.now()
        bound_item = self.peek(self.failing_rate.limit - weight + 1)

        def _calc_availability(inner_now: int, inner_bound_item: RateItem) -> int:
            assert self.failing_rate is not None
            lower_time_bound = inner_now - self.failing_rate.interval
            upper_time_bound = inner_bound_item.timestamp
            return upper_time_bound - lower_time_bound

        async def _calc_availability_async():
            nonlocal now, bound_item
            now = await now

            if iscoroutine(bound_item):
                bound_item = await bound_item

            if bound_item is None:
                # NOTE: if no bound item, that means bucket is available
                return 0

            return _calc_availability(now, bound_item)

        if iscoroutine(now) or iscoroutine(bound_item):
            return _calc_availability_async()

        assert isinstance(now, int)

        if bound_item is None:
            # NOTE: if no bound item, that means bucket is available
            return 0

        assert isinstance(bound_item, RateItem)
        return _calc_availability(now, bound_item)


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def wrap_item(
        self,
        name: str,
        weight: int = 1,
    ) -> Union[RateItem, Coroutine[None, None, RateItem]]:
        """Mark the current timestamp to the receiving item,
        if neccessary then wrap it into a RateItem.
        Can return either a coroutine or a RateItem instance
        """

    @abstractmethod
    def get(self, item: RateItem) -> Optional[Union[AbstractBucket, AbstractClockingBucket]]:
        """Create or get the corresponding bucket to this item"""

    @abstractmethod
    def schedule_leak(self) -> None:
        """Schedule all the buckets' leak"""

    @abstractmethod
    def schedule_flush(self) -> None:
        """Schedule all the buckets' flush"""
