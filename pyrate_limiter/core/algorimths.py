""" Providing rate-limitting algorithms
"""
from typing import Any
from enum import Enum
from .base import (
    AbstractBucket,
    HitRate,
    LoggedItem,
)


def sliding_window_log(
    bucket: AbstractBucket,
    rate: HitRate,
    item: Any,
    now: int,
):
    volume = len(bucket)

    if not volume or volume < rate.hit:
        logged_item = LoggedItem(item=item, timestamp=now, nth=1)
        bucket.append(logged_item)
        return True

    after_leak_volume = volume

    for idx in range(volume):
        item: LoggedItem = bucket[0]
        timestamp = item.timestamp
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


######################################################
# Algorithm Enum Class, extensible at much as needed #
######################################################


class Algorithms(Enum):
    SLIDING_WINDOW_LOG: sliding_window_log
