from threading import RLock as Lock
from typing import List
from typing import Optional

from redis import Redis

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..utils import id_generator


class LuaScript:
    """Scripts that deal with bucket operations"""

    PUT_ITEM = """
    local now = ARGV[1]
    local space_required = tonumber(ARGV[2])
    local bucket = ARGV[3]
    local item_name = ARGV[4]

    for idx, key in ipairs(KEYS) do
        if idx > 4 then
            local interval = tonumber(key)
            local limit = tonumber(ARGV[idx])
            local count = redis.call('ZCOUNT', bucket, now - interval, now)
            local space_available = limit - tonumber(count)
            if space_available < space_required then
                return idx - 5
            end
        end
    end

    for i=1,space_required do
        redis.call('ZADD', bucket, now, item_name..i)
    end
    return -1
    """


class RedisSyncBucket(AbstractBucket):
    """A bucket using redis for storing data
    - We are not using redis' built-in TIME since it is non-deterministic
    - In distributed context, use local server time, but beware of
    the consistency between server instances
    - Each bucket instance use a dedicated connection to avoid race-condition
    """

    rates: List[Rate]
    failing_rate: Optional[Rate]
    lock: Lock
    bucket_key: str
    script_hash: str

    def __init__(
        self,
        rates: List[Rate],
        redis: Redis,
        bucket_key: str,
        script_hash: Optional[str] = None,
    ):
        self.rates = rates
        self.lock = Lock()
        self.redis = redis
        self.bucket_key = bucket_key
        self.script_hash = script_hash or self.redis.script_load(LuaScript.PUT_ITEM)

    def count_bucket(self) -> int:
        """Count all items in the bucket"""
        return self.redis.zcount(self.bucket_key, 0, float("+inf"))

    def _check_and_insert(self, item: RateItem) -> Optional[Rate]:
        keys = [
            "timestamp",
            "weight",
            "bucket",
            "name",
            *[rate.interval for rate in self.rates],
        ]

        args = [
            item.timestamp,
            item.weight,
            self.bucket_key,
            # this is to avoid key collision since we are using ZSET
            f"{item.name}:{id_generator()}:",
            *[rate.limit for rate in self.rates],
        ]

        idx = self.redis.evalsha(self.script_hash, len(keys), *keys, *args)

        if idx < 0:
            return None

        return self.rates[idx]

    def put(self, item: RateItem) -> bool:
        """Add item to key"""
        with self.lock:
            self.failing_rate = self._check_and_insert(item)
            return not bool(self.failing_rate)

    def leak(self, current_timestamp: Optional[int] = None) -> int:
        assert current_timestamp is not None
        with self.lock:
            remove_count = self.redis.zremrangebyscore(
                self.bucket_key,
                0,
                current_timestamp - self.rates[-1].interval - 1,
            )
            return remove_count

    def flush(self):
        with self.lock:
            self.redis.delete(self.bucket_key)
