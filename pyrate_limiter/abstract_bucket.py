"""Implementing Leaky-Bucket algorimth
bucket = Bucket(capacity=10, window=60)
class MyBucket(Bucket):

"""
from typing import List
from abc import ABC, abstractmethod
import Enum
from time import time
# from collections import deque


class AlgorimthTypes(Enum):
    Fixed = 'FIXED_WINDOW'
    Slide = 'SLIDING_WINDOW'
    Log = 'SLIDING_LOG'


class Bucket(ABC):

    bucket = []
    capacity = None
    window = None

    def __init__(self, capacity=10, window=3600):
        self.capacity = capacity
        self.window = window

    def __append(self, item):
        self.__leak()

        if self.get_bucket_slots() > self.capacity:
            raise Exception('Bucket full')

        self.bucket = self.append(item)

    def __leak(self):
        if not len(self.bucket):
            return

        now = time()

        for idx, item in enumerate(self.bucket):
            point = item.get('time')

            if now - point < self.window:
                self.bucket = self.bucket[idx:]
                break

    @abstractmethod
    def append(self, item) -> List:
        pass

    @abstractmethod
    def slide(self, from_idx):
        pass

    @abstractmethod
    def get_bucket_slots(self):
        pass
