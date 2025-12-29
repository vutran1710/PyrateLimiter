import threading

import pytest

from pyrate_limiter import Duration, PostgresBucket, Rate
from pyrate_limiter.abstracts import RateItem


@pytest.mark.postgres
class TestPostgresConcurrent:

    @pytest.fixture
    def pg_pool(self):
        from psycopg_pool import ConnectionPool

        pool = ConnectionPool(
            "postgresql://postgres:postgres@localhost:5432",
            min_size=4,
            max_size=10,
            open=True,
        )
        yield pool
        pool.close()

    @pytest.fixture
    def clean_table(self, pg_pool):
        from pyrate_limiter import id_generator

        table = f"test_concurrent_{id_generator()}"
        yield table
        with pg_pool.connection() as conn:
            conn.execute(f"DROP TABLE IF EXISTS ratelimit___{table}")

    def test_concurrent_put(self, pg_pool, clean_table):
        rate_limit = 5
        rates = [Rate(rate_limit, Duration.SECOND)]
        num_threads = 8
        attempts_per_thread = 10

        results = []
        results_lock = threading.Lock()

        def worker(thread_id: int):
            bucket = PostgresBucket(pg_pool, clean_table, rates)
            thread_results = []

            for _ in range(attempts_per_thread):
                timestamp = bucket.now()
                item = RateItem(f"thread_{thread_id}", timestamp, weight=1)
                success = bucket.put(item)
                thread_results.append((timestamp, success))

            with results_lock:
                results.extend(thread_results)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Verify db state
        full_table = f"ratelimit___{clean_table}"
        with pg_pool.connection() as conn:
            cur = conn.execute(f"SELECT COUNT(*) FROM {full_table}")  # noqa: S608
            total_in_db = cur.fetchone()[0]
            cur.close()

            # Check in sliding windows to make sure rate didn't exceed
            cur = conn.execute(
                f"SELECT EXTRACT(EPOCH FROM item_timestamp)::bigint as ts FROM {full_table}"  # noqa: S608
            )
            db_timestamps = [row[0] for row in cur.fetchall()]
            cur.close()

        for ts in db_timestamps:
            window_start = ts - 1  # 1 second window
            count_in_window = sum(1 for t in db_timestamps if t > window_start and t <= ts)
            assert count_in_window <= rate_limit, (
                f"Rate limit exceeded in DB: {count_in_window} items in 1-second window ending at {ts}"
            )

        # Verify anything worked
        total_success = sum(1 for _, success in results if success)
        assert total_success > 0, "No successful acquisitions"
        assert total_success == total_in_db, (
            f"Mismatch: {total_success} reported successes but {total_in_db} items in DB"
        )

        # Verify some rejections
        total_rejected = sum(1 for _, success in results if not success)
        assert total_rejected > 0, (
            "No rejections occurred - rate limiting may not be working"
        )

    def test_concurrent_put_multiple_rates(self, pg_pool, clean_table):
        rates = [
            Rate(3, 500),   # 3 per 500ms
            Rate(5, 1000),  # 5 per second
        ]
        num_threads = 4
        attempts_per_thread = 5

        results = []
        results_lock = threading.Lock()

        def worker(thread_id: int):
            bucket = PostgresBucket(pg_pool, clean_table, rates)
            thread_results = []

            for _ in range(attempts_per_thread):
                timestamp = bucket.now()
                item = RateItem(f"thread_{thread_id}", timestamp, weight=1)
                success = bucket.put(item)
                thread_results.append((timestamp, success))

            with results_lock:
                results.extend(thread_results)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successful_timestamps = sorted([ts for ts, success in results if success])

        # Check sliding windows for both rates
        for ts in successful_timestamps:
            # 1-second sliding window
            count_1s = sum(1 for t in successful_timestamps if ts - 1000 <= t <= ts)
            assert count_1s <= 5, f"1-second rate exceeded: {count_1s} items in window ending at {ts}"

            # 500ms sliding window
            count_500ms = sum(1 for t in successful_timestamps if ts - 500 <= t <= ts)
            assert count_500ms <= 3, f"500ms rate exceeded: {count_500ms} items in window ending at {ts}"

    def test_concurrent_put_weighted(self, pg_pool, clean_table):
        rate_limit = 10
        rates = [Rate(rate_limit, Duration.SECOND)]
        num_threads = 4
        weight = 3

        results = []
        results_lock = threading.Lock()

        def worker(thread_id: int):
            bucket = PostgresBucket(pg_pool, clean_table, rates)
            thread_results = []

            for _ in range(5):
                timestamp = bucket.now()
                item = RateItem(f"thread_{thread_id}", timestamp, weight=weight)
                success = bucket.put(item)
                thread_results.append((timestamp, success, weight))

            with results_lock:
                results.extend(thread_results)

        threads = [
            threading.Thread(target=worker, args=(i,)) for i in range(num_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        successful_results = sorted([(ts, w) for ts, success, w in results if success])

        # Check sliding windows for weighted items
        for ts, _ in successful_results:
            weight_in_window = sum(w for t, w in successful_results if ts - 1000 <= t <= ts)
            assert weight_in_window <= rate_limit, (
                f"Rate limit exceeded: weight {weight_in_window} in 1-second window ending at {ts}"
            )
