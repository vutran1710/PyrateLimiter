# ruff: noqa: T201
"""
Example of using pyrate_limiter with httpx.

"""

import logging

from httpx import AsyncHTTPTransport, HTTPTransport, Request, Response

from pyrate_limiter import Limiter, limiter_factory

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger.setLevel(logging.DEBUG)


class RateLimiterTransport(HTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    def handle_request(self, request: Request, **kwargs) -> Response:
        # using a constant string for item name means that the same
        # rate is applied to all requests.
        self.limiter.try_acquire("httpx_ratelimiter")

        logger.debug("Acquired")
        return super().handle_request(request, **kwargs)


class AsyncRateLimiterTransport(AsyncHTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    async def handle_async_request(self, request: Request, **kwargs) -> Response:
        await self.limiter.try_acquire_async("httpx_ratelimiter")

        logger.debug("Acquired")
        response = await super().handle_async_request(request, **kwargs)

        return response


# Example below


def fetch(start_time: int):
    import httpx

    url = "https://httpbin.org/get"

    assert limiter_factory.LIMITER is not None

    with httpx.Client(transport=RateLimiterTransport(limiter=limiter_factory.LIMITER)) as client:
        client.get(url)


def singleprocess_example():
    import os
    import time

    import httpx

    from pyrate_limiter import Duration, limiter_factory

    start_time = time.time()

    url = "https://httpbin.org/get"
    limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=1, duration=Duration.SECOND)
    transport = RateLimiterTransport(limiter=limiter)
    with httpx.Client(transport=transport) as client:
        for _ in range(10):
            response = client.get(url)
            print(f"{round(time.time() - start_time, 2)}s-{os.getpid()}: {response.json()}")


def asyncio_example():
    import asyncio
    import time

    import httpx

    from pyrate_limiter import Duration, limiter_factory

    url = "https://httpbin.org/get"

    async def ticker():
        """loops and prints time, showing the eventloop isn't blocked"""
        while True:
            print(f"[TICK] {time.time()}")
            await asyncio.sleep(1)

    async def afetch(client: httpx.AsyncClient, start_time: int):
        await client.get(url)

    async def example():
        limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=1, duration=Duration.SECOND)
        transport = AsyncRateLimiterTransport(limiter=limiter)
        client = httpx.AsyncClient(transport=transport)

        tasks = [afetch(client, url) for _ in range(10)]

        asyncio.create_task(ticker())
        results = await asyncio.gather(*tasks)

        await client.aclose()
        return results

    asyncio.run(example())


def multiprocess_example():
    import time
    from concurrent.futures import ProcessPoolExecutor, wait

    from pyrate_limiter import Duration, MultiprocessBucket, Rate

    rate = Rate(1, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    start_time = time.time()
    with ProcessPoolExecutor(initializer=limiter_factory.init_global_limiter, initargs=(bucket,)) as executor:
        futures = [executor.submit(fetch, start_time) for _ in range(10)]
        wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception:
            logger.exception("Task raised")


if __name__ == "__main__":
    print("Single Process example: 10 requests")
    singleprocess_example()

    print("Multiprocessing example: 10 requests")
    multiprocess_example()

    print("Asyncio example: 10 requests")
    asyncio_example()
