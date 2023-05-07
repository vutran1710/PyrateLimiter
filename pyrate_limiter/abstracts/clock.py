from abc import ABC
from abc import abstractmethod
from typing import Coroutine
from typing import Union


class Clock(ABC):
    """Clock that return timestamp for `now`"""

    @abstractmethod
    def now(self) -> Union[int, Coroutine[None, None, int]]:
        """Get time as of now, in miliseconds"""
