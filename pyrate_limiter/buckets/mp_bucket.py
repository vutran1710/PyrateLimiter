"""Naive bucket implementation using built-in list
"""
from multiprocessing import Manager
from multiprocessing.managers import ListProxy
from typing import List

from ..abstracts import Rate
from ..abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket


class MultiprocessBucket(InMemoryBucket):
    """MultiProcessing In-memory Bucket using a multiprocessing.Manager
     and a multiprocessing.Lock.
    """

    items: List[RateItem]  # ListProxy

    def __init__(self, rates: List[Rate], items: List[RateItem]):

        if not isinstance(items, ListProxy):
            raise ValueError("items must be a ListProxy")

        self.rates = sorted(rates, key=lambda r: r.interval)
        self.items = items

    @classmethod
    def init(
        cls,
        rates: List[Rate],
    ):
        """
        Creates a single ListProxy so that this bucket can be shared across multiple processes.
        """
        shared_items: ListProxy[int] = Manager().list()

        return cls(rates=rates, items=shared_items)  # type: ignore
