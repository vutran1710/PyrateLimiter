"""Ref:
- https://www.figma.com/blog/an-alternative-approach-to-rate-limiting/
- https://nordicapis.com/everything-you-need-to-know-about-api-rate-limiting/
"""
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, NamedTuple, NewType, Callable, Sequence
from abc import ABC, abstractmethod
from time import time
from .exceptions import InvalidParams, BucketFullException


class LoggedItem(NamedTuple):
    """Add counter and timestamp to the item in queue
    """
    __name__ = 'LoggedItem'
    nth: int
    item: Any
    timestamp: int


class HitRate(NamedTuple):
    """A supporting class for GenericLimiter
    """
    __name__ = 'HitRate'
    hit: int
    time: int


AlgorithmFunc = NewType(
    'AlgorithmFunc', Callable[[
        Sequence[LoggedItem],
        HitRate,
        Any,
        int,
    ], bool])


class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue
    """
    def __init__(self,
                 alg: AlgorithmFunc = None,
                 rate: HitRate = None,
                 err: str = None):
        """For a bucket to work, provide:
        - proper algorithm and rate
        - an Error description that matches the Bucket's full-exception
        """
        if not alg or not rate:
            raise InvalidParams('no algorithm or hit-rate')

        self.__alg = alg
        self.__rate = rate
        self.__err = err

    def check_in(self, item):
        """Register an incoming item/request
        """
        now = int(time())
        if not self.__alg(self, self.__rate, item, now):
            raise BucketFullException(self.__err)

    @property
    def queue(self):
        """Setting the Queue
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
        """Public method to append item to the Queue
        should it pass the limiter's validation
        :return: new queue's length
        :rtype: int
        """

    @abstractmethod
    def discard(self, number=1) -> int:
        """Public method to remove item(s) from the Queue
        :return: queue's length after discard its first item
        :rtype: int
        """
