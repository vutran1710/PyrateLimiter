"""Redis-backed store for constant-state algorithms."""

from __future__ import annotations

from inspect import isawaitable
from math import ceil
from typing import TYPE_CHECKING, Awaitable, Dict, List, Optional, Union

from ..abstracts.algorithm import ADMITTED, Decision, State, StateAlgorithm
from ..abstracts.rate import Rate
from ..abstracts.store import StateStore
from ..clocks import WallClock

if TYPE_CHECKING:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis


class RedisStateStore(StateStore):
    """One Redis hash per key, holding a few floats however much traffic passes.

    This is where the constant-state algorithms pay off: a sorted-set log grows
    with every consumed unit and must be trimmed, while this stays the same size
    and expires on its own.

    The transition runs as Lua so the read-modify-write is atomic across
    clients. Works with either a sync or an async redis client.
    """

    #: Unknown until the client is seen; the Leaker probes. ``leak()`` on
    #: ``StateBucket`` is a sync no-op either way.
    is_async = None

    #: State is shared between machines, where a monotonic clock is meaningless.
    default_clock = WallClock()

    def __init__(
        self,
        redis: Union["Redis", "AsyncRedis"],
        key: str,
        ttl_ms: Optional[int] = None,
    ):
        self.redis = redis
        self.key = key
        self._ttl_ms = ttl_ms
        self._scripts: Dict[str, object] = {}

    def _script(self, algorithm: StateAlgorithm):
        """Registered script for this policy, cached by its source.

        ``register_script`` reloads on NOSCRIPT by itself, so a restarted or
        failed-over Redis needs no special handling here.
        """
        lua = algorithm.redis_script()

        if lua is None:
            raise TypeError(f"{type(algorithm).__name__} has no Redis implementation; use a local store instead")

        script = self._scripts.get(lua)

        if script is None:
            script = self.redis.register_script(lua)
            self._scripts[lua] = script

        return script

    def _ttl_for(self, rates: List[Rate]) -> int:
        """How long the state stays meaningful.

        State matters until the bucket has fully drained, which takes at most
        ``burst * interval / limit``. Doubled, so an expiry never truncates a
        window still in use.
        """
        if self._ttl_ms is not None:
            return self._ttl_ms

        return max(ceil(2 * rate.burst * rate.interval / rate.limit) for rate in rates)

    def check(self, algorithm, rates, now, weight):
        # Header, then whatever the policy's own script expects. The store never
        # inspects the tail, so script and arguments stay a matched pair owned
        # by the algorithm rather than a GCRA-shaped layout baked in here.
        args: List[Union[int, float]] = [now, weight, self._ttl_for(rates), len(rates)]
        args.extend(algorithm.redis_args(rates))

        reply = self._script(algorithm)(keys=[self.key], args=args, client=self.redis)

        if isawaitable(reply):

            async def _await_decision() -> Decision:
                return self._decision(rates, await reply)

            return _await_decision()

        return self._decision(rates, reply)

    @staticmethod
    def _decision(rates: List[Rate], reply) -> Decision:
        index, retry_after = int(reply[0]), int(reply[1])

        if index < 0:
            return ADMITTED

        rate = rates[index]

        # Negative retry means the weight exceeds the burst and never fits.
        return Decision(failing_rate=rate) if retry_after < 0 else Decision(failing_rate=rate, retry_after_ms=retry_after)

    def read(self, algorithm, rates):
        fields = [f"tat{index + 1}" for index in range(len(rates))]
        stored = self.redis.hmget(self.key, fields)

        if isawaitable(stored):

            async def _await_state() -> State:
                return self._parse(algorithm, rates, await stored)

            return _await_state()

        return self._parse(algorithm, rates, stored)

    @staticmethod
    def _parse(algorithm: StateAlgorithm, rates: List[Rate], stored) -> State:
        if not stored or any(value is None for value in stored):
            return algorithm.initial(rates)

        # The algorithm decodes: it knows whether its numbers are integers.
        return algorithm.decode([value.decode() if isinstance(value, bytes) else value for value in stored])

    def reset(self) -> Union[None, Awaitable[None]]:
        deleted = self.redis.delete(self.key)

        if isawaitable(deleted):

            async def _await_reset() -> None:
                await deleted

            return _await_reset()

        # StateStore.reset() is contracted to None; don't leak DEL's count.
        return None
