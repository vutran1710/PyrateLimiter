from logzero import logger    # noqa
from time import sleep, time
import pytest
from pyrate_limiter.limiters import (
    LocalBucket,
    BasicLimiter,
)

from pyrate_limiter.core import (
    HitRate,
    LoggedItem,
)

from pyrate_limiter.exceptions import (    # noqa
    InvalidInitialValues, BucketFullException,
)


def test_invalid_initials():
    with pytest.raises(InvalidInitialValues):
        LocalBucket(initial='abcde')


def test_name_tuple():
    item = LoggedItem(item='x', timestamp=int(time()), nth=2)
    obj = item._asdict()
    assert obj['item'] == 'x'
    assert item.item == 'x'
    assert item.nth == 2


def test_sliding_window_log_limiter():
    bucket = LocalBucket()
    avg_rate = HitRate(5, 10)
    limiter = BasicLimiter(bucket, avg_rate)
    now = int(time())

    for idx in range(7):
        item = 'item_{}'.format(idx)
        allowed = limiter.allow(item)
        then = int(time())
        elapsed = then - now

        if idx < 5:
            assert allowed
            assert len(limiter.bucket) == idx + 1

        if idx == 5:
            assert not allowed
            logger.debug('Elapsed:%s', elapsed)
            sleep(11)

        if idx == 6:
            logger.debug('Elapsed:%s', elapsed)
            assert len(limiter.bucket) == 1
            assert allowed
