""" Basic Rate-Limiter
"""
from logging import getLogger
from typing import Union, Type
from time import time
from pyrate_limiter.exceptions import InvalidParams, BucketFullException
from pyrate_limiter.request_rate import RequestRate
from pyrate_limiter.bucket import AbstractBucket, MemoryQueueBucket
from pyrate_limiter.limit_context_decorator import LimitContextDecorator


logger = getLogger(__name__)


class Limiter:
    """Basic rate-limiter class that makes use of built-in python Queue"""

    def __init__(
        self,
        *rates: RequestRate,
        bucket_class: Type[AbstractBucket] = MemoryQueueBucket,
        bucket_kwargs=None,
    ):
        """Init a limiter with rates and specific bucket type
        - Bucket type can be any class that extends AbstractBucket
        - 3 kinds of Bucket are provided, being MemoryQueueBucket, MemoryListBucket and RedisBucket
        - Opts is extra keyword-arguements for Bucket class constructor
        """
        self._validate_rate_list(rates)
        self._rates = rates
        # R1: avoid short names like bkclass, it is less readable.
        self._bkclass = bucket_class
        # R2: Here the object property is renamed, for not good reason
        # R3: Also, it might be better to pass a bucket factory that
        # takes no arguments.
        self._bucket_args = bucket_kwargs or {}
        self.bucket_group = {}

    def _validate_rate_list(self, rates):  # pylint: disable=no-self-use
        if not rates:
            raise InvalidParams("Rate(s) must be provided")

        # R0: Smart. Here is another approach
        for previous, rate in zip(rates, rates[:1]):
            invalid = rate.limit <= previous.limit or rate.interval <= previous.interval
            if invalid:
                msg = f"{previous} cannot come before {rate}"
                raise InvalidParams(msg)

    def _init_buckets(self, identities) -> None:
        """Setup Queue for each Identity if needed Queue's maxsize equals the
        max limit of request-rates

        """
        for id in identities:
            if not self.bucket_group.get(id):
                maxsize = self._rates[-1].limit
                msg = "Creating bucket for identity: %r, with klass: %r args: %r"
                logger.debug(msg, id, self._bkclass, self._bucket_args)
                self.bucket_group[id] = self._bkclass(
                    maxsize=maxsize,
                    identity=id,
                    **self._bucket_args,
                )

    # R4: I am not sure what is the best approach, and I am not sure
    # but I think *args will create a copy of identities at at the
    # call site. My approach is to use sparingly.
    def try_acquire(self, *identities) -> None:
        """Acquiring an item or reject it if rate-limit has been exceeded"""
        self._init_buckets(identities)
        # R5: time is slow.
        now = int(time())

        # R8: Instead of two loops, one can use itertools.product It
        # is the same complexity... but it can be faster.
        for rate in self._rates:
            # R6: here identity is better than id.
            for id in identities:
                bucket = self.bucket_group[id]
                volume = bucket.size()

                if volume < rate.limit:
                    continue

                # Determine rate's time-window starting point
                start_time = now - rate.interval
                item_count, remaining_time = bucket.inspect_expired_items(start_time)

                if item_count >= rate.limit:
                    raise BucketFullException(id, rate, remaining_time)

                # is it the last?
                if rate is self._rates[-1]:
                    # We remove item based on the request-rate with the max-limit
                    # R7: Here i would see a purge method instead of bucket.get.
                    bucket.get(volume - item_count)

        for id in identities:
            self.bucket_group[id].put(now)

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
        # R9: I think the 'abstraction shouldn't leak' and in general
        # what is called 'sugar' must be used sparingly (ref:
        # https://en.wikipedia.org/wiki/Leaky_abstraction)
        bucket = self.bucket_group[identity]
        return bucket.size()

    # def get_filled_slots(self, rate, identity) -> List[int]:
    #     """ Get logged items in bucket for a specific identity
    #     """
    #     found_rate = next(
    #         (r for r in self._rates
    #          if r.limit == rate.limit and r.interval == rate.interval), None)

    #     if not found_rate:
    #         raise ValueError(f'Such rate {rate} is not found')

    #     if not self.bucket_group.get(identity):
    #         raise ValueError(f'Such identity {identity} is not found')

    #     bucket = self.bucket_group[identity]
    #     time_frame_start_point = int(time()) - rate.interval
    #     return [
    #         log_item for log_item in bucket.all_items()
    #         if log_item >= time_frame_start_point
    #     ]
