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
