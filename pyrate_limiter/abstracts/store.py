"""Storage for constant-state algorithms."""

from abc import ABC, abstractmethod
from typing import Awaitable, List, Optional, Union

from ..clocks import AbstractClock, MonotonicClock
from .algorithm import Decision, State, StateAlgorithm
from .rate import Rate


class StateStore(ABC):
    """Holds one key's state for a ``StateAlgorithm``.

    The store's only real job is atomicity: ``check()`` must read the state,
    apply the transition and persist the result without another writer
    interleaving. How it achieves that is its own business - a lock in-process,
    a Lua script in Redis.
    """

    #: ``None`` means "ask the Leaker to probe" (a client that may be either).
    is_async: Optional[bool] = False

    #: Used when the bucket is not given a clock. Shared stores override it,
    #: since a monotonic clock means nothing across machines.
    default_clock: AbstractClock = MonotonicClock()

    @abstractmethod
    def check(
        self,
        algorithm: StateAlgorithm,
        rates: List[Rate],
        now: int,
        weight: int,
    ) -> Union[Decision, Awaitable[Decision]]:
        """Apply ``algorithm.step`` to the stored state, atomically."""

    @abstractmethod
    def read(self, algorithm: StateAlgorithm, rates: List[Rate]) -> Union[State, Awaitable[State]]:
        """Current state. For reporting only - never the basis of a decision."""

    @abstractmethod
    def reset(self) -> Union[None, Awaitable[None]]:
        """Forget everything, as though the key had never been used."""

    def close(self) -> None:  # noqa: B027
        """Release any resources held. Optional."""
