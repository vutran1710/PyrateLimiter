"""Background leak workers must stop before their owned resources are closed."""

import asyncio
from threading import Event, Thread

import pytest

from pyrate_limiter import Duration, InMemoryBucket, Limiter, Rate, SingleBucketFactory
from pyrate_limiter.abstracts.bucket import Leaker


def start_call(function):
    done = Event()
    errors = []

    def call():
        try:
            function()
        except BaseException as error:
            errors.append(error)
        finally:
            done.set()

    thread = Thread(target=call, daemon=True)
    thread.start()
    return thread, done, errors


def test_close_before_worker_enters_run(monkeypatch):
    entered, proceed = Event(), Event()
    errors = []
    original_run = Leaker._run

    def delayed_run(leaker):
        entered.set()
        assert proceed.wait(3)
        try:
            original_run(leaker)
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(Leaker, "_run", delayed_run)
    limiter = Limiter(InMemoryBucket([Rate(1, Duration.SECOND)]))
    leaker = limiter.bucket_factory._leaker
    worker = leaker._thread
    assert entered.wait(3)
    closer, done, close_errors = start_call(limiter.close)
    try:
        # Let close request shutdown while the worker has not entered _run.
        assert leaker._stop_event.wait(3)
    finally:
        proceed.set()
        closer.join(3)
        worker.join(3)
    assert done.is_set()
    assert not worker.is_alive()
    assert not errors
    assert not close_errors


def test_close_wakes_idle_worker(monkeypatch):
    sleeping = Event()
    original_sleep = asyncio.sleep

    async def long_sleep(delay):
        sleeping.set()
        await original_sleep(60)

    monkeypatch.setattr("pyrate_limiter.abstracts.bucket.asyncio.sleep", long_sleep)
    limiter = Limiter(InMemoryBucket([Rate(1, Duration.SECOND)]))
    worker = limiter.bucket_factory._leaker._thread
    assert sleeping.wait(3)
    limiter.close()
    assert not worker.is_alive()
    limiter.close()


def test_close_waits_for_inflight_leak_before_closing_bucket():
    entered, proceed, closed = Event(), Event(), Event()
    calls = []

    class Bucket(InMemoryBucket):
        def leak(self, current_timestamp):
            calls.append("leak-start")
            entered.set()
            assert proceed.wait(3)
            calls.append("leak-end")
            return super().leak(current_timestamp)

        def close(self):
            calls.append("bucket-close")
            closed.set()

    limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
    worker = limiter.bucket_factory._leaker._thread
    assert entered.wait(3)
    closer, done, errors = start_call(limiter.close)
    try:
        closed_while_leaking = closed.wait(0.1)
    finally:
        proceed.set()
        closer.join(3)
        worker.join(3)
    assert done.is_set()
    assert not errors
    assert not closed_while_leaking
    assert calls == ["leak-start", "leak-end", "bucket-close"]
    assert not worker.is_alive()


def test_close_cancels_an_awaited_clock(monkeypatch):
    entered = Event()
    pending = []
    errors = []
    original_run = Leaker._run

    class Bucket(InMemoryBucket):
        async def now(self):
            pending.append((asyncio.get_running_loop(), asyncio.current_task()))
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                # A clock may finish gracefully when cancellation is requested.
                pass
            return 0

        def leak(self, current_timestamp):
            raise AssertionError("clock completed after shutdown; do not leak")

    def captured_run(leaker):
        try:
            original_run(leaker)
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(Leaker, "_run", captured_run)
    limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
    worker = limiter.bucket_factory._leaker._thread
    assert entered.wait(3)
    try:
        limiter.close()
        assert not worker.is_alive()
        assert not errors
    finally:
        if worker.is_alive():
            loop, task = pending[0]
            loop.call_soon_threadsafe(task.cancel)
            worker.join(3)


def test_concurrent_close_from_worker_callback_does_not_deadlock():
    entered, proceed, callback_done = Event(), Event(), Event()
    worker_errors = []
    limiter = None

    class Bucket(InMemoryBucket):
        def leak(self, current_timestamp):
            entered.set()
            assert proceed.wait(3)
            try:
                limiter.close()
            except BaseException as error:
                worker_errors.append(error)
            callback_done.set()
            return super().leak(current_timestamp)

    limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
    leaker = limiter.bucket_factory._leaker
    worker = leaker._thread
    assert entered.wait(3)
    closer, done, close_errors = start_call(limiter.close)
    try:
        assert leaker._stop_event.wait(3)
    finally:
        proceed.set()
        closer.join(3)
        worker.join(3)
    assert callback_done.is_set()
    assert done.is_set()
    assert not worker.is_alive()
    assert not worker_errors
    assert not close_errors


def test_worker_close_stops_remaining_bucket_callbacks():
    entered, proceed = Event(), Event()
    calls = []
    leaker = Leaker(60_000)

    class ClosingBucket(InMemoryBucket):
        def leak(self, current_timestamp):
            entered.set()
            assert proceed.wait(3)
            leaker.close()
            calls.append("first")
            return 0

    class NextBucket(InMemoryBucket):
        def leak(self, current_timestamp):
            calls.append("second")
            return 0

    leaker.register(ClosingBucket([Rate(1, Duration.SECOND)]))
    leaker.register(NextBucket([Rate(1, Duration.SECOND)]))
    leaker.start()
    worker = leaker._thread
    assert entered.wait(3)
    proceed.set()
    worker.join(3)
    assert not worker.is_alive()
    assert calls == ["first"]


