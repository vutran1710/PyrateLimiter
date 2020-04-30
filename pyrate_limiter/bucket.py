""" Implement this class to create
a workable bucket for Limiter to use
"""
from typing import List
from abc import ABC, abstractmethod
from queue import Queue
from threading import RLock


class AbstractBucket(ABC):
    """Documentation for AbstractBucket

    """
    def __init__(self, maxsize=0):
        self._maxsize = maxsize

    def maxsize(self) -> int:
        """ Return the maximum size of the bucket,
        ie the maxinum number of item this bucket can hold
        """
        return self._maxsize

    @abstractmethod
    def size(self) -> int:
        """ Return the current size of the bucket,
        ie the count of all items currently in the bucket
        """

    @abstractmethod
    def put(self, item) -> int:
        """ Putting an item in the bucket
        Return 1 if successful, else 0
        """

    @abstractmethod
    def get(self, number: int) -> int:
        """ Get items and remove them from the bucket in the FIFO fashion
        Return the number of items that have been removed
        """

    @abstractmethod
    def all_items(self) -> List[int]:
        """ Return a list as copies of all items in the bucket
        """


class MemoryQueueBucket(AbstractBucket):
    """ A bucket that resides in memory
    using python's built-in Queue class
    """
    def __init__(self, maxsize=0):
        super(MemoryQueueBucket, self).__init__()
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
    """ A bucket that resides in memory
    using python's List
    """
    def __init__(self, maxsize=0):
        super(MemoryListBucket, self).__init__(maxsize=maxsize)
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
