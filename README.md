<img align="left" width="95" height="120" src="https://raw.githubusercontent.com/vutran1710/PyrateLimiter/master/img/log.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorithm

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)
[![Python 3.7](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/release/python-370/)
[![Python 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/downloads/release/python-380/)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/vutran1710/PyrateLimiter/graphs/commit-activity)
[![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/pyrate-limiter/)
[![HitCount](http://hits.dwyl.io/vutran1710/PyrateLimiter.svg)](http://hits.dwyl.io/vutran1710/PyrateLimiter)

<br>

## Introduction
- This lib is being rewritten from scratch for the next major release (v2.0). Checkout `master` branch for `v1.0`

- Feature with checked-box is done


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
      request-rate history, ie `Redis`. This lib provides a ready-use `RedisBucket` to handle such case, and required
      `redis-py` as its peer-dependency. The usage difference is when using Redis, a naming `prefix` must be provide so
      the keys can be distinct for each item's identity.

``` python
from redis import ConnectionPool

pool = ConnectionPool.from_url('redis://localhost:6379')

rate = RequestRate(3, 5 * Duration.SECOND)

bucket_kwargs = {
    "redis_pool": redis_pool,
    "bucket_name": "my-ultimate-bucket-prefix"
}

# so each item buckets will have a key name as
# my-ultimate-bucket-prefix__item-identity

limiter = Limiter(rate, bucket_class=RedisBucket, bucket_kwargs=bucket_kwargs)
item = 'vutran_item'
limiter.try_acquire(item)
```

- [ ] RequestRate may be required to `reset` on a fixed schedule, eg: every first-day of a month

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

- [ ] Sometimes, we may need to apply specific rate-limiting strategies based on schedules/region or some other metrics. It
requires the capability to `switch` the strategies instantly without re-deploying the whole service.
