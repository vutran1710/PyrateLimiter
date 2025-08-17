# ruff: noqa: T201

"""
May need to install the psycopg binaries:
# uv pip install psycopg[binary]

"""

import time
from datetime import datetime
from typing import List

from psycopg_pool import ConnectionPool as PgConnectionPool

from pyrate_limiter import Duration, Limiter, PostgresBucket, Rate


def create_postgres_bucket(rates: List[Rate]):
    pool = PgConnectionPool("postgresql://postgres:postgres@localhost:5432", open=True)
    table = f"test_bucket_{int(time.time())}"
    bucket = PostgresBucket(pool, table, rates)
    assert bucket.count() == 0
    return bucket


def test_postgres():
    rates = [Rate(3, Duration.SECOND * 3)]

    def task(name, weight):
        acquired = limiter.try_acquire(name, weight)
        print(f"{datetime.now()} {name}: {weight}, {acquired=}")

    redis_bucket = create_postgres_bucket(rates)
    limiter = Limiter(redis_bucket, raise_when_fail=False, max_delay=Duration.DAY)
    for i in range(10):
        task(str(i), 1)


if __name__ == "__main__":
    print("To start a postgres container: ")
    print("# docker run --name postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 -d postgres")

    test_postgres()
