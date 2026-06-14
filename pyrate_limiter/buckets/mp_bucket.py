"""multiprocessing In-memory Bucket using a multiprocessing.Manager.ListProxy
and a multiprocessing.Lock.
"""

from multiprocessing import Manager, RLock
from multiprocessing.managers import ListProxy
from multiprocessing.synchronize import RLock as LockType
from typing import List, Optional

from ..abstracts import Rate, RateItem
from ..buckets import InMemoryBucket
from ..clocks import MonotonicClock


class MultiprocessBucket(InMemoryBucket):
    items: List[RateItem]  # ListProxy
    mp_lock: LockType

    def __init__(self, rates: List[Rate], items: List[RateItem], mp_lock: LockType):
        if not isinstance(items, ListProxy):  # pragma: no cover - guard only
            raise ValueError("items must be a ListProxy")

        self._clock = MonotonicClock()

        self.rates = rates  # AbstractBucket.rates setter sorts + validates
        self.items = items
        self.mp_lock = mp_lock
        # InMemoryBucket.put/peek/count/flush guard `self.items` via self._lock
        # (issue #300). MultiprocessBucket does NOT call super().__init__(), so
        # set it here. Aliasing it to the cross-process mp_lock means the
        # inherited count()/peek()/flush() become process-safe too, and the
        # reentrant RLock tolerates put()/leak() re-acquiring it via super().
        self._lock = mp_lock  # type: ignore[assignment]

    def put(self, item: RateItem) -> bool:
        with self.mp_lock:
            return super().put(item)

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        with self.mp_lock:
            return super().leak(current_timestamp)

    def limiter_lock(self):
        return self.mp_lock

    def __setstate__(self, state):
        # Re-alias _lock to the shared cross-process mp_lock rather than the
        # thread-local RLock InMemoryBucket.__setstate__ would create, so the
        # inherited count()/peek()/flush() stay tied to mp_lock across processes.
        self.__dict__.update(state)
        self._lock = self.mp_lock  # type: ignore[assignment]

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
