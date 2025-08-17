# ruff: noqa: T201, G004
"""
Example of using pyrate_limiter with requests.
"""

import logging
import time

from pyrate_limiter import Duration, limiter_factory
from pyrate_limiter.extras.requests_limiter import RateLimitedRequestsSession

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger.setLevel(logging.DEBUG)


def test_requests():
    url = "https://httpbin.org/get"
    limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=2, duration=Duration.SECOND)

    session = RateLimitedRequestsSession(limiter)
    start = time.time()
    for i in range(10):
        logger.info(f"Request {i} at {round(time.time() - start, 2)}s")
        resp = session.get(url)
        logger.info(f"Response {i}: {resp.status_code}")
    session.close()


if __name__ == "__main__":
    test_requests()
