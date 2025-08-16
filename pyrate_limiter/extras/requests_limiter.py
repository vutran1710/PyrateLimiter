import logging

import requests

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimitedRequestsSession:
    def __init__(self, limiter: Limiter, name: str = __name__, **kwargs):
        self._limiter = limiter
        self._session = requests.Session(**kwargs)
        self._name = name

    def get(self, *a, **k):
        self._limiter.try_acquire(self._name)
        return self._session.get(*a, **k)

    def post(self, *a, **k):
        self._limiter.try_acquire(self._name)
        return self._session.post(*a, **k)

    def close(self):
        self._session.close()
