from time import sleep
import pytest

from pyrate_limiter.exceptions import BucketFullException
from pyrate_limiter.enums import TimeEnum
from pyrate_limiter.request_rate import RequestRate
from pyrate_limiter.limiter import Limiter


def test_simple_limiter():
    rate = RequestRate(3, 5 * TimeEnum.SECOND)
    limiter = Limiter(rate)
    item = 'vutran'

    with pytest.raises(BucketFullException):
        for _ in range(4):
            limiter.try_acquire(item)

    sleep(6)
    limiter.try_acquire(item)
    vol = limiter.get_current_volume(item)
    assert vol == 1

    limiter.try_acquire(item)
    limiter.try_acquire(item)

    with pytest.raises(BucketFullException):
        limiter.try_acquire(item)
