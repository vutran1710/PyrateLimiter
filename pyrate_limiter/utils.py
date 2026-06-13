import sqlite3
import uuid
from pathlib import Path
from tempfile import gettempdir
from typing import List

from .abstracts.rate import Rate


def validate_rate_list(rates: List[Rate]) -> bool:
    """Raise false if rates are incorrectly ordered."""
    if not rates:
        return False

    for idx, current_rate in enumerate(rates[1:]):
        prev_rate = rates[idx]

        if current_rate.interval <= prev_rate.interval:
            return False

        if current_rate.limit <= prev_rate.limit:
            return False

        if (current_rate.limit / current_rate.interval) > (prev_rate.limit / prev_rate.interval):
            return False

    return True


def enforce_rate_list(rates: List[Rate]) -> None:
    """Raise ValueError if rates are not a well-formed, ordered rate list.

    A valid list is ordered by strictly increasing interval, with strictly
    increasing limits and non-increasing density (limit/interval) - i.e. the
    "generous-before-tight" contract. Pass rates already in the order the
    bucket will use them (sort first if the bucket sorts).
    """
    if not validate_rate_list(rates):
        raise ValueError(
            "Invalid rate list: rates must be non-empty and ordered by strictly "
            "increasing interval, with strictly increasing limits and non-increasing "
            f"density (limit/interval). Got: {rates}"
        )


def id_generator(
    size=10,
) -> str:
    return uuid.uuid4().hex[:size]


def dedicated_sqlite_clock_connection():
    temp_dir = Path(gettempdir())
    default_db_path = temp_dir / "pyrate_limiter_clock_only.sqlite"

    conn = sqlite3.connect(
        default_db_path,
        isolation_level="EXCLUSIVE",
        check_same_thread=False,
    )
    return conn
