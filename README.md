<p align="center">
  <img src="https://raw.githubusercontent.com/vutran1710/PyrateLimiter/master/docs/_static/logo.png" alt="PyrateLimiter logo" height="120">
</p>

<h1 align="center">PyrateLimiter</h1>

<p align="center">
  <em>A fast, async-friendly rate limiter for Python — Leaky-Bucket algorithm with pluggable backends.</em>
</p>

<p align="center">
  <a href="https://pypi.org/project/pyrate-limiter"><img src="https://img.shields.io/pypi/v/pyrate-limiter?color=E5484D" alt="PyPI version"></a>
  <a href="https://pypi.org/project/pyrate-limiter"><img src="https://img.shields.io/pypi/pyversions/pyrate-limiter" alt="Python versions"></a>
  <a href="https://pypi.org/project/pyrate-limiter"><img src="https://img.shields.io/pypi/dm/pyrate-limiter?color=blue" alt="Downloads"></a>
  <a href="https://codecov.io/gh/vutran1710/PyrateLimiter"><img src="https://codecov.io/gh/vutran1710/PyrateLimiter/branch/master/graph/badge.svg?token=E0Q0YBSINS" alt="codecov"></a>
  <a href="https://pyratelimiter.readthedocs.io"><img src="https://img.shields.io/readthedocs/pyratelimiter" alt="Docs"></a>
  <a href="https://pypi.org/project/pyrate-limiter"><img src="https://img.shields.io/pypi/l/pyrate-limiter" alt="License"></a>
</p>

<p align="center">
  <b><a href="https://pyratelimiter.readthedocs.io">Documentation</a></b> ·
  <b><a href="#quickstart">Quickstart</a></b> ·
  <b><a href="#backends">Backends</a></b> ·
  <b><a href="https://github.com/vutran1710/PyrateLimiter/blob/master/docs/migrating.md">Migrating from v3</a></b>
</p>

