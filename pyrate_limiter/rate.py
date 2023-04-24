"""Initialize this class to define rates for limiter
"""
from .exceptions import ImmutableClassProperty


class RateItem:
    name: str
    timestamp: int
    weight: int

    def __init__(self, name: str, timestamp: int, weight: int = 1):
        self.name = name
        self.timestamp = timestamp
        self.weight = weight


class Rate:
    """Rate definition.

    Args:
        limit: Number of requests allowed within ``interval``
        interval: Time interval, in miliseconds
    """

    def __init__(
        self,
        limit: int,
        interval: int,
    ):
        self._limit = limit
        self._interval = interval

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
