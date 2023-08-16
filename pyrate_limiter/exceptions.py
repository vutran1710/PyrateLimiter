# pylint: disable=C0114,C0115
from typing import Dict
from typing import Union

from .abstracts.rate import Rate


class BucketFullException(Exception):
    def __init__(self, name: str, rate: Rate):
        error = f"Bucket for {name} with Rate {rate} is already full"
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "name": name,
            "rate": str(rate),
        }
        super().__init__(error)


class LimiterDelayException(Exception):
    def __init__(self, name: str, rate: Rate, actual_delay: int, allowed_delay: int):
        error = f"""
        Actual delay exceeded allowance: actual={actual_delay}, allowed={allowed_delay}
        Bucket for {name} with Rate {rate} is already full
        """
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "name": name,
            "rate": str(rate),
            "allowed_delay": allowed_delay,
            "actual_delay": actual_delay,
        }
        super().__init__(error)
