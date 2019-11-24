# Request Rate Limiter using Leaky-bucket algorimth


## Introduction
This module can be used to apply rate-limit for API request, using `leaky-bucket` algorimth. User defines `window`
duration and the limit of function calls within such interval.

Currently this package requires `Redis` to work with.

## Installation

``` shell
$ pip install snaky-bucket
```

# Usage

``` python
from rate_limiter import Bucket, Bites

# Init bucket singleton
Bucket(redis_url='redis-url', prefix='redis-prefix')

# Init rate_limiter
rate_limiter = Bites(
    capacity=10,
    interval=60,
    suffix=lambda *args, **kwargs: 'some-key-parsed-from-function-argument',
)

# Use as decorator
@rate_limiter
def call(*args, **kwargs):
    pass
```
