<img align="left" width="95" height="120" src="https://raw.githubusercontent.com/vutran1710/PyrateLimiter/master/img/log.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorithm

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)
[![PyPI - Python Versions](https://img.shields.io/pypi/pyversions/pyrate-limiter)](https://pypi.org/project/pyrate-limiter)
[![codecov](https://codecov.io/gh/vutran1710/PyrateLimiter/branch/master/graph/badge.svg?token=E0Q0YBSINS)](https://codecov.io/gh/vutran1710/PyrateLimiter)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/vutran1710/PyrateLimiter/graphs/commit-activity)
[![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/pyrate-limiter/)

<br>

- [PyrateLimiter](#pyratelimiter)
  * [Introduction](#introduction)
  * [Available modules](#available-modules)
  * [Strategies](#strategies)
    + [Subscription strategies](#subscription-strategies)
    + [BucketFullException](#bucketfullexception)
    + [Decorator](#decorator)
    + [Rate-limiting delays](#rate-limiting-delays)
    + [Contextmanager](#contextmanager)
    + [Async decorator/contextmanager](#async-decorator-contextmanager)
    + [Examples](#examples)
    + [Spam-protection strategies](#spam-protection-strategies)
    + [Throttling handling](#throttling-handling)
    + [More complex scenario](#more-complex-scenario)
  * [Development](#development)
  * [Notes](#notes)

<small><i><a href='http://ecotrust-canada.github.io/markdown-toc/'>Table of contents generated with markdown-toc</a></i></small>

## Introduction
This module can be used to apply rate-limit for API request. User defines window duration and the limit of function calls within such interval.
To hold the state of the Bucket, you can use MemoryListBucket/MemoryQueueBucket as internal bucket.
To use PyrateLimiter with Redis, redis-py is required to be installed.
It is also possible to use your own Bucket implementation, by extending AbstractBucket from pyrate_limiter.core

## Available modules
```python
from pyrate_limiter import (
    BucketFullException,
    Duration,
    RequestRate,
    Limiter,
    MemoryListBucket,
    MemoryQueueBucket,
)
```

## Strategies

### Subscription strategies

Considering API throttling logic for usual business models of Subscription, we usually see strategies somewhat similar to these.

``` shell
Some commercial/free API (Linkedin, Github etc)
- 500 requests/hour, and
- 1000 requests/day, and
- maximum 10,000 requests/month
```

- [x] `RequestRate` class is designed to describe this strategies - eg for the above strategies we have a Rate-Limiter defined
as following

``` python
hourly_rate = RequestRate(500, Duration.HOUR) # maximum 500 requests/hour
daily_rate = RequestRate(1000, Duration.DAY) # maximum 1000 requests/day
monthly_rate = RequestRate(10000, Duration.MONTH) # and so on

limiter = Limiter(hourly_rate, daily_rate, monthly_rate, *other_rates, bucket_class=MemoryListBucket) # default is MemoryQueueBucket

# usage
identity = user_id # or ip-address, or maybe both
limiter.try_acquire(identity)
```

As the logic is pretty self-explainatory, note that the superior rate-limit must come after the inferiors, ie
1000 req/day must be declared after an hourly-rate-limit, and the daily-limit must be larger than hourly-limit.

- [x] `bucket_class` is the type of bucket that holds request. It could be an in-memory data structure like Python List (`MemoryListBucket`), or Queue `MemoryQueueBucket`.


- [x] For microservices or decentralized platform, multiple rate-Limiter may share a single store for storing
      request-rate history, ie `Redis`. This lib provides ready-to-use `RedisBucket` (`redis-py` is required), and `RedisClusterBucket` (with `redis-py-cluster` being required). The usage difference is when using Redis, a naming `prefix` must be provide so the keys can be distinct for each item's identity.

``` python
from pyrate_limiter.bucket import RedisBucket, RedisClusterBucket
from redis import ConnectionPool

redis_pool = ConnectionPool.from_url('redis://localhost:6379')

rate = RequestRate(3, 5 * Duration.SECOND)

bucket_kwargs = {
    "redis_pool": redis_pool,
    "bucket_name": "my-ultimate-bucket-prefix"
}

# so each item buckets will have a key name as
# my-ultimate-bucket-prefix__item-identity

limiter = Limiter(rate, bucket_class=RedisBucket, bucket_kwargs=bucket_kwargs)
# or RedisClusterBucket when used with a redis cluster
# limiter = Limiter(rate, bucket_class=RedisClusterBucket, bucket_kwargs=bucket_kwargs)
item = 'vutran_item'
limiter.try_acquire(item)
```

### BucketFullException
If the Bucket is full, an exception *BucketFullException* will be raised, with meta-info about the identity it received, the rate that has raised, and the remaining time until the next request can be processed.

```python
rate = RequestRate(3, 5 * Duration.SECOND)
limiter = Limiter(rate)
item = 'vutran'

has_raised = False
try:
    for _ in range(4):
        limiter.try_acquire(item)
        sleep(1)
except BucketFullException as err:
    has_raised = True
    assert str(err)
    # Bucket for vutran with Rate 3/5 is already full
    assert isinstance(err.meta_info, dict)
    # {'error': 'Bucket for vutran with Rate 3/5 is already full', 'identity': 'tranvu', 'rate': '5/5', 'remaining_time': 2}
```

- [ ] *RequestRate may be required to `reset` on a fixed schedule, eg: every first-day of a month

### Decorator
Rate-limiting is also available in decorator form, using `Limiter.ratelimit`. Example:
```python
@limiter.ratelimit(item)
def my_function():
    do_stuff()
```

As with `Limiter.try_acquire`, if calls to the wrapped function exceed the rate limits you
defined, a `BucketFullException` will be raised.

### Rate-limiting delays
In some cases, you may want to simply slow down your calls to stay within the rate limits instead of
canceling them. In that case you can use the `delay` flag, optionally with a `max_delay`
(in seconds) that you are willing to wait in between calls.

Example:
```python
@limiter.ratelimit(item, delay=True, max_delay=10)
def my_function():
    do_stuff()
```

In this case, calls may be delayed by at most 10 seconds to stay within the rate limits; any longer
than that, and a `BucketFullException` will be raised instead. Without specifying `max_delay`, calls
will be delayed as long as necessary.

### Contextmanager
`Limiter.ratelimit` also works as a contextmanager:

```python
def my_function():
    with limiter.ratelimit(item, delay=True):
        do_stuff()
```

### Async decorator/contextmanager
All the above features of `Limiter.ratelimit` also work on async functions:
```python
@limiter.ratelimit(item, delay=True)
async def my_function():
    await do_stuff()

async def my_function():
    async with limiter.ratelimit(item):
        await do_stuff()
```

When delays are enabled, `asyncio.sleep` will be used instead of `time.sleep`.

### Examples
To prove that pyrate-limiter is working as expected, here is a complete example to demonstrate
rate-limiting with delays:
```python
from time import perf_counter as time
from pyrate_limiter import Duration, Limiter, RequestRate

limiter = Limiter(RequestRate(5, Duration.SECOND))
n_requests = 27

@limiter.ratelimit("test", delay=True)
def limited_function(start_time):
    print(f"t + {(time() - start_time):.5f}")

start_time = time()
for _ in range(n_requests):
    limited_function(start_time)
print(f"Ran {n_requests} requests in {time() - start_time:.5f} seconds")
```

And an equivalent example for async usage:
```python
import asyncio
from time import perf_counter as time
from pyrate_limiter import Duration, Limiter, RequestRate

limiter = Limiter(RequestRate(5, Duration.SECOND))
n_requests = 27

@limiter.ratelimit("test", delay=True)
async def limited_function(start_time):
    print(f"t + {(time() - start_time):.5f}")

async def test_ratelimit():
    start_time = time()
    tasks = [limited_function(start_time) for _ in range(n_requests)]
    await asyncio.gather(*tasks)
    print(f"Ran {n_requests} requests in {time() - start_time:.5f} seconds")

asyncio.run(test_ratelimit())
```

Limiter can be used with any custom time source. For example user may want to use
Redis time to use same time in distributed installation. By default `time.monotonic` is
used. To adjust time source use `time_function` parameter with any no arguments function.
```python
from datetime import datetime
from pyrate_limiter import Duration, Limiter, RequestRate
from time import time

limiter_datetime = Limiter(RequestRate(5, Duration.SECOND), time_function=lambda: datetime.utcnow().timestamp())
limiter_time = Limiter(RequestRate(5, Duration.SECOND), time_function=time)
```

### Spam-protection strategies
- [x] Sometimes, we need a rate-limiter to protect our API from spamming/ddos attack. Some usual strategies for this could be as
following

``` shell
1. No more than 100 requests/minute, or
2. 100 request per minute, and no more than 300 request per hour
```

### Throttling handling
When the number of incoming requets go beyond the limit, we can either do..

``` shell
1. Raise a 429 Http Error, or
2. Keep the incoming requests, wait then slowly process them one by one.
```

### More complex scenario
https://www.keycdn.com/support/rate-limiting#types-of-rate-limits

- [ ] *Sometimes, we may need to apply specific rate-limiting strategies based on schedules/region or some other metrics. It
requires the capability to `switch` the strategies instantly without re-deploying the whole service.

## Development

### Setup & Commands
- To setup local development,  *Poetry* and *Python 3.6* is required. Python can be installed using *Pyenv* or normal installation from binary source. To install *poetry*, follow the official guideline (https://python-poetry.org/docs/#installation).

Then, in the repository directory...
```shell
$ poetry install
```

- Other than built-in Poetry commands, there are some custom commands defined in **scripts.py**. What you should care about are:
  - Run test with: `poetry run test`
  - Format code base: `poetry run format`
  - To run test with coverage: `poetry run cover`
  - Check for lint error: `poetry run lint`

### Guideline & Notes
We have CICD running on Travis to do the checking, testing and publishing work. So, there are few small notes when making Pull Request:
- All existing tests must pass (Of course!)
- Reduction in *Coverage* shall result in failure. (below 98% is not accepted)
- When you are making bug fixes, or adding more features, remember to bump the version number in **pyproject.toml**. The number should follow *semantic-versioning* rules

## Notes
Todo-items marked with (*) are planned for v3 release.
