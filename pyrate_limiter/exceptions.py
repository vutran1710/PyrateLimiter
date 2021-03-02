# pylint: disable=C0114,C0115
from json import dumps


class BucketFullException(Exception):
    def __init__(self, identity, rate, remaining_time):
        error = f"Bucket for {identity} with Rate {rate} is already full"
        self.meta_info = {
            "error": error,
            "identity": identity,
            "rate": str(rate),
            "remaining_time": remaining_time,
        }
        super().__init__(error)


class InvalidParams(Exception):
    def __init__(self, param_name: str):
        self.message = f"Parameters missing or invalid:{param_name}"
        super().__init__(self.message)


class ImmutableClassProperty(Exception):
    def __init__(self, class_instance, prop: str):
        """Mutating class property is forbidden"""
        self.message = f"{class_instance}.{prop} must not be mutated"
        super().__init__(self.message)
