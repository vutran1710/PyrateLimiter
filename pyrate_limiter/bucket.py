""" Implement this class to create
a workable bucket for Limiter to use
"""
from typing import List
from abc import ABC, abstractmethod


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
