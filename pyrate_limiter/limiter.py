"""Basic Rate-Limiter."""
from time import monotonic
from typing import Any
from typing import Callable
from typing import Dict
from typing import Union

from .bucket import AbstractBucket
from .bucket import MemoryQueueBucket
from .exceptions import BucketFullException
from .exceptions import InvalidParams
from .limit_context_decorator import LimitContextDecorator
from .request_rate import RequestRate


class Limiter:
    """Basic rate-limiter class that makes use of built-in python Queue"""

    bucket_group: Dict[Any, Any]

    def __init__(
        self,
        *rates: RequestRate,
        bucket_class=MemoryQueueBucket,
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
        self.bucket_group: Dict[str, AbstractBucket] = {}
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
        """Initialize a bucket for each identity, if needed.
        The bucket's maxsize equals the max limit of request-rates.
        """
        maxsize = self._rates[-1].limit
        for item_id in sorted(identities):
            if not self.bucket_group.get(item_id):
                self.bucket_group[item_id] = self._bkclass(
                    maxsize=maxsize,
                    identity=item_id,
                    **self._bucket_args,
                )
            self.bucket_group[item_id].lock_acquire()

    def _release_buckets(self, identities) -> None:
        """Release locks after bucket transactions, if applicable"""
        for item_id in sorted(identities):
            self.bucket_group[item_id].lock_release()

    def try_acquire(self, *identities: str) -> None:
        """Attempt to acquire an item, or raise an error if a rate limit has been exceeded"""
        self._init_buckets(identities)
        now = self.time_function()

        for rate in self._rates:
            for item_id in identities:
                bucket = self.bucket_group[item_id]
                volume = bucket.size()

                if volume < rate.limit:
                    continue

                # Determine rate's starting point, and check requests made during its time window
                item_count, remaining_time = bucket.inspect_expired_items(now - rate.interval)
                if item_count >= rate.limit:
                    self._release_buckets(identities)
                    raise BucketFullException(item_id, rate, remaining_time)

                # Remove expired bucket items beyond the last (maximum) rate limit,
                if rate is self._rates[-1]:
                    bucket.get(volume - item_count)

        # If no buckets are full, add another item to each bucket representing the next request
        for item_id in identities:
            self.bucket_group[item_id].put(now)
        self._release_buckets(identities)

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

    def flush_all(self) -> int:
        cnt = 0

        for _, bucket in self.bucket_group.items():
            bucket.flush()
            cnt += 1

        return cnt
