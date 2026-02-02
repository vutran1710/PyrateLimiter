from pyrate_limiter.buckets import postgres
from pyrate_limiter.buckets.postgres import PostgresBucket
import pytest


class DummyCursor:
    def __init__(self, row=None):
        self._row = row
        self.closed = False
        self._parent = None

    def fetchone(self):
        return self._row

    def close(self):
        self.closed = True

    def execute(self, query, args=None):
        # if bound to a parent connection, update its last_query/last_args
        if self._parent is not None:
            self._parent.last_query = query
            self._parent.last_args = args

        # populate _row for time query
        if "EXTRACT(EPOCH" in (query or "") and self._parent is not None:
            self._row = (self._parent.now_row,)
        else:
            self._row = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyConn:
    def __init__(self, now_row=None):
        self.now_row = now_row
        self.last_query = None
        self.last_args = None

    def execute(self, query, args=None):
        self.last_query = query
        self.last_args = args

        # if the query is the time query, return a cursor with the now_row
        # return a DummyCursor bound to this connection so cursor.execute()
        # calls update the connection's last_query/last_args as expected.
        cur = DummyCursor(None)
        cur._parent = self
        # allow execute on the returned cursor to populate its _row
        cur.execute(query, args)
        return cur

    def cursor(self):
        # return a context-manager-compatible cursor bound to this conn
        cur = DummyCursor(None)
        cur._parent = self
        return cur

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class DummyPool:
    def __init__(self, conn: DummyConn):
        self._conn = conn
        self.closed = False

    def connection(self):
        # return the same DummyConn instance as a context manager
        return self._conn


class FailingConn:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, args=None):
        # raise an exception so that the fallback code path in
        # PostgresBucket.now() is exercised.
        raise RuntimeError("execute failed")


class BadPool:
    def connection(self):
        # return a connection-like object whose execute() raises
        return FailingConn()


def make_rate_list():
    # make simple object with attributes expected by PostgresBucket;
    # values are not used by now()
    return [type("R", (), {"limit": 1, "interval": 1000})()]


def test_now_uses_db_time():
    expected_ms = 1_600_000_000_000
    conn = DummyConn(now_row=expected_ms)
    pool = DummyPool(conn)

    bucket = PostgresBucket(pool=pool, table="testbucket", rates=make_rate_list())

    got = bucket.now()
    assert got == expected_ms
    assert conn.last_query is not None
    assert "EXTRACT(EPOCH" in conn.last_query


def test_now_falls_back_to_local_on_exception(monkeypatch):
    conn = DummyConn(now_row=0)
    pool = DummyPool(conn)
    bucket = PostgresBucket(pool=pool, table="tb", rates=make_rate_list())

    bucket.pool = BadPool()

    mocked_ns = 1234567890000
    expected_ms = mocked_ns // 1000000
    monkeypatch.setattr(postgres, "time_ns", lambda: mocked_ns)

    got = bucket.now()
    assert got == expected_ms


@pytest.mark.postgres
def test_now_with_real_postgres(postgres_pool):
    """Integration test against a real Postgres instance."""
    bucket = PostgresBucket(
        pool=postgres_pool,
        table="integration_test_bucket",
        rates=make_rate_list(),
    )

    now_first = bucket.now()
    assert isinstance(now_first, int)
    assert now_first > 0

    now_second = bucket.now()
    assert isinstance(now_second, int)
    assert now_second > 0

    assert now_second >= now_first
