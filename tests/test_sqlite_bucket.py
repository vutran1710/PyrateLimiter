import sqlite3

from pyrate_limiter.buckets import SQLiteBucket
from pyrate_limiter.buckets import SQLiteQueries


def test_bucket_init():
    file_path = "/Users/vutran/pyrate-limiter.sqlite"
    conn = sqlite3.connect(file_path)
    table_name = "pyrate-test-bucket"
    index_name = table_name + "__timestamp_index"

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
