# pylint: disable=C0114,C0115
from typing import Any
from typing import Dict
from typing import Type
from typing import TYPE_CHECKING
from typing import Union

from .abstracts import AbstractAsyncBucket
from .abstracts import AbstractBucket
from .abstracts import BucketFactory

if TYPE_CHECKING:
    from .abstracts import Rate


class BucketFullException(Exception):
    def __init__(self, identity: str, rate: "Rate", remaining_time: float):
        error = f"Bucket for {identity} with Rate {rate} is already full"
        self.meta_info: Dict[str, Union[str, float]] = {
            "error": error,
            "identity": identity,
            "rate": str(rate),
            "remaining_time": remaining_time,
        }
        super().__init__(error)


class BucketRetrievalFail(Exception):
    def __init__(
        self,
        identity: str,
        expected_bucket_class: Type[Union[AbstractBucket, AbstractAsyncBucket]],
    ):
        error = f"Can't retrieve bucket={expected_bucket_class} for item={identity}"
        super().__init__(error)


class BucketInitializationFail(Exception):
    def __init__(
        self,
        identity: str,
        factory: BucketFactory,
        error: Any,
    ):
        error = f"Failed to create bucket for item={identity}, factory={BucketFactory}, err={error}"
        super().__init__(error)


class InvalidParams(Exception):
    def __init__(self, param_name: str):
        self.message = f"Parameters missing or invalid:{param_name}"
        super().__init__(self.message)


class ImmutableClassProperty(Exception):
    def __init__(self, class_instance: Any, prop: str):
        """Mutating class property is forbidden"""
        self.message = f"{class_instance}.{prop} must not be mutated"
        super().__init__(self.message)
