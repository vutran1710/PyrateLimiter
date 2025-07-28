"""multiprocessing In-memory Bucket using a multiprocessing.Manager.ListProxy
     and a multiprocessing.Lock.
"""
from multiprocessing import Manager
from multiprocessing import RLock
from multiprocessing.managers import ListProxy
from multiprocessing.synchronize import RLock as LockType
from typing import List
from typing import Optional

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

    def put(self, item: RateItem) -> bool:
        with self.mp_lock:
            return super().put(item)

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        with self.mp_lock:
            return super().leak(current_timestamp)

    def limiter_lock(self):
        return self.mp_lock

    @classmethod
    def init(
        cls,
        rates: List[Rate],
    ):
        """
        Creates a single ListProxy so that this bucket can be shared across multiple processes.
        """
        shared_items: List[RateItem] = Manager().list()  # type: ignore[assignment]

        mp_lock: LockType = RLock()

        return cls(rates=rates, items=shared_items, mp_lock=mp_lock)
