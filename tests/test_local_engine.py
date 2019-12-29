from logzero import logger    # noqa
from time import sleep, time
import pytest
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.core import (
    BasicLimiter,
    HitRate,
    LoggedItem,
)
from pyrate_limiter.exceptions import (
    InvalidInitialValues,
    BucketFullException,
)


def test_invalid_initials():
    with pytest.raises(InvalidInitialValues):
        LocalBucket(initial='abcde')


def test_name_tuple():
    item = LoggedItem(item='x', timestamp=int(time()))
    obj = item._asdict()
    assert obj['item'] == 'x'
    assert item.item == 'x'


def test_block():
    bucket = LocalBucket()
    avg_rate = HitRate(5, 10)
    max_rate = HitRate(10, 15)
    limiter = BasicLimiter(bucket, average=avg_rate, maximum=max_rate)
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
