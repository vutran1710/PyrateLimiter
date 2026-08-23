"""Bucket and local stores for constant-state algorithms."""

from inspect import isawaitable
from multiprocessing import Manager
from multiprocessing import RLock as MpRLock
from threading import RLock
from typing import Awaitable, List, Optional, Union

from ..abstracts.algorithm import ADMITTED, GCRA, State, StateAlgorithm
from ..abstracts.bucket import AbstractBucket
from ..abstracts.rate import Rate, RateItem
from ..abstracts.store import StateStore
from ..clocks import AbstractClock


class InMemoryStateStore(StateStore):
    """State in a local attribute, guarded by a reentrant lock."""

    is_async = False

    def __init__(self) -> None:
        self._state: Optional[State] = None
        self._lock = RLock()

    def check(self, algorithm, rates, now, weight):
        with self._lock:
            state = self._state if self._state is not None else algorithm.initial(rates)
            new_state, decision = algorithm.step(rates, state, now, weight)
            self._state = new_state
            return decision

    def read(self, algorithm, rates):
        with self._lock:
            return self._state if self._state is not None else algorithm.initial(rates)

    def reset(self) -> None:
        with self._lock:
            self._state = None

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_lock", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)
        self._lock = RLock()


class MultiprocessStateStore(StateStore):
    """State in a ``Manager`` list, guarded by a cross-process lock."""

    is_async = False

    def __init__(self, values, lock) -> None:
        self._values = values
        self._lock = lock

    @classmethod
    def init(cls) -> "MultiprocessStateStore":
        return cls(Manager().list(), MpRLock())

    def _load(self, algorithm: StateAlgorithm, rates: List[Rate]) -> State:
        stored = tuple(self._values)
        # A rate list can change between processes; fall back rather than
        # applying a transition against a mismatched tuple.
        return stored if len(stored) == len(rates) else algorithm.initial(rates)

    def check(self, algorithm, rates, now, weight):
        with self._lock:
            new_state, decision = algorithm.step(rates, self._load(algorithm, rates), now, weight)

            if decision.allowed:
                # step() returns the state untouched on denial, so only an
                # admit is worth the round trip through the manager.
                self._values[:] = list(new_state)

            return decision

    def read(self, algorithm, rates):
        with self._lock:
            return self._load(algorithm, rates)

    def reset(self) -> None:
        with self._lock:
            self._values[:] = []


class StateBucket(AbstractBucket):
    """Bucket for constant-state algorithms - GCRA, TokenBucket.

    Keeps a few numbers per key rather than an entry per consumed unit, so
    storage does not grow with traffic and the wait is exact without a lookup.

    The log contract does not apply: ``peek()`` has nothing to return and
    ``leak()`` nothing to trim. Use ``count()`` for how many units are
    currently owed.
    """

    # Mirrors the store's; ``None`` lets the Leaker probe a client it cannot
    # classify. leak() is a sync no-op either way, so routing is harmless.
    is_async: Optional[bool] = False

    def __init__(
        self,
        rates: List[Rate],
        algorithm: Optional[StateAlgorithm] = None,
        store: Optional[StateStore] = None,
        clock: Optional[AbstractClock] = None,
    ):
        self.algorithm: StateAlgorithm = algorithm or GCRA()
        self.store: StateStore = store or InMemoryStateStore()
        self._clock = clock or self.store.default_clock
        self.is_async = self.store.is_async
        self.rates = rates  # AbstractBucket.rates setter sorts + validates

    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        if item.weight == 0:
            return self._record(item, ADMITTED)

        decision = self.store.check(self.algorithm, self.rates, item.timestamp, item.weight)

        if isawaitable(decision):

            async def _await_decision() -> bool:
                return self._record(item, await decision)

            return _await_decision()

        return self._record(item, decision)

    def waiting(self, item: RateItem) -> Union[int, Awaitable[int]]:
        """Wait recorded by the last put(), or re-derived for a different weight.

        Never inspects a log the way the window buckets do - there is none.
        When the query does not match the last put, the wait is recomputed by
        replaying ``step()`` against the stored state, which spends nothing.
        """
        if self.failing_rate is None:
            return 0

        assert item.weight > 0, "Item's weight must > 0"

        if item.weight > self.algorithm.max_weight(self.failing_rate):
            return -1

        recorded = self._recorded_wait(item)

        if recorded is not None:
            return recorded

        state = self.store.read(self.algorithm, self.rates)

        if isawaitable(state):

            async def _await_wait() -> int:
                return self._replay(await state, item)

            return _await_wait()

        return self._replay(state, item)

    def _replay(self, state: State, item: RateItem) -> int:
        """Wait for `item` against `state`, without committing anything."""
        _, decision = self.algorithm.step(self.rates, state, item.timestamp, item.weight)

        if decision.allowed:
            return 0

        return 0 if decision.retry_after_ms is None else decision.retry_after_ms

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        """No-op: state is constant-size, so there is nothing to trim.

        Shared stores expire idle keys themselves (Redis via a TTL).
        """
        return 0

    def flush(self) -> Union[None, Awaitable[None]]:
        self.failing_rate = None
        self._last_wait = None
        return self.store.reset()

    def count(self) -> Union[int, Awaitable[int]]:
        """Units currently owed to the bucket - an estimate, not a log length."""
        now = self.now()
        state = self.store.read(self.algorithm, self.rates)

        if isawaitable(state):

            async def _await_count() -> int:
                return self.algorithm.consumed(self.rates, await state, now)

            return _await_count()

        return self.algorithm.consumed(self.rates, state, now)

    def peek(self, index: int) -> Optional[RateItem]:
        """Always ``None``: this bucket keeps no per-item log to peek into."""
        return None

    def close(self) -> None:
        self.store.close()
