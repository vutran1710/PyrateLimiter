# Migrating to PyrateLimiter 4.0

This guide covers the breaking changes when upgrading from PyrateLimiter 3.x to 4.0.

## Quick Summary

Version 4.0 simplifies the API by:
- Removing exception-based flow control in favor of blocking behavior
- Simplifying the decorator API
- Adding proper async support with `try_acquire_async`
- Moving clock responsibility from Limiter to Bucket
- Adding context manager support

## Breaking Changes

### 1. try_acquire is Now Blocking by Default

This is the most significant change. Previously, `try_acquire` would raise `BucketFullException` when the rate limit was exceeded. Now it blocks until a permit is available.

**v3.x:**
```python
from pyrate_limiter import BucketFullException

try:
    limiter.try_acquire("item")
except BucketFullException as e:
    print(f"Rate limited: {e.meta_info}")
```

**v4.0:**
```python
# Blocking (default) - waits until permit is available
limiter.try_acquire("item")  # blocks until success when called without a timeout

# Non-blocking - returns immediately with False if bucket is full
success = limiter.try_acquire("item", blocking=False)
if not success:
    print("Rate limited")
```

New `try_acquire` signature:
```python
def try_acquire(
    name: str = "pyrate",
    weight: int = 1,
    blocking: bool = True,    # NEW: wait for permit
    timeout: int = -1         # NEW: max wait time (used only by try_acquire_async)
) -> bool
```

### 2. Use try_acquire_async for Async Code

For async code, use the new `try_acquire_async` method which uses `asyncio.Lock` and `asyncio.sleep`:

**v3.x:**
```python
# v3.x used try_acquire for both sync and async
result = await limiter.try_acquire("item")
```

**v4.0:**
```python
# Use try_acquire_async for proper async behavior
success = await limiter.try_acquire_async("item")

# With timeout (in seconds)
success = await limiter.try_acquire_async("item", timeout=5)
if not success:
    print("Timed out waiting for permit")

# Non-blocking async
success = await limiter.try_acquire_async("item", blocking=False)
```

### 3. Decorator API Simplified

The decorator no longer requires a mapping function. Pass `name` and `weight` directly.

**v3.x:**
```python
decorator = limiter.as_decorator()

def mapping(*args, **kwargs):
    return ("item_name", 1)  # (name, weight) tuple

@decorator(mapping)
def my_function():
    pass

@decorator(mapping)
async def my_async_function():
    pass
```

**v4.0:**
```python
@limiter.as_decorator(name="item_name", weight=1)
def my_function():
    pass

@limiter.as_decorator(name="item_name", weight=1)
async def my_async_function():
    pass
```

### 4. Exception Classes Removed

`BucketFullException` and `LimiterDelayException` have been removed entirely. Use `blocking=False` to get non-blocking behavior.

**v3.x:**
```python
from pyrate_limiter import BucketFullException, LimiterDelayException

try:
    limiter.try_acquire("item")
except BucketFullException as e:
    handle_rate_limit(e.meta_info)
except LimiterDelayException as e:
    handle_delay_exceeded(e.meta_info)
```

**v4.0:**
```python
success = limiter.try_acquire("item", blocking=False)
if not success:
    handle_rate_limit()
```

### 5. Limiter Constructor Simplified

**v3.x:**
```python
limiter = Limiter(
    bucket,
    clock=TimeClock(),
    raise_when_fail=True,
    max_delay=5000,
    retry_until_max_delay=True,
)
```

**v4.0:**
```python
limiter = Limiter(
    bucket,
    buffer_ms=50,  # optional, default 50ms
)
```

Removed parameters:
- `clock` - each bucket now manages its own clock via `bucket.now()`
- `raise_when_fail` - no exceptions are raised; use `blocking=False`
- `max_delay` - blocking is controlled per-call via `blocking` parameter
- `retry_until_max_delay` - blocking mode retries automatically

### 6. BucketFactory Changes

If you implement a custom `BucketFactory`, remove the clock parameter from `schedule_leak` and `create` calls.

**v3.x:**
```python
class MyFactory(BucketFactory):
    def __init__(self, clock):
        self.clock = clock

    def wrap_item(self, name, weight=1):
        return RateItem(name, self.clock.now(), weight=weight)

bucket = factory.create(clock, InMemoryBucket, rates)
factory.schedule_leak(bucket, clock)
```

**v4.0:**
```python
class MyFactory(BucketFactory):
    def wrap_item(self, name, weight=1):
        return RateItem(name, self.bucket.now(), weight=weight)

bucket = factory.create(InMemoryBucket, rates)
factory.schedule_leak(bucket)
```

### 7. Clock Changes

*Most users won't need to change anything here - clocks are now managed internally by buckets.*

If you explicitly used clock classes:
- `TimeClock` removed - buckets use `MonotonicClock` by default
- `SQLiteClock` removed - buckets manage their own time
- `TimeAsyncClock` renamed to `MonotonicAsyncClock`

## New Features

### Context Manager Support

```python
with Limiter(bucket) as limiter:
    limiter.try_acquire("item")
# Resources automatically cleaned up
```

### limiter_factory Module

Convenience functions for common patterns:

```python
from pyrate_limiter import limiter_factory, Duration

limiter = limiter_factory.create_inmemory_limiter(
    rate_per_duration=5,
    duration=Duration.SECOND,
)

limiter = limiter_factory.create_sqlite_limiter(
    rate_per_duration=100,
    duration=Duration.MINUTE,
    db_path="/path/to/db.sqlite",
)
```

### Web Request Helpers

```python
from pyrate_limiter.extras.aiohttp_limiter import RateLimitedSession
from pyrate_limiter.extras.httpx_limiter import RateLimiterTransport
from pyrate_limiter.extras.requests_limiter import RateLimitedRequestsSession
```

### MultiprocessBucket

```python
from pyrate_limiter import MultiprocessBucket

bucket = MultiprocessBucket(rates, manager)
```
