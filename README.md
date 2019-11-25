# Request Rate Limiter using Leaky-bucket algorimth


## Introduction
This module can be used to apply rate-limit for API request, using `leaky-bucket` algorimth. User defines `window`
duration and the limit of function calls within such interval.

Currently this package requires `Redis` to work with.

## Installation

``` shell
$ pip install pyrate-limiter
```

# Usage

``` python
from pyrate_limiter.core import TokenBucketLimiter, LeakyBucketLimiter
from pyrate_limiter.engines.redis import RedisBucket
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
```

# Understanding the Algorimths
View `tests/test_leaky_bucket.py` and `tests/test_token_bucket.py` for explaination. Documents are on the way.
