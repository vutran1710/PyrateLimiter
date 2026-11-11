"""A leak that raises must not stop the leaker from leaking its buckets."""

import asyncio
from threading import Event

import pytest

from pyrate_limiter import Duration, InMemoryBucket, Rate
from pyrate_limiter.abstracts.bucket import Leaker


class CountingBucket(InMemoryBucket):
    """Counts leaks; with ``fail_first`` its first leak raises, as a backend does when its
    connection drops."""

    def __init__(self, fail_first=False):
        super().__init__([Rate(5, Duration.SECOND)])
        self.fail_first = fail_first
        self.calls = 0
        self.leaked_after_failure = Event()

    def leak(self, current_timestamp=None):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise ConnectionError("connection dropped")
        if self.calls > 1:
            self.leaked_after_failure.set()
        return super().leak(current_timestamp)


class AsyncCountingBucket(CountingBucket):
    is_async = True

    async def now(self):
        return super().now()

    async def leak(self, current_timestamp=None):
        return CountingBucket.leak(self, current_timestamp)


async def wait_until(event, task=None):
    for _ in range(300):
        if event.is_set() or (task is not None and task.done()):
            break
        await asyncio.sleep(0.01)
    return event.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("bucket_class", [CountingBucket, AsyncCountingBucket])
async def test_leaker_keeps_leaking_after_a_failed_leak(bucket_class, caplog):
    failing, healthy = bucket_class(fail_first=True), bucket_class()
    leaker = Leaker(10)
    leaker.register(failing)
    leaker.register(healthy)
    if bucket_class.is_async:
        leaker.leak_async()
        task = leaker.aio_leak_task
    else:
        leaker.start()
        task = None
    try:
        assert await wait_until(failing.leaked_after_failure, task)
        assert await wait_until(healthy.leaked_after_failure, task)
        assert leaker.is_alive() if task is None else not task.done()
    finally:
        leaker.close()
    assert "ConnectionError: connection dropped" in caplog.text


@pytest.mark.asyncio
async def test_runtime_error_still_stops_the_leaker():
    """RuntimeError is how the event loop's shutdown reaches the leak loop."""

    class ClosedLoopBucket(AsyncCountingBucket):
        async def leak(self, current_timestamp=None):
            raise RuntimeError("Event loop is closed")

    leaker = Leaker(10)
    leaker.register(ClosedLoopBucket())
    leaker.leak_async()
    task = leaker.aio_leak_task
    try:
        await asyncio.wait_for(task, 3)
        assert task.exception() is None
    finally:
        leaker.close()


@pytest.mark.asyncio
async def test_cancelling_the_leaker_during_a_leak_stops_it():
    """CancelledError is a BaseException, so the per-bucket handler must let it through."""
    entered = asyncio.Event()

    class BlockingBucket(AsyncCountingBucket):
        async def leak(self, current_timestamp=None):
            entered.set()
            await asyncio.sleep(60)

    leaker = Leaker(10)
    leaker.register(BlockingBucket())
    leaker.leak_async()
    task = leaker.aio_leak_task
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait({task}, timeout=3)
        assert task.cancelled()
    finally:
        leaker.close()
