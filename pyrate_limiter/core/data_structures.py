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
