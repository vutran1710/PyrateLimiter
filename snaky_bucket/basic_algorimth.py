from time import time
from .exceptions import BucketFullException


class Bucket:

    queue = []
    capacity = None
    window = None

    def __init__(self, capacity=10, window=3600):
        self.capacity = capacity
        self.window = window

    def append(self, item):
        self.leak()

        if len(self.queue) >= self.capacity:
            raise BucketFullException('Bucket full')

        timestamp = time()
        self.queue.append({'timestamp': timestamp, 'item': item})

    def leak(self):
        if not len(self.queue):
            return

        now = time()
        new_queue = self.queue

        for idx, item in enumerate(self.queue):
            interval = now - item.get('timestamp')
            if interval > self.window:
                new_queue = self.queue[idx + 1:]
            else:
                break

        self.queue = new_queue
