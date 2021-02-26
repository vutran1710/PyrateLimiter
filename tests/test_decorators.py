import asyncio
import pytest
from logging import basicConfig
from time import sleep

from pyrate_limiter import (
    BucketFullException,
    Duration,
    RequestRate,
    Limiter,
)

# Make log messages visible on test failure (or with pytest -s)
basicConfig(level='INFO')


def test_ratelimit__synchronous():
    """ Test ratelimit decorator - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.SECOND))

    @limiter.ratelimit('identity_1')
    def limited_function():
        pass

    # If we stay under 5 requests/sec, expect no errors
    for i in range(6):
        limited_function()
        sleep(0.5)

    sleep(1)

    # If we exceed 5 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(6):
            limited_function()


def test_ratelimit__delay_synchronous():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.SECOND))

    @limiter.ratelimit('identity_1', delay=True)
    def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    for i in range(10):
        limited_function()


def test_ratelimit__exceeds_max_delay_synchronous():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.MINUTE))

    @limiter.ratelimit('identity_1', delay=True, max_delay=10)
    def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    with pytest.raises(BucketFullException):
        for i in range(10):
            limited_function()


@pytest.mark.asyncio
async def test_ratelimit__async():
    """ Test ratelimit decorator - async version """
    limiter = Limiter(RequestRate(5, Duration.SECOND))

    @limiter.ratelimit('identity_2')
    async def limited_function():
        pass

    # If we stay under 5 requests/sec, expect no errors
    for i in range(6):
        await limited_function()
        await asyncio.sleep(0.5)

    await asyncio.sleep(1)

    # If we exceed 5 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(6):
            await limited_function()


@pytest.mark.asyncio
async def test_ratelimit__delay_async():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.SECOND))

    @limiter.ratelimit('identity_1', delay=True)
    async def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    for i in range(10):
        await limited_function()


@pytest.mark.asyncio
async def test_ratelimit__exceeds_max_delay_async():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.MINUTE))

    @limiter.ratelimit('identity_1', delay=True, max_delay=10)
    async def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    with pytest.raises(BucketFullException):
        for i in range(10):
            await limited_function()
