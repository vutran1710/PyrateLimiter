from time import monotonic
from time import time
from typing import Callable
from typing import List
from typing import Optional

from .bucket import BucketFactory
from .bucket import DefaultBucketFactory
from .exceptions import InvalidParams
from .rate import Rate
from .rate import RateItem

TimeFunction = Callable[[], int]


def int_monotonic() -> int:
    return int(monotonic() * 1000)


def simple_int_time() -> int:
    return int(time() * 1000)


def validate_rate_list(rates: List[Rate]) -> None:
    """Raise exception if rates are incorrectly ordered."""
    if not rates:
        raise InvalidParams("Rate(s) must be provided")

    for idx, rate in enumerate(rates[1:]):
        prev_rate = rates[idx]
        invalid = rate.limit <= prev_rate.limit or rate.interval <= prev_rate.interval

        if invalid:
            msg = f"{prev_rate} cannot come before {rate}"
            raise InvalidParams(msg)


class Limiter:
    """Main rate-limiter class

    Args:
        rates: rate definitions
        bucket_factory: A specific implementation of BucketFactory Class,
    fall back to DefaultBucketFactory if not provided
        time_function: a function that calculates time, precise to milisecs,
    default system time
    """

    _bucket_factory: BucketFactory
    _rates: List[Rate]
    # _timefn: TimeFunction

    def __init__(
        self,
        *rates: Rate,
        bucket_factory: Optional[BucketFactory] = None,
        time_function: Optional[TimeFunction] = None,
    ):
        self._rates = list(rates)
        validate_rate_list(self._rates)

        if bucket_factory is not None:
            self._bucket_factory = bucket_factory
        else:
            self._bucket_factory = DefaultBucketFactory()

        self._timefn = simple_int_time if time_function is None else time_function
        # Anchor the monotonic clock if needed
        self._timefn()

    def try_acquire(self, item: str, weight: int = 1, timestamp: Optional[int] = None):
        rate_item = RateItem(
            name=item,
            weight=weight,
            timestamp=self._timefn() if timestamp is None else timestamp,
        )
        bucket = self._bucket_factory.get(rate_item)
        return bucket.put(rate_item, self._rates)
