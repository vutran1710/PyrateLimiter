""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC, abstractmethod
from typing import List, Type

from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket interface"""

    @abstractmethod
    def put(self, item: RateItem) -> None:
        """Put an item (typically the current time) in the bucket
        """

    @abstractmethod
    def load(self) -> List[RateItem]:
        """Return a list as copies of all items in the bucket"""

    @abstractmethod
    def flush(self) -> None:
        """Flush/reset bucket"""


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def get(self, item: RateItem) -> Type[AbstractBucket]:
        """Init or get the corresponding bucket to this item"""
