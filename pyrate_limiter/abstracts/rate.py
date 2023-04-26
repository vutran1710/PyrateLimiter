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
