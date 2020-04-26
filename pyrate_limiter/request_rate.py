from enum import Enum
from .exceptions import ImmutableClassProperty


class ResetTypes(Enum):
    SCHEDULED = 1
    INTERVAL = 2


class RequestRate:
    def __init__(self,
                 limit,
                 interval,
                 reset: ResetTypes = ResetTypes.INTERVAL):
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

    def valid_rate(
        self,
        identity,
        total_reqs: int,
        now: int,
    ):
        last_req = self._log.get(identity)

        if not last_req:
            return True

        elapsed = now - last_req

        if total_reqs < self._limit:
            return True

        if total_reqs >= self._limit and elapsed <= self._interval:
            return False

        return False

    def log_now(
        self,
        identity,
        time,
    ):
        last_req = self._log.get(identity, 0)

        if time - last_req > self._interval:
            self._log[identity] = time
