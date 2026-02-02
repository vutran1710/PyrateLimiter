from pyrate_limiter import clocks
import pytest
from inspect import isawaitable


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

        # populate _row for time query (case-insensitive)
        if "extract(epoch" in (query or "").lower() and self._parent is not None:
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
        # PostgresClock.now() is exercised.
        raise RuntimeError("execute failed")

    def cursor(self):
        # return a cursor-like object whose execute() raises as well
        # so code using `with conn.cursor() as cur:` exercises the
        # same failure path as conn.execute()
        return self


class BadPool:
    def connection(self):
        # return a connection-like object whose execute() raises
        return FailingConn()


def make_rate_list():
    # make simple object with attributes expected by PostgresBucket;
    # values are not used by now()
    return [type("R", (), {"limit": 1, "interval": 1000})()]


def test_postgres_clock_now_uses_db_time():
    expected_ms = 1_600_000_000_000
    conn = DummyConn(now_row=expected_ms)
    pool = DummyPool(conn)

    clock = clocks.PostgresClock(pool=pool)

    got = clock.now()
    assert got == expected_ms
    assert conn.last_query is not None
    # check for lowercase extract to match codebase convention
    assert "extract(epoch" in conn.last_query.lower()


def test_postgres_clock_fallback_to_local_on_exception(monkeypatch):
    conn = DummyConn(now_row=0)
    pool = DummyPool(conn)
    clock = clocks.PostgresClock(pool=pool)

    clock.pool = BadPool()

    mocked_ns = 1234567890000
    expected_ms = mocked_ns // 1000000
    # patch the clocks._get_monotonic_ms used in PostgresClock fallback
    monkeypatch.setattr(
        "pyrate_limiter.clocks.AbstractClock._get_monotonic_ms",
        staticmethod(lambda: expected_ms),
        raising=False,
    )

    got = clock.now()
    assert got == expected_ms


@pytest.mark.postgres
def test_postgres_clock_with_real_postgres(postgres_pool):
    """Integration test against a real Postgres instance."""
    clock = clocks.PostgresClock(
        pool=postgres_pool,
    )

    now_first = clock.now()
    assert isinstance(now_first, int)
    assert now_first > 0

    now_second = clock.now()
    assert isinstance(now_second, int)
    assert now_second > 0

    assert now_second >= now_first


def test_monotonic_clock_now_non_decreasing():
    clock = clocks.MonotonicClock()
    t1 = clock.now()
    t2 = clock.now()

    assert isinstance(t1, int)
    assert isinstance(t2, int)
    assert t2 >= t1


@pytest.mark.asyncio
async def test_monotonic_async_clock_now_non_decreasing():
    clock = clocks.MonotonicAsyncClock()

    # ensure now() returns awaitable
    maybe_awaitable = clock.now()
    assert isawaitable(maybe_awaitable)

    t1 = await maybe_awaitable
    t2 = await clock.now()

    assert isinstance(t1, int)
    assert isinstance(t2, int)
    assert t2 >= t1
