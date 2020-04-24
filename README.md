<img align="left" width="95" height="120" src="https://raw.githubusercontent.com/vutran1710/PyrateLimiter/master/img/log.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorithm

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)
[![Python 3.7](https://img.shields.io/badge/python-3.7-blue.svg)](https://www.python.org/downloads/release/python-370/)
[![Maintenance](https://img.shields.io/badge/Maintained%3F-yes-green.svg)](https://github.com/vutran1710/PyrateLimiter/graphs/commit-activity)
[![PyPI license](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/pyrate-limiter/)
[![HitCount](http://hits.dwyl.io/vutran1710/PyrateLimiter.svg)](http://hits.dwyl.io/vutran1710/PyrateLimiter)

<br>

## Introduction
This lib is being rewritten from scratch for the next major release (v2.0).
Checkout `master` branch for `v1.0`


## Available modules
```python
from pyrate_limiter import (
    Bucket,
    Strategies,
    RequestRate,
    Limiter,
    TimeEnum,
    Option,
)
```

## Strategies

`Bucket` class is a python abstract class that provides the Interface for, well, a `queue`. The algorithms provided in
`pyrate_limiter.core` all make use of this data-structure. A concrete implementation of this abstract class must includes 4
methods of the *bucket* instance.

### Subscription strategies

Considering API throttling logic for usual business models of Subscription, we usually see strategies somewhat similar to these.

``` shell
Some commercial/free API (Linkedin, Github etc)
- 500 requests/hour, and
- 1000 requests/day, and
- maximum 10,000 requests/month
```

`RequestRate` class is designed to describe this strategies - eg for the above strategies we have a Rate-Limiter defined
as following

``` python
hourly_rate = RequestRate(500, 3600)
daily_rate = RequestRate(1000, 3600 * 24)
monthly_rate = RequestRate(10000, 3600 * 24 * 30)

Limiter = Limiter(bucket, hourly_rate, daily_rate, monthly_rate, *other_rates)
```

### Spam-protection strategies

Sometimes, we need a rate-limiter to protect our API from spamming/ddos attack. Some usual strategies for this could be as
following

``` shell
1. No more than 100 requests/minute, or
2. 100 request per minute, and no more than 300 request per hour
```

### More complex scenario
https://www.keycdn.com/support/rate-limiting#types-of-rate-limits

Sometimes, we may need to apply specific rate-limiting strategies based on schedules/region or some other metrics. It
requires the capability to `switch` the strategies instantly without re-deploying the whole service.
