"""Bucket implementation using Redis"""

from __future__ import annotations

from inspect import isawaitable
from time import time_ns
from typing import TYPE_CHECKING, Awaitable, List, Optional, Tuple, Union

from ..abstracts import AbstractBucket, Rate, RateItem
from ..abstracts.algorithm import ADMITTED, Decision, LogAlgorithm
from ..utils import id_generator

if TYPE_CHECKING:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis


class LuaScript:
    """Scripts that deal with bucket operations"""

    PUT_ITEM = """
    local bucket = KEYS[1]
    local now = ARGV[1]
    local space_required = tonumber(ARGV[2])
    local item_name = ARGV[3]
    local rates_count = tonumber(ARGV[4])

    -- Per rate the client supplies (window_start, limit, blocking_rank); the
    -- window bounds and rank come from the algorithm, so this script stays
    -- policy-agnostic. blocking_rank < 0 means "resolve no entry".
    for i=1,rates_count do
        local offset = (i - 1) * 3
        local window_start = tonumber(ARGV[5 + offset])
        local limit = tonumber(ARGV[5 + offset + 1])
        local blocking_rank = tonumber(ARGV[5 + offset + 2])
        local count = redis.call('ZCOUNT', bucket, window_start, now)
        local space_available = limit - tonumber(count)
        if space_available < space_required then
            local blocking_timestamp = -1

            if blocking_rank >= 0 then
                local blocking = redis.call('ZRANGE', bucket, -1 - blocking_rank, -1 - blocking_rank, 'WITHSCORES')
                if blocking[2] then
                    blocking_timestamp = tonumber(blocking[2])
                end
            end

            return {i - 1, blocking_timestamp}
        end
    end

    local batch = {}
    -- Each member adds two unpacked arguments; 1000 stays below Lua 5.1 limits.
    local batch_size = 1000

    for i=1,space_required do
        batch[#batch + 1] = now
        batch[#batch + 1] = item_name..i

        if #batch == batch_size * 2 then
            redis.call('ZADD', bucket, unpack(batch))
            batch = {}
        end
    end

    if #batch > 0 then
        redis.call('ZADD', bucket, unpack(batch))
    end

    return {-1, -1}
    """


class RedisBucket(AbstractBucket):
    """A bucket using redis for storing data
    - We are not using redis' built-in TIME since it is non-deterministic
    - In distributed context, use local server time or a remote time server
    - Each bucket instance use a dedicated connection to avoid race-condition
    - can be either sync or async
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    bucket_key: str
    script_hash: str
    redis: Union[Redis, AsyncRedis]

    def __init__(
        self,
        rates: List[Rate],
        redis: Union[Redis, AsyncRedis],
        bucket_key: str,
        script_hash: str,
        algorithm: Optional[LogAlgorithm] = None,
    ):
        if algorithm is not None:
            self._algorithm = algorithm

        self.rates = rates
        self.redis = redis
        self.bucket_key = bucket_key
        self.script_hash = script_hash
        self.failing_rate = None

    def now(self):
        # TODO: Use a Redis time source via a Lua script
        return time_ns() // 1000000

    @classmethod
    def init(
        cls,
        rates: List[Rate],
        redis: Union[Redis, AsyncRedis],
        bucket_key: str,
        algorithm: Optional[LogAlgorithm] = None,
    ):
        script_hash = redis.script_load(LuaScript.PUT_ITEM)

        if isawaitable(script_hash):

            async def _async_init():
                nonlocal script_hash
                script_hash = await script_hash
                return cls(rates, redis, bucket_key, script_hash, algorithm)

            return _async_init()

        return cls(rates, redis, bucket_key, script_hash, algorithm)

    def _check_and_insert(self, item: RateItem) -> Union[Decision, Awaitable[Decision]]:
        """Check-and-insert, returning the full verdict.

        The script returns the blocking timestamp alongside the failing rate, so
        the wait comes from the same atomic evaluation - no second ZRANGE.
        Window bounds and the blocking rank are computed by the algorithm and
        passed in, keeping the script policy-agnostic.
        """
        keys = [self.bucket_key]

        args = [
            item.timestamp,
            item.weight,
            # NOTE: this is to avoid key collision since we are using ZSET
            f"{item.name}:{id_generator()}:",  # noqa: E231
            len(self.rates),
        ]

        for rate in self.rates:
            offset = self._algorithm.blocking_offset(rate, item.weight)
            args.extend(
                (
                    self._algorithm.window_start(rate, item.timestamp),
                    rate.limit,
                    -1 if offset is None else offset,
                )
            )

        reply = self.redis.evalsha(self.script_hash, len(keys), *keys, *args)

        def _handle_sync(returned: List[int]) -> Decision:
            idx, blocking_timestamp = int(returned[0]), int(returned[1])

            if idx < 0:
                return ADMITTED

            rate = self.rates[idx]

            if item.weight > self._algorithm.max_weight(rate):
                # Can never fit; waiting() reports -1 and the limiter gives up.
                return Decision(failing_rate=rate)

            # Any negative reply means "no entry resolved" - either the policy
            # asked for none, or the rank was out of range.
            blocking = blocking_timestamp if blocking_timestamp >= 0 else None

            return Decision(
                failing_rate=rate,
                retry_after_ms=self._algorithm.retry_after(rate, item.timestamp, blocking),
            )

        async def _handle_async(pending: Awaitable[List[int]]) -> Decision:
            return _handle_sync(await pending)

        return _handle_async(reply) if isawaitable(reply) else _handle_sync(reply)

    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Add item to key"""
        decision = self._check_and_insert(item)

        if isawaitable(decision):

            async def _handle_async():
                return self._record(item, await decision)

            return _handle_async()

        assert isinstance(decision, Decision)
        return self._record(item, decision)

    def leak(self, current_timestamp: Optional[int] = None) -> Union[int, Awaitable[int]]:
        assert current_timestamp is not None
        return self.redis.zremrangebyscore(
            self.bucket_key,
            0,
            self._algorithm.leak_bound(self.rates, current_timestamp),
        )

    def flush(self):
        self.failing_rate = None
        self._last_wait = None
        return self.redis.delete(self.bucket_key)

    def count(self):
        return self.redis.zcard(self.bucket_key)

    def peek(self, index: int) -> Union[RateItem, None, Awaitable[Optional[RateItem]]]:
        items = self.redis.zrange(
            self.bucket_key,
            -1 - index,
            -1 - index,
            withscores=True,
            score_cast_func=int,
        )

        if not items:
            return None

        def _handle_items(received_items: List[Tuple[str, int]]):
            if not received_items:
                return None

            item = received_items[0]
            rate_item = RateItem(name=str(item[0]), timestamp=item[1])
            return rate_item

        if isawaitable(items):

            async def _awaiting():
                nonlocal items
                items = await items
                return _handle_items(items)

            return _awaiting()

        assert isinstance(items, list)
        return _handle_items(items)
