from time import monotonic
from time import time

from .abstracts import SyncClock


class MonotonicClock(SyncClock):
    def __init__(self):
        monotonic()

    def now(self):
        return int(1000 * monotonic())


class TimeClock(SyncClock):
    def now(self):
        return int(1000 * time())
