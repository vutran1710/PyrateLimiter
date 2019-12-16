from logzero import logger  # noqa
from time import sleep
import pytest
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.exceptions import InvalidInitialValues


bucket = None

def test_invalid_initials():
    with pytest.raises(InvalidInitialValues):
        LocalBucket(initial_values='abc')


def test_valid_initials():
    global bucket
    bucket = LocalBucket()


def test_independence():
    bucket_one = LocalBucket(initial_values=[1, 2, 3])
    bucket_two = LocalBucket()
    assert bucket_one.__values__ == [1, 2, 3]
    assert bucket_two.__values__ == []


def test_values():
    global bucket
    assert bucket.values() == []


def test_append():
    global bucket
    bucket.append(1)
    assert bucket.values() == [1]


def test_update():
    global bucket
    bucket.update([4, 5, 6])
    assert bucket.values() == [4, 5, 6]


