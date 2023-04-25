from typing import List

from .exceptions import InvalidParams
from .rate import Rate


def validate_rate_list(rates: List[Rate]) -> None:
    """Raise exception if rates are incorrectly ordered."""
    if not rates:
        raise InvalidParams("Rate(s) must be provided")

    for idx, rate in enumerate(rates[1:]):
        prev_rate = rates[idx]
        invalid = rate.limit <= prev_rate.limit or rate.interval <= prev_rate.interval

        if invalid:
            msg = f"{prev_rate} cannot come before {rate}"
            raise InvalidParams(msg)


class Limiter:
    pass
