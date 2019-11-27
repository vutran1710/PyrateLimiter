from time import time
from .exceptions import BucketFullException


class LeakyBucket:
    """Sliding window
    """
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
        if not self.queue:
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


class TokenBucket:
    """Fixed window
    """

    queue = []
    capacity = None
    window = None

    def __init__(self, capacity=10, window=3600):
        self.capacity = capacity
        self.window = window

    def process(self, item):
        self.refill()

        if len(self.queue) >= self.capacity:
            raise BucketFullException('No more tokens')

        self.queue.append({'timestamp': time(), 'item': item})

    def refill(self):
        if not self.queue:
            return

        last_item = self.queue[-1]
        now = time()

        if now - last_item['timestamp'] >= self.window:
            self.queue = []
