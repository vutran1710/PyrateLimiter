from abc import ABC
from abc import abstractmethod


class AbstractClock(ABC):
    """Clock that return timestamp for `now`"""

    @abstractmethod
    def now(self) -> int:
        """Get time as of now, in miliseconds"""
