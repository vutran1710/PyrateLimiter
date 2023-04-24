from time import sleep, time
from typing import List, Optional

from pyrate_limiter.constants import Duration


class RateItem:
    name: str
    timestamp: int
    weight: int

    def __init__(self, name: str, weight: int = 1, timestamp: Optional[int] = None):
        self.name = name
        self.weight = weight
        self.timestamp = int(time() * 1000) if timestamp is None else timestamp


class TimeWindow:
    length: int

    def __init__(self, duration: Duration):
        self.length = duration * 1000

    def binary_search(self, items: List[RateItem], lower: int) -> Optional[int]:
        if not items:
            return None

        if items[0].timestamp > lower:
            return 0

        if items[-1].timestamp < lower:
            return None

        pivot_idx = int(len(items) / 2)

        left = items[pivot_idx - 1].timestamp
        right = items[pivot_idx].timestamp

        if left < lower <= right:
            return pivot_idx

        if left >= lower:
            return self.binary_search(items[:pivot_idx], lower)

        if right < lower:
            return pivot_idx + self.binary_search(items[pivot_idx:], lower)

    def count(self, time_streams: List[RateItem], from_idx: int = 0) -> int:
        """Count how many items within the window"""
        upper = int(time() * 1000)
        lower = upper - self.length
        counter = 0

        idx = self.binary_search(time_streams, lower)

        if idx is not None:
            counter = len(time_streams) - idx - from_idx
            return counter

        return 0


def test_binary_search():
    items = []

    for n in range(10):
        item = RateItem(n, timestamp=n * 2)
        items.append(item)

    window = TimeWindow(Duration.SECOND)

    found_idxes = []
    for n in [5, 13, 10, 14, 20]:
        idx = window.binary_search(items, n)
        found_idxes.append(idx)

    assert found_idxes == [3, 7, 5, 7, None]


def data_generator():
    for number in range(50):
        yield number
        sleep(0.01)


def test_process_data_stream():
    time_streams = []
    window = TimeWindow(0.3 * Duration.SECOND)

    for number in data_generator():
        item = RateItem(number)
        time_streams.append(item)
        count = window.count(time_streams)
        print(f"count={count}")


def test_with_very_large_stream():
    items = []
    now = int(time() * 1000)

    for num in range(2_000_000):
        item = RateItem('item')
        item.timestamp += num - 1000000

        if item.timestamp > now:
            break

        items.append(item)

    print(f"total={len(items)}")

    window = TimeWindow(5 * Duration.MINUTE)
    before = time()
    count = window.count(items)
    elapsed = time() - before
    print(f"time cost = {elapsed}s -> count={count}")
