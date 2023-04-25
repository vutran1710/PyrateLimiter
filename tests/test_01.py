from time import sleep

from pyrate_limiter import BucketFullException
from pyrate_limiter import Limiter
from pyrate_limiter import Rate


def test_01():
    rates = [Rate(5, 500)]
    limiter = Limiter(*rates)

    limiter.try_acquire("item")
    limiter.try_acquire("item")
    limiter.try_acquire("item")
    limiter.try_acquire("item")
    limiter.try_acquire("item")

    assert True

    try:
        limiter.try_acquire("item")
        assert False
    except BucketFullException as err:
        print(err)

    sleep(0.2)

    assert len(limiter.get_bucket("item").items) == 0

    limiter.factory.stop()
