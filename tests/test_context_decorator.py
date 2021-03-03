"""Test LimitContextDecorator with all relevant combinations of:
* Async + synchronous
* Decorator + contextmanager
* No delay + delay + delay w/ max_delay
"""
import asyncio
from logging import getLogger
from time import sleep
from uuid import uuid4

import pytest

from pyrate_limiter import BucketFullException, Duration, Limiter, RequestRate

# Make log messages visible on test failure (or with pytest -s)
getLogger("pyrate_limiter").setLevel("DEBUG")


def test_ratelimit__synchronous():
    """ Test ratelimit decorator - synchronous version """
    limiter = Limiter(RequestRate(10, Duration.SECOND))

    @limiter.ratelimit(uuid4())
    def limited_function():
        pass

    # If we stay under 10 requests/sec, expect no errors
    for i in range(12):
        limited_function()
        sleep(0.1)

    sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(12):
            limited_function()


def test_ratelimit__delay_synchronous():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(10, Duration.SECOND))

    @limiter.ratelimit(uuid4(), delay=True)
    def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    for i in range(12):
        limited_function()


def test_ratelimit__exceeds_max_delay_synchronous():
    """ Test ratelimit decorator with automatic delays - synchronous version """
    limiter = Limiter(RequestRate(5, Duration.MINUTE))

    @limiter.ratelimit(uuid4(), delay=True, max_delay=10)
    def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    with pytest.raises(BucketFullException):
        for i in range(10):
            limited_function()


def test_ratelimit__contextmanager_synchronous():
    """Test ratelimit decorator with contextmanager - synchronous version
    Aside from using __enter__ and __exit__, all behavior is identical to the decorator version,
    so this only needs one test case
    """
    limiter = Limiter(RequestRate(10, Duration.SECOND))
    identity = uuid4()

    def limited_function():
        with limiter.ratelimit(identity):
            pass

    # If we stay under 10 requests/sec, expect no errors
    for i in range(12):
        limited_function()
        sleep(0.1)

    sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(12):
            limited_function()


@pytest.mark.asyncio
async def test_ratelimit__async():
    """ Test ratelimit decorator - async version """
    limiter = Limiter(RequestRate(10, Duration.SECOND))

    @limiter.ratelimit(uuid4())
    async def limited_function():
        pass

    # If we stay under 10 requests/sec, expect no errors
    for i in range(12):
        await limited_function()
        await asyncio.sleep(0.1)

    await asyncio.sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(12):
            await limited_function()


@pytest.mark.asyncio
async def test_ratelimit__delay_async():
    """ Test ratelimit decorator with automatic delays - async version """
    limiter = Limiter(RequestRate(10, Duration.SECOND))

    @limiter.ratelimit(uuid4(), delay=True)
    async def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    for i in range(12):
        await limited_function()


@pytest.mark.asyncio
async def test_ratelimit__exceeds_max_delay_async():
    """ Test ratelimit decorator with automatic delays - async version """
    limiter = Limiter(RequestRate(5, Duration.MINUTE))

    @limiter.ratelimit(uuid4(), delay=True, max_delay=10)
    async def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    with pytest.raises(BucketFullException):
        for i in range(10):
            await limited_function()


@pytest.mark.asyncio
async def test_ratelimit__contextmanager_async():
    """Test ratelimit decorator with contextmanager - async version
    Aside from using __aenter__ and __aexit__, all behavior is identical to the decorator version,
    so this only needs one test case
    """
    limiter = Limiter(RequestRate(10, Duration.SECOND))
    identity = uuid4()

    async def limited_function():
        async with limiter.ratelimit(identity):
            pass

    # If we stay under 10 requests/sec, expect no errors
    for i in range(12):
        await limited_function()
        await asyncio.sleep(0.1)

    await asyncio.sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for i in range(12):
            await limited_function()
