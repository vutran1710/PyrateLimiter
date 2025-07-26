"""
Example of using pyrate_limiter with httpx.

"""
import logging

from httpx import AsyncHTTPTransport
from httpx import HTTPTransport
from httpx import Request
from httpx import Response

from pyrate_limiter import AbstractBucket
from pyrate_limiter import Limiter
logger = logging.getLogger(__name__)


class RateLimiterTransport(HTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    def handle_request(self, request: Request, **kwargs) -> Response:
        # using a constant string for item name means that the same
        # rate is applied to all requests.
        acquired = self.limiter.try_acquire("httpx_ratelimiter")
        if not acquired:
            raise RuntimeError("Did not acquire lock")
        logger.debug("Acquired lock")
        return super().handle_request(request, **kwargs)


class AsyncRateLimiterTransport(AsyncHTTPTransport):
    def __init__(self, limiter: Limiter, **kwargs):
        super().__init__(**kwargs)
        self.limiter = limiter

    async def handle_async_request(self, request: Request, **kwargs) -> Response:
        acquired = await self.limiter.try_acquire_async("httpx_ratelimiter")
        if not acquired:
            raise RuntimeError("Did not acquire lock")
        logger.debug("Acquired lock")
        response = await super().handle_async_request(request, **kwargs)

        return response


# Example below

LIMITER = None


def fetch(start_time: int):
    import httpx

    url = "https://httpbin.org/get"

    assert LIMITER is not None

    with httpx.Client(transport=RateLimiterTransport(limiter=LIMITER)) as client:
        client.get(url)


def init_process(bucket: AbstractBucket):
    """Initializes the process by creating a global LIMITER from the pickled
    bucket, which contains the ListProxy and multiprocess.Manager().Lock.
    """

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S"
                        )
    logger.setLevel(logging.DEBUG)

    from pyrate_limiter import Duration

    global LIMITER
    LIMITER = Limiter(bucket, raise_when_fail=False,
                      max_delay=Duration.HOUR, retry_until_max_delay=True)


def multiprocess_example():
    import time
    from concurrent.futures import ProcessPoolExecutor, wait
    from functools import partial
    from pyrate_limiter import Duration, MultiprocessBucket, Rate

    rate = Rate(1, Duration.SECOND)
    bucket = MultiprocessBucket.init([rate])

    start_time = time.time()
    with ProcessPoolExecutor(initializer=partial(init_process, bucket)) as executor:
        futures = [executor.submit(fetch, start_time) for _ in range(10)]
        wait(futures)

    for f in futures:
        try:
            f.result()
        except Exception as e:
            print(f"Task raised: {e}")


def singleprocess_example():
    from pyrate_limiter import limiter_factory, Duration
    import httpx
    import time
    import os

    start_time = time.time()

    url = "https://httpbin.org/get"
    limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=1,
                                                      duration=Duration.SECOND,
                                                      max_delay=Duration.HOUR)
    transport = RateLimiterTransport(limiter=limiter)
    with httpx.Client(transport=transport) as client:
        for _ in range(10):
            response = client.get(url)
            print(f"{round(time.time() - start_time, 2)}s-{os.getpid()}: {response.json()}")


def asyncio_example():
    import asyncio
    import time
    import os
    import httpx
    from pyrate_limiter import limiter_factory, Duration

    async def async_example():
        start_time = time.time()
        url = "https://httpbin.org/get"

        limiter = limiter_factory.create_inmemory_limiter(
            rate_per_duration=1,
            duration=Duration.SECOND,
            max_delay=Duration.HOUR,
            async_wrapper=True
        )

        transport = AsyncRateLimiterTransport(limiter=limiter)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(10):
                response = await client.get(url)
                print(f"{round(time.time() - start_time, 2)}s-{os.getpid()}: {response.json()}")

    asyncio.run(async_example())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S"
                        )
    logger.setLevel(logging.DEBUG)

    print("Single Process example: 10 requests")
    singleprocess_example()

    print("Multiprocessing example: 10 requests")
    multiprocess_example()

    print("Asyncio example: 10 requests")
    asyncio_example()
