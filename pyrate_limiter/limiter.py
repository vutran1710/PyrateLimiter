from inspect import iscoroutinefunction
from typing import Callable
from typing import List
from typing import NewType
from typing import Optional
from typing import Type
from typing import Union

from .bucket import AbstractBucket
from .bucket import BucketFactory
from .bucket import DefaultBucketFactory
from .exceptions import BucketFullException
from .exceptions import InvalidParams
from .limit_context_decorator import LimitContextDecorator
from .rate import Rate
from .rate import RateItem

TimeFunction = NewType("TimeFunction", Callable[[], int])


def validate_rate_list(rates: List[Rate]):
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
    """

    def __init__(self, *rates: Rate, bucket_factory: Optional[Type[BucketFactory]] = None):
        validate_rate_list(rates)
        self._rates = rates
        self._bucket_factory = bucket_factory if bucket_factory is not None else DefaultBucketFactory()

    def try_acquire(self, item: RateItem):
        bucket = self._bucket_factory.get(item)

        if iscoroutinefunction(bucket.get):
            return self._acquire_async(bucket, item)

        return self._acquire_sync(bucket, item)

    def _acquire_sync(self, bucket: Type[AbstractBucket], item: RateItem) -> None:
        bucket_items = bucket.load()

        for rate in self._rates:
            check = rate.can_accquire(bucket_items, space_required=item.weight)

            if check is False:
                raise BucketFullException(item.name, rate, 0.0)

        bucket.put(item)

    async def _acquire_async(self, bucket: Type[AbstractBucket], item: RateItem) -> None:
        bucket_items = await bucket.load()

        for rate in self._rates:
            check = rate.can_accquire(bucket_items, space_required=item.weight)

            if check is False:
                raise BucketFullException(item.name, rate, 0.0)

        await bucket.put(item)

    def ratelimit(
        self,
        item: RateItem,
        delay: bool = False,
        max_delay: Union[int, float] = None,
    ) -> LimitContextDecorator:
        return LimitContextDecorator(
            self,
            item,
            delay=delay,
            max_delay=max_delay,
        )
