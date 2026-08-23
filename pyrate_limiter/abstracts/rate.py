"""Unit classes that deals with rate, item & duration"""

from enum import Enum
from typing import Optional, Union


class Duration(Enum):
    """Interval helper class"""

    SECOND = 1000
    MINUTE = 1000 * 60
    HOUR = 1000 * 60 * 60
    DAY = 1000 * 60 * 60 * 24
    WEEK = 1000 * 60 * 60 * 24 * 7

    def __mul__(self, mutiplier: float) -> int:
        return int(self.value * mutiplier)

    def __rmul__(self, multiplier: float) -> int:
        return self.__mul__(multiplier)

    def __add__(self, another_duration: Union["Duration", int]) -> int:
        return self.value + int(another_duration)

    def __radd__(self, another_duration: Union["Duration", int]) -> int:
        return self.__add__(another_duration)

    def __int__(self) -> int:
        return self.value

    def __eq__(self, duration: object) -> bool:
        if not isinstance(duration, (Duration, int)):
            return NotImplemented

        return self.value == int(duration)

    @staticmethod
    def readable(value: int) -> str:
        notes = [
            (Duration.WEEK, "w"),
            (Duration.DAY, "d"),
            (Duration.HOUR, "h"),
            (Duration.MINUTE, "m"),
            (Duration.SECOND, "s"),
        ]

        for note, shorten in notes:
            if value >= note.value:
                decimal_value = value / note.value
                return f"{decimal_value:0.1f}{shorten}"  # noqa: E231

        return f"{value}ms"


class RateItem:
    """RateItem is a wrapper for bucket to work with"""

    name: str
    weight: int
    timestamp: int

    def __init__(self, name: str, timestamp: int, weight: int = 1):
        self.name = name
        self.timestamp = timestamp
        self.weight = weight

    def __str__(self) -> str:
        return f"RateItem(name={self.name}, weight={self.weight}, timestamp={self.timestamp})"


class Rate:
    """Rate definition.

    Args:
        limit: Number of requests allowed within ``interval``
        interval: Time interval, in miliseconds
        burst: How many units may be spent at once. Only the constant-state
            algorithms (``GCRA``, ``TokenBucket``) read it; the window
            algorithms admit up to ``limit`` per window regardless. Defaults to
            ``limit``, which is classic token-bucket behaviour - a full bucket
            at rest. ``burst=1`` makes the output perfectly smooth.
    """

    limit: int
    interval: int
    burst: int

    def __init__(
        self,
        limit: int,
        interval: Union[int, Duration],
        burst: Optional[int] = None,
    ):
        self.limit = limit
        self.interval = int(interval)
        self.burst = limit if burst is None else burst
        assert self.interval
        assert self.limit
        assert self.burst >= 1, "Rate's burst must be >= 1"

    def __str__(self) -> str:
        suffix = f", burst={self.burst}" if self.burst != self.limit else ""
        return f"limit={self.limit}/{Duration.readable(self.interval)}{suffix}"  # noqa: E231

    def __repr__(self) -> str:
        suffix = f", burst={self.burst}" if self.burst != self.limit else ""
        return f"limit={self.limit}/{self.interval}{suffix}"  # noqa: E231
