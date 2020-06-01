""" Basic Rate-Limiter
"""
from typing import List, Dict
from time import time
from .exceptions import InvalidParams, BucketFullException
from .request_rate import RequestRate
from .bucket import AbstractBucket, MemoryQueueBucket


class Limiter:
    """ Basic rate-limiter class that makes use of built-in python Queue
    """
    bucket_group: Dict[str, AbstractBucket] = {}

    def __init__(
        self,
        *rates: List[RequestRate],
        bucket_class: AbstractBucket = MemoryQueueBucket,
        bucket_kwargs=None,
    ):
        """ Init a limiter with rates and specific bucket type
        - Bucket type can be any class that extends AbstractBucket
        - 3 kinds of Bucket are provided, being MemoryQueueBucket, MemoryListBucket and RedisBucket
        - Opts is extra keyword-arguements for Bucket class constructor
        """
        if not rates:
            raise InvalidParams('Rates')

        # Validate rates
        for idx, rate in enumerate(rates):
            if idx == 0:
                continue

            prev_rate = rates[idx - 1]
            if rate.limit < prev_rate.limit or rate.interval < prev_rate.interval:
                raise InvalidParams(f'{prev_rate} cannot come before {rate}')

        self._rates = rates
        self._bkclass = bucket_class
        self._bucket_args = bucket_kwargs or {}

    def try_acquire(self, *identities) -> None:
        """ Acquiring an item or reject it if rate-limit has been exceeded
        """
        for idt in identities:
            # Setup Queue for each Identity if needed
            # Queue's maxsize equals the max limit of request-rates
            if not self.bucket_group.get(idt):
                maxsize = self._rates[-1].limit
                # print(self._bucket_args)
                self.bucket_group[idt] = self._bkclass(
                    maxsize=maxsize,
                    identity=idt,
                    **self._bucket_args,
                )

        now = int(time())

        for idx, rate in enumerate(self._rates):
            for idt in identities:
                bucket = self.bucket_group[idt]
                volume = bucket.size()
                # print(f'bucket-size: {volume}')
                if volume < rate.limit:
                    continue

                # Determine time-window up until now
                time_window = now - rate.interval
                total_reqs = 0

                for log_idx, log in enumerate(bucket.all_items()):
                    if log >= time_window:
                        total_reqs = volume - log_idx
                        break

                if total_reqs >= rate.limit:
                    raise BucketFullException(idt, rate)

                if idx == len(self._rates) - 1:
                    # We remove item based on the request-rate with the max-limit
                    bucket.get(volume - total_reqs)

        for idt in identities:
            bucket = self.bucket_group[idt]
            # print(bucket)
            bucket.put(now)

    def get_current_volume(self, identity) -> int:
        """ Get current bucket volume for a specific identity
        """
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
