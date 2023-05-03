""" Implement this class to create
a workable bucket for Limiter to use
"""
from abc import ABC
from abc import abstractmethod
from typing import List
from typing import Optional
from typing import Union

from .rate import Rate
from .rate import RateItem


class AbstractBucket(ABC):
    """Base bucket `SYNCHRONOUS` interface"""

    rates: List[Rate]
    failing_rate: Optional[Rate]

    @abstractmethod
    def put(self, item: RateItem) -> bool:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    def leak(self, current_timestamp: Optional[int] = None) -> int:
        """Schedule a leak and run in a task"""

    @abstractmethod
    def flush(self) -> None:
        """Flush the whole bucket"""


class AbstractAsyncBucket(ABC):
    """Base bucket `ASYNCHRONOUS` interface"""

    rates: List[Rate]
    failing_rate: Optional[Rate]

    @abstractmethod
    async def put(self, item: RateItem) -> bool:
        """Put an item (typically the current time) in the bucket"""

    @abstractmethod
    async def leak(self, current_timestamp: Optional[int] = None) -> int:
        """Schedule a leak and run in a task"""

    @abstractmethod
    async def flush(self) -> None:
        """Flush the whole bucket"""


class BucketFactory(ABC):
    """Asbtract BucketFactory class
    User must implement this class should
    he wants to use a custom bucket backend
    """

    @abstractmethod
    def get(self, item: RateItem) -> Union[AbstractBucket, AbstractAsyncBucket]:
        """Create or get the corresponding bucket to this item"""

    @abstractmethod
    def leak(self) -> None:
        """Leak all the buckets"""
