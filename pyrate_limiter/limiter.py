from typing import List, Dict
from queue import Queue
from time import time
from .exceptions import InvalidParams, BucketFullException
from .request_rate import RequestRate


class Limiter:
    bucket_group: Dict[str, Queue] = {}

    def __init__(
        self,
        *rates: List[RequestRate],
        opts=None,
    ):
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

        if opts:
            self._opts = opts

    def try_acquire(self, *identities):
        for idt in identities:
            # Setup Queue for each Identity if needed
            # Queue's maxsize equals the max limit of request-rates
            if not self.bucket_group.get(idt):
                maxsize = self._rates[-1].limit
                self.bucket_group[idt] = Queue(maxsize=maxsize)

        now = int(time())

        for idx, rate in enumerate(self._rates):
            for idt in identities:
                bucket = self.bucket_group[idt]
                volume = bucket.qsize()
                # print(f'bucket-size: {volume}')
                if volume < rate.limit:
                    continue

                # Determine time-window up until now
                time_window = now - rate.interval
                # print(f'window = {time_window}')
                total_reqs = 0

                for log_idx, log in enumerate(list(bucket.queue)):
                    # print(f'log-time: {log}')
                    if log >= time_window:
                        total_reqs = volume - log_idx
                        break
                # print(f'total_reqs = {total_reqs}')

                if total_reqs >= rate.limit:
                    raise BucketFullException(idt, rate)

                if idx == len(self._rates) - 1:
                    # We remove item based on the request-rate with the max-limit
                    for _ in range(volume - total_reqs):
                        bucket.get()

        for idt in identities:
            bucket = self.bucket_group[idt]
            # print(bucket)
            bucket.put(now)

    def get_current_volume(self, identity):
        bucket = self.bucket_group[identity]
        return bucket.qsize()

    def get_filled_slots(self, rate, identity):
        found_rate = next(
            (r for r in self._rates
             if r.limit == rate.limit and r.interval == rate.interval), None)

        if not found_rate:
            raise ValueError(f'Such rate {rate} is not found')

        if not self.bucket_group.get(identity):
            raise ValueError(f'Such identity {identity} is not found')

        bucket = self.bucket_group[identity]
        time_frame_start_point = int(time()) - rate.interval
        return [
            log_item for log_item in list(bucket.queue)
            if log_item >= time_frame_start_point
        ]
