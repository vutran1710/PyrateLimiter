"""Bucket implementation using Redis"""

from __future__ import annotations

from inspect import isawaitable
from time import time_ns
from typing import TYPE_CHECKING, Any, Awaitable, Generic, List, Optional, Tuple, TypeVar, Union, cast, overload

from ..abstracts import AbstractBucket, Rate, RateItem
from ..utils import id_generator

if TYPE_CHECKING:
    from redis import Redis
    from redis.asyncio import Redis as AsyncRedis

_RedisType = TypeVar("_RedisType", "Redis", "AsyncRedis")


class LuaScript:
    """Scripts that deal with bucket operations"""

    PUT_ITEM = """
    local bucket = KEYS[1]
    local now = ARGV[1]
    local space_required = tonumber(ARGV[2])
    local item_name = ARGV[3]
    local rates_count = tonumber(ARGV[4])

    for i=1,rates_count do
        local offset = (i - 1) * 2
        local interval = tonumber(ARGV[5 + offset])
        local limit = tonumber(ARGV[5 + offset + 1])
        local count = redis.call('ZCOUNT', bucket, now - interval, now)
        local space_available = limit - tonumber(count)
        if space_available < space_required then
            return i - 1
        end
    end

    for i=1,space_required do
        redis.call('ZADD', bucket, now, item_name..i)
    end
    return -1
    """


class RedisBucket(AbstractBucket[Any], Generic[_RedisType]):
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
    redis: _RedisType

    def __init__(
        self,
        rates: List[Rate],
        redis: _RedisType,
        bucket_key: str,
        script_hash: str,
    ):
        self.rates = rates
        self.redis = redis
        self.bucket_key = bucket_key
        self.script_hash = script_hash
        self.failing_rate = None

    def now(self):
        # TODO: Use a Redis time source via a Lua script
        return time_ns() // 1000000

    @overload
    @classmethod
    def init(cls, rates: List[Rate], redis: Redis, bucket_key: str) -> RedisBucket[Redis]: ...

    @overload
    @classmethod
    def init(cls, rates: List[Rate], redis: AsyncRedis, bucket_key: str) -> Awaitable[RedisBucket[AsyncRedis]]: ...

    @classmethod
    def init(
        cls,
        rates: List[Rate],
        redis: Union[Redis, AsyncRedis],
        bucket_key: str,
    ) -> Union[RedisBucket[Redis], Awaitable[RedisBucket[AsyncRedis]]]:
        script_hash = redis.script_load(LuaScript.PUT_ITEM)

        if isawaitable(script_hash):

            async def _async_init() -> RedisBucket[AsyncRedis]:
                nonlocal script_hash
                script_hash = await script_hash
                return cast("RedisBucket[AsyncRedis]", cls(rates, redis, bucket_key, script_hash))  # type: ignore[arg-type]  # type: 

            return _async_init()

        return cast("RedisBucket[Redis]", cls(rates, redis, bucket_key, script_hash))  # type: ignore[arg-type]

    def _check_and_insert(self, item: RateItem) -> Union[Optional[Rate], Awaitable[Optional[Rate]]]:
        keys = [self.bucket_key]

        args = [
            item.timestamp,
            item.weight,
            # NOTE: this is to avoid key collision since we are using ZSET
            f"{item.name}:{id_generator()}:",  # noqa: E231
            len(self.rates),
            *[value for rate in self.rates for value in (rate.interval, rate.limit)],
        ]

        idx = self.redis.evalsha(self.script_hash, len(keys), *keys, *args)

        def _handle_sync(returned_idx: int):
            assert isinstance(returned_idx, int), "Not int"
            if returned_idx < 0:
                return None

            return self.rates[returned_idx]

        async def _handle_async(returned_idx: Awaitable[int]):
            assert isawaitable(returned_idx), "Not corotine"
            awaited_idx = await returned_idx
            return _handle_sync(awaited_idx)

        return _handle_async(idx) if isawaitable(idx) else _handle_sync(idx)  # type: ignore[return-value]

    @overload
    def put(self: RedisBucket[Redis], item: RateItem) -> bool: ...

    @overload
    def put(self: RedisBucket[AsyncRedis], item: RateItem) -> Awaitable[bool]: ...

    def put(self, item: RateItem) -> Union[bool, Awaitable[bool]]:
        """Add item to key"""
        failing_rate = self._check_and_insert(item)
        if isawaitable(failing_rate):

            async def _handle_async():
                self.failing_rate = await failing_rate
                return not bool(self.failing_rate)

            return _handle_async()

        assert isinstance(failing_rate, Rate) or failing_rate is None
        self.failing_rate = failing_rate
        return not bool(self.failing_rate)

    @overload
    def leak(self: RedisBucket[Redis], current_timestamp: Optional[int] = None) -> int: ...

    @overload
    def leak(self: RedisBucket[AsyncRedis], current_timestamp: Optional[int] = None) -> Awaitable[int]: ...

    def leak(self, current_timestamp: Optional[int] = None) -> Union[int, Awaitable[int]]:
        assert current_timestamp is not None
        return self.redis.zremrangebyscore(
            self.bucket_key,
            0,
            current_timestamp - self.rates[-1].interval,
        )

    @overload
    def flush(self: RedisBucket[Redis]) -> None: ...

    @overload
    def flush(self: RedisBucket[AsyncRedis]) -> Awaitable[None]: ...

    def flush(self) -> Union[None, Awaitable[None]]:
        self.failing_rate = None
        return self.redis.delete(self.bucket_key)

    @overload
    def count(self: RedisBucket[Redis]) -> int: ...

    @overload
    def count(self: RedisBucket[AsyncRedis]) -> Awaitable[int]: ...

    def count(self) -> Union[int, Awaitable[int]]:
        return self.redis.zcard(self.bucket_key)

    @overload
    def peek(self: RedisBucket[Redis], index: int) -> Optional[RateItem]: ...

    @overload
    def peek(self: RedisBucket[AsyncRedis], index: int) -> Awaitable[Optional[RateItem]]: ...

    def peek(self, index: int) -> Union[Optional[RateItem], Awaitable[Optional[RateItem]]]:
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

    @overload
    def waiting(self: RedisBucket[Redis], item: RateItem) -> int: ...

    @overload
    def waiting(self: RedisBucket[AsyncRedis], item: RateItem) -> Awaitable[int]: ...

    def waiting(self, item: RateItem) -> Union[int, Awaitable[int]]:
        return super().waiting(item)
