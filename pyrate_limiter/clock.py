from abc import ABC
from abc import abstractmethod


class SyncClock(ABC):
    """Synchronous Clock"""

    @abstractmethod
    def now(self) -> int:
        """Get time as of now, in miliseconds"""


class AsyncClock(ABC):
    """Asynchronous Clock"""

    @abstractmethod
    async def now(self) -> int:
        """Get time as of now, in miliseconds"""