def test_leaker_can_restart_after_close():
    leaker = Leaker(60_000)
    calls = []
    leaked = Event()

    class Bucket(InMemoryBucket):
        def leak(self, current_timestamp):
            calls.append(id(self))
            leaked.set()
            return 0

    for _ in range(2):
        leaked.clear()
        bucket = Bucket([Rate(1, Duration.SECOND)])
        leaker.register(bucket)
        leaker.start()
        assert leaked.wait(3)
        leaker.close()
        assert not leaker.is_alive()
        assert not leaker.sync_buckets
        assert calls[-1] == id(bucket)
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("from_thread", [False, True])
async def test_close_requests_async_worker_cancellation(from_thread):
    entered = asyncio.Event()

    class Bucket(InMemoryBucket):
        is_async = True

        async def leak(self, current_timestamp):
            entered.set()
            await asyncio.Event().wait()
            return 0

    limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
    task = limiter.bucket_factory._leaker.aio_leak_task
    await asyncio.wait_for(entered.wait(), 3)
    if from_thread:
        await asyncio.to_thread(limiter.close)
    else:
        limiter.close()
    try:
        await asyncio.wait_for(asyncio.shield(task), 0.2)
    except asyncio.CancelledError:
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    assert task.cancelled()


@pytest.mark.asyncio
async def test_async_leaker_can_restart_after_close():
    leaker = Leaker(60_000)
    entered = asyncio.Event()

    class Bucket(InMemoryBucket):
        is_async = True

        async def leak(self, current_timestamp):
            entered.set()
            await asyncio.Event().wait()
            return 0

    for _ in range(2):
        entered.clear()
        leaker.register(Bucket([Rate(1, Duration.SECOND)]))
        leaker.leak_async()
        task = leaker.aio_leak_task
        await asyncio.wait_for(entered.wait(), 3)
        leaker.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not leaker.async_buckets


@pytest.mark.asyncio
async def test_dispose_before_async_start_does_not_leak_replacement_twice():
    calls = []

    class Bucket(InMemoryBucket):
        is_async = True

        async def leak(self, current_timestamp):
            calls.append(id(self))
            return 0

    first = Bucket([Rate(1, Duration.SECOND)])
    replacement = Bucket([Rate(1, Duration.SECOND)])
    factory = SingleBucketFactory(first)
    old_task = factory._leaker.aio_leak_task
    assert factory.dispose(first)
    factory.schedule_leak(replacement)
    new_task = factory._leaker.aio_leak_task
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert calls == [id(replacement)]
    finally:
        factory.close()
        for task in (old_task, new_task):
            task.cancel()
        await asyncio.gather(old_task, new_task, return_exceptions=True)


@pytest.mark.parametrize("completed", [False, True])
def test_close_after_async_loop_has_closed(completed):
    loop = asyncio.new_event_loop()
    closed = []

    class Bucket(InMemoryBucket):
        is_async = True

        async def leak(self, current_timestamp):
            await asyncio.Event().wait()
            return 0

        def close(self):
            closed.append(self)

    async def setup():
        limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
        task = limiter.bucket_factory._leaker.aio_leak_task
        await asyncio.sleep(0)
        if completed:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return limiter, task

    limiter, task = loop.run_until_complete(setup())
    loop.close()
    try:
        limiter.close()
        assert len(closed) == 1
    finally:
        # The deliberately closed loop cannot finalize a pending coroutine.
        task._log_destroy_pending = False
        task.get_coro().close()


def test_close_when_async_loop_closes_during_cancellation(monkeypatch):
    loop = asyncio.new_event_loop()
    closed = []

    class Bucket(InMemoryBucket):
        is_async = True

        async def leak(self, current_timestamp):
            await asyncio.Event().wait()
            return 0

        def close(self):
            closed.append(self)

    async def setup():
        limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
        await asyncio.sleep(0)
        return limiter, limiter.bucket_factory._leaker.aio_leak_task

    limiter, task = loop.run_until_complete(setup())
    schedule = loop.call_soon_threadsafe

    def close_before_schedule(callback):
        loop.close()
        return schedule(callback)

    monkeypatch.setattr(loop, "call_soon_threadsafe", close_before_schedule)
    try:
        limiter.close()
        assert len(closed) == 1
    finally:
        loop.close()
        task._log_destroy_pending = False
        task.get_coro().close()


def test_unrelated_clock_cancellation_is_not_suppressed(monkeypatch):
    errors = []
    original_run = Leaker._run

    class Bucket(InMemoryBucket):
        async def now(self):
            raise asyncio.CancelledError

    def captured_run(leaker):
        try:
            original_run(leaker)
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(Leaker, "_run", captured_run)
    limiter = Limiter(Bucket([Rate(1, Duration.SECOND)]))
    worker = limiter.bucket_factory._leaker._thread
    worker.join(3)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], asyncio.CancelledError)
    limiter.close()
