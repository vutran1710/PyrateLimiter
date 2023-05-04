# pylint: disable=C0114,C0115
from typing import Dict
from typing import TYPE_CHECKING
from typing import Union

if TYPE_CHECKING:
    from .abstracts import Rate


class BucketFullException(Exception):
    def __init__(self, identity: str, rate: "Rate"):
        error = f"Bucket for {identity} with Rate {rate} is already full"
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "identity": identity,
            "rate": str(rate),
        }
        super().__init__(error)


class BucketRetrievalFail(Exception):
    def __init__(self, identity: str):
        error = f"Can't retrieve bucket for item={identity}"
        super().__init__(error)
