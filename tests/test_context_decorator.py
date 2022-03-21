"""Test LimitContextDecorator with all relevant combinations of:
* Async + synchronous
* Decorator + contextmanager
* No delay + delay + delay w/ max_delay
"""
import asyncio
from time import sleep
from time import time
from uuid import uuid4

import pytest

from pyrate_limiter import BucketFullException
from pyrate_limiter import Duration
from pyrate_limiter import Limiter
from pyrate_limiter import RequestRate


def test_ratelimit__synchronous(time_function):
    """Test ratelimit decorator - synchronous version"""
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)

    @limiter.ratelimit(uuid4())
    def limited_function():
        pass

    # If we stay under 10 requests/sec, expect no errors
    for _ in range(12):
        limited_function()
        sleep(0.1)

    sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for _ in range(12):
            limited_function()


def test_ratelimit__delay_synchronous(time_function):
    """Test ratelimit decorator with automatic delays - synchronous version"""
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)

    @limiter.ratelimit(uuid4(), delay=True)
    def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    start = time()
    for _ in range(22):
        limited_function()

    # Exact time will depend on the test environment, but it should be slightly more than 2 seconds
    elapsed = time() - start
    assert 2 < elapsed <= 3


def test_ratelimit__exceeds_max_delay_synchronous(time_function):
    """Test ratelimit decorator with automatic delays - synchronous version"""
    limiter = Limiter(RequestRate(5, Duration.MINUTE), time_function=time_function)

    @limiter.ratelimit(uuid4(), delay=True, max_delay=10)
    def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    with pytest.raises(BucketFullException):
        for _ in range(10):
            limited_function()


def test_ratelimit__contextmanager_synchronous(time_function):
    """Test ratelimit decorator with contextmanager - synchronous version
    Aside from using __enter__ and __exit__, all behavior is identical to the decorator version,
    so this only needs one test case
    """
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)
    identity = uuid4()

    def limited_function():
        with limiter.ratelimit(identity):
            pass

    # If we stay under 10 requests/sec, expect no errors
    for _ in range(12):
        limited_function()
        sleep(0.1)

    sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    with pytest.raises(BucketFullException):
        for _ in range(12):
            limited_function()


@pytest.mark.asyncio
async def test_ratelimit__async(time_function):
    """Test ratelimit decorator - async version"""
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)

    @limiter.ratelimit(uuid4())
    async def limited_function():
        pass

    # If we stay under 10 requests/sec, expect no errors
    for _ in range(12):
        await limited_function()
        await asyncio.sleep(0.2)

    await asyncio.sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    tasks = [limited_function() for _ in range(12)]
    with pytest.raises(BucketFullException):
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_ratelimit__delay_async(time_function):
    """Test ratelimit decorator with automatic delays - async version"""
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)

    @limiter.ratelimit(uuid4(), delay=True)
    async def limited_function():
        pass

    # This should insert appropriate delays to stay within the rate limit
    tasks = [limited_function() for _ in range(22)]
    start = time()
    await asyncio.gather(*tasks)

    # Exact time will depend on the test environment, but it should be slightly more than 2 seconds
    elapsed = time() - start
    assert 2 < elapsed <= 3


@pytest.mark.asyncio
async def test_ratelimit__exceeds_max_delay_async(time_function):
    """Test ratelimit decorator with automatic delays - async version"""
    limiter = Limiter(RequestRate(5, Duration.MINUTE), time_function=time_function)

    @limiter.ratelimit(uuid4(), delay=True, max_delay=10)
    async def limited_function():
        pass

    # This should exceed the rate limit, with a delay above max_delay, and raise an error
    tasks = [limited_function() for _ in range(10)]
    with pytest.raises(BucketFullException):
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_ratelimit__contextmanager_async(time_function):
    """Test ratelimit decorator with contextmanager - async version
    Aside from using __aenter__ and __aexit__, all behavior is identical to the decorator version,
    so this only needs one test case
    """
    limiter = Limiter(RequestRate(10, Duration.SECOND), time_function=time_function)
    identity = uuid4()

    async def limited_function():
        async with limiter.ratelimit(identity):
            pass

    # If we stay under 10 requests/sec, expect no errors
    for _ in range(12):
        await limited_function()
        await asyncio.sleep(0.1)

    await asyncio.sleep(1)

    # If we exceed 10 requests/sec, expect an exception
    tasks = [limited_function() for _ in range(12)]
    with pytest.raises(BucketFullException):
        await asyncio.gather(*tasks)
