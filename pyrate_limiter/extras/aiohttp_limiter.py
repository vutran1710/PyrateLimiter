import logging

import aiohttp

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimitedSession:
    """
    A thin wrapper around :class:`aiohttp.ClientSession` that enforces
    rate limits using a provided :class:`~pyrate_limiter.Limiter`.

    Each request acquires a token from the limiter before delegating to
    the underlying ``aiohttp`` session.
    """

    def __init__(self, limiter: Limiter, name: str = "pyrate", **kwargs):
        """
        Initialize a new rate-limited session.

        Parameters
        ----------
        limiter : :class:`~pyrate_limiter.Limiter`
            Limiter used to control request rate.
        name : str, optional
            Token/key used by the limiter to bucket this session's requests.
        **kwargs
            Additional keyword arguments passed to
            :class:`aiohttp.ClientSession`.
        """
        self._limiter = limiter
        self._session = aiohttp.ClientSession(**kwargs)
        self.name = name

    async def get(self, *a, **k):
        """
        Perform a GET request after acquiring from the limiter.

        Parameters
        ----------
        *a, **k
            Arguments forwarded to :meth:`aiohttp.ClientSession.get`.

        Returns
        -------
        :class:`aiohttp.ClientResponse`
            The response object from the request.
        """
        await self._limiter.try_acquire_async(self.name)
        return await self._session.get(*a, **k)

    async def post(self, *a, **k):
        """
        Perform a POST request after acquiring from the limiter.

        Parameters
        ----------
        *a, **k
            Arguments forwarded to :meth:`aiohttp.ClientSession.post`.

        Returns
        -------
        :class:`aiohttp.ClientResponse`
            The response object from the request.
        """
        await self._limiter.try_acquire_async(self.name)
        return await self._session.post(*a, **k)

    async def __aenter__(self):
        """
        Enter the async context manager, returning the session itself.

        Returns
        -------
        RateLimitedSession
            The current session instance.
        """
        return self

    async def __aexit__(self, *exc):
        """
        Exit the async context manager and close the underlying session.

        Parameters
        ----------
        *exc
            Exception information, if any, from the context block.
        """
        await self._session.close()
