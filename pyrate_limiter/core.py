"""Ref:
- https://www.figma.com/blog/an-alternative-approach-to-rate-limiting/
"""
from time import time
from typing import List
from abc import ABC, abstractmethod
from copy import deepcopy
from .exceptions import BucketFullException


class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue"""

    __values__ = []

    @abstractmethod
    def append(self, item) -> None:
        """A method to append one single item to the value queue
        """
    @abstractmethod
    def values(self) -> List:
        """Return queue vlaues
        """
    @abstractmethod
    def update(self, new_list: List) -> None:
        """Completely replace the existing queue with a new one
        """
    def getlen(self) -> int:
        """Return current queue's length
        """
        return len(self.__values__)


class LeakyBucketLimiter:
    queue = None
    capacity = None
    window = None

    def __init__(self, bucket: AbstractBucket, capacity=10, window=3600):
        self.queue = bucket
        self.capacity = capacity
        self.window = window

    def append(self, item):
        self.leak()

        if self.queue.getlen() >= self.capacity:
            raise BucketFullException('Bucket full')

        timestamp = time()
        self.queue.append({'timestamp': timestamp, 'item': item})

    def leak(self):
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

    def __init__(self, bucket, capacity=10, window=3600):
        self.queue = bucket
        self.capacity = capacity
        self.window = window

    def process(self, item):
        self.refill()

        if self.queue.getlen() >= self.capacity:
            raise BucketFullException('No more tokens')

        self.queue.append({'timestamp': time(), 'item': item})

    def refill(self):
        if not self.queue.getlen():
            return

        last_item = self.queue.values()[-1]
        now = time()

        if now - last_item['timestamp'] >= self.window:
            self.queue.update([])
