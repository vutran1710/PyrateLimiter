import logging

from httpx2 import AsyncHTTPTransport, HTTPTransport, Request, Response

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimiterTransport(HTTPTransport):
    """
    A synchronous HTTPX2 transport that enforces a rate limit
    via a provided :class:`~pyrate_limiter.Limiter`.

    All requests share the same limiter item key, so the same
    rate limit is applied globally across requests.
    """

    def __init__(self, limiter: Limiter, **kwargs):
        """
        Initialize the transport.

        Parameters
        ----------
        limiter : :class:`~pyrate_limiter.Limiter`
            Limiter used to control request rate.
        **kwargs
            Additional keyword arguments passed to
            :class:`httpx2.HTTPTransport`.
        """
        super().__init__(**kwargs)
        self.limiter = limiter

    def handle_request(self, request: Request, **kwargs) -> Response:
        """
        Handle a synchronous HTTP request after acquiring from the limiter.

        The limiter is polled until a permit is acquired; all requests
        share the same limiter key.

        Parameters
        ----------
        request : :class:`httpx2.Request`
            The request to send.
        **kwargs
            Forwarded to :meth:`httpx2.HTTPTransport.handle_request`.

        Returns
        -------
        :class:`httpx2.Response`
            The HTTP response.
        """
        self.limiter.try_acquire(__name__)

        logger.debug("Acquired lock")
        return super().handle_request(request, **kwargs)


class AsyncRateLimiterTransport(AsyncHTTPTransport):
    """
    An asynchronous HTTPX2 transport that enforces a rate limit
    via a provided :class:`~pyrate_limiter.Limiter`.

    All requests share the same limiter item key, so the same
    rate limit is applied globally across requests.
    """

    def __init__(self, limiter: Limiter, **kwargs):
        """
        Initialize the transport.

        Parameters
        ----------
        limiter : :class:`~pyrate_limiter.Limiter`
            Limiter used to control request rate.
        **kwargs
            Additional keyword arguments passed to
            :class:`httpx2.AsyncHTTPTransport`.
        """
        super().__init__(**kwargs)
        self.limiter = limiter

    async def handle_async_request(self, request: Request, **kwargs) -> Response:
        """
        Handle an asynchronous HTTP request after acquiring from the limiter.

        The limiter is polled until a permit is acquired; all requests
        share the same limiter key.

        Parameters
        ----------
        request : :class:`httpx2.Request`
            The request to send.
        **kwargs
            Forwarded to :meth:`httpx2.AsyncHTTPTransport.handle_async_request`.

        Returns
        -------
        :class:`httpx2.Response`
            The HTTP response.
        """
        await self.limiter.try_acquire_async(__name__)

        logger.debug("Acquired lock")
        response = await super().handle_async_request(request, **kwargs)

        return response
