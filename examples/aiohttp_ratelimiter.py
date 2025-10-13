# ruff: noqa: T201, G004
"""
Example of using pyrate_limiter with aiohttp.
"""

import asyncio
import logging
import time

from pyrate_limiter import Duration, limiter_factory
from pyrate_limiter.extras.aiohttp_limiter import RateLimitedSession

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger.setLevel(logging.DEBUG)


async def test_aiohttp():
    url = "https://httpbin.org/get"
    limiter = limiter_factory.create_inmemory_limiter(
        rate_per_duration=3,
        duration=Duration.SECOND,
    )
    async with RateLimitedSession(limiter) as session:

        async def wrapped(i):
            logger.info(f"Request {i} at {round(time.time(), 2)}")
            resp = await session.get(url)
            logger.info(f"Response {i} at {round(time.time(), 2)}: {resp.status}")
            return resp

        await asyncio.gather(*(wrapped(i) for i in range(10)))


if __name__ == "__main__":
    asyncio.run(test_aiohttp())
