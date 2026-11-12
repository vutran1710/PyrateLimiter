"""Focused unit tests for SQLiteBucket edge cases."""
from pathlib import Path
from tempfile import gettempdir

import pytest

from pyrate_limiter import Duration, Rate, RateItem, SQLiteBucket, id_generator


def _make_bucket(rates):
    db_path = str(Path(gettempdir()) / f"pyrate_sqlite_test_{id_generator()}.sqlite")
    table = f"pyrate-test-{id_generator()}"
    return SQLiteBucket.init_from_file(rates, db_path=db_path, table=table, create_new_table=True)


@pytest.mark.sqlite
def test_sqlite_put_name_with_sql_metacharacters():
    """Bucket names are user-supplied (``try_acquire(name=...)``) and must be
    bound as parameters, not interpolated into SQL. A name containing a single
    quote previously crashed `put`, and a crafted name was an injection vector."""
    bucket = _make_bucket([Rate(100, Duration.SECOND)])
    try:
        name = "user's-key"
        assert bucket.put(RateItem(name, bucket.now(), weight=1)) is True
        assert bucket.count() == 1

        item = bucket.peek(0)
        assert item is not None
        assert item.name == name  # round-trips intact

        # An injection attempt must be stored as plain data, not executed.
        evil = "x', 1); DROP TABLE foo; --"
        assert bucket.put(RateItem(evil, bucket.now(), weight=2)) is True
        assert bucket.count() == 3  # 1 + weight(2)
    finally:
        bucket.close()


@pytest.mark.sqlite
def test_sqlite_leak_after_close_is_safe():
    """The background Leaker can call leak() during/after teardown; it must not
    crash on a closed (None) connection (issue #244)."""
    bucket = _make_bucket([Rate(100, Duration.SECOND)])
    bucket.put(RateItem("x", bucket.now(), weight=1))
    bucket.close()

    # Previously raised AttributeError: 'NoneType' object has no attribute 'execute'
    assert bucket.leak(bucket.now() + Duration.SECOND * 10) == 0


@pytest.mark.sqlite
@pytest.mark.parametrize("table", ['quoted"bucket', 'bucket" ORDER BY item_timestamp ASC --'])
def test_sqlite_peek_timestamp_quoted_table(tmp_path, table):
    bucket = SQLiteBucket.init_from_file(
        [Rate(2, Duration.SECOND)], table=table, db_path=str(tmp_path / "bucket.sqlite")
    )
    try:
        assert bucket._peek_timestamp(0) is None
        assert bucket.put(RateItem("first", 1000))
        assert bucket.put(RateItem("second", 1100))
        assert bucket._peek_timestamp(0) == 1100
        assert bucket._peek_timestamp(1) == 1000
        assert bucket._peek_timestamp(2) is None
        assert not bucket.put(RateItem("denied", 1200))
        assert bucket.count() == 2
    finally:
        bucket.close()
