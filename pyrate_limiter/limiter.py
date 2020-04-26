from typing import List
from queue import Queue
from time import time
from .exceptions import InvalidParams, BucketFullException
from .request_rate import RequestRate


class Limiter:
    bucket_group = {}
    time_logs = {}

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

    def process(
        self,
        *identities,
        exception_cls=BucketFullException,
        exception_args=None,
    ):
        now = int(time())

        for rate in self._rates:
            for idt in identities:
                bucket: Queue = self.bucket_group.get(idt)

                if not bucket:
                    # Set queue's maxsize equals the utter request-rate's limit
                    maxsize = self._rates[-1].limit
                    self.bucket_group[idt] = Queue(maxsize=maxsize)
                    continue

                volume = len(bucket)

                if rate.valid_rate(idt, volume, now):
                    continue

                if exception_cls:
                    raise exception_cls(exception_args)

        for rate in self._rates:
            for idt in identities:
                rate.log_now(idt, now)
