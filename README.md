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
from pyrate_limiter.core import RedisBucket as Bucket, HitRate

# Init bucket singleton
bucket = Bucket('redis-url', prefix='redis-prefix')

# Init rate_limiter
limiter = HitRate(
    bucket,
    capacity=10,
    interval=60,
)

# Use as decorator
@limiter('redis-key')
def call(*args, **kwargs):
    pass
```
