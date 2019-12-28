"""Ref:
- https://www.figma.com/blog/an-alternative-approach-to-rate-limiting/
- https://nordicapis.com/everything-you-need-to-know-about-api-rate-limiting/
"""
from __future__ import annotations
import math
from contextlib import contextmanager
from typing import Any, Callable, NamedTuple
from time import time
from abc import ABC, abstractmethod


class LoggedItem(NamedTuple):
    __name__ = 'LoggedItem'
    item: Any
    timestamp: int


class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue
    """
    @abstractmethod
    @contextmanager
    def synchronizing(self) -> AbstractBucket:
        """Synchronizing the local class values with remote queue value
        :return: remote queue
        :rtype: list
        """

    @abstractmethod
    def __iter__(self):
        """Bucket should be iterable
        """

    @abstractmethod
    def __getitem__(self, index: int):
        """Bucket should be subscriptable
        """

    @abstractmethod
    def __len__(self):
        """Bucket should return queue's size at request
        """

    @abstractmethod
    def append(self, item: LoggedItem) -> int:
        """A method to append one single item to the queue
        :return: new queue's length
        :rtype: int
        """

    @abstractmethod
    def discard(self, number=1) -> int:
        """A method to append one single item to the queue
        :return: queue's length after discard its first item
        :rtype: int
        """


class HitRate:
    """A supporting class for GenericLimiter
    """
    def __init__(self, hit: int, time: int):
        """Init a HitRate instance, defining number of hit / time
        :param hit: number of hit allowed over a time unit
        :param time: a single time-unit, in seconds
        """
        self.hit = hit
        self.time = time


class SpamBlocker:
    """Blocking spammer for a limited time based on
    how many times the bucket has been overflown
    """
    def __init__(
        self,
        failure_rate: HitRate,
        block_time: int,
        blocking_signal: Callable = None,
        unblocking_signal: Callable = None,
    ):
        """
        :param failure_rate: permitted number of time a request is disallowed over time
        :param block_time: how long the spammer will be blocked
        """
        self.rate = failure_rate
        self.block_time = block_time

    def cool_down(self, time_delta: int) -> int:
        """By design, cool-down is like a Token of Failure-Tokens being
        refilled at the rate of one token / (rate.time/rate.hit)
        :return int: number of refilled failure-token
        """
        pass

    def mark(self, time: int) -> None:
        """Mark a single-violence.
        Notify on blocking
        """
        pass


class BasicLimiter:
    """A Basic Rate-Limiter that supports both LeakyBucket & TokenBucket algorimth
    - Depending on how average HitRate is defined, the Limiter will behave like
    LeakyBucket (allowance time for each request) or TokenBucket (maximum
    number of each request over an unit of time)
    - In addition, there is an option to `cap` the request rate in a secondary time-window,
    eg: primary-rate=60 requests/minute and maximum-rate=1000 requests/day
    """
    bucket: AbstractBucket = None

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

    @property
    def leak_rate(self) -> float:
        """To ensure the stability & consistency of Average HitRate Limit
        - when override, should consider window-overlapping that results in
        actual hit-rate being greater than average hit-rate
        """
        rate: HitRate = self.average
        return rate.time / rate.hit

    def allow(self, item: Any) -> bool:
        """Determining if an item is allowed to pass through
        - Using lazy-mechanism to calculate the bucket's current volume
        - To prevent race condition, locking/synchronizinging should be considred accordingly
        """
        now = int(time())
        bucket: AbstractBucket = self.bucket

        with bucket.synchronizing() as Bucket:
            logged_item = LoggedItem(item=item, timestamp=now)
            bucket_capacity = self.average.hit

            if not len(Bucket) or len(Bucket) < bucket_capacity:
                bucket.append(logged_item)
                return True

            latest_item: NamedTuple = Bucket[-1]
            timestamp = latest_item.timestamp

            drain = min(
                int(math.floor((now - timestamp) / self.leak_rate)),
                bucket_capacity,
            )

            print('>>>>>> Drain ==', drain)

            if drain >= 1:
                bucket.discard(number=drain)
                bucket.append(logged_item)
                return True

            if self.blocker:
                self.blocker.mark(now)

            return False
