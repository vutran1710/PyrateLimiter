<img align="left" width="95" height="120" src="docs/_static/logo.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorithm.

Full project documentation can be found at [pyratelimiter.readthedocs.io](https://pyratelimiter.readthedocs.io).

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/pyrate-limiter)](https://pypi.org/project/pyrate-limiter)
[![codecov](https://codecov.io/gh/vutran1710/PyrateLimiter/branch/master/graph/badge.svg?token=E0Q0YBSINS)](https://codecov.io/gh/vutran1710/PyrateLimiter)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/vutran1710/PyrateLimiter/graphs/commit-activity)
[![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/pyrate-limiter/)

<br>

## Contents
- [PyrateLimiter](#pyratelimiter)
  - [Contents](#contents)
  - [Features](#features)
  - [Installation](#installation)
  - [Quickstart](#quickstart)
  - [Basic usage](#basic-usage)
    - [Key concepts](#key-concepts)
    - [Defining rate limits & buckets](#defining-rate-limits-and-buckets)
    - [Defining clock & routing logic](#defining-clock--routing-logic-with-bucketfactory)
    - [Wrapping all up with Limiter](#wrapping-all-up-with-limiter)
    - [Weight](#weight)
    - [Handling exceeded limits](#handling-exceeded-limits)
      - [Bucket analogy](#bucket-analogy)
      - [Rate limit exceptions](#rate-limit-exceptions)
       - [Rate limit delays](#rate-limit-delays)
    - [Backends](#backends)
      - [InMemoryBucket](#inmemorybucket)
      - [SQLiteBucket](#sqlitebucket)
      - [RedisBucket](#redisbucket)
    - [Decorator](#decorator)
  - [Advance Usage](#advance-usage)
    - [Component-level Diagram](#component-level-diagram)
    - [Time sources](#time-sources)
    - [Leaking](#leaking)
    - [Concurrency](#concurrency)
    - [Custom backend](#custom-backend)


## Features
* Tracks any number of rate limits and intervals you want to define
* Independently tracks rate limits for multiple services or resources
* Handles exceeded rate limits by either raising errors or adding delays
* Several usage options including a normal function call, a decorator
* Out-of-the-box workable with both sync & async
* Includes optional SQLite and Redis backends, which can be used to persist limit tracking across
  multiple threads, or application restarts

## Installation
**PyrateLimiter** supports **python ^3.8**

Install using pip:
```
pip install pyrate-limiter
```

Or using conda:
```
conda install --channel conda-forge pyrate-limiter
```

## Quickstart
Let's say you want to limit 5 requests over 2 seconds, and raise an exception if the limit is exceeded:
``` python
from pyrate_limiter import Duration, Rate, InMemoryBucket, Limiter, BucketFullException

rates = [Rate(5, Duration.SECOND * 2)]
bucket = InMemoryBucket(rates)
limiter = Limiter(bucket)

for request in range(6):
    try:
        limiter.try_acquire(request)
    except BucketFullException as err:
        print(err)
        print(err.meta_info)
# True
# True
# True
# True
# True
# Bucket for item=5 with Rate limit=5/2.0s is already full
# {'error': 'Bucket for item=5 with Rate limit=5/2.0s is already full', 'name': 5, 'weight': 1, 'rate': 'limit=5/2.0s'}
```

## Basic Usage
### Key concepts

#### Clock
-  Timestamp items

#### Bucket
- Hold items with timestamps.
- Behave like a FIFO queue
- It can `leak` - popping items that are no longer relevant out of the queue

#### BucketFactory
- BucketFactory keeps references to buckets & clocks: determine the exact time that items arrive then route them to their corresponding buckets
- Help schedule background tasks to run buckets' `leak` periodically to make sure buckets will not explode from containing too many items
- Where user define his own logic: routing, condition-checking, timing etc...

#### Limiter
The Limiter's most important responsibility is to make user's life as easiest as possible:
- Sums up all the underlying logic to a simple, intuitive API to work with
- Handles async/sync context seamlessly (everything just `works` by adding/removing `async/await` keyword to the user's code)
- Provides different ways of interacting with the underlying **BucketFactory** *(plain method call, decorator, context-manager (TBA))*
- Provides thread-safety using RLock


### Defining rate limits and buckets
Consider some public API (like LinkedIn, GitHub, etc.) that has rate limits like the following:
```
- 500 requests per hour
- 1000 requests per day
- 10000 requests per month
```

You can define these rates using the `Rate` class. `Rate` class has 2 properties only: **limit** and **interval**
``` python
from pyrate_limiter import Duration, Rate

hourly_rate = Rate(500, Duration.HOUR) # 500 requests per hour
daily_rate = Rate(1000, Duration.DAY) # 1000 requests per day
monthly_rate = Rate(10000, Duration.WEEK * 4) # 10000 requests per month

rates = [hourly_rate, daily_rate, monthly_rate]
```

Rates must be properly ordered:
- Rates' intervals & limits must be ordered from least to greatest
- Rates' ratio of **limit/interval** must be ordered from greatest to least

Existing implementations of Bucket come with rate-validation when init. If you are to use your own implementation, use the validator provided by the lib

```python
from pyrate_limiter import validate_rate_list

assert validate_rate_list(my_rates)
```

Then, add the rates to the bucket of your choices

```python
from pyrate_limiter import InMemoryBucket, RedisBucket

basic_bucket = InMemoryBucket(rates)

# Or, using redis
from redis import Redis

redis_connection = Redis(host='localhost')
redis_bucket = RedisBucket.init(rates, redis_connection, "my-bucket-name")

# Async Redis would work too!
from redis.asyncio import Redis

redis_connection = Redis(host='localhost')
redis_bucket = await RedisBucket.init(rates, redis_connection, "my-bucket-name")
```

If you only need a single Bucket for everything, and python's built-in `time()` is enough for you, then pass the bucket to Limiter then ready to roll!

```python
from pyrate_limiter import Limiter

# Limiter constructor accepts single bucket as the only parameter,
# the rest are 3 optional parameters with default values as following
# Limiter(bucket, clock=TimeClock(), raise_when_fail=True, max_delay=None)
limiter = Limiter(bucket)

# Limiter is now ready to work!
limiter.try_acquire("hello world")
```

If you want to have finer grain control with routing & clocks etc, then you should use `BucketFactory`.

### Defining Clock & routing logic with BucketFactory

If you need more than one type of Bucket, and be able to route items to different buckets based on some condition, you can use BucketFactory to do that.

From the above steps, you already have your buckets. Now it's time to define what `Time` is (funny?!). Most of the time (again!?), you can use the existing Clock backend provided by **pyrate_limiter**.

```python
from pyrate_limiter.clock import TimeClock, MonotonicClock, SQLiteClock

base_clock = TimeClock()
```


**PyrateLimiter** makes no assumption about users logic, so to map coming items to their correct buckets, implement your own **BucketFactory** class! At minimum, there are only 2 methods require implementing

```python
from pyrate_limiter import BucketFactory
from pyrate_limiter import AbstractBucket


class MyBucketFactory(BucketFactory):
    # You can use constructor here,
    # nor it requires to make bucket-factory work!

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        """Time-stamping item, return a RateItem"""
        now = clock.now()
        return RateItem(name, now, weight=weight)

    def get(self, _item: RateItem) -> AbstractBucket:
        """For simplicity's sake, all items route to the same, single bucket"""
        return bucket
```

### Wrapping all up with Limiter

Pass your bucket-factory to Limiter, and ready to roll!
```python
from pyrate_limiter import Limiter

limiter = Limiter(
    bucket_factory,
    raise_when_fail=False,  # Default = True
    max_delay=1000,     # Default = None
)

item = "the-earth"
limiter.try_acquire(item)

heavy_item = "the-sun"
limiter.try_acquire(heavy_item, weight=10000)
```

If your bucket's backend is `async`, well, we got you covered! Passing `await` to the limiter is enought to make it scream!

```python
await limiter.try_acquire(item)
```

Alternatively, you can use `Limiter.try_acquire` as a function decorator. But you have to provide a `mapping` function that map the wrapped function's arguments to a proper `limiter.try_acquire` argument - which is a tuple of `(str, int)` or just `str`
```python
my_beautiful_decorator = limiter.as_decorator()

def mapping(some_number: int):
    return str(some_number)

@my_beautiful_decorator(mapping)
def request_function(some_number: int):
    requests.get('https://example.com')

# Async would work too!
@my_beautiful_decorator(mapping)
async def async_request_function(some_number: int):
    requests.get('https://example.com')
```

### Weight

Item can have weight. By default item's weight = 1, but you can modify the weight before passing to `limiter.try_acquire`.

Item with weight W > 1 when consumed will be multiplied to (W) items with the same timestamp and weight = 1. Example with a big item with weight W=5, when put to bucket, it will be divided to 5 items with weight=1 + following names

```
BigItem(weight=5, name="item", timestamp=100) => [
    item(weight=1, name="item", timestamp=100),
    item(weight=1, name="item", timestamp=100),
    item(weight=1, name="item", timestamp=100),
    item(weight=1, name="item", timestamp=100),
    item(weight=1, name="item", timestamp=100),
]
```

Yet, putting this big, heavy item into bucket is expected to be transactional & atomic - meaning either all 5 items will be consumed or none of them will. This is made possible as bucket `put(item)` always check for available space before ingesting. All of the Bucket's implementations provided by **PyrateLimiter** follows this rule.

Any additional, custom implementation of Bucket are expected to behave alike - as we have unit tests to cover the case.

See [Additional usage options](#additional-usage-options) below for more details.

### Handling exceeded limits
When a rate limit is exceeded, you have two options: raise an exception, or add delays.

#### Bucket analogy
<img height="300" align="right" src="https://upload.wikimedia.org/wikipedia/commons/c/c4/Leaky_bucket_analogy.JPG">

At this point it's useful to introduce the analogy of "buckets" used for rate-limiting. Here is a
quick summary:

* This library implements the [Leaky Bucket algorithm](https://en.wikipedia.org/wiki/Leaky_bucket).
* It is named after the idea of representing some kind of fixed capacity -- like a network or service -- as a bucket.
* The bucket "leaks" at a constant rate. For web services, this represents the **ideal or permitted request rate**.
* The bucket is "filled" at an intermittent, unpredicatble rate, representing the **actual rate of requests**.
* When the bucket is "full", it will overflow, representing **canceled or delayed requests**.
* Item can have weight. Consuming a single item with weight W > 1 is the same as consuming W smaller, unit items - each with weight=1, with the same timestamp and maybe same name (depending on however user choose to implement it)

#### Rate limit exceptions
By default, a `BucketFullException` will be raised when a rate limit is exceeded.
The error contains a `meta_info` attribute with the following information:
* `name`: The name of item it received
* `weight`: The weight of item it received
* `rate`: The specific rate that has been exceeded

Here's an example that will raise an exception on the 4th request:
```python
rate = Rate(3, Duration.SECOND)
bucket = InMemoryBucket([rate])
clock = TimeClock()


class MyBucketFactory(BucketFactory):

    def wrap_item(self, name: str, weight: int = 1) -> RateItem:
        """Time-stamping item, return a RateItem"""
        now = clock.now()
        return RateItem(name, now, weight=weight)

    def get(self, _item: RateItem) -> AbstractBucket:
        """For simplicity's sake, all items route to the same, single bucket"""
        return bucket


limiter = Limiter(MyBucketFactory())

for _ in range(4):
    try:
        limiter.try_acquire('item', weight=2)
    except BucketFullException as err:
        print(err)
        # Output: Bucket with Rate 3/1.0s is already full
        print(err.meta_info)
        # Output: {'name': 'item', 'weight': 2, 'rate': '3/1.0s', 'error': 'Bucket with Rate 3/1.0s is already full'}
```

The rate part of the output is constructed as: `limit / interval`. On the above example, the limit
is 3 and the interval is 1, hence the `Rate 3/1`.

#### Rate limit delays
You may want to simply slow down your requests to stay within the rate limits instead of canceling
them. In that case you pass the `max_delay` argument the maximum value of delay (typically in *ms* when use human-clock).

```python
limiter = Limiter(factory, max_delay=500) # Allow to delay up to 500ms
```

As `max_delay` has been passed as a numeric value, when ingesting item, limiter will:
- First, try to ingest such item using the routed bucket
- If it fails to put item into the bucket, it will call `wait(item)` on the bucket to see how much time remains until the bucket can consume the item again?
- Comparing the `wait` value to the `max_delay`.
- if `max_delay` >= `wait`: delay (wait + 50ms as latency-tolerance) using either `asyncio.sleep` or `time.sleep` until the bucket can consume again
- if `max_delay` < `wait`: it raises `LimiterDelayException` if Limiter's `raise_when_fail=True`, otherwise silently fail and return False

Example:
```python
from pyrate_limiter import LimiterDelayException

for _ in range(4):
    try:
        limiter.try_acquire('item', weight=2, max_delay=200)
    except LimiterDelayException as err:
        print(err)
        # Output:
        # Actual delay exceeded allowance: actual=500, allowed=200
        # Bucket for 'item' with Rate 3/1.0s is already full
        print(err.meta_info)
        # Output: {'name': 'item', 'weight': 2, 'rate': '3/1.0s', 'max_delay': 200, 'actual_delay': 500}
```

### Backends
A few different bucket backends are available:
- InMemoryBucket using python built-in list as bucket
- RedisBucket, using err... redis, with both async/sync support
- SQLite, using sqlite3

#### InMemoryBucket
The default bucket is stored in memory, using python `list`

```python
from pyrate_limiter import InMemoryBucket, Rate, Duration

rates = [Rate(5, Duration.MINUTE * 2)]
bucket = InMemoryBucket(rates)
```

This bucket only availabe in `sync` mode. The only constructor argument is `List[Rate]`.

#### RedisBucket
RedisBucket uses `Sorted-Set` to store items with key being item's name and score item's timestamp
Because it is intended to work with both async & sync, we provide a classmethod `init` for it

```python
from pyrate_limiter import RedisBucket, Rate, Duration

# Using synchronous redis
from redis import ConnectionPool
from redis import Redis

rates = [Rate(5, Duration.MINUTE * 2)]
pool = ConnectionPool.from_url("redis://localhost:6379")
redis_db = Redis(connection_pool=pool)
bucket_key = "bucket-key"
bucket = RedisBucket.init(rates, redis_db, bucket_key)

# Using asynchronous redis
from redis.asyncio import ConnectionPool as AsyncConnectionPool
from redis.asyncio import Redis as AsyncRedis

pool = AsyncConnectionPool.from_url("redis://localhost:6379")
redis_db = AsyncRedis(connection_pool=pool)
bucket_key = "bucket-key"
bucket = await RedisBucket.init(rates, redis_db, bucket_key)
```

The API are the same, regardless of sync/async. If AsyncRedis is being used, calling `await bucket.method_name(args)` would just work!

#### SQLiteBucket
If you need to persist the bucket state, a SQLite backend is available.

Manully create a connection to Sqlite and pass it along with the table name to the bucket class:

```python
from pyrate_limiter import SQLiteBucket, Rate, Duration
import sqlite3

rates = [Rate(5, Duration.MINUTE * 2)]
conn = sqlite3.connect(
    "/var/mydb.sqlite",
    isolation_level="EXCLUSIVE",
    check_same_thread=False,
)
table = "my-bucket-table"
bucket = SQLiteBucket(rates, conn, table)
```

### Decorator

Limiter can be used as decorator, but you have to provide a `mapping` function that maps the wrapped function's arguments to `limiter.try_acquire` function arguments. The mapping function must return either a tuple of `(str, int)` or just a `str`

The decorator can work with both sync & async function

```python
decorator = limiter.as_decorator()

def mapping(*args, **kwargs):
    return "demo", 1

@decorator(mapping)
def handle_something(*args, **kwargs):
    """function logic"""

@decorator(mapping)
async def handle_something_async(*args, **kwargs):
    """function logic"""
```

## Advance Usage

### Component level diagram
![](https://raw.githubusercontent.com/vutran1710/PyrateLimiter/master/docs/_static/components.jpg)
![](./docs/_static/components.jpg)

### Time sources
Time source can be anything from anywhere: be it python's built-in time, or monotonic clock, sqliteclock, or crawling from world time server(well we don't have that, but you can!).

```python
from pyrate_limiter import TimeClock      # use python' time.time()
from pyrate_limiter import MonotonicClock # use python time.monotonic()
```

Clock's abstract interface only requires implementing a method `now() -> int`. And it can be both sync or async.


### Leaking
Typically bucket should not hold items forever. Bucket's abstract interface requires its implementation must be provided with `leak(current_timestamp: Optional[int] = None)`.

The `leak` method when called is expected to remove any items considered outdated  at that moment. During Limiter lifetime, all the buckets' `leak` should be called periodically.

**BucketFactory** provide a method called `schedule_leak` to help deal with this matter. Basically, it will run **1(one)** background task for a specific bucket, where interval between `leak` call by default is the bucket's longest rate's interval * 2.

```python
# Runnning a background task (whether it is sync/async - doesnt matter)
# calling the bucket's leak, using the clock as `bucket.leak(clock.now())`
# interval between call = bucket.rates[-1].interval * 2 (ms)
factory.schedule_leak(bucket, clock)
```

You can change this calling interval by overriding BucketFactory's `leak_interval`. For example, use the first rate's interval or a fixed value

```python
class MyBucketFactory(BucketFactory):
    ... other implementations

    def leak_interval(self, bucket):
        if isinstance(bucket, InMemoryBucket):
            return bucket.rates[0].interval

        if isinstance(bucket, RedisBucket):
            return 10_000

        return super().leak_interval()
```

When dealing with leak using BucketFactory, the author's suggestion is, we can be pythonic about this by implementing a constructor

```python
class MyBucketFactory(BucketFactory):

    def constructor(self, clock, buckets):
        self.clock = clock
        self.buckets = buckets

        for bucket in buckets:
            self.schedule_leak(bucket, clock)

```

### Concurrency
Generally, Lock is provided at Limiter's level, except SQLiteBucket case.

### Custom backends
If these don't suit your needs, you can also create your own bucket backend by implementing `pyrate_limiter.AbstractBucket` class.

One of **PyrateLimiter** design goals is powerful extensibility and maximum ease of development.

It must be not only be a ready-to-use tool, but also a guide-line, or a framework that help implementing new features/bucket free of the most hassles.

Due to the composition nature of the library, it is possbile to write minimum code and validate the result:

- Fork the repo
- Implement `pyrate_limiter.AbstractBucket`
- Add your own `create_bucket` method in `tests/conftest.py` and pass it to the `create_bucket` fixture
- Run the test suite to validate the result

If the tests pass through, the you are just good to go with your new, fancy bucket!
