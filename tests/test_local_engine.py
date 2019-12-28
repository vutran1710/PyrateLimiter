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
    avg_rate = HitRate(3, 5)
    max_rate = HitRate(10, 15)
    limiter = BasicLimiter(bucket, average=avg_rate, maximum=max_rate)

    for idx in range(5):
        item = 'item_{}'.format(idx)
        allowed = limiter.allow(item)

        if idx == 3:
            assert not allowed

        if idx < 3:
            assert allowed
            assert len(limiter.bucket) == idx + 1

        if idx > 3:
            assert allowed
            assert len(limiter.bucket) == 3

        sleep(1)
