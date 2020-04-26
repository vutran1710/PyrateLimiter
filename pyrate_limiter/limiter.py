from typing import List, Dict
from queue import Queue
from time import time
from .exceptions import InvalidParams, BucketFullException
from .request_rate import RequestRate


class Limiter:
    bucket_group: Dict[str, Queue]

    def __init__(
        self,
        *rates: List[RequestRate],
        opts=None,
    ):
        if not rates:
            raise InvalidParams('Rates')

        self._rates = rates

        if opts:
            self._opts = opts

    def process(self, *identities):
        for idt in identities:
            # Setup Queue for each Identity if needed
            # Queue's maxsize equals the max limit of request-rates
            if not self.bucket_group.get(idt):
                maxsize = self._rates[-1].limit
                self.bucket_group[idt] = Queue(maxsize=maxsize)

        # Check
        now = int(time())

        for idx, rate in enumerate(self._rates):
            for idt in identities:
                bucket = self.bucket_group[idt]
                volume = bucket.qsize()

                if volume < rate.limit:
                    if idx + 1 == len(self._rates):
                        bucket.put(now)
                    continue

                # Determine time-window up until now
                time_window = now - rate.interval
                total_reqs = 0

                for log_idx, log in enumerate(list(bucket.queue)):
                    if log >= time_window:
                        total_reqs = volume - log_idx
                        break

                if total_reqs >= rate.limit:
                    raise BucketFullException(idt, rate)
