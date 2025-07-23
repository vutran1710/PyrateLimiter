"""multiprocessing In-memory Bucket using a multiprocessing.Manager.ListProxy
     and a multiprocessing.Lock.
"""
from multiprocessing import Lock
from multiprocessing import Manager
from multiprocessing.managers import ListProxy
from multiprocessing.synchronize import Lock as LockType
from typing import List

from ..abstracts import Rate
from ..abstracts import RateItem
from pyrate_limiter.buckets import InMemoryBucket


class MultiprocessBucket(InMemoryBucket):

    items: List[RateItem]  # ListProxy
    mp_lock: LockType

    def __init__(self, rates: List[Rate], items: List[RateItem], mp_lock: LockType):

        if not isinstance(items, ListProxy):
            raise ValueError("items must be a ListProxy")

        self.rates = sorted(rates, key=lambda r: r.interval)
        self.items = items
        self.mp_lock = mp_lock

    @classmethod
    def init(
        cls,
        rates: List[Rate],
    ):
        """
        Creates a single ListProxy so that this bucket can be shared across multiple processes.
        """
        shared_items: List[RateItem] = Manager().list()  # type: ignore[assignment]

        mp_lock: LockType = Lock()

        return cls(rates=rates, items=shared_items, mp_lock=mp_lock)

    def get_combined_lock(self, lock):
        """Provides a new Lock that combines mp_lock with the RLock
        """
        class CombinedLock:
            def __init__(self, *locks):
                self.locks = locks

            def __enter__(self):
                for lock in self.locks:
                    lock.acquire()

            def __exit__(self, exc_type, exc_val, exc_tb):
                for lock in reversed(self.locks):
                    lock.release()

        return CombinedLock(self.mp_lock, lock)