> [!NOTE]
> **Upgrading from v3.x?** The v4 API is simpler and has breaking changes — see the [Migration Guide](https://github.com/vutran1710/PyrateLimiter/blob/master/docs/migrating.md).

---

## Contents

- [Features](#features)
- [Installation](#installation)
- [Quickstart](#quickstart)
- [How it works](#how-it-works)
- [Core concepts](#core-concepts)
- [Defining rates & buckets](#defining-rates--buckets)
- [Everyday usage](#everyday-usage)
  - [Blocking, non-blocking & timeout](#blocking-non-blocking--timeout)
  - [Weight](#weight)
  - [Decorator](#decorator)
  - [Context manager](#context-manager)
  - [asyncio & event loops](#asyncio--event-loops)
- [Backends](#backends)
- [Web request rate limiting](#web-request-rate-limiting)
- [Advanced usage](#advanced-usage)
  - [Custom routing with BucketFactory](#custom-routing-with-bucketfactory)
  - [Custom & distributed clocks](#custom--distributed-clocks)
  - [Leaking](#leaking)
  - [Concurrency](#concurrency)
  - [Custom backends](#custom-backends)
- [Examples](#examples)

## Features

- 🪣 **Leaky-bucket** algorithm — smooth, well-understood rate limiting.
- ⏱️ **Multiple rates at once** — e.g. *5/second* **and** *1000/hour* on the same key.
- 🔑 **Per-key limits** — track different services, users, or resources independently.
- 🧩 **Pluggable backends** — in-memory, SQLite, Redis (sync **and** async), Postgres, and multiprocessing.
- ⚡ **Sync & async** — the same API works in both; async paths never block the event loop.
- 🎀 **Direct calls or decorators** — `limiter.try_acquire(...)` or `@limiter.as_decorator(...)`.
- 🚦 **Blocking or non-blocking** — wait for a permit (with optional timeout) or fail fast.

## Installation

PyrateLimiter requires **Python 3.10+**.

```sh
pip install pyrate-limiter
# or
conda install --channel conda-forge pyrate-limiter
```

Optional backends pull in their own drivers:

```sh
pip install "pyrate-limiter[all]"   # redis + psycopg (Postgres) + filelock
```

## Quickstart

Limit to **5 requests per 2 seconds**:

```python
from pyrate_limiter import Duration, Rate, Limiter

# A Limiter with a single rate, backed by an in-memory bucket
limiter = Limiter(Rate(5, Duration.SECOND * 2))

# Blocking (default): waits until a permit is available
for i in range(6):
    limiter.try_acquire("my-resource")
    print(f"acquired {i}")

# Non-blocking: returns False immediately when the bucket is full
if not limiter.try_acquire("my-resource", blocking=False):
    print("rate limited!")
```

Prefer a one-liner? The `limiter_factory` covers the common cases:

```python
from pyrate_limiter import Duration, limiter_factory

limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=5, duration=Duration.SECOND)
limiter.try_acquire("my-resource")
```

## How it works

```mermaid
flowchart TB
    user([Your application]):::ext
    user -->|"limit a key: try_acquire · try_acquire_async · @as_decorator"| limiter

    subgraph pyrate["PyrateLimiter"]
        direction TB
        limiter["Limiter<br/>public API"]:::api
        factory["BucketFactory<br/>routes each key to its bucket"]:::core
        leaker["Leaker<br/>background cleanup"]:::leak
        clock(["Clock<br/>time source"]):::clk

        limiter --> factory
        factory -->|routes to| backends
        leaker -.->|periodic leak| backends
        backends -->|reads time from| clock

        subgraph backends["Bucket backend — choose one"]
            direction LR
            mem["InMemory"]:::bkt
            sqlite["SQLite"]:::bkt
            redis["Redis<br/>sync · async"]:::bkt
            pg["Postgres"]:::bkt
            mp["Multiprocess"]:::bkt
        end
    end

    classDef api fill:#E5484D,color:#ffffff,stroke:#E5484D;
    classDef core fill:#242A33,color:#ffffff,stroke:#242A33;
    classDef bkt fill:#EEF2F6,color:#242A33,stroke:#CBD5E1;
    classDef clk fill:#ffffff,color:#242A33,stroke:#242A33;
    classDef leak fill:#F2C94C,color:#242A33,stroke:#E0B53C;
    classDef ext fill:#ffffff,color:#242A33,stroke:#9AA5B1;
```

**The bucket analogy** — this library implements the [Leaky Bucket algorithm](https://en.wikipedia.org/wiki/Leaky_bucket):

- A bucket represents a fixed capacity (a service, an API quota, …).
- The bucket *fills* as requests arrive and *leaks* at a constant rate — the permitted request rate.
- When the bucket is **full**, new requests are delayed (blocking) or rejected (non-blocking).

## Core concepts

| Component | Role |
|---|---|
| **`Clock`** | Timestamps incoming items. Only needs `now() -> int` (sync or async). |
| **`Bucket`** | Stores timestamped items; enforces the rates; `leak()`s out expired items. |
| **`BucketFactory`** | Timestamps & routes each item to the right bucket; schedules background leaking. |
| **`Limiter`** | The friendly façade. Sync/async, blocking/non-blocking, direct call or decorator; thread-safe via `RLock` (and `asyncio.Lock` when async). |

For simple cases you only ever touch `Limiter` and `Rate` — the rest is wired up for you.

## Defining rates & buckets

An API might allow *500/hour*, *1000/day*, and *10000/month*. Express each as a `Rate(limit, interval)`:

```python
from pyrate_limiter import Duration, Rate

rates = [
    Rate(500, Duration.HOUR),       # 500 requests per hour
    Rate(1000, Duration.DAY),       # 1000 requests per day
    Rate(10000, Duration.WEEK * 4), # ~10000 requests per month
]
```

> [!IMPORTANT]
> Rates must be **ordered generous-to-tight**: increasing interval, increasing limit, and a non-increasing `limit/interval` ratio. Ill-formed lists raise `ValueError` at construction. Check a list yourself with `validate_rate_list(rates)`.

Pass the rates straight to a `Limiter` (uses an in-memory bucket), or build a specific bucket:

```python
from pyrate_limiter import InMemoryBucket, Limiter

limiter = Limiter(rates)            # shortcut: in-memory bucket
# equivalent to:
limiter = Limiter(InMemoryBucket(rates))

limiter.try_acquire("hello world")
```

See [Backends](#backends) for Redis, SQLite, Postgres, and multiprocessing.

## Everyday usage

### Blocking, non-blocking & timeout

`try_acquire` **blocks by default** until a permit frees up:

```python
from pyrate_limiter import Rate, Limiter, Duration

limiter = Limiter(Rate(3, Duration.SECOND))

for i in range(5):
    limiter.try_acquire("item")     # blocks when the bucket is full
```

Fail fast instead with `blocking=False`:

```python
if not limiter.try_acquire("item", blocking=False):
    print("rate limited!")
```

In async code use `try_acquire_async`, optionally with a `timeout` (seconds):

```python
acquired = await limiter.try_acquire_async("item", timeout=5)
if not acquired:
    print("timed out waiting for a permit")
```

The `buffer_ms` Limiter parameter (default `50`) adds a small slack to absorb clock drift:

```python
from pyrate_limiter import Rate, Duration, InMemoryBucket, Limiter

bucket = InMemoryBucket([Rate(5, Duration.SECOND)])
limiter = Limiter(bucket, buffer_ms=100)
```

### Weight

Items can carry weight (default `1`). An item of weight `W` consumes `W` unit-slots atomically — either all `W` fit or none do:

```text
BigItem(weight=5, name="item") → 5 × item(weight=1, name="item", same timestamp)
```

```python
limiter.try_acquire("the-sun", weight=10)
```

### Decorator

`as_decorator` wraps any sync **or** async function:

```python
from pyrate_limiter import Rate, Duration, Limiter

limiter = Limiter(Rate(5, Duration.SECOND))

@limiter.as_decorator(name="api_call", weight=1)
def handle_something(*args, **kwargs):
    ...

@limiter.as_decorator(name="background_job", weight=2)
async def handle_something_async(*args, **kwargs):
    ...
```

### Context manager

`Limiter` releases its resources (background leak tasks, connections) on exit:

```python
from pyrate_limiter import Rate, Duration, Limiter

with Limiter(Rate(5, Duration.SECOND)) as limiter:
    limiter.try_acquire("item")
# resources released here

# …or close manually
limiter = Limiter(Rate(5, Duration.SECOND))
try:
    limiter.try_acquire("item")
finally:
    limiter.close()
```

### asyncio & event loops

Use `try_acquire_async` so waiting uses `asyncio.sleep` instead of blocking the loop. With a sync bucket, wrap it in `BucketAsyncWrapper`:

```python
from pyrate_limiter import BucketAsyncWrapper, InMemoryBucket, Rate, Duration, Limiter

limiter = Limiter(BucketAsyncWrapper(InMemoryBucket([Rate(5, Duration.SECOND)])))
await limiter.try_acquire_async("item")
```

## Backends

| Backend | Sync | Async | Persistent | Multi-process | Best for |
|---|:---:|:---:|:---:|:---:|---|
| **InMemoryBucket** | ✅ | (wrap) | ❌ | ❌ | single process, fastest |
| **SQLiteBucket** | ✅ | ❌ | ✅ | ✅ (file lock) | persistence / one host, many processes |
| **RedisBucket** | ✅ | ✅ | ✅ | ✅ | distributed across hosts |
| **PostgresBucket** | ✅ | ❌ | ✅ | ✅ | distributed, already on Postgres |
| **MultiprocessBucket** | ✅ | (wrap) | ❌ | ✅ | a single `multiprocessing` pool |
| **BucketAsyncWrapper** | — | ✅ | — | — | make any sync bucket async-safe |

Every bucket takes a `List[Rate]`.

### InMemoryBucket

```python
from pyrate_limiter import InMemoryBucket, Rate, Duration

bucket = InMemoryBucket([Rate(5, Duration.MINUTE * 2)])
```

### RedisBucket

Stores items in a sorted set (key = item name, score = timestamp). Use the `init` classmethod — it works for sync **and** async clients (just `await` it for async):

```python
from pyrate_limiter import RedisBucket, Rate, Duration

rates = [Rate(5, Duration.MINUTE * 2)]

# sync
from redis import ConnectionPool, Redis
redis_db = Redis(connection_pool=ConnectionPool.from_url("redis://localhost:6379"))
bucket = RedisBucket.init(rates, redis_db, "bucket-key")

# async
from redis.asyncio import ConnectionPool as AsyncPool, Redis as AsyncRedis
redis_db = AsyncRedis(connection_pool=AsyncPool.from_url("redis://localhost:6379"))
bucket = await RedisBucket.init(rates, redis_db, "bucket-key")
```

RedisBucket stores one sorted-set member per consumed unit for exact sliding-window checks. For high-volume, long-window limits such as daily or monthly quotas, the retained sorted set can grow large; use shorter windows or a coarser counter-based backend if predictable memory and latency are more important than exact per-item history.

### SQLiteBucket

Persists state to SQLite (sync only):

```python
from pyrate_limiter import SQLiteBucket, Rate, Duration, Limiter

rate = Rate(5, Duration.MINUTE)
# set use_file_lock=True to share one DB file across processes on a host
bucket = SQLiteBucket.init_from_file([rate], use_file_lock=False)
limiter = Limiter(bucket)
```

`init_from_file(rates, table="rate_bucket", db_path=None, create_new_table=True, use_file_lock=False)` — `db_path=None` uses a temp file; `use_file_lock=True` uses [`filelock`](https://pypi.org/project/filelock/) for multi-process access on a single host.

### PostgresBucket

Requires `psycopg[pool]` (install via the `[all]` extra). Sync only. Use the built-in `PostgresClock`, or a custom time source:

```python
from pyrate_limiter import PostgresBucket, Rate, PostgresClock
from psycopg_pool import ConnectionPool

pool = ConnectionPool("postgresql://postgres:postgres@localhost:5432")
bucket = PostgresBucket(pool, "my_bucket_table", [Rate(3, 1000), Rate(4, 1500)])
```

### MultiprocessBucket

Shares a `ListProxy` across a `multiprocessing` pool / `ProcessPoolExecutor`, guarded by a multiprocessing lock. See [in_memory_multiprocess.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/in_memory_multiprocess.py).

> Under contention `bucket.waiting` estimates can be off, so prefer `try_acquire(..., blocking=True)` (the default) — the item keeps retrying instead of returning `False` on a transient miss.

### BucketAsyncWrapper

Wraps a sync bucket so every method returns an awaitable, letting the Limiter use `asyncio.sleep` during delays. See [asyncio & event loops](#asyncio--event-loops).

## Web request rate limiting

Drop-in helpers for the popular HTTP clients live in `pyrate_limiter.extras`:

<details>
<summary><b>AIOHTTP</b></summary>

```python
from pyrate_limiter import Duration, limiter_factory
from pyrate_limiter.extras.aiohttp_limiter import RateLimitedSession

limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=2, duration=Duration.SECOND)
session = RateLimitedSession(limiter)
```
[aiohttp_ratelimiter.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/aiohttp_ratelimiter.py)
</details>

<details>
<summary><b>HTTPX</b></summary>

```python
import httpx
from pyrate_limiter import Duration, limiter_factory
from pyrate_limiter.extras.httpx_limiter import AsyncRateLimiterTransport, RateLimiterTransport

limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=1, duration=Duration.SECOND)

with httpx.Client(transport=RateLimiterTransport(limiter=limiter)) as client:
    client.get("https://example.com")

async with httpx.AsyncClient(transport=AsyncRateLimiterTransport(limiter=limiter)) as client:
    await client.get("https://example.com")
```
[httpx_ratelimiter.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/httpx_ratelimiter.py)
</details>

<details>
<summary><b>Requests</b></summary>

```python
from pyrate_limiter import Duration, limiter_factory
from pyrate_limiter.extras.requests_limiter import RateLimitedRequestsSession

limiter = limiter_factory.create_inmemory_limiter(rate_per_duration=2, duration=Duration.SECOND)
session = RateLimitedRequestsSession(limiter)
```
[requests_ratelimiter.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/requests_ratelimiter.py)
</details>

## Advanced usage

### Custom routing with BucketFactory

When items must be routed to different buckets (per user, per endpoint, …), implement a `BucketFactory`. At minimum, define `wrap_item` and `get`:

```python
from pyrate_limiter import (
    AbstractBucket, BucketFactory, RateItem, MonotonicClock,
    InMemoryBucket, Rate, Duration, Limiter,
)

class SingleRouteFactory(BucketFactory):
    def __init__(self, clock, bucket):
        self.clock = clock
        self.bucket = bucket
        self.schedule_leak(bucket)   # run background leaking for this bucket

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        return RateItem(name, self.clock.now(), weight=weight)

    def get(self, _item: RateItem) -> AbstractBucket:
        return self.bucket
```

To create buckets on demand, use `self.create(bucket_class, *args, **kwargs)` — it builds the bucket **and** schedules its leak:

```python
class PerNameFactory(BucketFactory):
    def __init__(self, clock):
        self.clock = clock
        self.buckets = {}

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        return RateItem(name, self.clock.now(), weight=weight)

    def get(self, item: RateItem) -> AbstractBucket:
        if item.name not in self.buckets:
            self.buckets[item.name] = self.create(InMemoryBucket, [Rate(5, Duration.SECOND)])
        return self.buckets[item.name]
```

Then hand the factory to a Limiter:

```python
limiter = Limiter(SingleRouteFactory(MonotonicClock(), InMemoryBucket([Rate(5, Duration.SECOND)])))
limiter.try_acquire("the-earth")
limiter.try_acquire("the-sun", weight=100)
```

### Custom & distributed clocks

In v4 each **bucket** owns its time source via `bucket.now()` — the `Limiter` no longer takes a `clock=` parameter. To make distributed workers agree on "now" (e.g. a shared Redis/DB clock), either **override `now()`** on a bucket subclass (works on every backend, keeps `leak` consistent), or assign a clock to buckets that delegate to `self._clock` (e.g. `InMemoryBucket`, `PostgresBucket`):

```python
from pyrate_limiter import AbstractClock, InMemoryBucket, RedisBucket, Rate, Duration

class RedisClock(AbstractClock):
    def __init__(self, redis):
        self.redis = redis

    def now(self) -> int:
        seconds, microseconds = self.redis.time()
        return seconds * 1000 + microseconds // 1000

# Option A — override now() (recommended)
class RedisTimeBucket(RedisBucket):
    def now(self) -> int:
        seconds, microseconds = self.redis.time()
        return seconds * 1000 + microseconds // 1000

# Option B — inject a clock into a bucket that uses self._clock
bucket = InMemoryBucket([Rate(5, Duration.SECOND)])
bucket._clock = RedisClock(redis_client)
```

Built-in clocks: `MonotonicClock` (default), `MonotonicAsyncClock`, `PostgresClock`, `SQLiteClock`.

### Leaking

Buckets shouldn't hold items forever. Each bucket implements `leak(current_timestamp=None)` to drop expired items, and `BucketFactory.schedule_leak(bucket)` runs that in the background (default interval **10 s**):

```python
factory.schedule_leak(bucket)   # background leak for this bucket
```

Change the interval (in **milliseconds**) via the `leak_interval` property:

```python
class MyFactory(BucketFactory):
    def __init__(self, clock, buckets):
        self.clock = clock
        self.leak_interval = 5000          # leak every 5s
        for bucket in buckets:
            self.schedule_leak(bucket)
```

### Concurrency

Locking is handled at the `Limiter` level. `try_acquire` takes a thread `RLock`; `try_acquire_async` takes a loop-local `asyncio.Lock` in front of the `RLock`; `MultiprocessBucket` adds a multiprocessing lock on top. (`SQLiteBucket` manages its own locking.)

### Custom backends

Implement [`pyrate_limiter.AbstractBucket`](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/abstracts/bucket.py) to add your own backend. The test suite doubles as a conformance spec:

1. Fork the repo.
2. Implement your bucket against `AbstractBucket`.
3. Add a `create_bucket` to `tests/conftest.py` and wire it into the `create_bucket` fixture.
4. Run the suite — if it passes, your backend is good to go.

## Examples

- [asyncio_ratelimit.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/asyncio_ratelimit.py) — rate-limiting asyncio tasks
- [asyncio_decorator.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/asyncio_decorator.py) — the decorator with async functions
- [httpx_ratelimiter.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/httpx_ratelimiter.py) — HTTPX, sync / async / multiprocess
- [in_memory_multiprocess.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/in_memory_multiprocess.py) — multiprocessing with an in-memory bucket
- [sqlite_filelock_multiprocess.py](https://github.com/vutran1710/PyrateLimiter/blob/master/examples/sqlite_filelock_multiprocess.py) — multiprocessing with SQLite + a file lock

---

<p align="center"><sub>Full docs at <a href="https://pyratelimiter.readthedocs.io">pyratelimiter.readthedocs.io</a> · <a href="https://github.com/vutran1710/PyrateLimiter/blob/master/CONTRIBUTING.md">Contributing</a> · <a href="https://github.com/vutran1710/PyrateLimiter/blob/master/CHANGELOG.md">Changelog</a></sub></p>
