<img align="left" width="90" height="100" src="https://github.com/vutran1710/PyrateLimiter/blob/master/img/log.png">

# PyrateLimiter
The request rate limiter using Leaky-bucket algorimth

[![PyPI version](https://badge.fury.io/py/pyrate-limiter.svg)](https://badge.fury.io/py/pyrate-limiter)

<br>

## Introduction
This module can be used to apply rate-limit for API request, using `leaky-bucket` algorimth. User defines `window`
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
One of the most pleasing features of this lib is that it is meant to be very extensible. People's efforts to solve rate-limiting
problem has so far led to the introductions of few variations of the **leaky-bucket** algorimth. The idea behind this is
you can extend the main core data-structure that power every member of this algorimth family.

#### AbstractBucket
```python
from pyrate_limiter.core import AbstractBucket
```
AbstractBucket is a python abstract class that provide the Interface for, well, a `queue`. The algorimths provided in
`pyrate_limiter.core` all make use of this data-structure. A solid implementation of this abstract class must includes 4
methods of the *bucket* instance:

1. **append**:  `(self, item) -> None`
an instance method that allows a single item to be added to the queue
2. **values**: `(self) -> List[item]`
an instance method that returns the latest list of item in the queue
3. **update**: `(self, list) -> None`
an instance method that completely replace the current queue with another list of values
4. **getlen**: `(self) -> int`
an instance method that returns the queue's length

Due to personal needs, 2 ready-use implementations with [Redis](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/redis.py) and [Application Local State](https://github.com/vutran1710/PyrateLimiter/blob/master/pyrate_limiter/engines/local.py) are provided.

When designing a rate-limiting service that depends on different type of data-store, like `Postgres` or `Mysql`,
user can write his own AbstractBucket implementation that fits their needs.

## Usage

``` python
from pyrate_limiter.core import TokenBucketLimiter, LeakyBucketLimiter
from pyrate_limiter.engines.redis import RedisBucket
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.exceptions import BucketFullException

# Init redis bucket
bucket = RedisBucket('redis-url', hash='some-hash', key='some-key')

# Create Limiter using Token-Bucket Algorimth
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



# Similarly, using Leaky-Bucket Algorimth
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


## Understanding the Algorimths
View `tests/test_leaky_bucket.py` and `tests/test_token_bucket.py` for explaination. Documents are on the way.
#### LeakyBucket with Sliding-Window Algorimth
LeakyBucket with Sliding-Window Algorimth is a capped bucket of items. Every item expires after {window} time, making room for later items to go in.

Item's expiring-rate is {window} time.
Using a simple timeline model, we can describe it as follow
```
TIME <<----------[===========WINDOW===========]--------------------------------<<
REQS >>--- <req> ---- <req> ---- <req> ---- <req> ---- <req> ---- <req> ------->>
```

#### TokenBucket
TokenBucket with Fixed-Window Algorimth can be described as multiple groups of Going-In-Items that does not exceed the Bucket Capacity running into the Bucket at fixed-interval between groups.

Bucket's queue reset if interval between 2 items is larger or equal {window} time.

```
>>-- [x items] ----- (window) ------ [y items] ------ (window) ------ [z items] --->>
eg:  3reqs/3s         <5sec>          2reqs/1s         <5sec>          3reqs/3s
```

## Testing
Simple as it should be, given you have [poetry](https://poetry.eustace.io/) installed...

``` shell
$ poetry run test
```

CICD flow is not currently setup since I dont have much time, but FYI, the `coverage` is decent enought IMO...

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
pyrate_limiter/basic_algorimth.py      45      0   100%
pyrate_limiter/core.py                 63      3    95%
pyrate_limiter/engines/local.py        14      0   100%
pyrate_limiter/engines/redis.py        33      1    97%
pyrate_limiter/exceptions.py            5      0   100%
-------------------------------------------------------
TOTAL                                 161      4    98%
```

## License
Copyright *2019* **vutr**

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
