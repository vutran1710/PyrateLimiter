import logging

from httpx import AsyncHTTPTransport, HTTPTransport, Request, Response

from pyrate_limiter import Limiter

logger = logging.getLogger(__name__)


class RateLimiterTransport(HTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    def handle_request(self, request: Request, **kwargs) -> Response:
        # using a constant string for item name means that the same
        # rate is applied to all requests.
        while not self.limiter.try_acquire(__name__):
            logger.debug("Lock acquisition timed out, retrying")

        logger.debug("Acquired lock")
        return super().handle_request(request, **kwargs)


class AsyncRateLimiterTransport(AsyncHTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    async def handle_async_request(self, request: Request, **kwargs) -> Response:
        while not await self.limiter.try_acquire_async(__name__):
            logger.debug("Lock acquisition timed out, retrying")

        logger.debug("Acquired lock")
        response = await super().handle_async_request(request, **kwargs)

        return response
