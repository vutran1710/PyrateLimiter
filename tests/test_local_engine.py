from logzero import logger    # noqa
import pytest
from pyrate_limiter.engines.local import LocalBucket
from pyrate_limiter.exceptions import InvalidInitialValues


def test_invalid_initials():
    with pytest.raises(InvalidInitialValues):
        LocalBucket(initial='abcde')
