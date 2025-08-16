import logging

import aiohttp

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimitedSession:
    """Use this in place of a aiohttp.ClientSession"""

    def __init__(self, limiter: Limiter, name: str = __name__, **kwargs):
        self._limiter = limiter
        self._session = aiohttp.ClientSession(**kwargs)
        self.name = name

    async def get(self, *a, **k):
        await self._limiter.try_acquire_async(self.name)
        return await self._session.get(*a, **k)

    async def post(self, *a, **k):
        await self._limiter.try_acquire_async(self.name)
        return await self._session.post(*a, **k)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._session.close()
