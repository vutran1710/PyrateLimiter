from time import monotonic
from time import time

from .abstracts import Clock


class MonotonicClock(Clock):
    def __init__(self):
        monotonic()

    def now(self):
        return int(1000 * monotonic())


class TimeClock(Clock):
    def now(self):
        return int(1000 * time())
