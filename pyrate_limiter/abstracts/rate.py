"""Initialize this class to define rates for limiter
"""


class RateItem:
    name: str
    weight: int
    timestamp: int

    def __init__(self, name: str, timestamp: int, weight: int = 1):
        self.name = name
        self.timestamp = timestamp
        self.weight = weight

    def __str__(self) -> str:
        return f"RateItem(name={self.name}, weight={self.weight}, timestamp={self.timestamp})"


class Rate:
    """Rate definition.

    Args:
        limit: Number of requests allowed within ``interval``
        interval: Time interval, in miliseconds
    """

    limit: int
    interval: int

    def __init__(
        self,
        limit: int,
        interval: int,
    ):
        self.limit = limit
        self.interval = interval

    def __str__(self) -> str:
        return f"limit={self.limit}/{self.interval}ms"
