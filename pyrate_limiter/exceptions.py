# pylint: disable=C0114,C0115
from typing import Dict
from typing import Union

from .abstracts.rate import Rate
from .abstracts.rate import RateItem


class BucketFullException(Exception):
    def __init__(self, item: RateItem, rate: Rate):
        error = f"Bucket for item={item.name} with Rate {rate} is already full"
        self.item = item
        self.rate = rate
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "name": item.name,
            "weight": item.weight,
            "rate": str(rate),
        }
        super().__init__(error)

    def __reduce__(self):
        return (self.__class__, (self.item, self.rate))


class LimiterDelayException(Exception):
    def __init__(self, item: RateItem, rate: Rate, actual_delay: int, max_delay: int):
        self.item = item
        self.rate = rate
        self.actual_delay = actual_delay
        self.max_delay = max_delay
        error = f"""
        Actual delay exceeded allowance: actual={actual_delay}, allowed={max_delay}
        Bucket for {item.name} with Rate {rate} is already full
        """
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "name": item.name,
            "weight": item.weight,
            "rate": str(rate),
            "max_delay": max_delay,
            "actual_delay": actual_delay,
        }
        super().__init__(error)

    def __reduce__(self):
        return (self.__class__, (self.item, self.rate, self.actual_delay, self.max_delay))
