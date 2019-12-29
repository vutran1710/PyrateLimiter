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
This module can be used to apply rate-limit for API request, using `leaky-bucket` algorithm. User defines `window`
duration and the limit of function calls within such interval.

- To hold the state of the Bucket, you can use `LocalBucket` as internal bucket.
- To use PyrateLimiter with `Redis`,  `redis-py` is required to be installed.
- It is also possible to use your own Bucket implementation, by extending `AbstractBucket` from `pyrate_limiter.core`


## Installation
Using pip/pipenv/poetry, whatever that works for your

``` shell
$ pip install pyrate-limiter
```


## API
One of the most pleasing features of this lib is that it is meant to be very extensible. People's efforts to solve the rate-limiting
problem have so far led to the introduction of a few variations of the **leaky-bucket** algorithm. The idea behind this is project is that
you can extend the main core data-structure that powers every member of this algorithm family.

### Abstract Classes
`core` module provides 3 ready-for-use classes.

```python
from pyrate_limiter.core import (
    AbstractBucket,
    LoggedItem,
    HitRate,
)
```

#### AbstractBucket

AbstractBucket is a python abstract class that provides the Interface for, well, a `queue`. The algorithms provided in
`pyrate_limiter.core` all make use of this data-structure. A concrete implementation of this abstract class must includes 4
methods of the *bucket* instance.

``` python
class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue
    """
    @abstractmethod
    @contextmanager
    def synchronizing(self) -> AbstractBucket:
        """Synchronizing the local class values with remote queue value
        :return: remote queue
        :rtype: list
        """

    @abstractmethod
    def __iter__(self):
        """Bucket should be iterable
        """

    @abstractmethod
    def __getitem__(self, index: int):
        """Bucket should be subscriptable
        """

    @abstractmethod
    def __len__(self):
        """Bucket should return queue's size at request
        """

    @abstractmethod
    def append(self, item: LoggedItem) -> int:
        """A method to append one single item to the queue
        :return: new queue's length
        :rtype: int
        """

    @abstractmethod
    def discard(self, number=1) -> int:
        """A method to append one single item to the queue
        :return: queue's length after discard its first item
        :rtype: int
        """
```

A complete Bucket must be `iterable`, `subscriptable`, suport `len(Bucket)` syntax and support `synchronizing` in context
for prevent any kind of race-condition.

Due to personal needs, 2 ready-use implementations with [Redis](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/redis.py) and [Application Local State](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/local.py) are provided.

When designing a rate-limiting service that depends on a different type of data-store, like `Postgres` or `Mysql`,
the user can write their own AbstractBucket implementation that fits their needs.

#### HitRate

`HitRate` class is not abstract. `HitRate` is to describe how many `hit` per time unit the Limiter can allow to pass
thru.

Considering API throttling business models, we usually see strategies somewhat similar to this.

``` shell
Some commercial/free API (Linkedin, Github etc)
- 500 requests/hour, and
- 1000 requests/day, and
- maximum 10,000 requests/month
```

`HitRate` class is designed to describe this strategies, eg for the above we have a Limiter as following

``` python
hourly_rate = HitRate(500, 3600)
daily_rate = HitRate(1000, 3600 * 24)
monthly_rate = HitRate(10000, 3600 * 24 * 30)

Limiter = BasicLimiter(bucket, hourly_rate, daily_rate, monthly_rate)
```
