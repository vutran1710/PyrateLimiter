import random
import string
from typing import List

from .abstracts import Rate
from .abstracts import RateItem


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


def validate_rate_list(rates: List[Rate]) -> bool:
    """Raise false if rates are incorrectly ordered."""
    if not rates:
        return False

    for idx, rate in enumerate(rates[1:]):
        prev_rate = rates[idx]
        invalid = rate.limit <= prev_rate.limit or rate.interval <= prev_rate.interval

        if invalid:
            return False

    return True


def id_generator(
    size=6,
    chars=string.ascii_uppercase + string.digits + string.ascii_lowercase,
) -> str:
    return "".join(random.choice(chars) for _ in range(size))
