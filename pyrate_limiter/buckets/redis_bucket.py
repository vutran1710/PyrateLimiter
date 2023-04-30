from threading import RLock as Lock
from typing import List
from typing import Optional

from redis import Redis

from ..abstracts import AbstractBucket
from ..abstracts import Rate
from ..abstracts import RateItem
from ..abstracts import SyncClock


class LuaScript:
    PUT_ITEM = """
    for i=1,ARGV[4] do redis.call('ZADD', ARGV[1], ARGV[2], ARGV[3]..i); end
    """


class RedisSyncBucket(AbstractBucket):
    """A bucket using redis for storing data
    We are not using redis' built-in TIME since it is non-deterministic
    In distributed context, use local server time, but beware of
    the consistency between server instances
    """

    rates: List[Rate]
    lock: Lock
    bucket_key: str

    def __init__(self, rates: List[Rate], redis: Redis, bucket_key: str):
        self.rates = rates
        self.lock = Lock()
        self.redis = redis
        self.bucket_key = bucket_key

    def _put_item_with_script(self, item: RateItem):
        self.redis.execute_command(
            "EVAL",
            LuaScript.PUT_ITEM,
            0,  # No key
            self.bucket_key,
            item.timestamp,
            item.name,
            item.weight,
        )

    def put(self, item: RateItem):
        """Add item to key"""
        with self.lock:
            self._put_item_with_script(item)

    def leak(self, clock: Optional[SyncClock] = None) -> int:
        assert clock
        return 1

    def flush(self):
        with self.lock:
            self.redis.delete(self.bucket_key)
