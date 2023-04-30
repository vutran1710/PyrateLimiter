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
    rates: List[Rate]
    lock: Lock
    bucket_key: str

    def __init__(self, redis: Redis, bucket_key: str):
        self.lock = Lock()
        self.redis = redis
        self.bucket_key = bucket_key

    def put(self, item: RateItem):
        """Add item to key"""
        with self.lock:
            self.redis.execute_command(
                "EVAL",
                LuaScript.PUT_ITEM,
                0,  # No key
                self.bucket_key,
                item.timestamp,
                item.name,
                item.weight,
            )

    def leak(self, clock: Optional[SyncClock] = None) -> int:
        assert clock
        return 1

    def flush(self):
        with self.lock:
            self.redis.delete(self.bucket_key)
