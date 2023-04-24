""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from typing import Dict
from typing import List
from typing import Type
from typing import Union

from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket `SYNCHRONOUS` interface"""

    @abstractmethod
    def put(self, item: RateItem) -> None:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    def load(self) -> List[RateItem]:
        """Return a list as copies of all items in the bucket"""


class AbstractAsyncBucket(ABC):
    """Base bucket `ASYNCHRONOUS` interface"""

    @abstractmethod
    async def put(self, item: RateItem) -> None:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    async def load(self) -> List[RateItem]:
        """Return a list as copies of all items in the bucket"""


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def get(self, item: RateItem) -> Union[Type[AbstractBucket], Type[AbstractAsyncBucket]]:
        """Init or get the corresponding bucket to this item"""


# Default implementation of Bucket, in-memory list
class SimpleListBucket(AbstractBucket):
    def __init__(self):
        self.items = []

    def put(self, item: RateItem) -> None:
        self.items.append(item)

    def load(self) -> List[RateItem]:
        return self.items.copy()


class DefaultBucketFactory(BucketFactory):
    buckets: Dict[str, SimpleListBucket]

    def __init__(self):
        self.buckets = dict()

    def get(self, item: RateItem) -> SimpleListBucket:
        if item.name not in self.buckets:
            bucket = SimpleListBucket()
            self.buckets.update({item.name: bucket})

        return self.buckets.get(item.name)
