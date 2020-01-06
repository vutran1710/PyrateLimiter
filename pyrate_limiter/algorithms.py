""" Providing rate-limitting algorithms
"""
from typing import Any
from enum import Enum
from .core import HitRate, LoggedItem, AbstractBucket


def sliding_window_log(
    bucket: AbstractBucket,
    rate: HitRate,
    item: Any,
    now: int,
):
    """Sliding-Window-Log algorithm to limit rate, eg:
    - 100 req/min
    - For each request comes in, a timestamp and a counter number are added
    - Lazy-discarding outdated items at fixed-rate, eg 60/100 sec/item in the queue
    to ensure no excessiveness at any moment
    """
    volume = len(bucket)

    if not volume or volume < rate.hit:
        logged_item = LoggedItem(item=item, timestamp=now, nth=1)
        bucket.append(logged_item)
        return True

    after_leak_volume = volume

    for _ in range(volume):
        latest_item = bucket[0]
        timestamp = latest_item.timestamp
        if (now - timestamp) > rate.time:
            after_leak_volume = bucket.discard(number=1)
        else:
            break

    if after_leak_volume < rate.hit:
        logged_item = LoggedItem(
            item=item,
            timestamp=now,
            nth=volume + 1,
        )
        bucket.append(logged_item)
        return True

    return False


class Algorithms(Enum):
    """
    Algorithm Enum Class, extensible at much as needed
    """
    SLIDING_WINDOW_LOG = sliding_window_log
