"""Very basic Local-State Bucket for a stateful Backend application
"""
import traceback
import sys
from queue import Queue
from contextlib import contextmanager
from pyrate_limiter.core import AbstractBucket


class LocalBucket(AbstractBucket):
    """Implementation of AbstractBucket using native Queue as the Bucket
    """
    _queue = None

    @property
    def queue(self):
        if not self._queue:
            self._queue = Queue()
        return self._queue
    # fuck
    @contextmanager
    def synchronizing(self):
        try:
            yield self
        except Exception as err:
            traceback.print_exc(limit=2, file=sys.stdout)
            raise err

    def __iter__(self):
        return iter(self.queue.queue)

    def __getitem__(self, index):
        size = self.queue.qsize()

        if index < 0:
            index += size
        if index > size:
            raise IndexError

        return list(self.queue.queue)[index]

    def __len__(self):
        return self.queue.qsize()

    def append(self, item):
        self.queue.put(item)

    def discard(self, number=1):
        queue = self.queue

        while not queue.empty() and number > 0:
            queue.get()
            number -= 1

        return queue.qsize()
