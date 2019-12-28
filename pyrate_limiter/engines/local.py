from queue import Queue
from contextlib import contextmanager
from pyrate_limiter.core import AbstractBucket
from pyrate_limiter.exceptions import InvalidInitialValues


class LocalBucket(AbstractBucket):
    __q__ = None

    def __init__(self, initial: list = None):
        self.__q__ = Queue()

        if initial is None:
            return

        if not isinstance(initial, list):
            raise InvalidInitialValues

        if initial:
            [self.__q__.put(t) for t in initial]

    @contextmanager
    def synchronizing(self):
        try:
            yield self
        except Exception as err:
            print(err.__traceback__)
        finally:
            return None

    def __iter__(self):
        return list(self.__q__.queue)

    def __getitem__(self, index):
        size = self.__q__.qsize()

        if index < 0:
            index += size
        if index > size:
            raise IndexError

        return list(self.__q__.queue)[index]

    def __len__(self):
        return self.__q__.qsize()

    def append(self, item):
        self.__q__.put(item)

    def discard(self, number=1):
        q = self.__q__

        if number <= 0:
            return q.qsize()

        while not q.empty() and number > 0:
            q.get()
            number -= 1
