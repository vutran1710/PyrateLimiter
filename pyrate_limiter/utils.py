from time import monotonic
from time import time
from typing import List

from .rate import RateItem


def local_time_clock() -> int:
    return int(1000 * time())


def local_monotonic_clock() -> int:
    return int(1000 * monotonic())


def binary_search(items: List[RateItem], value: int) -> int:
    """Find the index of item in list where left.timestamp < value <= right.timestamp
    this is to determine the current size of some window that
    stretches from now back to  lower-boundary = value and
    """
    if not items:
        return 0

    if value == items[0].timestamp:
        return 0

    if value > items[-1].timestamp:
        return -1

    pivot = int(len(items) / 2)
    left, right = items[pivot - 1], items[pivot]

    if left.timestamp >= value:
        return binary_search(items[:pivot], value)

    if right.timestamp < value:
        return pivot + binary_search(items[pivot:], value)

    return pivot
