import hashlib
from threading import RLock as Lock
from typing import List
from typing import Optional

from redis import Redis

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..abstracts import SyncClock
from ..utils import id_generator


class LuaScript:
    """Scripts that deal with bucket operations"""

    CHECK_BEFORE_INSERT = """
    local now = ARGV[1]
    local space_required = tonumber(ARGV[2])
    local bucket = ARGV[3]
    for idx, key in ipairs(KEYS) do
        if idx > 3 then
            local interval = tonumber(key)
            local limit = tonumber(ARGV[idx])
            local count = redis.call('ZCOUNT', bucket, now - interval, now)
            local space_available = limit - tonumber(count)
            if space_available < space_required then
                return idx - 4
            end
        end
    end
    return -1
    """
    PUT_ITEM = """
    for i=1,ARGV[4] do
        redis.call('ZADD', ARGV[1], ARGV[2], ARGV[3]..i)
    end
    """


class RedisSyncBucket(AbstractBucket):
    """A bucket using redis for storing data
    We are not using redis' built-in TIME since it is non-deterministic
    In distributed context, use local server time, but beware of
    the consistency between server instances
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    lock: Lock
    bucket_key: str

    def __init__(self, rates: List[Rate], redis: Redis, bucket_key: str):
        self.rates = rates
        self.lock = Lock()
        self.redis = redis
        self.bucket_key = bucket_key
        self.hasher = hashlib.sha1()

    def _check_before_insert(self, item: RateItem) -> Optional[Rate]:
        keys = [
            "timestamp",
            "weight",
            "bucket",
            *[rate.interval for rate in self.rates],
        ]
        args = [
            item.timestamp,
            item.weight,
            self.bucket_key,
            *[rate.limit for rate in self.rates],
        ]
        idx = self.redis.execute_command("EVAL", LuaScript.CHECK_BEFORE_INSERT, len(keys), *keys, *args)

        if idx < 0:
            return None

        return self.rates[idx]

    def _put_item_with_script(self, item: RateItem):
        self.redis.execute_command(
            "EVAL",
            LuaScript.PUT_ITEM,
            0,  # No key
            self.bucket_key,
            item.timestamp,
            f"{item.name}:{id_generator()}:",  # this is to avoid key collision since we are using ZSET
            item.weight,
        )

    def put(self, item: RateItem) -> bool:
        """Add item to key"""
        with self.lock:
            failing_rate = self._check_before_insert(item)

            if failing_rate:
                self.failing_rate = failing_rate
                return False

            self.failing_rate = None
            self._put_item_with_script(item)
            return True

    def leak(self, clock: Optional[SyncClock] = None) -> int:
        assert clock
        with self.lock:
            remove_count = self.redis.zremrangebyscore(
                self.bucket_key,
                0,
                clock.now() - self.rates[-1].interval,
            )
            return remove_count

    def flush(self):
        with self.lock:
            self.redis.delete(self.bucket_key)
