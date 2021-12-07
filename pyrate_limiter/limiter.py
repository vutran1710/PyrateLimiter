"""Basic Rate-Limiter."""
from time import monotonic
from typing import Callable, Type, Union

from .bucket import AbstractBucket, MemoryQueueBucket
from .exceptions import BucketFullException, InvalidParams
from .limit_context_decorator import LimitContextDecorator
from .request_rate import RequestRate


class Limiter:
    """Basic rate-limiter class that makes use of built-in python Queue"""

    def __init__(
        self,
        *rates: RequestRate,
        bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
        bucket_kwargs=None,
        time_function: Callable[[], float] = None,
    ):
        """Init a limiter with rates and specific bucket type
        - Bucket type can be any class that extends AbstractBucket
        - 3 kinds of Bucket are provided, being MemoryQueueBucket, MemoryListBucket and RedisBucket
        - Opts is extra keyword-arguments for Bucket class constructor
        - Optional time function, that should return float as current second.microsecond
        """
        self._validate_rate_list(rates)
        self._rates = rates
        self._bkclass = bucket_class
        self._bucket_args = bucket_kwargs or {}
        self.bucket_group = {}
        self.time_function = monotonic
        if time_function is not None:
            self.time_function = time_function
        # Call for time_function to make an anchor if required.
        self.time_function()

    def _validate_rate_list(self, rates):  # pylint: disable=no-self-use
        """Raise exception if *rates are incorrectly ordered."""
        if not rates:
            raise InvalidParams("Rate(s) must be provided")

        for idx, rate in enumerate(rates[1:]):
            prev_rate = rates[idx]
            invalid = rate.limit <= prev_rate.limit or rate.interval <= prev_rate.interval
            if invalid:
                msg = f"{prev_rate} cannot come before {rate}"
                raise InvalidParams(msg)

    def _init_buckets(self, identities) -> None:
        """Setup Queue for each Identity if needed
        Queue's maxsize equals the max limit of request-rates
        """
        for item_id in identities:
            if not self.bucket_group.get(item_id):
                maxsize = self._rates[-1].limit
                self.bucket_group[item_id] = self._bkclass(
                    maxsize=maxsize,
                    identity=item_id,
                    **self._bucket_args,
                )

    def try_acquire(self, *identities) -> None:
        """Acquiring an item or reject it if rate-limit has been exceeded"""
        self._init_buckets(identities)
        now = self.time_function()

        for idx, rate in enumerate(self._rates):
            for item_id in identities:
                bucket = self.bucket_group[item_id]
                volume = bucket.size()

                if volume < rate.limit:
                    continue

                # Determine rate's time-window starting point
                start_time = now - rate.interval
                item_count, remaining_time = bucket.inspect_expired_items(start_time)

                if item_count >= rate.limit:
                    raise BucketFullException(item_id, rate, remaining_time)

                if idx == len(self._rates) - 1:
                    # We remove item based on the request-rate with the max-limit
                    bucket.get(volume - item_count)

        for item_id in identities:
            self.bucket_group[item_id].put(now)

    def ratelimit(
        self,
        *identities,
        delay: bool = False,
        max_delay: Union[int, float] = None,
    ):
        """A decorator and contextmanager that applies rate-limiting, with async support.
        Depending on arguments, calls that exceed the rate limit will either raise an exception, or
        sleep until space is available in the bucket.

        Args:
            identities: Bucket identities
            delay: Delay until the next request instead of raising an exception
            max_delay: The maximum allowed delay time (in seconds); anything over this will raise
                an exception
        """
        return LimitContextDecorator(self, *identities, delay=delay, max_delay=max_delay)

    def get_current_volume(self, identity) -> int:
        """Get current bucket volume for a specific identity"""
        bucket = self.bucket_group[identity]
        return bucket.size()
