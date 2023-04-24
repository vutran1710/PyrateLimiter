"""Initialize this class to define rates for limiter
"""
from time import time
from typing import List, Optional

from .exceptions import ImmutableClassProperty


class RateItem:
    name: str
    timestamp: int
    weight: int

    def __init__(self, name: str, weight: int = 1, timestamp: Optional[int] = None):
        self.name = name
        self.weight = weight
        self.timestamp = int(time() * 1000) if timestamp is None else timestamp


class TimeWindow:
    length: int

    def __init__(self, length: int):
        self.length = length

    def binary_search(self, items: List[RateItem], lower: int) -> Optional[int]:
        if not items:
            return None

        if items[0].timestamp > lower:
            return 0

        if items[-1].timestamp < lower:
            return None

        pivot_idx = int(len(items) / 2)

        left = items[pivot_idx - 1].timestamp
        right = items[pivot_idx].timestamp

        if left < lower <= right:
            return pivot_idx

        if left >= lower:
            return self.binary_search(items[:pivot_idx], lower)

        if right < lower:
            return pivot_idx + self.binary_search(items[pivot_idx:], lower)

    def count(self, items: List[RateItem]) -> int:
        """Count how many items within the window"""
        upper = int(time() * 1000)
        lower = upper - self.length
        counter = 0

        idx = self.binary_search(items, lower)

        if idx is not None:
            counter = len(items) - idx
            return counter

        return 0


class Rate:
    """Rate definition.

    Args:
        limit: Number of requests allowed within ``interval``
        interval: Time interval, in miliseconds
    """

    window: TimeWindow

    def __init__(
        self,
        limit: int,
        interval: int,
    ):
        self._limit = limit
        self._interval = interval
        self.window = TimeWindow(interval)

    @property
    def limit(self) -> int:
        return self._limit

    @limit.setter
    def limit(self, _):
        raise ImmutableClassProperty(self, "limit")

    @property
    def interval(self) -> int:
        return self._interval

    @interval.setter
    def interval(self, _):
        raise ImmutableClassProperty(self, "interval")

    def __str__(self):
        return f"{self.limit}/{self.interval}"

    def can_accquire(self, items: List[RateItem]) -> bool:
        return self.window.count(items) < self.limit
