"""Ref:
- https://www.figma.com/blog/an-alternative-approach-to-rate-limiting/
"""
from threading import RLock
from time import time
from typing import List
from abc import ABC, abstractmethod
from copy import deepcopy
from .exceptions import BucketFullException


class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue
    """

    __values__ = []

    @abstractmethod
    def sync(self) -> None:
        """Synchronizing the local class values with remote queue value
        """

    @abstractmethod
    def append(self, item) -> bool:
        """A method to append one single item to the queue
        :return: True for successful appending, False otherwise
        :rtype: bool
        """

    @abstractmethod
    def values(self) -> List:
        """Return queue vlaues
        :return: list of values
        :rtype: List
        """

    @abstractmethod
    def replace(self, new_list: List) -> bool:
        """Completely replace the existing queue with a new one
        :return: True if successful, False otherwise
        :rtype: bool
        """

    def length(self) -> int:
        """Return current queue's length
        :return: queue's length
        :rtype: int
        """
        return len(self.__values__)


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
    def __init__(self, failure_rate: HitRate, block_time: int):
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


class GenericLimiter:
    """A Basic Rate-Limiter that supports both LeakyBucket & TokenBucket algorimth
    - Depending on how average HitRate is defined, the Limiter will behave like
    LeakyBucket (allowance time for each request) or TokenBucket (maximum
    number of each request over an unit of time)
    - In addition, there is an option to `cap` the request rate in a secondary time-window,
    eg: primary-rate=60 requests/minute and secondary=1000 requests/day
    """
    bucket = None
    _lock = None

    def __init__(
        self,
        bucket: AbstractBucket,
        average: HitRate,
        maximum: HitRate = None,
        blocker: SpamBlocker = None,
    ):

        self.bucket = bucket
        self._lock = RLock()
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

    def allow(self, item):
        pass


class LeakyBucketLimiter:
    queue = None
    capacity = None
    window = None
    _lock = None

    def __init__(self, bucket: AbstractBucket, capacity=10, window=3600):
        self.queue = bucket
        self.capacity = capacity
        self.window = window
        self._lock = RLock()

    def append(self, item):
        with self._lock:
            self.leak()

            if self.queue.getlen() >= self.capacity:
                raise BucketFullException('Bucket full')

            timestamp = time()
            self.queue.append({'timestamp': timestamp, 'item': item})

    def leak(self):
        with self._lock:
            if not self.queue.getlen():
                return

            now = time()
            value_list = self.queue.values()
            new_queue = deepcopy(value_list)

            for idx, item in enumerate(value_list):
                interval = now - item.get('timestamp')
                if interval > self.window:
                    new_queue = value_list[idx + 1:]
                else:
                    break

            self.queue.update(new_queue)


class TokenBucketLimiter:
    queue = None
    capacity = None
    window = None
    _lock = None

    def __init__(self, bucket, capacity=10, window=3600):
        self.queue = bucket
        self.capacity = capacity
        self.window = window
        self._lock = RLock()

    def process(self, item):
        with self._lock:
            self.refill()

            if self.queue.getlen() >= self.capacity:
                raise BucketFullException('No more tokens')

            self.queue.append({'timestamp': time(), 'item': item})

    def refill(self):
        with self._lock:
            if not self.queue.getlen():
                return

            last_item = self.queue.values()[-1]
            now = time()

            if now - last_item['timestamp'] >= self.window:
                self.queue.update([])
