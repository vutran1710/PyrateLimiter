# pylint: disable=C0114,C0115
from typing import Dict
from typing import TYPE_CHECKING
from typing import Union

if TYPE_CHECKING:
    from .abstracts import Rate


class BucketFullException(Exception):
    def __init__(self, name: str, rate: "Rate"):
        error = f"Bucket for {name} with Rate {rate} is already full"
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "name": name,
            "rate": str(rate),
        }
        super().__init__(error)
