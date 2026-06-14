"""Rate-limiting algorithm abstraction.

Separates the *policy* (which rates admit an item, and how far back items can be
leaked) from the *storage* that counts and persists those items. In v4 this is
an internal seam: the built-in buckets delegate their per-rate admit decision
and leak bound here, so the sliding-window-log logic lives in exactly one place
instead of being copy-pasted across backends. v5 promotes ``Algorithm`` /
``Decision`` to a public extension point (a ``Store`` interface plus a generic
``Algorithm.check`` over it, with backends providing optional native
implementations), at which point ``Decision`` also carries retry-after and
replaces the ``failing_rate`` instance-state side-channel + the bool return.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .rate import Rate


@dataclass(frozen=True)
class Decision:
    """Outcome of an admit check.

    ``failing_rate is None`` means the item was admitted; otherwise it is the
    first rate whose window was full. In v4 the retry-after is still derived
    separately by ``AbstractBucket.waiting()``; v5 folds it into this type so a
    single atomic check yields both the verdict and the wait.
    """

    failing_rate: Optional[Rate] = None

    @property
    def allowed(self) -> bool:
        return self.failing_rate is None


class Algorithm(ABC):
    """A rate-limiting policy, expressed independently of any storage backend.

    A bucket supplies the per-rate windowed counts (however it obtains them -
    in-memory bisect, ``ZCOUNT``, ``COUNT(*) FILTER``...) and the algorithm
    decides admission. Implementations must be stateless so a single instance
    can be shared across buckets and threads.
    """

    @abstractmethod
    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        """Decide whether ``weight`` more items fit, given ``counts[i]`` items
        already inside ``rates[i]``'s window (``counts`` aligned to ``rates``)."""

    @abstractmethod
    def leak_bound(self, rates: List[Rate], now: int) -> int:
        """Timestamp below which an item is outside *every* rate's window and so
        may be leaked."""


class SlidingWindowLog(Algorithm):
    """Precise sliding-window-log policy.

    Admit while, for every rate, the count of items within its rolling interval
    stays under the limit. This is PyrateLimiter's default and (until v5) only
    algorithm; backends may implement it natively for atomicity/performance
    (Redis Lua, Postgres lock + ``COUNT FILTER``, in-memory bisect) but share
    this definition of the decision.
    """

    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        for rate, count in zip(rates, counts, strict=True):
            if rate.limit - int(count) < weight:
                return Decision(failing_rate=rate)
        return Decision()

    def leak_bound(self, rates: List[Rate], now: int) -> int:
        # rates are sorted ascending by interval (AbstractBucket.rates), so
        # rates[-1] is the widest window.
        return now - rates[-1].interval
