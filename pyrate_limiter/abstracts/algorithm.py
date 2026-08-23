"""Rate-limiting algorithm abstraction.

Separates the policy (which rates admit an item, how long a rejected one waits,
how far back items may be leaked) from the storage that counts and persists
them. Internal in v4; v5 promotes it to a public extension point.

Retry-after rides on ``Decision`` so one check under one lock yields both the
verdict and the wait. Deriving it afterwards costs a second round trip and
reads state that may have moved - and is impossible for algorithms whose state
is not a log (token bucket, GCRA), which compute the wait in closed form.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Final, List, Optional, Sequence

from .rate import Rate


@dataclass(frozen=True)
class Decision:
    """Outcome of an admit check.

    ``retry_after_ms`` is measured from the checked item's own timestamp.
    ``None`` means "unknown, ask ``AbstractBucket.waiting()``" - either the
    weight can never fit, or the backend does not compute a wait. It does not
    mean "no wait".
    """

    failing_rate: Optional[Rate] = None
    retry_after_ms: Optional[int] = None

    @property
    def allowed(self) -> bool:
        return self.failing_rate is None


#: Reused on every admit; ``Decision`` is immutable, so the hot path allocates nothing.
ADMITTED: Final["Decision"] = Decision()


class Algorithm(ABC):
    """A rate-limiting policy, independent of any storage backend.

    Implementations must be stateless so one instance can be shared across
    buckets and threads.
    """

    @abstractmethod
    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        """Whether ``weight`` more units fit, given ``counts`` aligned to ``rates``."""


class LogAlgorithm(Algorithm):
    """Policy over storage holding one timestamped entry per consumed unit.

    Constant-state policies (token bucket, GCRA) will not implement this.
    """

    @abstractmethod
    def window_start(self, rate: Rate, now: int) -> int:
        """Inclusive lower bound of ``rate``'s counting window at ``now``."""

    @abstractmethod
    def retry_after(self, rate: Rate, now: int, blocking_timestamp: Optional[int]) -> int:
        """Milliseconds until room exists under ``rate``.

        ``blocking_timestamp`` is the entry named by ``blocking_offset()``, or
        ``None`` when there is none - or when the policy never asks for one.
        """

    def blocking_offset(self, rate: Rate, weight: int) -> Optional[int]:
        """Offset from the newest stored entry (0-based) whose expiry makes room
        for ``weight``, or ``None`` if the wait does not depend on an entry."""
        return None

    def leak_bound(self, rates: List[Rate], now: int) -> int:
        """Timestamp below which an entry is outside every rate's window."""
        return min(self.window_start(rate, now) for rate in rates)

    def decide(
        self,
        rates: List[Rate],
        counts: Sequence[int],
        weight: int,
        now: int,
        peek_timestamp: Callable[[int], Optional[int]],
    ) -> Decision:
        """``admit()``, resolving the retry-after in the same step on denial.

        ``peek_timestamp(offset)`` is only called when the policy asks for an
        entry and the item was rejected, so backends pay for the lookup only
        when it is needed.
        """
        decision = self.admit(rates, counts, weight)

        if decision.allowed:
            return decision

        rate = decision.failing_rate
        assert rate is not None

        if weight > rate.limit:
            # Can never fit; waiting() reports -1 and the limiter gives up.
            return decision

        offset = self.blocking_offset(rate, weight)
        blocking = None if offset is None else peek_timestamp(offset)

        return Decision(failing_rate=rate, retry_after_ms=self.retry_after(rate, now, blocking))


class SlidingWindowLog(LogAlgorithm):
    """Precise rolling window: admit while each rate's last ``interval`` stays
    under its limit.

    The default. Exact, at the cost of one stored entry per consumed unit.
    """

    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        for rate, count in zip(rates, counts, strict=True):
            if rate.limit - int(count) < weight:
                return Decision(failing_rate=rate)
        return ADMITTED

    def window_start(self, rate: Rate, now: int) -> int:
        return now - rate.interval

    def blocking_offset(self, rate: Rate, weight: int) -> Optional[int]:
        # Counting from the newest entry keeps this independent of both the
        # in-window count and any expired-but-unleaked entries still stored.
        return rate.limit - weight

    def retry_after(self, rate: Rate, now: int, blocking_timestamp: Optional[int]) -> int:
        if blocking_timestamp is None:
            return 0

        # +1 clears the inclusive lower bound: landing exactly on it leaves the
        # entry still counted, so the re-put fails and the limiter spins at 0.
        return blocking_timestamp + rate.interval - now + 1


class FixedWindow(LogAlgorithm):
    """Counts within a wall-clock-aligned window that resets every ``interval``.

    Cheaper and coarser than the rolling window: up to ``2 * limit`` can pass
    across a window boundary. Use it to mirror an upstream API that genuinely
    resets on the hour rather than rolling.
    """

    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        for rate, count in zip(rates, counts, strict=True):
            if rate.limit - int(count) < weight:
                return Decision(failing_rate=rate)
        return ADMITTED

    def window_start(self, rate: Rate, now: int) -> int:
        return now - now % rate.interval

    def retry_after(self, rate: Rate, now: int, blocking_timestamp: Optional[int]) -> int:
        # The whole window clears at once, so no stored entry is consulted.
        # now < window_start + interval always, so this is never 0.
        return self.window_start(rate, now) + rate.interval - now
