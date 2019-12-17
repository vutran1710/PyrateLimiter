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

#### AbstractBucket
```python
from pyrate_limiter.core import AbstractBucket
```
AbstractBucket is a python abstract class that provides the Interface for, well, a `queue`. The algorithms provided in
`pyrate_limiter.core` all make use of this data-structure. A concrete implementation of this abstract class must includes 4
methods of the *bucket* instance.

``` python
class AbstractBucket(ABC):
    """An abstract class for Bucket as Queue"""

    __values__ = []

    @abstractmethod
    def append(self, item) -> None:
        """Add single item to the queue
        """
    @abstractmethod
    def values(self) -> List:
        """Return queue values
        """
    @abstractmethod
    def update(self, new_list: List) -> None:
        """Completely replace the existing queue with a new one
        """
    def getlen(self) -> int:
        """Return the current queue's length
        """
        return len(self.__values__)
```

Due to personal needs, 2 ready-use implementations with [Redis](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/redis.py) and [Application Local State](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/local.py) are provided.

When designing a rate-limiting service that depends on a different type of data-store, like `Postgres` or `Mysql`,
the user can write their own AbstractBucket implementation that fits their needs.

## Usage

``` python
from pyrate_limiter.core import TokenBucketLimiter, LeakyBucketLimiter
from pyrate_limiter.engines.redis import RedisBucket
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.exceptions import BucketFullException

# Init redis bucket
bucket = RedisBucket('redis-url', hash='some-hash', key='some-key')

# Create Limiter using Token-Bucket Algorithm
# Maximum 10 items over 60 seconds
limiter = TokenBucketLimiter(bucket, capacity=10, window=60)
limiter.queue.config(key='change-key')
# Process an item
try:
    limiter.process('some-json-serializable-value')
    print('Item allowed to pass through')
except BucketFullException:
    print('Bucket is full')
    # do something



# Similarly, using Leaky-Bucket Algorithm
limiter = LeakyBucketLimiter(bucket, capacity=5, window=6)
limiter.queue.config(key='change-key')
# Process an item
try:
    # For LeakyBucketLimiter using the similar process method, only
    # different in naming...
    limiter.append('some-json-serializable-value')
    print('Item allowed to pass through')
except BucketFullException:
    print('Bucket is full')
    # do something


# If using LocalBucket, the instantiation is even simpler
bucket = LocalBucket(initial_values=some_list_type_value)
```


## Understanding the Algorithms

#### LeakyBucket with Sliding-Window Algorithm
LeakyBucket with Sliding-Window Algorithm is a capped bucket of items. Every item expires after {window} time, making room for later items to go in.

Item's expiring-rate is {window} time.
Using a simple timeline model, we can describe it as follow
```
TIME <<----------[===========WINDOW===========]--------------------------------<<
REQS >>--- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---- <req> ------->>
```

#### TokenBucket
TokenBucket with Fixed-Window Algorithm can be described as multiple groups of Going-In-Items that do not exceed the Bucket Capacity running into the Bucket with fixed-intervals between groups.

The bucket's queue resets if the interval between 2 items is larger or equal to {window} time.

```
>>-- [x items] ----- (window) ------ [y items] ------ (window) ------ [z items] --->>
eg:  3reqs/3s         <5sec>          2reqs/1s         <5sec>          3reqs/3s
```

## Testing
Simple as it should be, given you have [poetry](https://poetry.eustace.io/) installed...

``` shell
$ poetry run test
```

CICD flow is not currently set up since I dont have much time, but FYI, the `coverage` is decent enought IMO...

``` shell
tests/test_leaky_bucket.py::test_bucket_overloaded PASSED
tests/test_leaky_bucket.py::test_bucket_cooldown PASSED
tests/test_local_engine.py::test_invalid_initials PASSED
tests/test_local_engine.py::test_leaky_bucket_overloaded PASSED
tests/test_local_engine.py::test_leaky_bucket_cooldown PASSED
tests/test_local_engine.py::test_token_bucket_overloaded PASSED
tests/test_local_engine.py::test_token_bucket_cooldown PASSED
tests/test_redis_engine.py::test_bucket_overloaded PASSED
tests/test_redis_engine.py::test_bucket_cooldown PASSED
tests/test_redis_engine.py::test_normalize_redis_value PASSED
tests/test_redis_engine.py::test_token_bucket_overloaded PASSED
tests/test_redis_engine.py::test_token_bucket_cooldown PASSED
tests/test_token_bucket.py::test_bucket_overloaded PASSED
tests/test_token_bucket.py::test_bucket_cooldown PASSED

---------- coverage: platform darwin, python 3.7.5-final-0 -----------
Name                                Stmts   Miss  Cover
-------------------------------------------------------
pyrate_limiter/__init__.py              1      0   100%
pyrate_limiter/basic_algorithm.py      45      0   100%
pyrate_limiter/core.py                 63      3    95%
pyrate_limiter/engines/local.py        14      0   100%
pyrate_limiter/engines/redis.py        33      1    97%
pyrate_limiter/exceptions.py            5      0   100%
-------------------------------------------------------
TOTAL                                 161      4    98%
```
