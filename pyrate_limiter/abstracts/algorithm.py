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
from math import ceil
from typing import Callable, Final, List, Optional, Sequence, Tuple, Union

from .rate import Rate

#: Constant-state policies keep a small tuple of floats per key, opaque to the
#: store that persists it. GCRA uses one theoretical-arrival-time per rate.
State = Tuple[float, ...]


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


class Algorithm(ABC):  # noqa: B024 - base of the family; the abstract surface differs per sub-interface
    """A rate-limiting policy, independent of any storage backend.

    Implementations must be stateless so one instance can be shared across
    buckets and threads. The two sub-interfaces differ in what they need
    remembered per key: ``LogAlgorithm`` an entry per consumed unit,
    ``StateAlgorithm`` a fixed handful of numbers.
    """

    def max_weight(self, rate: Rate) -> int:
        """Largest weight this policy can ever admit under ``rate``."""
        return rate.limit


class LogAlgorithm(Algorithm):
    """Policy over storage holding one timestamped entry per consumed unit."""

    @abstractmethod
    def admit(self, rates: List[Rate], counts: Sequence[int], weight: int) -> Decision:
        """Whether ``weight`` more units fit, given ``counts`` aligned to ``rates``."""

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

        if weight > self.max_weight(rate):
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


class StateAlgorithm(Algorithm):
    """Policy whose state is a fixed-size tuple of numbers, not a log.

    Storage keeps one small value per key however much traffic passes, and the
    wait comes out in closed form. In exchange the check is *destructive* - it
    spends what it admits - so ``step()`` must evaluate every rate before
    committing any of them.
    """

    @abstractmethod
    def initial(self, rates: List[Rate]) -> State:
        """State for a key that has never been used."""

    @abstractmethod
    def step(self, rates: List[Rate], state: State, now: int, weight: int) -> Tuple[State, Decision]:
        """Apply an arrival of ``weight`` at ``now``.

        Returns the state to persist and the verdict. On denial it must return
        ``state`` unchanged: a rejected request spends nothing, under any rate.
        """

    def decode(self, values: Sequence[str]) -> State:
        """Parse persisted strings back into state."""
        return tuple(float(value) for value in values)

    def consumed(self, rates: List[Rate], state: State, now: int) -> int:
        """Units currently owed - the closest analogue to a log's length."""
        return 0

    def redis_script(self) -> Optional[str]:
        """Lua implementing ``step()`` atomically, if this policy has one."""
        return None

    def redis_args(self, rates: List[Rate]) -> List[Union[int, float]]:
        """Arguments ``redis_script()`` needs, after the standard header.

        The store passes these through without inspecting them, so a policy's
        script and its arguments stay a matched pair that only the policy knows
        the shape of. The header the store supplies first is
        ``now, weight, ttl_ms, len(rates)``.
        """
        return []


class GCRA(StateAlgorithm):
    """Generic Cell Rate Algorithm - a leaky bucket kept as one timestamp.

    Tracks a theoretical arrival time (TAT) per rate: the moment the bucket
    would next be empty. Admitting ``weight`` pushes the TAT forward by
    ``weight * emission_interval``; the request is allowed while that stays
    within ``burst`` units of ``now``.

    Sustains ``limit`` per ``interval`` while tolerating a burst of
    ``rate.burst``, using one number per rate instead of an entry per unit.

    State is integer *microseconds*, not fractional milliseconds. An absolute
    TAT in epoch ms is ~1.7e12, and accumulating a fractional emission interval
    onto it loses the low bits - enough that the accumulated sum of `burst`
    emissions no longer equals `burst * emission`, and the last unit of a full
    burst gets rejected by a rounding error. Integers make it exact, and stay
    well inside the 2**53 a Lua double holds.
    """

    @staticmethod
    def _emission_us(rate: Rate) -> int:
        """Microseconds per unit.

        Rounded up, so a rate that does not divide evenly errs on the strict
        side rather than admitting marginally faster than configured.
        """
        return max(1, ceil(rate.interval * 1000 / rate.limit))

    def initial(self, rates: List[Rate]) -> State:
        # 0 reads as "long past", so step() clamps it up to `now`.
        return tuple(0 for _ in rates)

    def max_weight(self, rate: Rate) -> int:
        return rate.burst

    def step(self, rates: List[Rate], state: State, now: int, weight: int) -> Tuple[State, Decision]:
        now_us = now * 1000
        advanced = []

        for rate, tat in zip(rates, state, strict=True):
            if weight > rate.burst:
                # Never admissible; no wait to report.
                return state, Decision(failing_rate=rate)

            emission = self._emission_us(rate)
            new_tat = max(int(tat), now_us) + weight * emission
            allow_at = new_tat - rate.burst * emission

            if allow_at > now_us:
                return state, Decision(failing_rate=rate, retry_after_ms=ceil((allow_at - now_us) / 1000))

            advanced.append(new_tat)

        # Committed only here, so a rate failing late costs the earlier ones
        # nothing.
        return tuple(advanced), ADMITTED

    def consumed(self, rates: List[Rate], state: State, now: int) -> int:
        now_us = now * 1000
        units = 0

        for rate, tat in zip(rates, state, strict=True):
            emission = self._emission_us(rate)
            units = max(units, ceil(max(0, int(tat) - now_us) / emission))

        return units

    def decode(self, values: Sequence[str]) -> State:
        return tuple(int(value) for value in values)

    def redis_script(self) -> Optional[str]:
        return _GCRA_LUA

    def redis_args(self, rates: List[Rate]) -> List[Union[int, float]]:
        return [value for rate in rates for value in (self._emission_us(rate), rate.burst)]


class TokenBucket(GCRA):
    """Token bucket, which is GCRA under a more familiar name.

    A bucket of ``rate.burst`` tokens refilling at ``rate.limit / rate.interval``
    admits exactly what GCRA does with an emission interval of
    ``interval / limit``. Same implementation, one float of state rather than a
    token count plus a refill timestamp.
    """


_GCRA_LUA = """
local key = KEYS[1]
-- Microseconds throughout, mirroring GCRA.step: integers stay exact in a Lua
-- double up to 2**53, which epoch-us (~1.7e15) sits comfortably below.
local now_us = tonumber(ARGV[1]) * 1000
local weight = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local n = tonumber(ARGV[4])

local fields = {}
for i = 1, n do
    fields[i] = 'tat' .. i
end

local stored = redis.call('HMGET', key, unpack(fields))
local advanced = {}

for i = 1, n do
    local offset = (i - 1) * 2
    local emission = tonumber(ARGV[5 + offset])
    local burst = tonumber(ARGV[5 + offset + 1])

    if weight > burst then
        return {i - 1, -1}
    end

    local tat = now_us
    if stored[i] then
        local parsed = tonumber(stored[i])
        if parsed and parsed > now_us then
            tat = parsed
        end
    end

    local new_tat = tat + weight * emission
    local allow_at = new_tat - burst * emission

    if allow_at > now_us then
        return {i - 1, math.ceil((allow_at - now_us) / 1000)}
    end

    advanced[i] = new_tat
end

-- Reached only when every rate admits, so the write is all-or-nothing.
local write = {}
for i = 1, n do
    write[#write + 1] = 'tat' .. i
    -- %.0f, not tostring: Lua's default number formatting is 14 significant
    -- digits, which would mangle an integer this large.
    write[#write + 1] = string.format('%.0f', advanced[i])
end

redis.call('HSET', key, unpack(write))
redis.call('PEXPIRE', key, ttl)
return {-1, 0}
"""
