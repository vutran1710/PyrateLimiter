from enum import Enum
from .exceptions import ImmutableClassProperty


class ResetTypes(Enum):
    SCHEDULED = 1
    INTERVAL = 2


class RequestRate:
    def __init__(
        self,
        limit,
        interval,
        reset: ResetTypes = ResetTypes.INTERVAL,
    ):
        self._limit = limit
        self._interval = interval
        self._reset = reset
        self._log = {}

    @property
    def limit(self):
        return self._limit

    @limit.setter
    def limit(self, _):
        raise ImmutableClassProperty(self, 'limit')

    @property
    def interval(self):
        return self._interval

    @interval.setter
    def interval(self, _):
        raise ImmutableClassProperty(self, 'interval')

    def __str__(self):
        return f'{self.limit}/{self.interval}'
