from queue import SimpleQueue
from contextlib import contextmanager
from pyrate_limiter.core import AbstractBucket
from pyrate_limiter.exceptions import InvalidInitialValues


class LocalBucket(AbstractBucket):
    __q__ = None

    def __init__(self, initial: list = None):
        self.__q__ = SimpleQueue()

        if initial is None:
            return

        if not isinstance(initial, list):
            raise InvalidInitialValues

        if initial:
            [self.__q__.put(t) for t in initial]

    @contextmanager
    def sync(self):
        try:
            yield self.__q__.qsize()
        finally:
            pass

    def append(self, item):
        self.__q__.put(item)

    def discard(self, number=1):
        if number <= 0:
            return self.__q__.qsize()

        while not q.empty() and number > 0:
            self.__q__.get(item)
