""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from queue import Queue
from threading import RLock
from typing import List
from typing import Tuple

from .exceptions import InvalidParams


class AbstractBucket(ABC):
    """Documentation for AbstractBucket"""

    def __init__(self, maxsize=0, **_kwargs):
        self._maxsize = maxsize

    def maxsize(self) -> int:
        """Return the maximum size of the bucket,
        ie the maxinum number of item this bucket can hold
        """
        return self._maxsize

    @abstractmethod
    def size(self) -> int:
        """Return the current size of the bucket,
        ie the count of all items currently in the bucket
        """

    @abstractmethod
    def put(self, item: float) -> int:
        """Put an item (typically the current time) in the bucket
        Return 1 if successful, else 0
        """

    @abstractmethod
    def get(self, number: int) -> float:
        """Get items and remove them from the bucket in the FIFO fashion
        Return the number of items that have been removed
        """

    @abstractmethod
    def all_items(self) -> List[float]:
        """Return a list as copies of all items in the bucket"""

    def inspect_expired_items(self, time: float) -> Tuple[int, float]:
        """Find how many items in bucket that have slipped out of the time-window"""
        volume = self.size()
        item_count, remaining_time = 0, 0.0

        for log_idx, log_item in enumerate(self.all_items()):
            if log_item > time:
                item_count = volume - log_idx
                remaining_time = log_item - time
                break

        return item_count, remaining_time


class MemoryQueueBucket(AbstractBucket):
    """A bucket that resides in memory
    using python's built-in Queue class
    """

    def __init__(self, maxsize=0, **_kwargs):
        super().__init__()
        self._q = Queue(maxsize=maxsize)

    def size(self):
        return self._q.qsize()

    def put(self, item):
        return self._q.put(item)

    def get(self, number):
        counter = 0
        for _ in range(number):
            self._q.get()
            counter += 1

        return counter

    def all_items(self):
        return list(self._q.queue)


class MemoryListBucket(AbstractBucket):
    """A bucket that resides in memory
    using python's List
    """

    def __init__(self, maxsize=0, **_kwargs):
        super().__init__(maxsize=maxsize)
        self._q = []
        self._lock = RLock()

    def size(self):
        return len(self._q)

    def put(self, item):
        with self._lock:
            if self.size() < self.maxsize():
                self._q.append(item)
                return 1
            return 0

    def get(self, number):
        with self._lock:
            counter = 0
            for _ in range(number):
                self._q.pop(0)
                counter += 1

            return counter

    def all_items(self):
        return self._q.copy()


class RedisBucket(AbstractBucket):
    """A bucket with Redis
    using List
    """

    def __init__(
        self,
        maxsize=0,
        redis_pool=None,
        bucket_name: str = None,
        identity: str = None,
        **_kwargs,
    ):
        super().__init__(maxsize=maxsize)

        if not bucket_name or not isinstance(bucket_name, str):
            msg = "keyword argument bucket-name is missing: a distict name is required"
            raise InvalidParams(msg)

        self._pool = redis_pool
        self._bucket_name = f"{bucket_name}___{identity}"

    def get_connection(self):
        """Obtain a connection from redis pool"""
        from redis import Redis  # type: ignore

        return Redis(connection_pool=self._pool)

    def get_pipeline(self):
        """Using redis pipeline for batch operation"""
        conn = self.get_connection()
        pipeline = conn.pipeline()
        return pipeline

    def size(self):
        conn = self.get_connection()
        return conn.llen(self._bucket_name)

    def put(self, item):
        conn = self.get_connection()
        current_size = conn.llen(self._bucket_name)

        if current_size < self.maxsize():
            conn.rpush(self._bucket_name, item)
            return 1

        return 0

    def get(self, number):
        pipeline = self.get_pipeline()
        counter = 0

        for _ in range(number):
            pipeline.lpop(self._bucket_name)
            counter += 1

        pipeline.execute()
        return counter

    def all_items(self):
        conn = self.get_connection()
        items = conn.lrange(self._bucket_name, 0, -1)
        return sorted([float(i.decode("utf-8")) for i in items])


class RedisClusterBucket(RedisBucket):
    """A bucket with RedisCluster"""

    def get_connection(self):
        """Obtain a connection from redis pool"""
        from rediscluster import RedisCluster  # pylint: disable=import-outside-toplevel

        return RedisCluster(connection_pool=self._pool)
