from logzero import logger    # noqa
import pytest    # noqa
from time import sleep, time
from pyrate_limiter.limiters import BasicLimiter
from pyrate_limiter.buckets import LocalBucket

from pyrate_limiter.core import HitRate
from pyrate_limiter.algorithms import Algorithms

from pyrate_limiter.exceptions import (    # noqa
    InvalidInitialValues, BucketFullException,
)


def test_sliding_window_log_limiter():
    rate = HitRate(5, 10)
    bucket = LocalBucket(alg=Algorithms.SLIDING_WINDOW_LOG, rate=rate)
    limiter = BasicLimiter(bucket)
    bucket = limiter.buckets[0]

    now = int(time())

    for idx in range(7):
        item = 'item_{}'.format(idx)
        allowed = False

        try:
            limiter.allow(item)
            allowed = True
        except Exception as err:
            assert isinstance(err, BucketFullException)
            print('>>> Exception', err)
            print('>>> allowed?', allowed)

        then = int(time())
        elapsed = then - now

        if idx < 5:
            assert allowed
            assert len(bucket) == idx + 1

        if idx == 5:
            assert not allowed
            logger.debug('Elapsed:%s', elapsed)
            sleep(11)

        if idx == 6:
            logger.debug('Elapsed:%s', elapsed)
            assert len(bucket) == 1
            assert allowed
