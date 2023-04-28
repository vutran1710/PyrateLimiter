import sqlite3

from pyrate_limiter.abstracts import RateItem
from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries

file_path = "/Users/vutran/pyrate-limiter.sqlite"
table_name = "pyrate-test-bucket"
index_name = table_name + "__timestamp_index"


def clean_up_db(conn: sqlite3.Connection):
    conn.execute("DROP TABLE IF EXISTS '%s'" % table_name)
    conn.execute("DROP INDEX IF EXISTS '%s'" % index_name)


def test_bucket_init():
    conn = sqlite3.connect(file_path)
    clean_up_db(conn)

    create_table_query = SQLiteQueries.CREATE_BUCKET_TABLE.format(table=table_name)
    conn.execute(create_table_query)

    create_idx_query = SQLiteQueries.CREATE_INDEX_ON_TIMESTAMP.format(
        index_name=index_name,
        table_name=table_name,
    )

    conn.execute(create_idx_query)

    conn.commit()

    bucket = SQLiteBucket(conn, table_name)
    assert bucket is not None

    bucket.put(RateItem("my-item", 0))

    count = conn.execute("SELECT COUNT(*) FROM '%s'" % table_name).fetchone()[0]
    assert count == 1

    bucket.put(RateItem("my-item", 0, weight=10))
    count = conn.execute("SELECT COUNT(*) FROM '%s'" % table_name).fetchone()[0]
    assert count == 11
