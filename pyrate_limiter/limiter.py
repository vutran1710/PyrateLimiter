from time import monotonic
from typing import Callable, NewType, Optional, Type

from .bucket import BucketFactory
from .exceptions import BucketFullException, InvalidParams
from .rate import Rate, RateItem

TimeFunction = NewType('TimeFunction', Callable[[], int])


class Limiter:
    """Main rate-limiter class

    Args:
        rates: rate definitions
        time_function: Time function that returns the current time as a float, in seconds
    """

    def __init__(
        self,
        *rates: Rate,
        time_function: Optional[TimeFunction] = None,
        bucket_factory: Optional[Type[BucketFactory]] = None
    ):
        self._validate_rate_list(rates)
        self._rates = rates
        self._bucket_factory = bucket_factory if bucket_factory is not None else BucketFactory()
        self.time_function = monotonic

        if time_function is not None:
            self.time_function = time_function

        # Call for time_function to make an anchor if required.
        self.time_function()

    def validate_rate_list(self, rates):  # pylint: disable=no-self-use
        """Raise exception if rates are incorrectly ordered."""
        if not rates:
            raise InvalidParams("Rate(s) must be provided")

        for idx, rate in enumerate(rates[1:]):
            prev_rate = rates[idx]
            invalid = rate.limit <= prev_rate.limit or rate.interval <= prev_rate.interval

            if invalid:
                msg = f"{prev_rate} cannot come before {rate}"
                raise InvalidParams(msg)

    def try_acquire(self, item: RateItem) -> None:
        bucket = self._bucket_factory.get(item)
        bucket_items = bucket.load()

        for rate in self._rates:
            check = rate.can_accquire(bucket_items, space_required=item.weight)

            if check is False:
                raise BucketFullException(item.name, rate, 0.0)

        bucket.put(item)
