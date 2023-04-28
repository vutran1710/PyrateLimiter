import sqlite3
from time import sleep

from pyrate_limiter.abstracts import Rate
from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries

file_path = "/Users/vutran/pyrate-limiter.sqlite"
table_name = "pyrate-test-bucket"
index_name = table_name + "__timestamp_index"


def setup_db(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS '%s'" % table_name)
    conn.execute("DROP INDEX IF EXISTS '%s'" % index_name)
    create_table_query = SQLiteQueries.CREATE_BUCKET_TABLE.format(table=table_name)
    conn.execute(create_table_query)

    create_idx_query = SQLiteQueries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=index_name,
        table_name=table_name,
    )

    conn.execute(create_idx_query)

    conn.commit()


def test_bucket_init():
    conn = sqlite3.connect(file_path, isolation_level="EXCLUSIVE")
    setup_db(conn)

    rates = [Rate(20, 1000)]
    bucket = SQLiteBucket(conn, table_name, rates)
    assert bucket is not None

    bucket.put(RateItem("my-item", 0))

    count = conn.execute("SELECT COUNT(*) FROM '%s'" % table_name).fetchone()[0]
    assert count == 1

    bucket.put(RateItem("my-item", 0, weight=10))
    count = conn.execute("SELECT COUNT(*) FROM '%s'" % table_name).fetchone()[0]
    assert count == 11

    count = conn.execute(
        SQLiteQueries.COUNT_BEFORE_INSERT.format(
            table=table_name,
            interval=1000,
        )
    ).fetchone()[0]
    assert count == 11

    # Insert 10 more item, it should fail
    sleep(1)
    for ntn in range(21):
        is_ok = bucket.put(RateItem("my-item", 0))
        sleep(0.01)

        if ntn == 20:
            assert is_ok is False

    bucket.leak()
    count = conn.execute(
        SQLiteQueries.COUNT_BEFORE_INSERT.format(
            table=table_name,
            interval=100,
        )
    ).fetchone()[0]
    assert count == 10

    conn.close()
