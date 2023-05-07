import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import gettempdir
from time import time
from typing import Union

import pytest

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries as Queries
from pyrate_limiter.clocks import MonotonicClock
from pyrate_limiter.clocks import TimeClock
from pyrate_limiter.utils import id_generator

TEMP_DIR = Path(gettempdir())
DEFAULT_DB_PATH = TEMP_DIR / "pyrate_limiter.sqlite"
TABLE_NAME = f"pyrate-test-bucket-{id_generator(size=10)}"
INDEX_NAME = TABLE_NAME + "__timestamp_index"


def count_all(conn: sqlite3.Connection) -> int:
    count = conn.execute(Queries.COUNT_ALL.format(table=TABLE_NAME)).fetchone()[0]
    return count


@pytest.fixture
def conn():
    db_conn = sqlite3.connect(
        DEFAULT_DB_PATH,
        isolation_level="EXCLUSIVE",
        check_same_thread=False,
    )
    drop_table_query = Queries.DROP_TABLE.format(table=TABLE_NAME)
    drop_index_query = Queries.DROP_INDEX.format(index=INDEX_NAME)
    create_table_query = Queries.CREATE_BUCKET_TABLE.format(table=TABLE_NAME)

    db_conn.execute(drop_table_query)
    db_conn.execute(drop_index_query)
    db_conn.execute(create_table_query)

    create_idx_query = Queries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=INDEX_NAME,
        table_name=TABLE_NAME,
    )

    db_conn.execute(create_idx_query)

    db_conn.commit()

    yield db_conn


def test_bucket_01(clock: Union[MonotonicClock, TimeClock], conn: sqlite3.Connection):
    rates = [Rate(20, 1000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)
    assert bucket is not None

    bucket.put(RateItem("my-item", clock.now()))
    assert bucket.count() == 1

    bucket.put(RateItem("my-item", clock.now(), weight=10))
    assert bucket.count() == 11

    assert bucket.put(RateItem("my-item", clock.now(), weight=20)) is False
    assert bucket.failing_rate == rates[0]

    assert bucket.put(RateItem("my-item", clock.now(), weight=9)) is True
    assert bucket.count() == 20

    assert bucket.put(RateItem("my-item", clock.now())) is False


def test_bucket_02(clock: Union[MonotonicClock, TimeClock], conn: sqlite3.Connection):
    rates = [Rate(30, 1000), Rate(50, 2000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)
    assert bucket.count() == 0

    start = time()
    while bucket.count() < 150:
        bucket.put(RateItem("item", clock.now()))

        if bucket.count() == 31:
            cost = time() - start
            logging.info(">30 items: %s", cost)
            assert cost > 1

        if bucket.count() == 51:
            cost = time() - start
            logging.info(">50 items: %s", cost)
            assert cost > 2

        if bucket.count() == 81:
            cost = time() - start
            logging.info(">80 items: %s", cost)
            assert cost > 3

        if bucket.count() == 101:
            cost = time() - start
            logging.info(">100 items: %s", cost)
            assert cost > 4


def test_bucket_leak(clock: Union[MonotonicClock, TimeClock], conn: sqlite3.Connection):
    rates = [Rate(1000, 1000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    while bucket.count() < 2000:
        bucket.put(RateItem("item", clock.now()))

    bucket.leak(clock.now())
    assert bucket.count() == 1000


def test_bucket_flush(clock: Union[MonotonicClock, TimeClock], conn: sqlite3.Connection):
    rates = [Rate(5000, 1000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    while bucket.count() < 10000:
        bucket.put(RateItem("item", clock.now()))

    bucket.flush()
    assert bucket.count() == 0


def test_stress_test(clock: Union[MonotonicClock, TimeClock], conn: sqlite3.Connection):
    rates = [Rate(10000, 1000), Rate(20000, 3000), Rate(30000, 4000), Rate(40000, 5000)]
    bucket = SQLiteBucket(rates, conn, TABLE_NAME)

    assert count_all(conn) == 0

    before = time()

    def put_item(nth: int):
        bucket.put(RateItem(f"item={nth}", clock.now()))

    with ThreadPoolExecutor() as executor:
        for _ in executor.map(put_item, list(range(10000))):
            pass

    after = time()
    print("Cost: ", after - before)
    print("Count: ", count_all(conn))
